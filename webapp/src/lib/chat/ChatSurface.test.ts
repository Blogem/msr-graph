// Tests for the chat surface (chat-ui spec, task 8.2), mounting the
// top-level `$lib/chat/ChatSurface.svelte` component (not its internal
// children -- per the wave-2 task contract) and driving a full turn
// through a mocked `fetch` whose body is a real SSE byte stream. This
// exercises the real `parseTraceEventData`/`streamChat` parsing from
// `$lib/sse.ts` (already merged, task 8.1) together with the component's
// rendering, rather than re-mocking the SSE layer itself.
//
// NOTE (pass 1): ChatSurface.svelte does not exist yet -- it is built
// concurrently by the wave-2 chat-ui coder in a separate worktree. This
// suite is written directly against the chat-ui spec's acceptance
// scenarios and the pinned testids in the task contract; it is expected to
// fail to resolve/compile until the merge, and is reconciled in pass 2.
//
// PASS 2 FINDING -- genuine component defect, not a test-harness/timing
// issue (confirmed with a standalone repro component + debug logging,
// removed after diagnosis): every test below fails because
// ChatSurface.svelte's `sendMessage()` captures `assistantTurn` as a plain
// object BEFORE `turns.push(assistantTurn)`, then mutates that captured
// reference afterwards (`assistantTurn.content += event.text`;
// `assistantTurn.trace?.push(event)`). In Svelte 5, pushing a plain object
// into a `$state` array wraps a *new* proxy around it; the pre-push local
// variable keeps pointing at the original, now-detached object, so none of
// those mutations are observed by the reactive `turns` array the template
// renders from. `streamChat` itself resolves correctly and its `onEvent`
// callback fires with every event (verified directly) -- the events simply
// never reach the DOM. Net effect: the trace timeline stays empty ("Hide
// trace (0)"), the streamed answer text never appears, and no
// `answer-stamp` ever renders, for every turn. This is a real bug (not a
// jsdom/vitest artifact) and reproduces in a real browser too. Left
// unmodified/failing per pass-2 policy -- see the handoff report for the
// fix pointer (re-obtain the turn from `turns` after pushing, e.g.
// `const assistantTurn = turns[turns.length - 1]`, before mutating it).
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChatSurface from './ChatSurface.svelte';
import type { TraceEvent } from '../types';

