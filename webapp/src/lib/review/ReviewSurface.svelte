<script lang="ts">
	// Review surface (review-ui spec): status-filtered proposal queue,
	// proposal detail rendered as a highlighted ontology-neighborhood
	// diff, evidence panel, editable placement/unit fields persisting via
	// whole-graph PUT, approve/reject, legible 422 SHACL surfacing, and a
	// raw-triples advanced view. Consumes $lib/api.ts unchanged; holds no
	// direct store access (design D6/D7).
	import {
		ApiError,
		approveProposal,
		editProposalGraph,
		getProposal,
		listProposals,
		rejectProposal,
		type ApiViolation,
		type ProposalDetail,
		type ProposalSummary
	} from '$lib/api';
	import DiffView from './DiffView.svelte';
	import EvidencePanel from './EvidencePanel.svelte';
	import {
		applyPlacementEdit,
		applyUnitEdit,
		placementValueOf,
		serializeTriples,
		unitValueOf
	} from './triples';

	// A fixed reviewer identity: this is a single-user POC with no auth
	// (design "Non-Goals: no auth"), so the approve endpoint's required
	// `{reviewer, timestamp}` body always carries this constant name.
	const REVIEWER = 'reviewer';

	let statusFilter = $state('pending');
	let proposals = $state<ProposalSummary[]>([]);
	let queueError = $state<string | null>(null);

	let selectedId = $state<string | null>(null);
	let selectedStatus = $state<string | null>(null);
	let detail = $state<ProposalDetail | null>(null);
	let detailLoading = $state(false);
	let detailError = $state<string | null>(null);
	let notFound = $state(false);

	let placementValue = $state('');
	let unitValue = $state('');
	let actionError = $state<string | null>(null);
	let shaclViolations = $state<ApiViolation[] | null>(null);
	let showRaw = $state(false);

	async function loadQueue() {
		queueError = null;
		try {
			const res = await listProposals(statusFilter || undefined);
			proposals = res.proposals;
		} catch (err) {
			queueError = err instanceof ApiError ? err.message : 'Failed to load proposals';
		}
	}

	function onStatusFilterChange(event: Event) {
		statusFilter = (event.currentTarget as HTMLSelectElement).value;
		void loadQueue();
	}

	async function selectProposal(id: string) {
		selectedId = id;
		selectedStatus = proposals.find((p) => p.id === id)?.status ?? null;
		detail = null;
		detailError = null;
		notFound = false;
		actionError = null;
		shaclViolations = null;
		showRaw = false;
		detailLoading = true;
		try {
			const d = await getProposal(id);
			detail = d;
			placementValue = placementValueOf(d.triples);
			unitValue = unitValueOf(d.triples);
		} catch (err) {
			if (err instanceof ApiError && err.status === 404) {
				notFound = true;
			} else {
				detailError = err instanceof ApiError ? err.message : 'Failed to load proposal';
			}
		} finally {
			detailLoading = false;
		}
	}

	function handleActionError(err: unknown) {
		if (err instanceof ApiError) {
			actionError = err.message;
			shaclViolations = err.status === 422 ? (err.violations ?? []) : null;
		} else {
			actionError = 'Request failed';
			shaclViolations = null;
		}
	}

	/** Reflects a successful approve/reject's resulting status: updates
	 * the detail view's status badge, and either drops the row from the
	 * queue (if it no longer matches the active filter) or updates it in
	 * place (review-ui spec 4.5 "removed from the pending queue view"). */
	function applyStatus(id: string, newStatus: string) {
		selectedStatus = newStatus;
		if (statusFilter && statusFilter !== newStatus) {
			proposals = proposals.filter((p) => p.id !== id);
		} else {
			proposals = proposals.map((p) => (p.id === id ? { ...p, status: newStatus } : p));
		}
	}

	async function saveEdit() {
		if (!detail) return;
		let edited = applyPlacementEdit(detail.triples, placementValue);
		edited = applyUnitEdit(edited, unitValue);

		if (edited.length === 0) {
			// Guard (4.4): never persist an edit that would empty the whole
			// proposal graph -- the edit endpoint replaces the whole graph,
			// and the server rejects an empty "triples" body 400 anyway, so
			// short-circuit before ever calling it.
			return;
		}

		actionError = null;
		shaclViolations = null;
		try {
			await editProposalGraph(detail.id, serializeTriples(edited));
			detail = { ...detail, triples: edited };
			placementValue = placementValueOf(edited);
			unitValue = unitValueOf(edited);
		} catch (err) {
			handleActionError(err);
		}
	}

	async function approve() {
		if (!detail) return;
		actionError = null;
		shaclViolations = null;
		try {
			const res = await approveProposal(detail.id, REVIEWER, new Date().toISOString());
			applyStatus(detail.id, res.status);
		} catch (err) {
			handleActionError(err);
		}
	}

	async function reject() {
		if (!detail) return;
		actionError = null;
		shaclViolations = null;
		try {
			const res = await rejectProposal(detail.id);
			applyStatus(detail.id, res.status);
		} catch (err) {
			handleActionError(err);
		}
	}

	void loadQueue();
</script>

