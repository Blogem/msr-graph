## Context

The frontend (chunk 10, archived `2026-07-21-web-frontend`) is a SvelteKit 5 SPA built with `@sveltejs/adapter-static` and embedded in the Go `server` binary via `//go:embed`. It has three surfaces — chat, review, admin — consuming the chunk-4 `chat-api` (SSE) and chunk-9 `proposal-review-api` / `store-checkpoint-restore` contracts. The original design decision **D6 ("no UI framework")** left styling as ~50 lines of hand-rolled global CSS plus small `<style>` blocks per component, with hardcoded colors and spacing.

Concrete current-state facts this design responds to:
- `ChatSurface.svelte` renders assistant content as `<p class="message-content">{turn.content}</p>` with `white-space: pre-wrap` — no markdown parsing exists and there is no markdown dependency in `package.json`.
- `ReviewSurface.svelte`'s queue row is five unlabeled `<span>`s (`id`, `kind`, `status`, `term`, `docFrequency`) in a flex row; the URN `id` is leftmost/most prominent.
- No component sets `overflow-wrap`/`min-width: 0`, so long IRIs (`urn:msr:…`, `unit:MOL-PER-MOL`, `http://qudt.org/…`) overflow flex children.
- The tests assert on `data-testid` selectors and text content, not on CSS.

## Goals / Non-Goals

**Goals:**
- A shared design-token foundation so color/spacing/type are consistent and themeable, and dark mode works everywhere.
- Correct, safe markdown rendering of assistant answers.
- No layout can be broken by a long identifier.
- A proposal-queue row a reviewer can read at a glance.
- Nicer, more alive feel: loading states, streaming affordance, toasts, keyboard nav, onboarding.
- Zero backend contract changes; existing vitest suite keeps passing.

**Non-Goals:**
- No auth, no new backend endpoints, no changes to the build/embed pipeline or routing (`frontend-app-shell` requirements unchanged).
- No component-logic rewrites beyond what rendering/UX requires; `$lib/api.ts` and `$lib/sse.ts` stay byte-stable.
- No move to server-side rendering; the app stays a static SPA.
- Not a redesign of the admin surface's requirements (it only *adopts* the shared primitives).

## Decisions