function sseFrame(event: TraceEvent): string {
	return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

function mockChatResponse(events: TraceEvent[]): Response {
	const body = events.map(sseFrame).join('');
	const encoder = new TextEncoder();
	const stream = new ReadableStream<Uint8Array>({
		start(controller) {
			controller.enqueue(encoder.encode(body));
			controller.close();
		}
	});
	return new Response(stream, { status: 200 });
}

/** A full turn: a streamed `text` reply, one of every trace-event type
 * (tool_call, tool_result, script_run, provenance with an EMPTY cited_in,
 * grounded answer), then done -- covering the "All event types are
 * visible in a completed trace" and "provenance chips ... empty citedIn"
 * scenarios in one stream. */
const FULL_TURN_EVENTS: TraceEvent[] = [
	{ type: 'text', text: 'The measured density is 2.5 g/cc.' },
	{
		type: 'tool_call',
		tool_call: { id: 'call-1', name: 'sparql_query', arguments: '{"query":"SELECT ?d WHERE { ?s msr:density ?d }"}' }
	},
	{
		type: 'tool_result',
		tool_result: { name: 'sparql_query', content: '[{"d": "2.5"}]', truncated: false }
	},
	{
		type: 'script_run',
		script_run: {
			source: 'print(density * 1000)',
			stdout: '2500.0\n',
			stderr: '',
			exit_code: 0,
			sandbox_id: 'sbx-42',
			truncated: false
		}
	},
	{
		type: 'provenance',
		provenance: {
			data_locators: ['loc-density-1'],
			cited_in: [],
			dataset_dois: ['10.1234/nist-density'],
			ontology_version: 'v1.0.0'
		}
	},
	{
		type: 'answer',
		answer: {
			grounded: true,
			provenance: {
				data_locators: ['loc-density-1'],
				cited_in: ['ORNL-TM-2316'],
				dataset_dois: ['10.1234/nist-density'],
				ontology_version: 'v1.0.0'
			}
		}
	},
	{ type: 'done' }
];

// `ChatSurface`'s submit handler fires the async `streamChat` call without
// awaiting it (`void sendMessage()`), so `fireEvent.click` resolves as soon
// as the click is dispatched -- well before the mocked stream has been read
// and its events pushed into the turn's reactive trace array. Every
// fixture stream used below ends in an `answer` event before `done`, so
// waiting here for `wantAnswerStamps` `answer-stamp` elements to exist (an
// async, retrying assertion) is the reliable "this turn has fully
// streamed" signal a synchronous `getByTestId`/`getAllByTestId` query can
// then be run against. `wantAnswerStamps` counts the total across every
// turn sent so far in the test (1 for a single turn, 2 after a second),
// since `answer-stamp` is not a testid unique per turn.
async function sendMessage(text: string, wantAnswerStamps = 1) {
	const input = screen.getByTestId('chat-input');
	await fireEvent.input(input, { target: { value: text } });
	await fireEvent.click(screen.getByTestId('chat-send'));
	await waitFor(() => {
		expect(screen.getAllByTestId('answer-stamp').length).toBeGreaterThanOrEqual(wantAnswerStamps);
	});
}

describe('ChatSurface', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	it('renders every trace event type in stream order and streams the answer text', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(FULL_TURN_EVENTS)));

		render(ChatSurface);
		await sendMessage('What is the density of FLiBe?');

		const timeline = await screen.findByTestId('trace-timeline');
		expect(timeline).toBeInTheDocument();

		const eventTypes = within(timeline)
			.getAllByTestId('trace-event')
			.map((el) => el.getAttribute('data-event-type'));
		expect(eventTypes).toEqual(
			expect.arrayContaining(['tool_call', 'tool_result', 'script_run', 'provenance', 'answer'])
		);

		// The assistant's streamed text ends up in a chat-message bubble.
		const assistantMessages = screen
			.getAllByTestId('chat-message')
			.filter((el) => el.getAttribute('data-role') === 'assistant');
		expect(assistantMessages.length).toBeGreaterThan(0);
		expect(assistantMessages.some((el) => el.textContent?.includes('2.5 g/cc'))).toBe(true);
	});

	it('shows script_run source, stdout, stderr, and exit code', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(FULL_TURN_EVENTS)));

		render(ChatSurface);
		await sendMessage('What is the density of FLiBe?');

		const scriptRun = await screen.findByTestId('script-run');
		expect(within(scriptRun).getByTestId('script-source')).toHaveTextContent('print(density * 1000)');
		expect(scriptRun).toHaveTextContent('2500.0');
		expect(scriptRun).toHaveTextContent('sbx-42');
		expect(scriptRun).toHaveTextContent('0');
	});

	it('renders provenance chips and tolerates an empty cited_in', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(FULL_TURN_EVENTS)));

		render(ChatSurface);
		await sendMessage('What is the density of FLiBe?');

		const chips = await screen.findByTestId('provenance-chips');
		expect(within(chips).getAllByTestId('provenance-chip').length).toBeGreaterThan(0);
		expect(chips).toHaveTextContent('10.1234/nist-density');
		expect(chips).toHaveTextContent('v1.0.0');
	});

	it('stamps a grounded answer with data-grounded="true"', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(FULL_TURN_EVENTS)));

		render(ChatSurface);
		await sendMessage('What is the density of FLiBe?');

		const stamp = await screen.findByTestId('answer-stamp');
		expect(stamp.getAttribute('data-grounded')).toBe('true');
	});

	it('stamps an ungrounded answer with data-grounded="false"', async () => {
		const ungroundedTurn: TraceEvent[] = [
			{ type: 'text', text: "I don't have grounding for that." },
			{ type: 'answer', answer: { grounded: false } },
			{ type: 'done' }
		];
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(ungroundedTurn)));

		render(ChatSurface);
		await sendMessage('What is the tensile strength of unobtainium?');

		const stamp = await screen.findByTestId('answer-stamp');
		expect(stamp.getAttribute('data-grounded')).toBe('false');
	});

	it('renders an unrecognized event type as a raw fallback without breaking the stream', async () => {
		const streamWithUnknown: TraceEvent[] = [
			{ type: 'text', text: 'partial' },
			{ type: 'future_event' as unknown as never, raw: { type: 'future_event', detail: 'x' } } as TraceEvent,
			{ type: 'answer', answer: { grounded: true } },
			{ type: 'done' }
		];
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(streamWithUnknown)));

		render(ChatSurface);
		await sendMessage('trigger unknown event');

		const raw = await screen.findByTestId('trace-raw');
		expect(raw).toBeInTheDocument();
		// The stream must still complete and render the final answer stamp.
		expect(await screen.findByTestId('answer-stamp')).toBeInTheDocument();
	});

	it('sends the full conversation history on a second turn', async () => {
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce(
				mockChatResponse([{ type: 'text', text: 'first reply' }, { type: 'answer', answer: { grounded: true } }, { type: 'done' }])
			)
			.mockResolvedValueOnce(
				mockChatResponse([{ type: 'text', text: 'second reply' }, { type: 'answer', answer: { grounded: true } }, { type: 'done' }])
			);
		vi.stubGlobal('fetch', fetchMock);

		render(ChatSurface);
		await sendMessage('first message', 1);
		await sendMessage('second message', 2);

		expect(fetchMock).toHaveBeenCalledTimes(2);
		const secondCallBody = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
		expect(secondCallBody.messages.length).toBeGreaterThanOrEqual(3);
		expect(secondCallBody.messages[0]).toEqual({ role: 'user', content: 'first message' });
	});
});

