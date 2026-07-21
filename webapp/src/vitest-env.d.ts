// Ambient type augmentation for @testing-library/jest-dom's vitest matchers
// (toBeInTheDocument, toHaveTextContent, ...).
//
// vitest-setup.ts (webapp/vitest-setup.ts) imports
// '@testing-library/jest-dom/vitest' at RUNTIME, which registers the
// matchers on vitest's `expect` -- but it lives outside `src/`, and the
// SvelteKit-generated tsconfig's `include` only covers
// `../src/**/*.{js,ts,svelte}` and `../test(s)/**/*.{js,ts,svelte}` (see
// .svelte-kit/tsconfig.json), so svelte-check's type-checking program never
// picks it up. Without this file, every `expect(el).toHaveTextContent(...)`/
// `.toBeInTheDocument()` in a test file type-checks as an error
// ("Property '...' does not exist on type 'Assertion<HTMLElement>'"), even
// though the matcher works correctly at runtime.
//
// This file lives in src/ specifically so `../src/**/*.ts` picks it up; its
// only job is the triple-slash reference below, which pulls in
// @testing-library/jest-dom's `declare module 'vitest' { interface
// Assertion ... }` augmentation (node_modules/@testing-library/jest-dom/
// types/vitest.d.ts) for the whole program.
/// <reference types="@testing-library/jest-dom/vitest" />
