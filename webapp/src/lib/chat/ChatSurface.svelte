<script lang="ts">
	// The chat surface (chat-ui spec): a stateless conversation that
	// holds its full history client-side, POSTs it in full each turn via
	// `$lib/sse`'s streamChat, and renders a per-turn expandable trace
	// timeline over every chunk-4 trace event type (design D3/D4).
	//
	// Statelessness (spec "Stateless conversation posted in full per
	// turn"): each `Turn` here doubles as the display model and the
	// client-held history entry. The assistant turn is pushed onto
	// `turns` immediately (empty content, empty trace) and mutated in
	// place as events arrive, so by the time `done` fires the assistant
	// message is already "appended to history" for the next turn -- no
	// separate history array to keep in sync.
	import { streamChat } from '$lib/sse';
	import type { ChatMessage, TraceEvent } from '$lib/types';
	import TraceTimeline from './TraceTimeline.svelte';
	import './chat.css';

	interface Turn {
		role: 'user' | 'assistant';
		content: string;
		/** Present only for assistant turns; the ordered trace events for
		 * that turn (design D4 "events are appended as they arrive"). */
		trace?: TraceEvent[];
		expanded?: boolean;
	}

	let turns = $state<Turn[]>([]);
	let input = $state('');
	let sending = $state(false);
	let errorMessage = $state<string | null>(null);

	function toHistory(items: Turn[]): ChatMessage[] {
		return items.map((turn) => ({ role: turn.role, content: turn.content }));
	}

	async function sendMessage() {
		const text = input.trim();
		if (!text || sending) return;

		errorMessage = null;
		turns.push({ role: 'user', content: text });
		input = '';

		// Full prior history plus the new user message, per the
		// stateless-conversation requirement -- built before the empty
		// assistant placeholder below is pushed, so it never appears in
		// the outgoing request body.
		const requestMessages = toHistory(turns);

		const assistantTurn: Turn = { role: 'assistant', content: '', trace: [], expanded: true };
		turns.push(assistantTurn);
		sending = true;

		try {
			await streamChat(requestMessages, (event: TraceEvent) => {
				assistantTurn.trace?.push(event);
				// `'text' in event` / `'error' in event` (rather than
				// `event.type === '...'`) narrows the union down to exactly
				// TextTraceEvent/ErrorTraceEvent -- those are the only
				// members declaring that field, so UnknownTraceEvent (whose
				// `type` is a wide `string` that could equal 'text'/'error'
				// too) is correctly excluded. See TraceEventView.svelte for
				// the same pattern.
				if ('text' in event) {
					assistantTurn.content += event.text;
				} else if ('error' in event) {
					errorMessage = event.error;
				}
			});
		} catch (err) {
			errorMessage = err instanceof Error ? err.message : 'Chat request failed.';
		} finally {
			sending = false;
		}
	}

	function handleSubmit(event: SubmitEvent) {
		event.preventDefault();
		void sendMessage();
	}
</script>

<div class="chat-surface">
	<ol class="chat-message-list">
		{#each turns as turn, index (index)}
			<li class="chat-message" data-testid="chat-message" data-role={turn.role}>
				<div class="message-role">{turn.role}</div>
				<p class="message-content">{turn.content}</p>
				{#if turn.role === 'assistant' && turn.trace}
					<TraceTimeline events={turn.trace} bind:expanded={turn.expanded} />
				{/if}
			</li>
		{/each}
	</ol>

	{#if errorMessage}
		<p class="chat-error" data-testid="chat-error" role="alert">{errorMessage}</p>
	{/if}

	<form class="chat-input-row" onsubmit={handleSubmit}>
		<input
			type="text"
			data-testid="chat-input"
			placeholder="Ask a question…"
			bind:value={input}
			disabled={sending}
		/>
		<button type="submit" data-testid="chat-send" disabled={sending || input.trim() === ''}>
			Send
		</button>
	</form>
</div>
