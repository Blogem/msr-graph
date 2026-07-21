// Global vitest setup: registers @testing-library/jest-dom's matchers
// (toBeInTheDocument, toHaveTextContent, ...) for every test file, and
// runs @testing-library/svelte's automatic cleanup between tests.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/svelte';
import { afterEach } from 'vitest';

afterEach(() => {
	cleanup();
});
