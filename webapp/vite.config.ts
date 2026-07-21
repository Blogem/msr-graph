import { sveltekit } from '@sveltejs/kit/vite';
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
	plugins: [sveltekit(), svelteTesting()],
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
