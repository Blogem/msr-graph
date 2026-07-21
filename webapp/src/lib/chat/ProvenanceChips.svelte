<script lang="ts">
	// Renders one `provenance` payload as a row of chips: data locators,
	// dataset DOI(s), cited-in document(s), and the ontology version
	// (chat-ui spec "Provenance rendered as source-linking chips").
	// Reused by AnswerStamp for the grounded answer's aggregated
	// provenance chain (chat-ui spec 3.5).
	import type { ProvenancePayload } from '$lib/types';

	// `containerTestId`/`chipTestId` default to the standalone `provenance`
	// event's testids. AnswerStamp overrides them when embedding this same
	// component for the grounded answer's aggregated chain, so a turn that
	// carries both a standalone `provenance` event and a grounded `answer`
	// event (each with its own provenance payload) doesn't render two
	// elements sharing the identical `provenance-chips` testid.
	let {
		provenance,
		containerTestId = 'provenance-chips',
		chipTestId = 'provenance-chip'
	}: { provenance: ProvenancePayload; containerTestId?: string; chipTestId?: string } = $props();

	interface Chip {
		kind: string;
		label: string;
		value: string;
		href: string | null;
	}

	/** A DOI is rendered as a doi.org link (or used as-is if already a
	 * full URL); other identifiers are only linked when they already look
	 * like a URL, per the spec's "render as links where a URL/identifier
	 * is present" -- a bare document id with no resolvable URL is still
	 * shown as a chip, just not hyperlinked. */
	function doiHref(doi: string): string {
		return /^https?:\/\//i.test(doi) ? doi : `https://doi.org/${doi}`;
	}

	function urlHref(value: string): string | null {
		return /^https?:\/\//i.test(value) ? value : null;
	}

	// `cited_in` tolerates being empty/absent without error (spec
	// scenario "Provenance chips name the sources"): an empty array just
	// contributes no chips below, never a null-reference failure.
	let chips = $derived<Chip[]>([
		...(provenance.data_locators ?? []).map((loc) => ({
			kind: 'data-locator',
			label: 'Data locator',
			value: loc,
			href: urlHref(loc)
		})),
		...(provenance.dataset_dois ?? []).map((doi) => ({
			kind: 'dataset-doi',
			label: 'Dataset DOI',
			value: doi,
			href: doiHref(doi)
		})),
		...(provenance.cited_in ?? []).map((citation) => ({
			kind: 'cited-in',
			label: 'Cited in',
			value: citation,
			href: urlHref(citation)
		})),
		...(provenance.ontology_version
			? [
					{
						kind: 'ontology-version',
						label: 'Ontology version',
						value: provenance.ontology_version,
						href: null
					}
				]
			: [])
	]);
</script>

<div class="provenance-chips" data-testid={containerTestId}>
	{#if chips.length === 0}
		<span class="provenance-empty">No provenance recorded</span>
	{/if}
	{#each chips as chip (chip.kind + '|' + chip.value)}
		<span class="provenance-chip" data-testid={chipTestId} data-chip-kind={chip.kind}>
			<span class="chip-label">{chip.label}:</span>
			{#if chip.href}
				<a href={chip.href} target="_blank" rel="noreferrer">{chip.value}</a>
			{:else}
				<span class="chip-value">{chip.value}</span>
			{/if}
		</span>
	{/each}
</div>
