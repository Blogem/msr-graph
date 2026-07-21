// Light/dark/system theming (design D6 — frontend-design-system spec "App-wide
// light/dark theming with a persisted toggle"). Pure, unit-testable helpers;
// all `window`/`document`/`localStorage` access is guarded so this module is
// safe to import during SSR/prerendering (the app is a static SPA built with
// @sveltejs/adapter-static — see webapp/svelte.config.js).
//
// `+layout.svelte` owns applying this on mount and wiring the toggle control;
// this module owns the storage/resolution logic so it can be tested without
// mounting a component.

export type Theme = 'light' | 'dark' | 'system';

export const THEME_STORAGE_KEY = 'msr-theme';

const VALID_THEMES: readonly Theme[] = ['light', 'dark', 'system'];

function isTheme(value: unknown): value is Theme {
	return typeof value === 'string' && (VALID_THEMES as readonly string[]).includes(value);
}

/** Reads the persisted theme choice. Returns 'system' if unset, invalid, or
 * localStorage is unavailable (SSR/prerender, or a browser that blocks it). */
export function loadTheme(): Theme {
	if (typeof localStorage === 'undefined') {
		return 'system';
	}
	try {
		const stored = localStorage.getItem(THEME_STORAGE_KEY);
		return isTheme(stored) ? stored : 'system';
	} catch {
		// Some browsers throw on localStorage access (e.g. privacy modes).
		return 'system';
	}
}

/** Persists the theme choice. No-ops if localStorage is unavailable. */
export function saveTheme(theme: Theme): void {
	if (typeof localStorage === 'undefined') {
		return;
	}
	try {
		localStorage.setItem(THEME_STORAGE_KEY, theme);
	} catch {
		// Ignore write failures (quota, privacy mode) -- theming still works
		// for the current session via applyTheme, it just won't persist.
	}
}

/** Resolves 'system' to the OS preference via matchMedia; 'light'/'dark' pass
 * through unchanged. Falls back to 'light' if matchMedia is unavailable. */
export function resolveTheme(theme: Theme): 'light' | 'dark' {
	if (theme !== 'system') {
		return theme;
	}
	if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
		return 'light';
	}
	return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/** Applies the resolved theme to the document root via `data-theme`, the
 * attribute app.css themes off of. No-ops if `document` is unavailable. */
export function applyTheme(theme: Theme): void {
	if (typeof document === 'undefined') {
		return;
	}
	document.documentElement.setAttribute('data-theme', resolveTheme(theme));
}
