// Tests for the theme helper (frontend-design-system spec, "App-wide
// light/dark theming with a persisted toggle"; task 5.4), written against
// the pinned `$lib/theme.ts` contract:
//   type Theme = 'light' | 'dark' | 'system'
//   THEME_STORAGE_KEY = 'msr-theme'
//   loadTheme(): Theme
//   saveTheme(t: Theme): void
//   resolveTheme(t: Theme): 'light' | 'dark'
//   applyTheme(t: Theme): void
//
// NOTE (pass 1): $lib/theme.ts is built concurrently by the foundation
// coder in a separate worktree and is not visible here. This suite is
// written directly against the pinned contract and the spec's acceptance
// scenarios ("system preference is followed by default", "explicit choice
// persists across reload"); it is expected to fail to resolve/compile
// until the merge, and is reconciled in pass 2.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { applyTheme, loadTheme, resolveTheme, saveTheme, THEME_STORAGE_KEY } from './theme';

/** Installs a `window.matchMedia` mock that reports `matches` for every
 * query (only `(prefers-color-scheme: dark)` is exercised by `resolveTheme`/
 * `applyTheme`). Restored in `afterEach` via `vi.unstubAllGlobals()`. */
function stubMatchMedia(matches: boolean): void {
	vi.stubGlobal(
		'matchMedia',
		vi.fn().mockImplementation((query: string) => ({
			matches,
			media: query,
			onchange: null,
			addListener: vi.fn(),
			removeListener: vi.fn(),
			addEventListener: vi.fn(),
			removeEventListener: vi.fn(),
			dispatchEvent: vi.fn()
		}))
	);
}

beforeEach(() => {
	localStorage.clear();
});

afterEach(() => {
	vi.unstubAllGlobals();
	document.documentElement.removeAttribute('data-theme');
});

describe('loadTheme / saveTheme', () => {
	it('persists an explicit light choice across reload', () => {
		saveTheme('light');
		expect(loadTheme()).toBe('light');
	});

	it('persists an explicit dark choice across reload', () => {
		saveTheme('dark');
		expect(loadTheme()).toBe('dark');
	});

	it('defaults to system when no preference is stored', () => {
		expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
		expect(loadTheme()).toBe('system');
	});

	it('falls back to system when the stored value is invalid/garbage', () => {
		localStorage.setItem(THEME_STORAGE_KEY, 'not-a-real-theme');
		expect(loadTheme()).toBe('system');
	});
});

describe('resolveTheme', () => {
	it('resolves system to dark when the OS prefers dark', () => {
		stubMatchMedia(true);
		expect(resolveTheme('system')).toBe('dark');
	});

	it('resolves system to light when the OS prefers light', () => {
		stubMatchMedia(false);
		expect(resolveTheme('system')).toBe('light');
	});

	it('resolves an explicit light choice to light regardless of OS preference', () => {
		stubMatchMedia(true);
		expect(resolveTheme('light')).toBe('light');
	});

	it('resolves an explicit dark choice to dark regardless of OS preference', () => {
		stubMatchMedia(false);
		expect(resolveTheme('dark')).toBe('dark');
	});
});

describe('applyTheme', () => {
	it('sets data-theme on the document root for an explicit choice', () => {
		applyTheme('dark');
		expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

		applyTheme('light');
		expect(document.documentElement.getAttribute('data-theme')).toBe('light');
	});

	it('resolves system to the OS-preferred theme when applied', () => {
		stubMatchMedia(true);
		applyTheme('system');
		expect(document.documentElement.getAttribute('data-theme')).toBe('dark');

		stubMatchMedia(false);
		applyTheme('system');
		expect(document.documentElement.getAttribute('data-theme')).toBe('light');
	});
});
