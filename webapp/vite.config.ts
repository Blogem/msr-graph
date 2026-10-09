import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	// svelteTesting() (only active under vitest, per its own `if
	// (!process.env.VITEST) return` guard) adds `browser` ahead of `node` in
	// `resolve.conditions`. Without it, the sveltekit() plugin above resolves
	// Svelte 5's SSR entry point under vitest (jsdom is not treated as
	// "browser" by default), and every `render()` call in a component test
	// throws `lifecycle_function_unavailable: mount(...) is not available on
	// the server`. It also wires @testing-library/svelte's own
	// afterEach(act(); cleanup()) into setupFiles, which is redundant with
	// but harmless alongside vitest-setup.ts's explicit `cleanup()` call.
	// Kit 3 removed svelte.config.js — its contents live here now, passed
	// straight to the plugin.
	plugins: [
		sveltekit({
			preprocess: vitePreprocess(),
			// Kit 3 removed `$lib` in favour of `#lib`. There are 62 `$lib`
			// imports across the app; this alias is the escape hatch the
			// upgrade guide documents, keeping the migration reviewable.
			// Renaming them to `#lib` and dropping this line is a follow-up.
			alias: { $lib: 'src/lib' },
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
		}),
		svelteTesting()
	],
	test: {
		environment: 'jsdom',
		include: ['src/**/*.{test,spec}.{js,ts}'],
		setupFiles: ['./vitest-setup.ts'],
		// Wave 1 (this scaffold) ships no test files yet; the tester agent
		// adds them in parallel. Without this, `vitest run` exits 1 on an
		// empty suite, which would look like a config/build failure rather
		// than "no tests yet."
		passWithNoTests: true
	}
});
