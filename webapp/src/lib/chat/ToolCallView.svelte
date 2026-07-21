<script lang="ts">
	// Renders a `tool_call` trace event: the tool name and its raw
	// arguments string (chat-ui spec 3.3 "tool_call: name + args").
	import type { ToolCallPayload } from '$lib/types';

	let { toolCall }: { toolCall: ToolCallPayload } = $props();
</script>

<div class="tool-call">
	<span class="event-label">Tool call</span>
	<code data-testid="tool-call-name">{toolCall.name}</code>
	<pre data-testid="tool-call-args">{toolCall.arguments}</pre>
</div>