### D1: Open Props for design tokens, keep hand-rolled component CSS
Adopt [Open Props](https://open-props.style/) — a stylesheet of CSS custom properties (color/space/size/radius/shadow/type scales with built-in light/dark variants). Components keep their own `<style>` blocks but reference `var(--…)` tokens instead of literals.

- **Why over Tailwind**: Tailwind requires rewriting every component's markup with utility classes — high churn across already-complete components, and more friction with the `data-testid`-based tests. Open Props changes values, not markup.
- **Why over PicoCSS**: Pico styles semantic HTML but gives little to the app's custom components (trace timeline, diff, chips) and would be fought/overridden constantly.
- **Why not stay fully hardcoded**: dark mode and consistency both require a single source of truth for values; tokens are that source. This honors the *spirit* of D6 (still our hand-written CSS, no component framework) while superseding its "no external CSS" implication — recorded as a deliberate revision of D6.

### D2: `marked` + `DOMPurify` for chat markdown, sanitize before `{@html}`
Assistant `content` is parsed with `marked` to HTML, then run through `DOMPurify.sanitize()` before rendering via Svelte's `{@html}`. Only the assistant answer body is treated as markdown; user turns and trace-event payloads stay plain text.

- **Why sanitize**: the content is untrusted LLM output; rendering unsanitized HTML is an XSS sink. Sanitization is non-negotiable and belongs in a single helper (`$lib/markdown.ts`) so every render path goes through it.
- **Why `marked` over `svelte-exmarkdown`**: `marked` is small, framework-agnostic, and keeps the parse/sanitize/render steps explicit and unit-testable; the Svelte-native option is heavier and hides the sanitize boundary.
- **Streaming**: markdown is re-parsed on each token append. Partial/unterminated markdown (a half-written code fence) must render without throwing — the helper tolerates incomplete input and the streaming caret sits after the rendered body.

### D3: Queue-row information hierarchy inversion
Restructure the row into a two-line card: line 1 is the **term** (headline weight) plus right-aligned `kind`/`status` pills; line 2 is the humanized document frequency ("seen in N document(s)", singular/plural correct) plus the de-emphasized `id`. All fields remain present (the spec requires id/kind/status/term/docFrequency to be shown) and keep their existing `data-testid`/`class` hooks so tests are unaffected.

### D4: Overflow-safe identifier convention
A shared utility class (e.g. `.identifier`) applying `overflow-wrap: anywhere` + `min-width: 0` on flex children, applied wherever raw IRIs/URNs render (queue id, DiffView subject/predicate/object, EvidencePanel citedIn, raw-triples already uses a scrolling `<pre>`). Documented in the design-system spec as a convention so future surfaces inherit it.

### D5: Cross-cutting UX primitives live in the design-system capability
Loading/skeleton state, empty state, and toast notification are defined once (as small shared Svelte components + token-driven styles) and adopted by the surfaces. Toasts are ephemeral, non-blocking, and announced to assistive tech (`role="status"`/`aria-live`). Keyboard nav and onboarding are surface-specific (review and chat respectively) and specified in those capabilities.

### D6: Theme toggle persisted client-side
A light/dark/system toggle in the app shell, persisted to `localStorage`, applied by setting a `data-theme` (or `color-scheme`) attribute on the root. Defaults to `system`. No backend involvement.

### D7: Brand accent is distinct from the grounded-green semantic
The app already uses green semantically for the "grounded" answer stamp (`#d7f4de`/`#14622f`). The brand accent (primary buttons, active nav, send button, focus rings) SHALL therefore be a **different** hue — default **indigo** — so green keeps meaning "grounded" rather than becoming generic chrome. Both are tokens (`--accent`, `--grounded`), so the accent is swappable in one place if the brand direction changes.

- **Why**: the reference (Chatwind) uses green as its brand accent, but adopting that here would collide with an existing semantic and drain "grounded green" of its signal. Keeping them distinct preserves the meaning we already ship.
- **Alternative considered**: green-as-brand with grounded distinguished by icon/shape instead of color — rejected as more work and weaker signal than simply reserving the hue.

## Visual Design Direction (reference-inspired)

The look is inspired by the Chatwind reference the user provided, adopted as an **aesthetic layer over the existing top-nav layout** (no icon rail / multi-column relayout — that would expand `frontend-app-shell` scope and was explicitly out). The reference's *feel* is what we borrow:

- **Generous whitespace and a calm surface** — content sits on a faint neutral background; primary content in white/elevated cards. Fewer hard `1px #ccc` borders; more separation by background and spacing (tokens `--surface`, `--surface-2`, `--space-*`).
- **Soft rounded cards** — messages, proposal rows, evidence, and trace blocks become rounded cards (`--radius-2/3`) with a subtle shadow (`--shadow-1`) rather than thin-bordered boxes.
- **Clear type hierarchy** — a bold headline + muted secondary line pattern (used by the reference's history cards) maps directly onto the redesigned proposal row (term headline + muted "seen in N documents") and message role labels.
- **Per-message action row** — assistant answers get a lightweight action row (at minimum **copy answer**), echoing the reference's copy/edit affordances. Feedback (👍/👎) and edit/regenerate are **out** — there is no backend for them in this POC.
- **Distinctive input bar** — the chat composer becomes a single rounded bar with an accent (indigo) circular send button, replacing the plain input + button.
- **One confident accent** — indigo used sparingly for primary action, active state, and focus; green reserved for grounded, red/amber for errors/warnings, all via tokens.

This direction is realized through the same token/theme foundation (D1/D4/D7) — it adds no new layout capability, only styling and the small copy-answer affordance.

## Risks / Trade-offs

- **[XSS via markdown]** → All assistant HTML passes through `DOMPurify` in one shared helper; a unit test asserts a `<script>`/`onerror` payload is stripped. No `{@html}` anywhere else in the answer path.
- **[Test breakage from markup changes]** → Preserve every existing `data-testid` and the text content tests assert on; run the vitest suite as the gate after each surface change. Row redesign keeps the five field hooks.
- **[Bundle size from new deps]** → `marked`+`dompurify`+`open-props` are modest and static-build friendly; Open Props ships as CSS (tree-shakeable per-module imports if size matters). Acceptable for a single-user POC.
- **[Re-parsing markdown every streamed token]** → For POC answer lengths this is negligible; if it ever matters, parse only on a debounce or on stream completion. Not optimizing pre-emptively.
- **[Dark-mode regressions in hardcoded spots]** → Grep for remaining hex/`rgba(0,0,0,…)` literals after the token pass; the theme is only correct once literals are gone.
- **[Deliberate revision of D6]** → Adding external CSS/JS deps revises the original "no UI framework / no external CSS" stance. Documented here so the change is intentional, not accidental scope creep.

## Migration Plan

Foundation-first ordering, since markdown/overflow/row work all consume the tokens:
1. Add deps; add token layer + theme + shared primitives (`frontend-design-system`).
2. Chat: markdown helper + rendering, streaming caret, onboarding, trace-timeline restyle.
3. Review: row redesign, overflow-safe identifiers, keyboard nav, toasts.
4. Admin + shell: adopt theme toggle, loading/empty states, toasts.
5. Run `svelte-check` + vitest; visual pass in light and dark.

Rollback is trivial (frontend-only, no data/schema/API change): revert the branch and rebuild the embedded assets.

## Open Questions

- None blocking. Theme default is `system`; example onboarding prompts can be finalized during implementation from real demo queries.
