## 1. Foundation — design tokens, theming, shared primitives (frontend-design-system)

- [ ] 1.1 Add `open-props`, `marked`, and `dompurify` (+ types) to `webapp/package.json` and install
- [ ] 1.2 Import Open Props and define the app's semantic token layer (color/space/radius/type/shadow) in `webapp/src/routes/app.css`, mapping to Open Props scales
- [ ] 1.3 Replace hardcoded literals in `app.css` and each component `<style>` block / `chat.css` with token references (`var(--…)`)
- [ ] 1.4 Implement light/dark/system theming driven by a root `data-theme` attribute; ensure both themes read correctly from tokens
- [ ] 1.5 Add a theme toggle to the app shell (`+layout.svelte`) persisting the choice to `localStorage`, defaulting to system
- [ ] 1.6 Add a shared `.identifier` overflow-safe convention (`overflow-wrap: anywhere` + `min-width: 0` on flex children)
- [ ] 1.7 Create shared loading/skeleton and empty-state treatments usable by the surfaces
- [ ] 1.8 Create a shared, non-blocking toast component with an `aria-live`/`role=status` region and auto/manual dismissal
- [ ] 1.9 Define the reference-inspired visual layer on tokens: `--accent` (indigo, distinct from grounded green), `--surface`/`--surface-2`, elevation (`--shadow-*`), rounded-card radii, and a calm neutral page background — applied to the existing top-nav layout (no icon rail)

## 2. Chat surface (chat-ui)

- [ ] 2.1 Add `$lib/markdown.ts` — a single helper that parses markdown with `marked` and sanitizes with `DOMPurify`, tolerant of incomplete/streamed input
- [ ] 2.2 Render the assistant answer body via the helper + `{@html}` in `ChatSurface.svelte`; keep user turns and trace payloads plain text; preserve `data-testid` hooks
- [ ] 2.3 Add an in-progress streaming affordance (caret/pulse) shown while a turn streams and removed on done/error
- [ ] 2.4 Add empty-conversation onboarding with clickable example prompts, hidden once the conversation starts
- [ ] 2.5 Restyle the trace timeline, provenance chips, and grounded/ungrounded answer stamp on the shared tokens (no change to which events render)
- [ ] 2.6 Restyle turns as rounded cards with a bold role label + muted secondary treatment; add the composer as a single rounded input bar with an indigo circular send button
- [ ] 2.7 Add a per-answer action row with a copy-answer action and a transient "copied" confirmation

## 3. Review surface (review-ui)

- [ ] 3.1 Redesign the proposal-queue row: term as headline, `kind`/`status` as pills, humanized document frequency (singular/plural), de-emphasized URN id; keep all five field `data-testid`/`class` hooks
- [ ] 3.2 Apply the overflow-safe identifier convention to the queue, `DiffView`, `EvidencePanel`, and raw-triples view
- [ ] 3.3 Add keyboard navigation to the queue (previous/next selection, approve/reject on the selected proposal) reusing the existing action handlers and their confirmation/validation paths
- [ ] 3.4 Surface approve/reject outcomes as toasts (success + failure) without altering the SHACL `422` violation rendering
- [ ] 3.5 Adopt loading/empty states for the queue and detail fetches

## 4. Admin surface + shell adoption

- [ ] 4.1 Adopt theming, loading/empty states, and toasts (create/restore outcomes) in `AdminSurface.svelte`
- [ ] 4.2 Verify the theme toggle and shared primitives render correctly across all three surfaces in both light and dark

## 5. Tests

- [ ] 5.1 Unit-test `$lib/markdown.ts`: renders bold/list/code/table/link; strips a `<script>`/`onerror` payload (XSS); does not throw on unterminated markdown
- [ ] 5.2 Test `ChatSurface`: assistant markdown renders as HTML (not literal); streaming affordance appears while streaming and clears on done; onboarding shows when empty and hides after first message
- [ ] 5.3 Test `ReviewSurface`: queue row shows term-first with humanized frequency and all five fields present; keyboard next/prev changes selection; approve/reject fire via keyboard; success/failure toasts appear
- [ ] 5.4a Test the copy-answer action: activating it writes the answer text to the clipboard and shows a transient confirmation
- [ ] 5.4 Test theming: explicit choice persists across reload (localStorage) and system default is honored when unset
- [ ] 5.5 Confirm the full existing vitest suite still passes (no `data-testid`/contract regressions) and `svelte-check` is clean

## 6. Verification

- [ ] 6.1 Grep for remaining hardcoded color literals in redesigned surfaces; confirm dark mode has no broken/hardcoded fills
- [ ] 6.2 Manual visual pass in light and dark across chat (with a markdown-heavy grounded answer), review (long-IRI proposal), and admin
- [ ] 6.3 Rebuild the embedded static assets and confirm the Go `server` binary serves the redesigned app (no build/embed pipeline change needed)
