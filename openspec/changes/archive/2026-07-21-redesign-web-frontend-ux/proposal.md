## Why

The frontend shipped functionally complete but visually raw: chat answers render LLM markdown as literal `**`/`#`/backticks, long IRIs and URNs overflow their containers across the review surfaces, the proposal-queue row is five unlabeled values a reviewer can't decode at a glance, and the whole app is ~50 lines of hardcoded CSS with no theming. It works, but it is not pleasant or legible to use — and the review queue, the surface a human operator spends the most time in, is the least readable. This change makes the app attractive and usable without altering any backend contract.

## What Changes

- **Introduce a design-token layer** (Open Props CSS custom properties) for color, spacing, radius, type scale, and shadows, replacing hardcoded values (`#ccc`, `#b00020`, `0.25rem`, …) throughout the components. This is the foundation the rest of the redesign builds on.
- **Real light/dark theming** built on those tokens, applied app-wide with a user-toggleable preference, replacing the current partial `color-scheme: light dark` declaration that leaves hardcoded fills broken in dark.
- **Markdown rendering for chat answers** — parse assistant markdown with `marked` and **sanitize with `DOMPurify`** before injecting HTML, so bold/lists/code/tables/links render properly. Sanitization is mandatory because the content is untrusted LLM output.
- **Overflow-safe rendering of long identifiers** (IRIs, URNs, unit codes) across the review surfaces — queue rows, the neighborhood diff, the evidence panel, and the raw-triples view — so no single long token blows out a layout.
- **Redesign the proposal-queue row** so the mined **term** is the headline, `kind`/`status` become labeled pills, `docFrequency` is humanized ("seen in 47 documents"), and the URN `id` is de-emphasized — inverting today's hierarchy where the noise (URN) is most prominent and the signal (term) is buried.
- **Polish the trace timeline** — the app's standout feature (tool calls, script runs, provenance chips, grounded/ungrounded answer stamps) gets a clearer visual treatment on the shared tokens.
- **Shared UX affordances**: loading skeletons/spinners, meaningful empty states, a streaming caret in chat while tokens arrive, action toasts for approve/reject (review) and create/restore (admin), keyboard navigation of the review queue (`j`/`k` to move, `a`/`r` to approve/reject), and example-prompt onboarding on the empty chat.

None of the above changes any HTTP contract; `$lib/api.ts`, the SSE event shapes, and the existing `data-testid` attributes stay stable so the current test suite continues to pass.

## Capabilities

### New Capabilities
- `frontend-design-system`: A cross-cutting design foundation consumed by every surface — design tokens (via Open Props), app-wide light/dark theming with a persisted user toggle, a convention for overflow-safe rendering of long identifiers, and shared UX primitives (loading/skeleton states, empty states, and toast notifications).

### Modified Capabilities
- `chat-ui`: Assistant answers render sanitized markdown (not literal plain text); the streaming turn shows a live in-progress affordance; the empty conversation shows example-prompt onboarding; the trace timeline is restyled on the shared tokens without changing which events it renders.
- `review-ui`: The proposal-queue row presents a legible information hierarchy (term-first, humanized document frequency, labeled kind/status, de-emphasized id); long identifiers render overflow-safe across the queue, diff, evidence, and raw views; the queue supports keyboard navigation; and approve/reject outcomes surface as toast feedback.

## Impact

- **Code**: `webapp/src/routes/app.css`, `webapp/src/routes/+layout.svelte`, `webapp/src/lib/chat/*` (ChatSurface, TraceTimeline, ProvenanceChips, AnswerStamp, chat.css), `webapp/src/lib/review/*` (ReviewSurface, DiffView, EvidencePanel), and `webapp/src/lib/admin/AdminSurface.svelte` adopt the tokens/theme/primitives.
- **Dependencies (new)**: `open-props`, `marked`, `dompurify` (+ `@types/dompurify` as needed) added to `webapp/package.json`. All are static-build compatible; the app remains a `@sveltejs/adapter-static` SPA embedded in the Go `server` binary — no server-side runtime added.
- **Stable contracts (unchanged)**: `$lib/api.ts`, `$lib/sse.ts`, all `/api/*` endpoints, SSE trace-event shapes, and existing `data-testid` selectors. The existing vitest suite must keep passing.
- **Not in scope**: no auth, no new backend endpoints, no changes to the build/embed pipeline or routing (`frontend-app-shell` requirements unchanged). `admin-ui` adopts the shared theming/toast/loading primitives but its requirements do not change.