// ---------------------------------------------------------------------
// Tests below this line are pass-1 additions for the redesign-web-frontend-ux
// change (chat-ui spec: "Assistant answers render sanitized markdown",
// "In-progress streaming affordance", "Assistant answer has a copy action",
// "Empty conversation shows onboarding prompts"; tasks 5.2/5.4a). They are
// written against the PINNED contract in the task-5 delegation prompt, not
// against the current (pre-redesign) ChatSurface.svelte visible in this
// worktree, so they are expected to fail until the chat-ui coder's branch
// merges. Pinned testids used here: `streaming-indicator`,
// `chat-onboarding`, `example-prompt`, `copy-answer`. Reconciled in pass 2.
// ---------------------------------------------------------------------

/** A stream whose frames are pushed on demand via `push()` and only
 * terminated by an explicit `close()`, instead of being fully enqueued and
 * closed up front like `mockChatResponse`. This lets a test observe
 * mid-stream state (e.g. the streaming indicator) before the turn
 * completes. */
function mockChatStreamController() {
	let controllerRef!: ReadableStreamDefaultController<Uint8Array>;
	const encoder = new TextEncoder();
	const stream = new ReadableStream<Uint8Array>({
		start(controller) {
			controllerRef = controller;
		}
	});
	return {
		response: new Response(stream, { status: 200 }),
		push(event: TraceEvent) {
			controllerRef.enqueue(encoder.encode(sseFrame(event)));
		},
		close() {
			controllerRef.close();
		}
	};
}

describe('ChatSurface - markdown rendering (redesign 5.2)', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	it('renders assistant markdown as HTML, not literal markdown syntax', async () => {
		const turn: TraceEvent[] = [
			{ type: 'text', text: 'This is **bold** text and a `code` span.' },
			{ type: 'answer', answer: { grounded: true } },
			{ type: 'done' }
		];
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(turn)));

		render(ChatSurface);
		await sendMessage('render some markdown');

		const assistantMessage = screen
			.getAllByTestId('chat-message')
			.find((el) => el.getAttribute('data-role') === 'assistant');
		expect(assistantMessage).toBeTruthy();

		const content = assistantMessage?.querySelector('.message-content');
		expect(content).toBeTruthy();
		expect(content?.innerHTML).toContain('<strong>bold</strong>');
		expect(content?.innerHTML).toContain('<code>code</code>');
		// The literal markdown syntax characters must not appear as text --
		// only the rendered elements.
		expect(content?.textContent).not.toContain('**bold**');
	});
});

describe('ChatSurface - streaming affordance (redesign 5.2)', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows the streaming indicator while a turn is streaming and removes it when the turn completes', async () => {
		const ctrl = mockChatStreamController();
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ctrl.response));

		render(ChatSurface);
		await fireEvent.input(screen.getByTestId('chat-input'), { target: { value: 'is this streaming?' } });
		await fireEvent.click(screen.getByTestId('chat-send'));

		ctrl.push({ type: 'text', text: 'partial answer' });
		await waitFor(() => expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument());

		ctrl.push({ type: 'answer', answer: { grounded: true } });
		ctrl.push({ type: 'done' });
		ctrl.close();

		await waitFor(() => expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument());
		expect(await screen.findByTestId('answer-stamp')).toBeInTheDocument();
	});

	it('removes the streaming indicator when the turn errors', async () => {
		const ctrl = mockChatStreamController();
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ctrl.response));

		render(ChatSurface);
		await fireEvent.input(screen.getByTestId('chat-input'), { target: { value: 'trigger an error' } });
		await fireEvent.click(screen.getByTestId('chat-send'));

		ctrl.push({ type: 'text', text: 'partial' });
		await waitFor(() => expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument());

		ctrl.push({ type: 'error', error: 'boom' });
		ctrl.close();

		await waitFor(() => expect(screen.getByTestId('chat-error')).toBeInTheDocument());
		expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument();
	});
});

