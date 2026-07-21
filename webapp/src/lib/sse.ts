// Hand-rolled SSE client for POST /api/chat (design D3): native
// `EventSource` cannot POST, and the chat-api contract requires the full
// conversation in the request body, so the stream is read directly off
// `fetch`'s `ReadableStream` and parsed against the server's framing
// (cmd/server/sse.go newSSEEmitter): each frame is
// `event: <type>\n` + `data: <json>\n` + a blank line separator. The
// discriminant used here is the JSON payload's own `type` field (which
// cmd/server/sse.go guarantees agrees with the `event:` line), so the
// `event:` line itself does not need to be parsed.
//
// No dependency beyond the platform fetch/streams APIs (design D6): this
// keeps the parser small enough to own and test directly, including the
// "an event's bytes split across two reads" edge case the chat-ui spec
// requires (buffer across reads, split only on complete `\n\n` frames).
import type { ChatMessage, TraceEvent } from './types';

/** The trace-event `type` values the server is known to emit (see
 * internal/agent/events.go). A parsed event whose `type` is not in this
 * set (or is missing/malformed) becomes a raw `UnknownTraceEvent` instead
 * of being dropped (chat-ui spec "Unknown event types degrade
 * gracefully"). */
const KNOWN_TRACE_EVENT_TYPES = new Set([
	'text',
	'tool_call',
	'tool_result',
	'script_run',
	'provenance',
	'answer',
	'done',
	'error'
]);

/** Parses one SSE frame's already-joined `data:` payload into a
 * TraceEvent. Exported for direct unit testing of the parsing logic
 * without driving a full mocked stream. */
export function parseTraceEventData(data: string): TraceEvent {
	let parsed: unknown;
	try {
		parsed = JSON.parse(data);
	} catch {
		return { type: 'unknown', raw: data };
	}

	if (parsed !== null && typeof parsed === 'object' && 'type' in (parsed as Record<string, unknown>)) {
		const type = (parsed as { type: unknown }).type;
		if (typeof type === 'string' && KNOWN_TRACE_EVENT_TYPES.has(type)) {
			return parsed as TraceEvent;
		}
		return { type: typeof type === 'string' ? type : 'unknown', raw: parsed };
	}

	return { type: 'unknown', raw: parsed };
}

/** Extracts and joins every `data:` line of one SSE frame (a chunk of
 * text between `\n\n` separators), per the SSE spec's multi-line data
 * field rule. Lines that are not a `data:` field (e.g. `event:`) are
 * ignored -- the JSON payload's own `type` field is the discriminant
 * used by parseTraceEventData, so the `event:` line carries no
 * information this parser needs. Returns null if the frame has no data
 * line at all (e.g. a pure comment/keep-alive frame).
 */
function extractFrameData(frame: string): string | null {
	const dataLines: string[] = [];
	for (const line of frame.split('\n')) {
		if (line.startsWith('data:')) {
			dataLines.push(line.slice('data:'.length).replace(/^ /, ''));
		}
	}
	return dataLines.length > 0 ? dataLines.join('\n') : null;
}

/** POSTs `messages` as the full conversation history to `/api/chat`
 * (chat-ui spec "Stateless conversation posted in full per turn"), reads
 * the SSE response body incrementally via `response.body.getReader()`,
 * and calls `onEvent` once per parsed TraceEvent, in stream order, as
 * soon as each complete frame is available.
 *
 * Buffers decoded text across reads and only splits on complete `\n\n`
 * frame separators, so an event whose bytes are delivered split across
 * two network chunks is still reassembled into exactly one event
 * (chat-ui spec "Event split across chunk boundaries is parsed
 * correctly").
 *
 * Rejects if the request fails outright (non-2xx status, e.g. the
 * malformed-body 400 chat.go returns before starting a turn) or if the
 * response carries no readable body.
 */
export async function streamChat(
	messages: ChatMessage[],
	onEvent: (event: TraceEvent) => void,
	init?: { signal?: AbortSignal }
): Promise<void> {
	const response = await fetch('/api/chat', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ messages }),
		signal: init?.signal
	});

	if (!response.ok) {
		const text = await response.text().catch(() => '');
		throw new Error(text || `chat request failed with status ${response.status}`);
	}
	if (!response.body) {
		throw new Error('chat response has no readable body to stream');
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';

	const processFrame = (frame: string) => {
		if (!frame.trim()) return;
		const data = extractFrameData(frame);
		if (data === null) return;
		onEvent(parseTraceEventData(data));
	};

	for (;;) {
		const { value, done } = await reader.read();
		if (value) {
			buffer += decoder.decode(value, { stream: true });
			let separatorIndex: number;
			while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
				const frame = buffer.slice(0, separatorIndex);
				buffer = buffer.slice(separatorIndex + 2);
				processFrame(frame);
			}
		}
		if (done) {
			// Flush the decoder's internal state (any pending multi-byte
			// sequence) and process a final trailing frame that was not
			// terminated by a closing "\n\n" (e.g. the server closed the
			// connection immediately after the last frame's data line).
			buffer += decoder.decode();
			if (buffer.trim()) {
				processFrame(buffer);
			}
			break;
		}
	}
}
