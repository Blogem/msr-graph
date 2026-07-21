<script lang="ts">
	// Highlighted ontology-neighborhood diff (review-ui spec "Proposal
	// detail rendered as an ontology-neighborhood diff", design D5): a
	// focused node/edge list with highlighting, not a graph-viz library.
	import type { NeighborhoodTriple, Triple } from '$lib/api';
	import { buildDiff, localName } from './triples';

	let { triples, neighborhood }: { triples: Triple[]; neighborhood: NeighborhoodTriple[] } =
		$props();

	let diff = $derived(buildDiff(triples, neighborhood));

	// Keyed-each key for an edge row. Concatenated via a named-constant
	// delimiter (String.fromCharCode) rather than an inline character
	// literal so this file stays plain ASCII text with no embedded
	// control byte -- see ./triples.ts's KEY_DELIMITER for the same
	// pattern applied to the diff's own edge map keys.
	const EDGE_KEY_DELIMITER = String.fromCharCode(0);
	function edgeKey(edge: { subject: string; predicate: string; object: string }): string {
		return edge.subject + EDGE_KEY_DELIMITER + edge.predicate + EDGE_KEY_DELIMITER + edge.object;
	}
</script>

<div data-testid="diff-view">
	<section class="diff-nodes">
		<h3>Nodes</h3>
		{#if diff.nodes.length === 0}
			<p class="empty">No nodes in this neighborhood.</p>
		{:else}
			<ul>
				{#each diff.nodes as node (node.iri)}
					<li
						data-testid={node.added ? 'diff-added' : undefined}
						data-added={node.added ? 'true' : undefined}
						class:diff-added={node.added}
						class="identifier"
						title={node.iri}
					>
						{localName(node.iri)}
					</li>
				{/each}
			</ul>
		{/if}
	</section>
	<section class="diff-edges">
		<h3>Edges</h3>
		{#if diff.edges.length === 0}
			<p class="empty">No edges in this neighborhood.</p>
		{:else}
			<ul>
				{#each diff.edges as edge (edgeKey(edge))}
					<li
						data-testid={edge.added ? 'diff-added' : undefined}
						data-added={edge.added ? 'true' : undefined}
						class:diff-added={edge.added}
						title={`${edge.subject} ${edge.predicate} ${edge.object}`}
					>
						<span class="s identifier">{localName(edge.subject)}</span>
						<span class="p identifier">{localName(edge.predicate)}</span>
						<span class="o identifier">{localName(edge.object)}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</div>

<style>
	.diff-nodes ul,
	.diff-edges ul {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.diff-nodes li,
	.diff-edges li {
		border: 1px solid var(--border);
		border-radius: var(--radius-1);
		padding: var(--space-1) var(--space-2);
		font-size: var(--font-size-0);
	}

	.diff-edges li {
		display: flex;
		gap: var(--space-1);
		min-width: 0;
		max-width: 100%;
	}

	.diff-edges .p {
		opacity: 0.7;
		font-style: italic;
	}

	.diff-added {
		background: var(--grounded-bg);
		border-color: var(--grounded-text);
		font-weight: 600;
	}

	.empty {
		opacity: 0.7;
		font-size: var(--font-size-0);
	}
</style>
