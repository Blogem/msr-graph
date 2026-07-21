<script lang="ts">
	// Fallback renderer for a trace event of an unrecognized type (chat-ui
	// spec "Unknown event types degrade gracefully"). Rendering this must
	// never throw -- JSON.stringify on arbitrary `unknown` data can throw
	// only for circular structures, which the SSE parser's JSON.parse
	// output cannot produce, so this is safe for any parsed payload.
	let { eventType, raw }: { eventType: string; raw: unknown } = $props();

	function stringify(value: unknown): string {
		try {
			return JSON.stringify(value, null, 2) ?? String(value);
		} catch {
			return String(value);
		}
	}
</script>

<div class="trace-raw" data-testid="trace-raw" data-event-type={eventType}>
	<span class="event-label">Unrecognized event: {eventType}</span>
	<pre>{stringify(raw)}</pre>
</div>
