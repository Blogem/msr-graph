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
	import LoadingState from '$lib/ui/LoadingState.svelte';
	import EmptyState from '$lib/ui/EmptyState.svelte';
	import { pushToast } from '$lib/ui/toast.svelte';
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

	/** Humanizes a raw document-frequency count for the queue row (review-ui
	 * spec "Document frequency is humanized", design D3): "seen in 1
	 * document" / "seen in 47 documents" with correct singular/plural,
	 * rather than a bare number. */
	function humanizeDocFrequency(count: number): string {
		return `seen in ${count} document${count === 1 ? '' : 's'}`;
	}

	let statusFilter = $state('pending');
	let proposals = $state<ProposalSummary[]>([]);
	let queueLoading = $state(false);
	let queueError = $state<string | null>(null);
	let queueEl: HTMLUListElement | undefined = $state();

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
		queueLoading = true;
		try {
			const res = await listProposals(statusFilter || undefined);
			proposals = res.proposals;
		} catch (err) {
			queueError = err instanceof ApiError ? err.message : 'Failed to load proposals';
		} finally {
			queueLoading = false;
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
			pushToast({ message: `Proposal ${detail.id} approved`, kind: 'success' });
		} catch (err) {
			handleActionError(err);
			pushToast({ message: actionError ?? 'Approve failed', kind: 'error' });
		}
	}

	async function reject() {
		if (!detail) return;
		actionError = null;
		shaclViolations = null;
		try {
			const res = await rejectProposal(detail.id);
			applyStatus(detail.id, res.status);
			pushToast({ message: `Proposal ${detail.id} rejected`, kind: 'success' });
		} catch (err) {
			handleActionError(err);
			pushToast({ message: actionError ?? 'Reject failed', kind: 'error' });
		}
	}

	// --- Keyboard navigation (review-ui spec "Proposal queue is
	// keyboard-navigable", task 3.3) --- PINNED keys: j/ArrowDown = next,
	// k/ArrowUp = previous, a = approve selected, r = reject selected.
	// Reuses the same approve()/reject() handlers as the buttons so their
	// confirmation/validation (incl. SHACL 422) paths are unchanged. The
	// listener is bound to the proposal-queue container itself (it is
	// focusable -- tabindex + role="listbox" -- so "the queue is focused"
	// from the spec's scenario is literally true), with a defensive
	// input/textarea/select guard kept in case focus is ever routed into an
	// editable control from within the queue's subtree (editing
	// placement/unit must never be hijacked).
	function isEditableTarget(target: EventTarget | null): boolean {
		if (!(target instanceof HTMLElement)) return false;
		const tag = target.tagName;
		return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
	}

	function focusRow(id: string) {
		const button = queueEl?.querySelector<HTMLButtonElement>(`button[data-id="${id}"]`);
		button?.focus();
	}

	function moveSelection(delta: number) {
		if (proposals.length === 0) return;
		const currentIndex = proposals.findIndex((p) => p.id === selectedId);
		const nextIndex =
			currentIndex === -1 ? 0 : (currentIndex + delta + proposals.length) % proposals.length;
		const nextId = proposals[nextIndex].id;
		void selectProposal(nextId);
		focusRow(nextId);
	}

	function handleSurfaceKeydown(event: KeyboardEvent) {
		if (isEditableTarget(event.target) || event.ctrlKey || event.metaKey || event.altKey) return;
		switch (event.key) {
			case 'j':
			case 'ArrowDown':
				event.preventDefault();
				moveSelection(1);
				break;
			case 'k':
			case 'ArrowUp':
				event.preventDefault();
				moveSelection(-1);
				break;
			case 'a':
				if (!detail) return;
				event.preventDefault();
				void approve();
				break;
			case 'r':
				if (!detail) return;
				event.preventDefault();
				void reject();
				break;
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
		<ul
			data-testid="proposal-queue"
			bind:this={queueEl}
			tabindex="0"
			role="listbox"
			aria-label="Proposal queue"
			onkeydown={handleSurfaceKeydown}
		>
			{#if queueLoading}
				<li class="queue-status"><LoadingState label="Loading proposals…" /></li>
			{:else if proposals.length === 0}
				<li class="queue-status empty"><EmptyState message="No proposals." /></li>
			{:else}
				{#each proposals as p (p.id)}
					<li>
						<button
							type="button"
							data-testid="proposal-row"
							data-id={p.id}
							class="proposal-row"
							class:selected={p.id === selectedId}
							role="option"
							aria-selected={p.id === selectedId}
							onclick={() => selectProposal(p.id)}
						>
							<span class="row-line row-line-1">
								<span class="field term">{p.term}</span>
								<span class="row-pills">
									<span class="field kind pill">{p.kind}</span>
									<span
										class="field status pill"
										class:pill-pending={p.status === 'pending'}
										class:pill-approved={p.status === 'approved'}
										class:pill-rejected={p.status === 'rejected'}
									>
										{p.status}
									</span>
								</span>
							</span>
							<span class="row-line row-line-2">
								<span class="field doc-frequency">{humanizeDocFrequency(p.docFrequency)}</span>
								<span class="field id identifier">{p.id}</span>
							</span>
						</button>
					</li>
				{/each}
			{/if}
		</ul>

		{#if selectedId}
			<div data-testid="proposal-detail">
				{#if notFound}
					<p data-testid="not-found">Proposal {selectedId} was not found.</p>
				{:else if detailLoading}
					<LoadingState label="Loading proposal…" />
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
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	.layout {
		display: flex;
		gap: var(--space-5);
		align-items: flex-start;
	}

	ul[data-testid='proposal-queue'] {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 20rem;
		min-height: 3rem;
	}

	ul[data-testid='proposal-queue']:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	.queue-status {
		border: 1px solid var(--border);
		border-radius: var(--radius-2);
		background: var(--surface-2);
	}

	/* Card-style row (design D3): two lines -- term headline + kind/status
	   pills on line 1, humanized doc-frequency + de-emphasized id on line 2. */
	button.proposal-row {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		width: 100%;
		min-width: 0;
		text-align: left;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--border);
		border-radius: var(--radius-2);
		background: var(--surface-2);
		box-shadow: var(--shadow-1);
		font: inherit;
		cursor: pointer;
	}

	button.proposal-row.selected {
		border-color: var(--accent);
		background: var(--surface-3);
	}

	.row-line {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		min-width: 0;
	}

	.row-line-1 {
		justify-content: space-between;
	}

	.row-pills {
		display: flex;
		gap: var(--space-1);
		flex-shrink: 0;
	}

	.field.term {
		font-size: var(--font-size-1);
		font-weight: 700;
		color: var(--text);
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.field.pill {
		display: inline-block;
		font-size: var(--font-size-0);
		line-height: 1;
		border-radius: var(--radius-1);
		padding: var(--space-1) var(--space-2);
		background: var(--surface-3);
		color: var(--text-muted);
		text-transform: capitalize;
		white-space: nowrap;
	}

	.field.status.pill-pending {
		background: var(--warning-bg);
		color: var(--warning-text);
	}

	.field.status.pill-approved {
		background: var(--grounded-bg);
		color: var(--grounded-text);
	}

	.field.status.pill-rejected {
		background: var(--error-bg);
		color: var(--error-text);
	}

	.row-line-2 {
		justify-content: space-between;
		font-size: var(--font-size-0);
		color: var(--text-muted);
	}

	.field.doc-frequency {
		flex-shrink: 0;
		white-space: nowrap;
	}

	.field.id {
		text-align: right;
		font-family: var(--font-mono);
	}

	[data-testid='proposal-detail'] {
		flex: 1;
		min-width: 0;
	}

	.badge {
		font-size: var(--font-size-0);
		border-radius: var(--radius-3);
		padding: var(--space-1) var(--space-2);
		border: 1px solid currentColor;
		vertical-align: middle;
		margin-left: var(--space-2);
		text-transform: uppercase;
	}

	.edit-fields {
		display: flex;
		gap: var(--space-4);
		align-items: flex-end;
		flex-wrap: wrap;
		margin: var(--space-3) 0;
	}

	.edit-fields label {
		display: flex;
		flex-direction: column;
		font-size: var(--font-size-0);
		gap: var(--space-1);
	}

	.actions {
		display: flex;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	[data-testid='shacl-error'] {
		border: 1px solid var(--error-text);
		color: var(--error-text);
		background: var(--error-bg);
		border-radius: var(--radius-1);
		padding: var(--space-2) var(--space-3);
		margin-bottom: var(--space-3);
	}

	[data-testid='shacl-error'] ul {
		margin: var(--space-1) 0 0;
		padding-left: 1.1rem;
	}

	[data-testid='shacl-error'] .path,
	[data-testid='shacl-error'] .constraint {
		font-weight: 600;
		margin-right: var(--space-1);
	}

	[data-testid='raw-triples'] {
		background: var(--surface-3);
		border-radius: var(--radius-1);
		padding: var(--space-2);
		overflow: auto;
		max-height: 20rem;
	}

	.error {
		color: var(--error-text);
	}
</style>
