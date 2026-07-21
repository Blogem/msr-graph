// Tests for the SSE client (design D3, chat-ui spec "SSE stream consumed
// via fetch streaming"): parseTraceEventData's per-event-type parsing and
// unknown-type fallback (task 8.1), and streamChat's chunk-boundary
// reassembly driven against a mocked fetch Response whose
// body.getReader() yields bytes split mid-frame.
//
// This suite exercises only $lib/sse.ts, which already exists after the
// Wave 1 merge (webapp/src/lib/sse.ts) -- it is expected to pass now, unlike
// the surface-component suites (8.2-8.5) which are gated on the
// concurrently-built Wave 2 components.
import { describe, expect, it, vi } from 'vitest';
import { parseTraceEventData, streamChat } from './sse';
import type { ChatMessage, TraceEvent } from './types';

describe('parseTraceEventData', () => {
	it('parses a text event', () => {
		const event = parseTraceEventData(JSON.stringify({ type: 'text', text: 'hello' }));
		expect(event).toEqual({ type: 'text', text: 'hello' });
	});

	it('parses a reasoning event as a typed event (not a raw fallback)', () => {
		const payload = { type: 'reasoning', reasoning: 'step one' };
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
		expect('raw' in event).toBe(false);
	});

	it('parses a tool_call event', () => {
		const payload = { type: 'tool_call', tool_call: { id: 't1', name: 'sparql_query', arguments: '{}' } };
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses a tool_result event', () => {
		const payload = {
			type: 'tool_result',
			tool_result: { name: 'sparql_query', content: '[]', truncated: false }
		};
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses a script_run event', () => {
		const payload = {
			type: 'script_run',
			script_run: {
				source: 'print(1)',
				stdout: '1\n',
				stderr: '',
				exit_code: 0,
				sandbox_id: 'sbx-1',
				truncated: false
			}
		};
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses a script_run event with data_locators', () => {
		const payload = {
			type: 'script_run',
			script_run: {
				source: 'print(1)',
				stdout: '1\n',
				stderr: '',
				exit_code: 0,
				sandbox_id: 'sbx-1',
				truncated: false,
				data_locators: ['locator-1']
			}
		};
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses a provenance event', () => {
		const payload = {
			type: 'provenance',
			provenance: {
				data_locators: ['loc-1'],
				cited_in: ['ORNL-TM-2316'],
				dataset_dois: ['10.1234/abc'],
				ontology_version: 'v1.2.0'
			}
		};
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses a provenance event with empty cited_in', () => {
		const payload = {
			type: 'provenance',
			provenance: {
				data_locators: ['loc-1'],
				cited_in: [],
				dataset_dois: ['10.1234/abc'],
				ontology_version: 'v1.2.0'
			}
		};
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses a grounded answer event', () => {
		const payload = {
			type: 'answer',
			answer: {
				grounded: true,
				provenance: {
					data_locators: ['loc-1'],
					cited_in: ['ORNL-TM-2316'],
					dataset_dois: ['10.1234/abc'],
					ontology_version: 'v1.2.0'
				}
			}
		};
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses an ungrounded answer event with no provenance', () => {
		const payload = { type: 'answer', answer: { grounded: false } };
		const event = parseTraceEventData(JSON.stringify(payload));
		expect(event).toEqual(payload);
	});

	it('parses a done event', () => {
		const event = parseTraceEventData(JSON.stringify({ type: 'done' }));
		expect(event).toEqual({ type: 'done' });
	});

	it('parses an error event', () => {
		const event = parseTraceEventData(JSON.stringify({ type: 'error', error: 'llm call failed' }));
		expect(event).toEqual({ type: 'error', error: 'llm call failed' });
	});

	it('yields a raw fallback for an unknown event type', () => {
		const event = parseTraceEventData(JSON.stringify({ type: 'future_event', foo: 'bar' }));
		expect(event.type).toBe('future_event');
		expect((event as { raw: unknown }).raw).toEqual({ type: 'future_event', foo: 'bar' });
	});

	it('yields a raw fallback for malformed JSON', () => {
		const event = parseTraceEventData('not json{');
		expect(event).toEqual({ type: 'unknown', raw: 'not json{' });
	});

	it('yields a raw fallback for JSON with no type field', () => {
		const event = parseTraceEventData(JSON.stringify({ foo: 'bar' }));
		expect(event).toEqual({ type: 'unknown', raw: { foo: 'bar' } });
	});
});

