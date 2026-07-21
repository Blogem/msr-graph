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
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
