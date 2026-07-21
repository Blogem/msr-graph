// This app is a pure client-side SPA embedded in the Go server binary
// (design D1): there is no Node runtime in production, so SSR and
// prerendering are both disabled. Routing for direct/deep links and
// reloads is instead handled by adapter-static's `fallback: 'index.html'`
// (svelte.config.js) plus the Go server's SPA-fallback static handler
// (frontend-app-shell, task 6.2) serving index.html for any non-/api,
// non-/healthz path.
export const ssr = false;
export const prerender = false;
