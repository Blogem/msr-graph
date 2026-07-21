<script lang="ts">
	// Shared in-flight/loading treatment (frontend-design-system spec "Shared
	// loading and empty states" -- "In-flight fetch shows a loading state").
	// Token-styled spinner + optional label; surfaces render this instead of
	// a blank area while a fetch is pending.
	let { label = 'Loading…' }: { label?: string } = $props();
</script>

<div class="loading-state" data-testid="loading-state" role="status" aria-live="polite">
	<span class="loading-spinner" aria-hidden="true"></span>
	<span class="loading-label">{label}</span>
</div>

<style>
	.loading-state {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-4);
		color: var(--text-muted);
	}

	.loading-spinner {
		width: var(--size-3);
		height: var(--size-3);
		border-radius: 50%;
		border: 2px solid var(--border);
		border-top-color: var(--accent);
		animation: loading-spin 0.7s linear infinite;
	}

	.loading-label {
		font-size: var(--font-size-0);
	}

	@keyframes loading-spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.loading-spinner {
			animation-duration: 2.4s;
		}
	}
</style>
