<script lang="ts">
	// Renders the shared toast list (see `toast.svelte.ts`). Mount once in
	// the app shell (`+layout.svelte`) -- every surface pushes into the same
	// store, so there is exactly one live region on the page (frontend-design-
	// system spec "announced to assistive technology via a live region").
	import { toasts, dismissToast } from './toast.svelte';
</script>

<div class="toast-region" data-testid="toast-region" role="status" aria-live="polite">
	{#each toasts as toast (toast.id)}
		<div class="toast" data-testid="toast" data-kind={toast.kind}>
			<span class="toast-message">{toast.message}</span>
			<button
				class="toast-dismiss"
				type="button"
				aria-label="Dismiss notification"
				onclick={() => dismissToast(toast.id)}
			>
				&times;
			</button>
		</div>
	{/each}
</div>

<style>
	/* Fixed, pointer-events: none on the region so an empty/transparent area
	   never blocks clicks on the page beneath it (spec "does not trap focus
	   / overlay-block the page"); individual toasts opt back into pointer
	   events so their dismiss button stays clickable. */
	.toast-region {
		position: fixed;
		inset-block-end: var(--space-4);
		inset-inline-end: var(--space-4);
		z-index: var(--layer-4, 400);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		pointer-events: none;
		max-width: min(24rem, calc(100vw - 2 * var(--space-4)));
	}

	.toast {
		pointer-events: auto;
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		border-radius: var(--radius-2);
		box-shadow: var(--shadow-2);
		padding: var(--space-3) var(--space-4);
		background: var(--surface-2);
		color: var(--text);
		border: 1px solid var(--border);
	}

	.toast[data-kind='success'] {
		background: var(--grounded-bg);
		color: var(--grounded-text);
		border-color: transparent;
	}

	.toast[data-kind='error'] {
		background: var(--error-bg);
		color: var(--error-text);
		border-color: transparent;
	}

	.toast-message {
		flex: 1;
		font-size: var(--font-size-0);
	}

	.toast-dismiss {
		appearance: none;
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
		font-size: var(--font-size-2);
		line-height: 1;
		padding: 0;
		opacity: 0.7;
	}

	.toast-dismiss:hover {
		opacity: 1;
	}
</style>
