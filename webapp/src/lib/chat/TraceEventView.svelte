<script lang="ts">
	// Dispatches one TraceEvent to its per-type renderer (chat-ui spec
	// "Trace timeline renders every event type" / design D4). The
	// `'raw' in event` check is checked first and narrows the union down
	// to UnknownTraceEvent (the only member declaring a `raw` field)
	// before the remaining `event.type === '...'` checks run, so those
	// checks narrow cleanly against a purely-literal-discriminant union
	// instead of also matching UnknownTraceEvent's wide `type: string`.
	import type { TraceEvent } from '$lib/types';
	import ToolCallView from './ToolCallView.svelte';
	import ToolResultView from './ToolResultView.svelte';
	import ScriptRunView from './ScriptRunView.svelte';
	import ProvenanceChips from './ProvenanceChips.svelte';
	import AnswerStamp from './AnswerStamp.svelte';
	import RawEventView from './RawEventView.svelte';

	let { event }: { event: TraceEvent } = $props();
</script>

<div class="trace-event" data-testid="trace-event" data-event-type={event.type}>
	{#if 'raw' in event}
		<RawEventView eventType={event.type} raw={event.raw} />
	{:else if event.type === 'tool_call'}
		<ToolCallView toolCall={event.tool_call} />
	{:else if event.type === 'tool_result'}
		<ToolResultView toolResult={event.tool_result} />
	{:else if event.type === 'script_run'}
		<ScriptRunView scriptRun={event.script_run} />
	{:else if event.type === 'provenance'}
		<ProvenanceChips provenance={event.provenance} />
	{:else if event.type === 'answer'}
		<AnswerStamp answer={event.answer} />
	{:else if event.type === 'text'}
		<p class="trace-text">{event.text}</p>
	{:else if event.type === 'error'}
		<p class="trace-error" role="alert">{event.error}</p>
	{:else if event.type === 'done'}
		<p class="trace-done">Turn complete.</p>
	{/if}
</div>
