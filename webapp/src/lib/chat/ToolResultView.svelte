<script lang="ts">
	// Renders a `tool_result` trace event: the result content (bindings
	// or rows serialized as text by the server), a truncated badge when
	// the server truncated it, and an expand affordance (chat-ui spec 3.3
	// "tool_result: bindings/rows, truncated + expand").
	import type { ToolResultPayload } from '$lib/types';

	let { toolResult }: { toolResult: ToolResultPayload } = $props();

	let expanded = $state(false);

	const PREVIEW_LENGTH = 400;

	let isLong = $derived(toolResult.content.length > PREVIEW_LENGTH);
	let displayContent = $derived(
		expanded || !isLong ? toolResult.content : toolResult.content.slice(0, PREVIEW_LENGTH) + '…'
	);
</script>

<div class="tool-result" data-testid="tool-result">
	<span class="event-label">Tool result: {toolResult.name}</span>
	{#if toolResult.truncated}
		<span class="badge-truncated">truncated by server</span>
	{/if}
	<pre data-testid="tool-result-content">{displayContent}</pre>
	{#if isLong || toolResult.truncated}
		<button type="button" data-testid="tool-result-expand" onclick={() => (expanded = !expanded)}>
			{expanded ? 'Show less' : 'Show more'}
		</button>
	{/if}
</div>