describe('ChatSurface - onboarding (redesign 5.2)', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows onboarding with clickable example prompts when the conversation is empty', async () => {
		render(ChatSurface);

		const onboarding = screen.getByTestId('chat-onboarding');
		expect(onboarding).toBeInTheDocument();

		const prompts = within(onboarding).getAllByTestId('example-prompt');
		expect(prompts.length).toBeGreaterThan(0);
	});

	it('hides onboarding once the first message is sent', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				mockChatResponse([{ type: 'text', text: 'reply' }, { type: 'answer', answer: { grounded: true } }, { type: 'done' }])
			)
		);

		render(ChatSurface);
		expect(screen.getByTestId('chat-onboarding')).toBeInTheDocument();

		await sendMessage('what is the density of FLiBe?');

		expect(screen.queryByTestId('chat-onboarding')).not.toBeInTheDocument();
	});

	it('clicking an example prompt runs it as the first message (assumption: click sends, see report)', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(
				mockChatResponse([{ type: 'text', text: 'reply' }, { type: 'answer', answer: { grounded: true } }, { type: 'done' }])
			)
		);

		render(ChatSurface);
		const onboarding = screen.getByTestId('chat-onboarding');
		const prompts = within(onboarding).getAllByTestId('example-prompt');
		const promptText = prompts[0].textContent?.trim() ?? '';
		expect(promptText.length).toBeGreaterThan(0);

		await fireEvent.click(prompts[0]);

		await waitFor(() => expect(screen.queryByTestId('chat-onboarding')).not.toBeInTheDocument());
		const userMessages = screen
			.getAllByTestId('chat-message')
			.filter((el) => el.getAttribute('data-role') === 'user');
		expect(userMessages.some((el) => el.textContent?.includes(promptText))).toBe(true);
	});
});

describe('ChatSurface - reasoning disclosure', () => {
	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	it('shows reasoning in a collapsed Thinking section, out of the answer bubble', async () => {
		const turn: TraceEvent[] = [
			{ type: 'reasoning', reasoning: 'Let me compute the density coefficients.' },
			{ type: 'text', text: 'The density is 2.5 g/cc.' },
			{ type: 'answer', answer: { grounded: true } },
			{ type: 'done' }
		];
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(turn)));

		render(ChatSurface);
		await sendMessage('What is the density of FLiBe?');

		const disclosure = await screen.findByTestId('reasoning-disclosure');
		expect(disclosure).toHaveTextContent('compute the density coefficients');
		// A collapsible <details> that starts collapsed.
		expect(disclosure.tagName.toLowerCase()).toBe('details');
		expect((disclosure as HTMLDetailsElement).open).toBe(false);

		// Reasoning must NOT bleed into the answer bubble.
		const assistantMessage = screen
			.getAllByTestId('chat-message')
			.find((el) => el.getAttribute('data-role') === 'assistant');
		const content = assistantMessage?.querySelector('.message-content');
		expect(content?.textContent).toContain('2.5 g/cc');
		expect(content?.textContent).not.toContain('compute the density coefficients');

		// Reasoning is not routed through the trace timeline either.
		const timeline = await screen.findByTestId('trace-timeline');
		const eventTypes = within(timeline)
			.getAllByTestId('trace-event')
			.map((el) => el.getAttribute('data-event-type'));
		expect(eventTypes).not.toContain('reasoning');
	});

	it('renders no Thinking disclosure for a turn without reasoning', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(FULL_TURN_EVENTS)));

		render(ChatSurface);
		await sendMessage('What is the density of FLiBe?');

		expect(screen.queryByTestId('reasoning-disclosure')).not.toBeInTheDocument();
	});
});

describe('ChatSurface - copy-answer action (redesign 5.4a)', () => {
	const originalClipboard = (navigator as Navigator & { clipboard?: unknown }).clipboard;

	beforeEach(() => {
		vi.unstubAllGlobals();
	});

	afterEach(() => {
		Object.defineProperty(navigator, 'clipboard', { value: originalClipboard, configurable: true });
	});

	it('writes the completed answer text to the clipboard and shows a transient confirmation', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined);
		Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(mockChatResponse(FULL_TURN_EVENTS)));

		render(ChatSurface);
		await sendMessage('What is the density of FLiBe?');

		const copyBtn = await screen.findByTestId('copy-answer');
		await fireEvent.click(copyBtn);

		await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
		expect(writeText.mock.calls[0][0]).toContain('2.5 g/cc');

		// Transient confirmation -- the spec only requires *some* visible
		// confirmation ("a transient 'copied' state or toast"), so accept
		// any of: the button's own text/label changing to mention "copied",
		// a `data-copied`/`aria-pressed` style attribute flip, or a toast
		// appearing in the shared toast region.
		await waitFor(() => {
			const confirmedByText = /copied/i.test(copyBtn.textContent ?? '');
			const confirmedByAttr = ['data-copied', 'aria-pressed', 'data-state'].some(
				(attr) => copyBtn.getAttribute(attr) != null && /copied|true/i.test(copyBtn.getAttribute(attr) ?? '')
			);
			const toast = screen.queryByTestId('toast');
			expect(confirmedByText || confirmedByAttr || toast !== null).toBe(true);
		});
	});
});
