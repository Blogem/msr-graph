// Single typed API client wrapping the chunk-9 proposal + checkpoint HTTP
// API (design D6 "API access through one typed client module"). Every
// call goes through the module-scope `request` helper below, which calls
// the global `fetch` directly (never cached into a local binding) so
// tests can stub `globalThis.fetch` per call.
//
// Shapes are pinned to the concrete JSON the merged server emits
// (design D7), verified against cmd/server/proposals.go,
// cmd/server/checkpoints.go, and cmd/server/apierror.go -- see
// src/lib/types.ts for the field-by-field mapping. Extra/unknown JSON
// fields on any response are tolerated: this client only reads the
// fields it declares and does not reject on additional ones.
import type {
	ApiErrorBody,
	ApiViolation,
	CheckpointListResponse,
	CheckpointManifest,
	ProposalDetail,
	ProposalQueueResponse,
	StatusResponse
} from './types';

const jsonHeaders = { 'Content-Type': 'application/json' };

/** Typed error thrown for every non-2xx API response (design D7 "Errors
 * are a typed body {error, message, violations?}"). `status` is the HTTP
 * status code; `code` is the machine-readable error string
 * (`bad_request`, `invalid_label`, `not_found`, `invalid_transition`,
 * `validation`, `internal`, ...); `violations` is populated only for the
 * 422 SHACL rejection. */
export class ApiError extends Error {
	readonly status: number;
	readonly code: string;
	readonly violations?: ApiViolation[];

	constructor(status: number, body: ApiErrorBody) {
		super(body.message);
		this.name = 'ApiError';
		this.status = status;
		this.code = body.error;
		this.violations = body.violations;
	}
}

/** Parses a non-ok Response's typed `{error, message, violations?}` body
 * into an ApiError. Tolerates a body that fails to parse as JSON or is
 * missing the expected fields (e.g. a proxy/500 page that never reached
 * this API's handlers) by falling back to a generic message, so a caller
 * never has to guard against `parseApiError` itself throwing. */
async function parseApiError(response: Response): Promise<ApiError> {
	let body: Partial<ApiErrorBody> = {};
	try {
		body = (await response.json()) as Partial<ApiErrorBody>;
	} catch {
		// Non-JSON error body (e.g. a plain-text 400/405) -- fall through to
		// the generic fallback below.
	}

	const error = typeof body.error === 'string' ? body.error : 'unknown';
	const message =
		typeof body.message === 'string' && body.message !== ''
			? body.message
			: `request failed with status ${response.status}`;
	const violations = Array.isArray(body.violations) ? body.violations : undefined;

	return new ApiError(response.status, { error, message, violations });
}

/** Issues one API request and decodes the JSON response, throwing a
 * parsed ApiError for any non-2xx status. Every exported client function
 * below is a thin wrapper over this. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(path, init);
	if (!response.ok) {
		throw await parseApiError(response);
	}
	return (await response.json()) as T;
}

// --- Proposal review endpoints ---

/** `GET /api/proposals[?status=]` -- the review queue, optionally
 * filtered to one review status (pending/approved/rejected). */
export async function listProposals(status?: string): Promise<ProposalQueueResponse> {
	const query = status ? `?status=${encodeURIComponent(status)}` : '';
	return request<ProposalQueueResponse>(`/api/proposals${query}`);
}

/** `GET /api/proposals/{id}` -- proposed triples, evidence, and the
 * affected one-hop ontology neighborhood. Rejects with an ApiError whose
 * `status` is 404 (`code: "not_found"`) for an unknown id. */
export async function getProposal(id: string): Promise<ProposalDetail> {
	return request<ProposalDetail>(`/api/proposals/${encodeURIComponent(id)}`);
}

/** `PUT /api/proposals/{id}/graph` -- replaces the *whole* proposal graph
 * with `triples` (a fully re-serialized graph, not a field patch). The
 * caller must guarantee `triples` is non-empty; an empty/whitespace body
 * is rejected 400 by the server. */
export async function editProposalGraph(id: string, triples: string): Promise<StatusResponse> {
	return request<StatusResponse>(`/api/proposals/${encodeURIComponent(id)}/graph`, {
		method: 'PUT',
		headers: jsonHeaders,
		body: JSON.stringify({ triples })
	});
}

/** `POST /api/proposals/{id}/approve` -- always sends `{reviewer,
 * timestamp}` (an empty body is rejected 400 by the server, unlike
 * reject). Resolves to `{status: "approved"}` on success. */
export async function approveProposal(
	id: string,
	reviewer: string,
	timestamp: string
): Promise<StatusResponse> {
	return request<StatusResponse>(`/api/proposals/${encodeURIComponent(id)}/approve`, {
		method: 'POST',
		headers: jsonHeaders,
		body: JSON.stringify({ reviewer, timestamp })
	});
}

/** `POST /api/proposals/{id}/reject` -- no request body. Resolves to
 * `{status: "rejected"}` on success. */
export async function rejectProposal(id: string): Promise<StatusResponse> {
	return request<StatusResponse>(`/api/proposals/${encodeURIComponent(id)}/reject`, {
		method: 'POST'
	});
}

// --- Checkpoint endpoints ---

/** `GET /api/checkpoints` -- the checkpoint list. Note `ontology_version`
 * is snake_case on the wire (internal/checkpoint.Manifest), not
 * camelCased here. */
export async function listCheckpoints(): Promise<CheckpointListResponse> {
	return request<CheckpointListResponse>('/api/checkpoints');
}

/** `POST /api/checkpoints` body `{label}` -- creates a checkpoint and
 * resolves to its manifest (201 Created). Rejects with a 400
 * `invalid_label` ApiError for an unsafe/rejected label. */
export async function createCheckpoint(label: string): Promise<CheckpointManifest> {
	return request<CheckpointManifest>('/api/checkpoints', {
		method: 'POST',
		headers: jsonHeaders,
		body: JSON.stringify({ label })
	});
}

/** `POST /api/checkpoints/{label}/restore` -- no request body. Resolves
 * to `{status: "restored"}` on success. */
export async function restoreCheckpoint(label: string): Promise<StatusResponse> {
	return request<StatusResponse>(`/api/checkpoints/${encodeURIComponent(label)}/restore`, {
		method: 'POST'
	});
}

/** `DELETE /api/checkpoints/{label}` -- no request body. Removes the
 * checkpoint's stored artifacts and resolves to `{status: "deleted"}` on
 * success. Rejects with a 404 `not_found` ApiError for an unknown label. */
export async function deleteCheckpoint(label: string): Promise<StatusResponse> {
	return request<StatusResponse>(`/api/checkpoints/${encodeURIComponent(label)}`, {
		method: 'DELETE'
	});
}

// Re-exported for convenience so a surface component can `import { ... }
// from '$lib/api'` for both the client functions and their wire types.
export type {
	ApiErrorBody,
	ApiViolation,
	ChatMessage,
	CheckpointListResponse,
	CheckpointManifest,
	CorpusObservations,
	DocumentObservation,
	Evidence,
	NeighborhoodTriple,
	ObservationBreakdown,
	ProposalDetail,
	ProposalQueueResponse,
	ProposalSummary,
	StatusResponse,
	TraceEvent,
	Triple
} from './types';
