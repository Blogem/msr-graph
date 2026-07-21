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
							<a class="identifier" href={item.citedIn} target="_blank" rel="noreferrer"
								>{item.citedIn}</a
							>
						{:else}
							<span class="cited-in identifier">{item.citedIn}</span>
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
		gap: var(--space-2);
	}

	li {
		border-left: 3px solid var(--border);
		padding: var(--space-1) var(--space-2);
	}

	.meta {
		font-size: var(--font-size-0);
		opacity: 0.75;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		min-width: 0;
	}

	.meta .identifier {
		flex: 1 1 auto;
	}

	.offsets {
		flex-shrink: 0;
	}

	.empty {
		opacity: 0.7;
		font-size: var(--font-size-0);
	}
</style>