// --- streamChat: driven against a mocked fetch Response whose
// body.getReader() yields raw byte chunks, so the SSE-frame reassembly
// logic (buffering across reads, splitting only on complete "\n\n"
// separators) runs for real. ---

function sseFrame(event: TraceEvent): string {
	return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

/** Builds a fetch-compatible Response whose body is a ReadableStream that
 * yields exactly the given string chunks, in order, one per read(). */
function mockStreamResponse(chunks: string[]): Response {
	const encoder = new TextEncoder();
	let index = 0;
	const stream = new ReadableStream<Uint8Array>({
		pull(controller) {
			if (index < chunks.length) {
				controller.enqueue(encoder.encode(chunks[index]));
				index++;
			} else {
				controller.close();
			}
		}
	});
	return new Response(stream, { status: 200 });
}

describe('streamChat', () => {
	it('reassembles an event whose bytes are split across two chunks', async () => {
		const done: TraceEvent = { type: 'done' };
		const answer: TraceEvent = { type: 'answer', answer: { grounded: true } };
		const fullFrame = sseFrame(answer);
		// Split the single frame's bytes mid-way through the data: line, well
		// before its closing "\n\n", so a naive per-chunk parser would see two
		// incomplete frames instead of one complete one.
		const splitPoint = Math.floor(fullFrame.length / 2);
		const chunk1 = fullFrame.slice(0, splitPoint);
		const chunk2 = fullFrame.slice(splitPoint) + sseFrame(done);

		const response = mockStreamResponse([chunk1, chunk2]);
		const fetchMock = vi.fn().mockResolvedValue(response);
		vi.stubGlobal('fetch', fetchMock);

		const events: TraceEvent[] = [];
		const messages: ChatMessage[] = [{ role: 'user', content: 'hi' }];
		await streamChat(messages, (event) => events.push(event));

		expect(events).toEqual([answer, done]);
		expect(fetchMock).toHaveBeenCalledWith(
			'/api/chat',
			expect.objectContaining({
				method: 'POST',
				body: JSON.stringify({ messages })
			})
		);

		vi.unstubAllGlobals();
	});

	it('parses multiple complete events delivered in one chunk', async () => {
		const events_: TraceEvent[] = [
			{ type: 'text', text: 'part 1' },
			{ type: 'tool_call', tool_call: { id: 't1', name: 'sparql_query', arguments: '{}' } },
			{ type: 'done' }
		];
		const body = events_.map(sseFrame).join('');
		const response = mockStreamResponse([body]);
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(response)
		);

		const received: TraceEvent[] = [];
		await streamChat([{ role: 'user', content: 'hi' }], (event) => received.push(event));

		expect(received).toEqual(events_);

		vi.unstubAllGlobals();
	});

	it('yields the raw fallback event for an unrecognized event type mid-stream', async () => {
		const body =
			sseFrame({ type: 'text', text: 'hi' }) +
			`event: future_event\ndata: ${JSON.stringify({ type: 'future_event', detail: 'x' })}\n\n` +
			sseFrame({ type: 'done' });
		const response = mockStreamResponse([body]);
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));

		const received: TraceEvent[] = [];
		await streamChat([{ role: 'user', content: 'hi' }], (event) => received.push(event));

		expect(received[0]).toEqual({ type: 'text', text: 'hi' });
		expect(received[1]).toEqual({
			type: 'future_event',
			raw: { type: 'future_event', detail: 'x' }
		});
		expect(received[2]).toEqual({ type: 'done' });

		vi.unstubAllGlobals();
	});

	it('rejects when the response is not ok', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue(new Response('bad request', { status: 400 }))
		);

		await expect(
			streamChat([{ role: 'user', content: 'hi' }], () => {})
		).rejects.toThrow();

		vi.unstubAllGlobals();
	});
});
