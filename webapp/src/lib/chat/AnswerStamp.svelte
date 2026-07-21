<script lang="ts">
	// Renders the `answer` trace event as a visible groundedness stamp
	// (chat-ui spec "Answer groundedness is stamped"): grounded shows the
	// aggregated provenance chain, ungrounded is visibly flagged as
	// unsourced.
	import type { AnswerPayload } from '$lib/types';
	import ProvenanceChips from './ProvenanceChips.svelte';

	let { answer }: { answer: AnswerPayload } = $props();
</script>

<div class="answer-stamp" data-testid="answer-stamp" data-grounded={answer.grounded ? 'true' : 'false'}>
	{#if answer.grounded}
		<span class="stamp-badge stamp-grounded">Grounded</span>
		{#if answer.provenance}
			<ProvenanceChips provenance={answer.provenance} />
		{/if}
	{:else}
		<span class="stamp-badge stamp-ungrounded" role="alert">Unsourced answer</span>
	{/if}
</div>
