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
	import { renderMarkdown } from '$lib/markdown';
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
		/** True from the moment the assistant turn is created until its
		 * stream completes or errors (chat-ui spec "In-progress streaming
		 * affordance"). Drives the `streaming-indicator` caret and gates
		 * the per-answer copy action, which only makes sense once the
		 * answer text is final. */
		streaming?: boolean;
	}

	// Realistic molten-salt domain prompts (chat-ui spec "Empty conversation
	// shows onboarding prompts"), drawn from the demo queries already
	// grounded in the real corpus (see openspec/specs/analysis-agent/spec.md
	// and docs/DATA_SCOPE.md) rather than invented placeholders.
	const EXAMPLE_PROMPTS = [
		'What is the density of FLiBe (LiF-BeF₂, 66-34 mol%) at 900 K?',
		'What is the solubility of PuF₃ in a LiF-BeF₂ solvent?',
		"Which document mentions FLiBe's density measurement?"
	];

	let turns = $state<Turn[]>([]);
	let input = $state('');
	let sending = $state(false);
	let errorMessage = $state<string | null>(null);
	let copiedIndex = $state<number | null>(null);
	let copyResetTimer: ReturnType<typeof setTimeout> | undefined;

	function toHistory(items: Turn[]): ChatMessage[] {
		return items.map((turn) => ({ role: turn.role, content: turn.content }));
	}

	async function sendMessage(overrideText?: string) {
		const text = (overrideText ?? input).trim();
		if (!text || sending) return;

		errorMessage = null;
		turns.push({ role: 'user', content: text });
		input = '';

		// Full prior history plus the new user message, per the
		// stateless-conversation requirement -- built before the empty
		// assistant placeholder below is pushed, so it never appears in
		// the outgoing request body.
		const requestMessages = toHistory(turns);

		turns.push({ role: 'assistant', content: '', trace: [], expanded: true, streaming: true });
		// Re-obtain the just-pushed turn from the reactive `turns` array
		// itself rather than holding onto the plain object literal above:
		// in Svelte 5, pushing a plain object into a `$state` array wraps
		// it in a NEW proxy, so the pre-push local variable would keep
		// pointing at the original, now-detached object and mutations to
		// it would never be observed by the template. Indexing back into
		// `turns` gets the reactive proxy so `.content +=`/`.trace.push`
		// below actually trigger re-renders.
		const assistantTurn = turns[turns.length - 1];
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
			// The turn completes or errors here (chat-ui spec "In-progress
			// streaming affordance" scenario "Completed turn is not marked
			// in progress") -- both the success and error paths land in
			// this `finally`, so the caret always clears.
			assistantTurn.streaming = false;
		}
	}

	function handleSubmit(event: SubmitEvent) {
		event.preventDefault();
		void sendMessage();
	}

	function sendExamplePrompt(prompt: string) {
		void sendMessage(prompt);
	}

	async function copyAnswer(turn: Turn, index: number) {
		if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
			// No Clipboard API available (unsupported browser/insecure
			// context) -- silently skip rather than throwing.
			return;
		}
		try {
			await navigator.clipboard.writeText(turn.content);
		} catch {
			return;
		}
		copiedIndex = index;
		if (copyResetTimer) clearTimeout(copyResetTimer);
		copyResetTimer = setTimeout(() => {
			copiedIndex = null;
		}, 2000);
	}
</script>

<div class="chat-surface">
	{#if turns.length === 0}
		<div class="chat-onboarding" data-testid="chat-onboarding">
			<p class="onboarding-heading">Ask a question about molten-salt reactor materials.</p>
			<ul class="example-prompt-list">
				{#each EXAMPLE_PROMPTS as prompt (prompt)}
					<li>
						<button
							type="button"
							class="example-prompt"
							data-testid="example-prompt"
							onclick={() => sendExamplePrompt(prompt)}
						>
							{prompt}
						</button>
					</li>
				{/each}
			</ul>
		</div>
	{:else}
		<ol class="chat-message-list">
			{#each turns as turn, index (index)}
				<li class="chat-message" data-testid="chat-message" data-role={turn.role}>
					<div class="message-role">{turn.role}</div>
					{#if turn.role === 'assistant'}
						<div class="message-content">{@html renderMarkdown(turn.content)}</div>
						{#if turn.streaming}
							<span class="streaming-indicator" data-testid="streaming-indicator" aria-hidden="true"
							></span>
						{/if}
					{:else}
						<p class="message-content">{turn.content}</p>
					{/if}
					{#if turn.role === 'assistant' && turn.trace}
						<TraceTimeline events={turn.trace} bind:expanded={turn.expanded} />
					{/if}
					{#if turn.role === 'assistant' && !turn.streaming}
						<div class="message-actions">
							<button
								type="button"
								class="copy-answer-btn"
								data-testid="copy-answer"
								onclick={() => copyAnswer(turn, index)}
							>
								{copiedIndex === index ? 'Copied' : 'Copy answer'}
							</button>
						</div>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}

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
		<button
			type="submit"
			class="chat-send-btn"
			data-testid="chat-send"
			aria-label="Send message"
			disabled={sending || input.trim() === ''}
		>
			<span aria-hidden="true">→</span>
		</button>
	</form>
</div>
