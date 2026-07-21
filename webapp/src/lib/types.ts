// Shared wire types for the frontend. Field names deliberately mirror the
// server's JSON exactly (snake_case where the server emits snake_case) so
// there is no silent translation layer between the wire and the client --
// see internal/agent/events.go (agent.Event and its payload structs),
// cmd/server/proposals.go, cmd/server/checkpoints.go, and
// cmd/server/apierror.go, which are the source of truth this file was
// typed against (openspec/changes/web-frontend design D7).

// --- Chat SSE trace events (chunk-4 chat-api, internal/agent/events.go) ---

/** Payload of a `tool_call` event: internal/agent/events.go ToolCallEvent. */
export interface ToolCallPayload {
	id: string;
	name: string;
	arguments: string;
}

/** Payload of a `tool_result` event: internal/agent/events.go ToolResultEvent. */
export interface ToolResultPayload {
	name: string;
	content: string;
	truncated: boolean;
}

/** Payload of a `script_run` event: internal/agent/events.go ScriptRunEvent. */
export interface ScriptRunPayload {
	source: string;
	stdout: string;
	stderr: string;
	exit_code: number;
	sandbox_id: string;
	truncated: boolean;
	data_locators?: string[];
}

/** Payload of a `provenance` event, and of `answer.provenance` when
 * present: internal/agent/events.go ProvenanceEvent. */
export interface ProvenancePayload {
	data_locators: string[];
	cited_in: string[];
	dataset_dois: string[];
	ontology_version: string;
}

/** Payload of an `answer` event: internal/agent/events.go AnswerEvent.
 * `provenance` is absent/undefined for an ungrounded answer. */
export interface AnswerPayload {
	grounded: boolean;
	provenance?: ProvenancePayload;
}

/** A `text` trace event: assistant tokens (commentary or the final answer). */
export interface TextTraceEvent {
	type: 'text';
	text: string;
}

/** A `tool_call` trace event: the tool name/args the model requested. */
export interface ToolCallTraceEvent {
	type: 'tool_call';
	tool_call: ToolCallPayload;
}

/** A `tool_result` trace event: a tool's (possibly truncated) result. */
export interface ToolResultTraceEvent {
	type: 'tool_result';
	tool_result: ToolResultPayload;
}

/** A `script_run` trace event: one run_python execution. */
export interface ScriptRunTraceEvent {
	type: 'script_run';
	script_run: ScriptRunPayload;
}

/** A `provenance` trace event: grounding provenance for the turn so far. */
export interface ProvenanceTraceEvent {
	type: 'provenance';
	provenance: ProvenancePayload;
}

/** An `answer` trace event: the turn's groundedness verdict, emitted once
 * per final answer immediately before `done`. */
export interface AnswerTraceEvent {
	type: 'answer';
	answer: AnswerPayload;
}

/** A `done` trace event: marks the end of a turn, successful or not. It
 * carries no payload. */
export interface DoneTraceEvent {
	type: 'done';
}

/** An `error` trace event: a turn-ending error (e.g. an LLM call failure
 * or the max-iterations guard tripping). Emitted by the real server
 * (cmd/server/chat.go, internal/agent) immediately before `done`; modeled
 * explicitly here (rather than left to the raw fallback) since it is a
 * known, well-formed event type. */
export interface ErrorTraceEvent {
	type: 'error';
	error: string;
}

/** Fallback for a trace event of an unrecognized type, or one the client
 * does not explicitly model above -- forward-compat with later chunks
 * adding event types/fields (design D3/D7). `raw` is the fully decoded
 * JSON payload of the event so a caller can still inspect it. */
export interface UnknownTraceEvent {
	type: string;
	raw: unknown;
}

/** Discriminated union over every chat SSE trace event the server emits,
 * mirroring chunk-4's schema, plus the raw fallback for anything else. */
export type TraceEvent =
	| TextTraceEvent
	| ToolCallTraceEvent
	| ToolResultTraceEvent
	| ScriptRunTraceEvent
	| ProvenanceTraceEvent
	| AnswerTraceEvent
	| DoneTraceEvent
	| ErrorTraceEvent
	| UnknownTraceEvent;

/** One message in the client-held conversation history, OpenAI-style
 * (chat-ui spec "Stateless conversation posted in full per turn"). */
export interface ChatMessage {
	role: string;
	content: string;
}

// --- Proposal review + checkpoint API shapes (chunk-9, design D7) ---

/** One row of `GET /api/proposals` (cmd/server/proposals.go proposalSummary). */
export interface ProposalSummary {
	id: string;
	kind: string;
	status: string;
	term: string;
	docFrequency: number;
}

/** `GET /api/proposals[?status=]` response (proposalQueueResponse). */
export interface ProposalQueueResponse {
	proposals: ProposalSummary[];
}

/** One triple from a proposal's graph (cmd/server/proposals.go tripleJSON). */
export interface Triple {
	subject: string;
	predicate: string;
	object: string;
	objectType: string;
	datatype?: string;
	lang?: string;
}

/** One msr:Evidence node cited by a proposal (evidenceJSON). */
export interface Evidence {
	text: string;
	citedIn: string;
	startOffset: number;
	endOffset: number;
}

/** One core-graph triple in the proposal's affected one-hop neighborhood
 * (neighborTriple). */
export interface NeighborhoodTriple {
	subject: string;
	predicate: string;
	object: string;
}

/** `GET /api/proposals/{id}` response (proposalDetailResponse). */
export interface ProposalDetail {
	id: string;
	triples: Triple[];
	evidence: Evidence[];
	neighborhood: NeighborhoodTriple[];
}

/** One checkpoint manifest (internal/checkpoint.Manifest). Note the
 * snake_case `ontology_version` -- it is not camelCased on the wire. */
export interface CheckpointManifest {
	label: string;
	ontology_version: string;
}

/** `GET /api/checkpoints` response (checkpointListResponse). */
export interface CheckpointListResponse {
	checkpoints: CheckpointManifest[];
}

/** `{status: "..."}` shape returned by approve/reject/edit/restore
 * (cmd/server/apierror.go statusResponse). */
export interface StatusResponse {
	status: string;
}

// --- Typed API error contract (cmd/server/apierror.go apiError) ---

/** One SHACL violation, present only on a 422 validation rejection
 * (cmd/server/apierror.go violationJSON). */
export interface ApiViolation {
	focusNode?: string;
	constraint?: string;
	shape?: string;
	path?: string;
	message?: string;
}

/** The typed JSON error body every non-2xx API response carries. */
export interface ApiErrorBody {
	error: string;
	message: string;
	violations?: ApiViolation[];
}
