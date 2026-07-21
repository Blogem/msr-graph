import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [sveltekit()],
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
