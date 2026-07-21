<script lang="ts">
	import { page } from '$app/state';
	import './app.css';

	let { children } = $props();

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
	</nav>

	<main data-testid="app-main">
		{@render children()}
	</main>
</div>
