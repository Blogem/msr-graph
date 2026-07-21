<script lang="ts">
	// Per-turn expandable trace timeline: events are appended in stream
	// order as they arrive (chat-ui spec "Trace timeline renders every
	// event type" / design D4). `expanded` is bindable so the parent
	// (ChatSurface) can default a turn's timeline open while it is
	// streaming and let the user collapse/reopen it afterwards.
	import type { TraceEvent } from '$lib/types';
	import TraceEventView from './TraceEventView.svelte';

	let { events, expanded = $bindable(true) }: { events: TraceEvent[]; expanded?: boolean } =
		$props();
</script>

<div class="trace-timeline" data-testid="trace-timeline">
	<button
		type="button"
		class="trace-toggle"
		data-testid="trace-toggle"
		aria-expanded={expanded}
		onclick={() => (expanded = !expanded)}
	>
		{expanded ? 'Hide trace' : 'Show trace'} ({events.length})
	</button>
	{#if expanded}
		<ol class="trace-event-list">
			{#each events as event, index (index)}
				<li>
					<TraceEventView {event} />
				</li>
			{/each}
		</ol>
	{/if}
</div>
