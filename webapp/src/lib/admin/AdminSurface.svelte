<script lang="ts">
	// Admin surface (admin-ui spec): checkpoint list/create/restore driving
	// the chunk-9 store-checkpoint-restore API, so a pre-demo checkpoint can
	// reset the store and the evolution demo can be re-run end-to-end.
	//
	// All network access goes through the typed $lib/api client (design D6);
	// this component holds no direct store access.
	import { onMount } from 'svelte';
	import {
		listCheckpoints,
		createCheckpoint,
		restoreCheckpoint,
		ApiError,
		type CheckpointManifest
	} from '$lib/api';

	let checkpoints = $state<CheckpointManifest[]>([]);
	let listError = $state('');

	let label = $state('');
	let creating = $state(false);
	let createError = $state('');

	// Restore is a two-step flow: clicking "Restore" on an item arms the
	// confirmation (`confirmingLabel`); only clicking `restore-confirm`
	// actually fires POST /api/checkpoints/{label}/restore (spec "Restore is
	// confirmed before firing").
	let confirmingLabel = $state<string | null>(null);
	let restoring = $state(false);
	let restoreError = $state('');
	let restoreStatus = $state('');

	async function loadCheckpoints(): Promise<void> {
		try {
			const response = await listCheckpoints();
			checkpoints = response.checkpoints;
			listError = '';
		} catch (err) {
			listError = err instanceof ApiError ? err.message : 'Failed to load checkpoints.';
		}
	}

	onMount(() => {
		void loadCheckpoints();
	});

	async function handleCreate(): Promise<void> {
		const trimmed = label.trim();
		if (!trimmed) {
			createError = 'Label is required.';
			return;
		}

		creating = true;
		createError = '';
		try {
			await createCheckpoint(trimmed);
			label = '';
			// Refresh from the server rather than optimistically appending, so
			// the list always reflects what the server actually persisted.
			await loadCheckpoints();
		} catch (err) {
			// A rejected label (e.g. 400 invalid_label) must not add anything
			// to the list -- we simply don't touch `checkpoints` here.
			createError = err instanceof ApiError ? err.message : 'Failed to create checkpoint.';
		} finally {
			creating = false;
		}
	}

	function startRestore(checkpointLabel: string): void {
		confirmingLabel = checkpointLabel;
		restoreError = '';
		restoreStatus = '';
	}

	function cancelRestore(): void {
		confirmingLabel = null;
	}

	async function confirmRestore(checkpointLabel: string): Promise<void> {
		restoring = true;
		restoreError = '';
		restoreStatus = '';
		try {
			await restoreCheckpoint(checkpointLabel);
			restoreStatus = `Restored checkpoint "${checkpointLabel}".`;
			confirmingLabel = null;
		} catch (err) {
			restoreError = err instanceof ApiError ? err.message : 'Failed to restore checkpoint.';
		} finally {
			restoring = false;
		}
	}
</script>

<div class="admin-panel">
	<section class="admin-create">
		<h2>Create checkpoint</h2>
		<form
			onsubmit={(event) => {
				event.preventDefault();
				void handleCreate();
			}}
		>
			<label for="checkpoint-label">Label</label>
			<input
				id="checkpoint-label"
				data-testid="checkpoint-label-input"
				type="text"
				bind:value={label}
				disabled={creating}
			/>
			<button data-testid="checkpoint-create" type="submit" disabled={creating}>
				{creating ? 'Creating…' : 'Create checkpoint'}
			</button>
		</form>
		{#if createError}
			<p data-testid="checkpoint-error" class="error" role="alert">{createError}</p>
		{/if}
	</section>

	<section class="admin-list">
		<h2>Checkpoints</h2>
		{#if listError}
			<p class="error" role="alert">{listError}</p>
		{/if}
		<ul data-testid="checkpoint-list">
			{#each checkpoints as checkpoint (checkpoint.label)}
				<li data-testid="checkpoint-item">
					<span class="checkpoint-label">{checkpoint.label}</span>
					<span class="checkpoint-version">{checkpoint.ontology_version}</span>

					{#if confirmingLabel === checkpoint.label}
						<span class="restore-confirm-group">
							<span class="confirm-text">
								Restore "{checkpoint.label}"? This replaces the live store.
							</span>
							<button
								data-testid="restore-confirm"
								type="button"
								disabled={restoring}
								onclick={() => confirmRestore(checkpoint.label)}
							>
								{restoring ? 'Restoring…' : 'Confirm restore'}
							</button>
							<button type="button" disabled={restoring} onclick={cancelRestore}> Cancel </button>
						</span>
					{:else}
						<button
							data-testid="checkpoint-restore"
							type="button"
							onclick={() => startRestore(checkpoint.label)}
						>
							Restore
						</button>
					{/if}
				</li>
			{:else}
				<li class="empty">No checkpoints yet.</li>
			{/each}
		</ul>
		{#if restoreStatus}
			<p data-testid="restore-status" role="status">{restoreStatus}</p>
		{/if}
		{#if restoreError}
			<p data-testid="restore-error" class="error" role="alert">{restoreError}</p>
		{/if}
	</section>
</div>

<style>
	.admin-panel {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		max-width: 40rem;
	}

	.admin-create form {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	ul[data-testid='checkpoint-list'] {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	li[data-testid='checkpoint-item'] {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 0.25rem;
		flex-wrap: wrap;
	}

	.checkpoint-label {
		font-weight: 600;
	}

	.checkpoint-version {
		color: #666;
		font-family: monospace;
		font-size: 0.85em;
	}

	.restore-confirm-group {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-left: auto;
	}

	.confirm-text {
		font-size: 0.85em;
	}

	.error {
		color: #b00020;
	}

	.empty {
		color: #666;
	}
</style>