<div data-testid="review-surface">
	<div class="toolbar">
		<label for="review-status-filter">Status</label>
		<select
			id="review-status-filter"
			data-testid="status-filter"
			value={statusFilter}
			onchange={onStatusFilterChange}
		>
			<option value="">All</option>
			<option value="pending">Pending</option>
			<option value="approved">Approved</option>
			<option value="rejected">Rejected</option>
		</select>
	</div>

	{#if queueError}
		<p class="error">{queueError}</p>
	{/if}

	<div class="layout">
		<ul data-testid="proposal-queue">
			{#each proposals as p (p.id)}
				<li>
					<button
						type="button"
						data-testid="proposal-row"
						data-id={p.id}
						class:selected={p.id === selectedId}
						onclick={() => selectProposal(p.id)}
					>
						<span class="field id">{p.id}</span>
						<span class="field kind">{p.kind}</span>
						<span class="field status">{p.status}</span>
						<span class="field term">{p.term}</span>
						<span class="field doc-frequency">{p.docFrequency}</span>
					</button>
				</li>
			{:else}
				<li class="empty">No proposals.</li>
			{/each}
		</ul>

		{#if selectedId}
			<div data-testid="proposal-detail">
				{#if notFound}
					<p data-testid="not-found">Proposal {selectedId} was not found.</p>
				{:else if detailLoading}
					<p>Loading…</p>
				{:else if detailError}
					<p class="error">{detailError}</p>
				{:else if detail}
					<h2>
						{detail.id}
						{#if selectedStatus}<span class="badge">{selectedStatus}</span>{/if}
					</h2>

					<DiffView triples={detail.triples} neighborhood={detail.neighborhood} />

					<EvidencePanel evidence={detail.evidence} />

					<div class="edit-fields">
						<label>
							Placement
							<input
								type="text"
								data-testid="edit-placement"
								bind:value={placementValue}
								placeholder="e.g. msr:PhysicalProperty or rdfs:subClassOf target"
							/>
						</label>
						<label>
							Unit
							<input
								type="text"
								data-testid="edit-unit"
								bind:value={unitValue}
								placeholder="e.g. unit:MOL-PER-MOL"
							/>
						</label>
						<button type="button" data-testid="edit-save" onclick={saveEdit}>Save</button>
					</div>

					<div class="actions">
						<button type="button" data-testid="approve-btn" onclick={approve}>Approve</button>
						<button type="button" data-testid="reject-btn" onclick={reject}>Reject</button>
					</div>

					{#if actionError}
						<div data-testid="shacl-error">
							<p>{actionError}</p>
							{#if shaclViolations && shaclViolations.length > 0}
								<ul>
									{#each shaclViolations as v, i (i)}
										<li data-testid="violation">
											{#if v.path}<span class="path">{v.path}</span>{/if}
											{#if v.constraint}<span class="constraint">{v.constraint}</span>{/if}
											{#if v.message}<span class="message">{v.message}</span>{/if}
										</li>
									{/each}
								</ul>
							{/if}
						</div>
					{/if}

					<div class="raw">
						<button type="button" data-testid="raw-toggle" onclick={() => (showRaw = !showRaw)}>
							{showRaw ? 'Hide' : 'Show'} raw triples
						</button>
						{#if showRaw}
							<pre data-testid="raw-triples">{JSON.stringify(detail.triples, null, 2)}</pre>
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	.toolbar {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
	}

	.layout {
		display: flex;
		gap: 1.5rem;
		align-items: flex-start;
	}

	ul[data-testid='proposal-queue'] {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		min-width: 20rem;
	}

	ul[data-testid='proposal-queue'] button {
		display: flex;
		gap: 0.5rem;
		width: 100%;
		text-align: left;
		padding: 0.4rem 0.5rem;
		border: 1px solid #ccc;
		border-radius: 0.25rem;
		background: none;
		font: inherit;
		cursor: pointer;
	}

	ul[data-testid='proposal-queue'] button.selected {
		border-color: currentColor;
		background: rgba(0, 0, 0, 0.06);
	}

	.field.kind,
	.field.status {
		opacity: 0.7;
	}

	[data-testid='proposal-detail'] {
		flex: 1;
		min-width: 0;
	}

	.badge {
		font-size: 0.7rem;
		border-radius: 0.75rem;
		padding: 0.1rem 0.5rem;
		border: 1px solid currentColor;
		vertical-align: middle;
		margin-left: 0.5rem;
		text-transform: uppercase;
	}

	.edit-fields {
		display: flex;
		gap: 1rem;
		align-items: flex-end;
		flex-wrap: wrap;
		margin: 0.75rem 0;
	}

	.edit-fields label {
		display: flex;
		flex-direction: column;
		font-size: 0.85rem;
		gap: 0.2rem;
	}

	.actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
	}

	[data-testid='shacl-error'] {
		border: 1px solid #b00020;
		color: #b00020;
		border-radius: 0.25rem;
		padding: 0.5rem 0.75rem;
		margin-bottom: 0.75rem;
	}

	[data-testid='shacl-error'] ul {
		margin: 0.4rem 0 0;
		padding-left: 1.1rem;
	}

	[data-testid='shacl-error'] .path,
	[data-testid='shacl-error'] .constraint {
		font-weight: 600;
		margin-right: 0.4rem;
	}

	[data-testid='raw-triples'] {
		background: rgba(0, 0, 0, 0.05);
		padding: 0.5rem;
		overflow: auto;
		max-height: 20rem;
	}

	.error {
		color: #b00020;
	}
</style>
