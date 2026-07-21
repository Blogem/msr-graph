<script lang="ts">
	// Shared empty-list treatment (frontend-design-system spec "Shared loading
	// and empty states" -- "Empty list shows a meaningful message"). Accepts a
	// message either via the `message` prop or, for richer content (e.g. the
	// chat surface's clickable example prompts), via the default slot/children.
	import type { Snippet } from 'svelte';

	let {
		message = 'Nothing here yet.',
		children
	}: { message?: string; children?: Snippet } = $props();
</script>

<div class="empty-state" data-testid="empty-state">
	{#if children}
		{@render children()}
	{:else}
		<p class="empty-state-message">{message}</p>
	{/if}
</div>

<style>
	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		padding: var(--space-6);
		text-align: center;
		color: var(--text-muted);
	}

	.empty-state-message {
		margin: 0;
		font-size: var(--font-size-0);
	}
</style>
