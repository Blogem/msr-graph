<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import './app.css';
	import { loadTheme, saveTheme, applyTheme, type Theme } from '$lib/theme';
	import Toaster from '$lib/ui/Toaster.svelte';

	let { children } = $props();

	// frontend-design-system spec "App-wide light/dark theming with a
	// persisted toggle": defaults to 'system' until onMount reads the
	// persisted choice (see $lib/theme.ts -- SSR/prerender-safe, so this
	// initial value is what a prerendered page's markup sees).
	let theme = $state<Theme>('system');

	onMount(() => {
		theme = loadTheme();
		applyTheme(theme);

		if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
			return;
		}
		// While following 'system', react live to an OS-level scheme change
		// (spec scenario "system preference is followed by default") rather
		// than only resolving it once at load.
		const media = window.matchMedia('(prefers-color-scheme: dark)');
		const handleSystemChange = () => {
			if (theme === 'system') {
				applyTheme(theme);
			}
		};
		media.addEventListener('change', handleSystemChange);
		return () => media.removeEventListener('change', handleSystemChange);
	});

	function handleThemeChange(next: Theme): void {
		theme = next;
		saveTheme(next);
		applyTheme(next);
	}

	// The three routed surfaces (frontend-app-shell spec: "Client-side
	// routing across the three surfaces"). Wave-2 surface agents fill in
	// the pages this nav links to; this list is the single place a new
	// surface would be added.
	const surfaces = [
		{ href: '/', label: 'Chat', testId: 'nav-link-chat' },
		{ href: '/review', label: 'Review', testId: 'nav-link-review' },
		{ href: '/admin', label: 'Admin', testId: 'nav-link-admin' }
	];

	function isActive(href: string): boolean {
		if (href === '/') return page.url.pathname === '/';
		return page.url.pathname.startsWith(href);
	}
</script>

<div class="app-shell">
	<nav data-testid="app-nav" aria-label="Main">
		<ul>
			{#each surfaces as surface (surface.href)}
				<li>
					<a
						href={surface.href}
						data-testid={surface.testId}
						aria-current={isActive(surface.href) ? 'page' : undefined}
					>
						{surface.label}
					</a>
				</li>
			{/each}
		</ul>

		<div class="theme-control">
			<label for="theme-toggle-select">Theme</label>
			<select
				id="theme-toggle-select"
				data-testid="theme-toggle"
				value={theme}
				onchange={(event) => handleThemeChange(event.currentTarget.value as Theme)}
			>
				<option value="system">System</option>
				<option value="light">Light</option>
				<option value="dark">Dark</option>
			</select>
		</div>
	</nav>

	<main data-testid="app-main">
		{@render children()}
	</main>

	<Toaster />
</div>

<style>
	.theme-control {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--font-size-0);
		color: var(--text-muted);
	}

	.theme-control select {
		border: 1px solid var(--border);
		border-radius: var(--radius-1);
		background: var(--surface-2);
		color: var(--text);
		padding: var(--space-1) var(--space-2);
	}
</style>
