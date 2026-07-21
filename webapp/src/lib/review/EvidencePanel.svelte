<script lang="ts">
	// Evidence panel (review-ui spec "Evidence panel shows source spans
	// and document links"): sentence text, citedIn document, and the
	// start/end offsets for every msr:Evidence node a proposal cites.
	import type { Evidence } from '$lib/api';

	let { evidence }: { evidence: Evidence[] } = $props();

	function isLink(citedIn: string): boolean {
		return /^https?:\/\//i.test(citedIn);
	}
</script>

<div data-testid="evidence-panel">
	<h3>Evidence</h3>
	{#if evidence.length === 0}
		<p class="empty">No evidence recorded.</p>
	{:else}
		<ul>
			{#each evidence as item, i (i)}
				<li data-testid="evidence-item">
					<p class="text">{item.text}</p>
					<p class="meta">
						{#if isLink(item.citedIn)}
							<a href={item.citedIn} target="_blank" rel="noreferrer">{item.citedIn}</a>
						{:else}
							<span class="cited-in">{item.citedIn}</span>
						{/if}
						<span class="offsets">[{item.startOffset}-{item.endOffset}]</span>
					</p>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	li {
		border-left: 3px solid #ccc;
		padding: 0.25rem 0.5rem;
	}

	.meta {
		font-size: 0.85rem;
		opacity: 0.75;
		display: flex;
		gap: 0.5rem;
	}

	.empty {
		opacity: 0.7;
		font-size: 0.9rem;
	}
</style>
