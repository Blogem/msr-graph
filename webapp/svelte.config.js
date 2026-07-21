import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),

	kit: {
		// Static adapter: no Node runtime in production. Build output goes to
		// webapp/build/ (the directory the Go server embeds via //go:embed --
		// see openspec/changes/web-frontend/design.md D1). `fallback:
		// 'index.html'` makes this a pure client-routed SPA: unknown paths at
		// build time (every route here) fall back to index.html so deep
		// links/reloads resolve client-side (frontend-app-shell spec).
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: true
		})
	}
};

export default config;
