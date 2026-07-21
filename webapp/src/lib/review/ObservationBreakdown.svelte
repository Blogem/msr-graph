<script lang="ts">
	// Observation breakdown (review-ui spec "Evidence panel shows source
	// spans and document links" -- the same requirement's second half:
	// "SHALL present the proposal's observation breakdown grouped by
	// corpus and document"): per corpus, lists each document's latest
	// occurrence count and when it was observed, so the reviewer can see
	// how broadly and how often the candidate is attested (design D7).
	// Rendered as a sibling of EvidencePanel rather than folded into it --
	// evidence (sampled sentences) and observations (complete counts) are
	// deliberately separate layers (design "Risks" -- hasEvidence vs
	// observations divergence).
	import type { ObservationBreakdown } from '$lib/api';
	import { corpusLabel } from './triples';

	let { observations }: { observations: ObservationBreakdown } = $props();

	function isLink(documentId: string): boolean {
		return /^https?:\/\//i.test(documentId);
	}
</script>

<div data-testid="observation-breakdown">
	<h3>Observations</h3>
	{#if observations.length === 0}
		<p class="empty">No corpus observations recorded.</p>
	{:else}
		<ul>
			{#each observations as group (group.corpus)}
				<li data-testid="observation-corpus-group" data-corpus={group.corpus}>
					<p class="corpus-name">{corpusLabel(group.corpus)}</p>
					<ul class="documents">
						{#each group.documents as doc (doc.documentId)}
							<li data-testid="observation-document">
								{#if isLink(doc.documentId)}
									<a class="identifier" href={doc.documentId} target="_blank" rel="noreferrer"
										>{doc.documentId}</a
									>
								{:else}
									<span class="identifier">{doc.documentId}</span>
								{/if}
								<span class="occurrence-count">{doc.occurrenceCount} occurrences</span>
								<span class="last-observed">last observed {doc.lastObserved}</span>
							</li>
						{/each}
					</ul>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	div > ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.corpus-name {
		font-weight: 700;
		font-size: var(--font-size-0);
		text-transform: capitalize;
		margin: 0 0 var(--space-1);
	}

	.documents {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.documents li {
		border-left: 3px solid var(--border);
		padding: var(--space-1) var(--space-2);
		font-size: var(--font-size-0);
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.identifier {
		flex: 1 1 auto;
		min-width: 0;
	}

	.occurrence-count,
	.last-observed {
		flex-shrink: 0;
		opacity: 0.75;
	}

	.empty {
		opacity: 0.7;
		font-size: var(--font-size-0);
	}
</style>
