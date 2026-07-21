// Pure helpers for the review surface (review-ui spec, design D5/D7): no
// Svelte here so the diff/edit/serialization logic is plain, independently
// testable TypeScript. Consumes only the wire types re-exported from
// $lib/api -- never redefines them.
import type { NeighborhoodTriple, Triple } from '$lib/api';

/** Returns the fragment/local name of an IRI (the part after the last
 * `#` or `/`) for compact display -- e.g.
 * `https://w3id.org/msr-kg/ontology#solubility` -> `solubility`. Returns
 * the input unchanged if it has no separator (a bare literal or an
 * already-short token). */
export function localName(iri: string): string {
	const idx = Math.max(iri.lastIndexOf('#'), iri.lastIndexOf('/'));
	return idx === -1 || idx === iri.length - 1 ? iri : iri.slice(idx + 1);
}

/** Renders a corpus identifier as a short friendly label for the queue's
 * cross-corpus badge and the detail view's observation breakdown
 * (review-ui spec, design D7): the server emits a corpus as an absolute
 * IRI (e.g. `https://w3id.org/msr-kg/data#corpus-chemistry`), but a CURIE
 * form (`msrd:corpus-chemistry`) is tolerated too -- both reduce to
 * `chemistry`. Falls back to the input unchanged if it doesn't look like
 * a `corpus-*` identifier at all. */
export function corpusLabel(corpus: string): string {
	const name = localName(corpus);
	const withoutPrefix = name.includes(':') ? (name.split(':').pop() ?? name) : name;
	return withoutPrefix.replace(/^corpus-/i, '');
}

// A delimiter for joining a triple's subject/predicate/object into one
// map key (tripleKey below). Built via String.fromCharCode rather than
// an inline character literal so the delimiter can never collide with
// real triple data (an IRI or literal could plausibly contain a space,
// but not a NUL character) -- and so this source file stays plain ASCII
// text with no embedded control byte.
const KEY_DELIMITER = String.fromCharCode(0);

function tripleKey(t: { subject: string; predicate: string; object: string }): string {
	return t.subject + KEY_DELIMITER + t.predicate + KEY_DELIMITER + t.object;
}

export interface DiffNode {
	iri: string;
	added: boolean;
}

export interface DiffEdge {
	subject: string;
	predicate: string;
	object: string;
	added: boolean;
}

export interface Diff {
	nodes: DiffNode[];
	edges: DiffEdge[];
}

/** Overlays a proposal's proposed `triples` on the affected one-hop
 * ontology `neighborhood` (review-ui spec "Proposal detail rendered as
 * an ontology-neighborhood diff", design D5): a node or edge present in
 * `triples` but absent from `neighborhood` is "added". Every
 * neighborhood node/edge is always present and never marked added; a
 * proposed triple identical to one already in the neighborhood
 * (same subject/predicate/object) is not duplicated. */
export function buildDiff(triples: Triple[], neighborhood: NeighborhoodTriple[]): Diff {
	const neighborhoodKeys = new Set(neighborhood.map(tripleKey));
	const neighborhoodNodes = new Set<string>();
	for (const t of neighborhood) {
		neighborhoodNodes.add(t.subject);
		neighborhoodNodes.add(t.object);
	}

	const edgesByKey = new Map<string, DiffEdge>();
	for (const t of neighborhood) {
		edgesByKey.set(tripleKey(t), {
			subject: t.subject,
			predicate: t.predicate,
			object: t.object,
			added: false
		});
	}
	for (const t of triples) {
		const key = tripleKey(t);
		if (!edgesByKey.has(key)) {
			edgesByKey.set(key, {
				subject: t.subject,
				predicate: t.predicate,
				object: t.object,
				added: !neighborhoodKeys.has(key)
			});
		}
	}

	const nodesByIri = new Map<string, DiffNode>();
	for (const iri of neighborhoodNodes) {
		nodesByIri.set(iri, { iri, added: false });
	}
	for (const t of triples) {
		for (const iri of [t.subject, t.object]) {
			if (!nodesByIri.has(iri)) {
				nodesByIri.set(iri, { iri, added: !neighborhoodNodes.has(iri) });
			}
		}
	}

	return { nodes: [...nodesByIri.values()], edges: [...edgesByKey.values()] };
}

// --- Editable placement/unit fields (review-ui spec 4.4) ---
//
// The proposal graph is a flat list of generic RDF triples; "placement"
// and "unit" are not separate API fields but specific predicates within
// that graph (internal/proposal/routing.go, candidate-triage spec):
// placement is the class/property's position in the ontology
// (rdfs:subClassOf for a class, rdfs:domain/rdfs:range for a property);
// unit is msr:canonicalUnit (a QUDT unit reference). These lists are the
// predicate local names this UI recognizes for each field.
const PLACEMENT_PREDICATE_NAMES = ['subClassOf', 'domain', 'range'];
const UNIT_PREDICATE_NAMES = ['canonicalUnit', 'hasUnit', 'unit'];

const DEFAULT_PLACEMENT_PREDICATE = 'http://www.w3.org/2000/01/rdf-schema#subClassOf';
const DEFAULT_UNIT_PREDICATE = 'https://w3id.org/msr-kg/ontology#canonicalUnit';

/** Index of the first triple in `triples` whose predicate's local name
 * matches one of `names` (case-insensitive), or -1 if none do. */
function findFieldTripleIndex(triples: Triple[], names: string[]): number {
	const wanted = names.map((n) => n.toLowerCase());
	return triples.findIndex((t) => wanted.includes(localName(t.predicate).toLowerCase()));
}

/** The current placement value (the matching triple's object), or `''`
 * if the proposal carries no placement triple yet. */
export function placementValueOf(triples: Triple[]): string {
	const idx = findFieldTripleIndex(triples, PLACEMENT_PREDICATE_NAMES);
	return idx === -1 ? '' : triples[idx].object;
}

/** The current unit value (the matching triple's object), or `''` if
 * the proposal carries no unit triple yet. */
export function unitValueOf(triples: Triple[]): string {
	const idx = findFieldTripleIndex(triples, UNIT_PREDICATE_NAMES);
	return idx === -1 ? '' : triples[idx].object;
}

/** True if `value` looks like an IRI or CURIE (an `http(s)://` URL, or
 * a bare `prefix:local` token like `unit:MOL-PER-MOL`) rather than a
 * free-text literal -- decides whether an edited placement/unit value
 * is re-serialized as a URI reference or a quoted literal. */
function looksLikeUriOrCurie(value: string): boolean {
	return /^https?:\/\/\S+$/i.test(value) || /^[A-Za-z][\w-]*:\S+$/.test(value);
}

/** Returns the most common subject across `triples` (a proxy for the
 * proposal's primary resource), falling back to the first triple's
 * subject. Used only as the subject for a newly-synthesized
 * placement/unit triple when the proposal doesn't already carry one. */
function primarySubject(triples: Triple[]): string {
	const counts = new Map<string, number>();
	for (const t of triples) counts.set(t.subject, (counts.get(t.subject) ?? 0) + 1);
	let best = triples[0]?.subject ?? '';
	let bestCount = -1;
	for (const [subject, count] of counts) {
		if (count > bestCount) {
			best = subject;
			bestCount = count;
		}
	}
	return best;
}

/** Applies an edited `value` for one field (placement or unit) to
 * `triples`, returning a new array (the input is never mutated):
 * - blank `value` removes the matching triple, if any;
 * - a matching triple already present has its object (and inferred
 *   objectType) replaced;
 * - otherwise a new triple is appended under `defaultPredicate`, with
 *   `primarySubject(triples)` as its subject. */
export function applyFieldEdit(
	triples: Triple[],
	fieldNames: string[],
	defaultPredicate: string,
	value: string
): Triple[] {
	const trimmed = value.trim();
	const idx = findFieldTripleIndex(triples, fieldNames);

	if (trimmed === '') {
		return idx === -1 ? triples : triples.filter((_, i) => i !== idx);
	}

	const objectType = looksLikeUriOrCurie(trimmed) ? 'uri' : 'literal';
	if (idx === -1) {
		return [
			...triples,
			{ subject: primarySubject(triples), predicate: defaultPredicate, object: trimmed, objectType }
		];
	}
	const updated = [...triples];
	updated[idx] = { ...updated[idx], object: trimmed, objectType, datatype: undefined, lang: undefined };
	return updated;
}

export function applyPlacementEdit(triples: Triple[], value: string): Triple[] {
	return applyFieldEdit(triples, PLACEMENT_PREDICATE_NAMES, DEFAULT_PLACEMENT_PREDICATE, value);
}

export function applyUnitEdit(triples: Triple[], value: string): Triple[] {
	return applyFieldEdit(triples, UNIT_PREDICATE_NAMES, DEFAULT_UNIT_PREDICATE, value);
}

function escapeTurtleLiteral(value: string): string {
	return value
		.replace(/\\/g, '\\\\')
		.replace(/"/g, '\\"')
		.replace(/\n/g, '\\n')
		.replace(/\r/g, '\\r');
}

/** Re-serializes `triples` as Turtle triple statements for the
 * whole-graph `PUT /api/proposals/{id}/graph` request body (design D7:
 * the edit endpoint replaces the whole proposal graph, so the client
 * must send the FULL edited graph, never a field patch). Every
 * subject/predicate/object is a full `<...>` IRI reference except a
 * literal object, rendered as a quoted string with an optional
 * `^^<datatype>` or `@lang` suffix -- mirroring
 * internal/proposal/engine.go's turtlePrefixes + escapeLiteral, the
 * server-side code that parses this body (it prepends its own
 * `@prefix` block, so this string needs only the triple statements). */
export function serializeTriples(triples: Triple[]): string {
	return triples
		.map((t) => {
			const subject = `<${t.subject}>`;
			const predicate = `<${t.predicate}>`;
			let object: string;
			if (t.objectType === 'uri') {
				object = `<${t.object}>`;
			} else {
				object = `"${escapeTurtleLiteral(t.object)}"`;
				if (t.datatype) object += `^^<${t.datatype}>`;
				else if (t.lang) object += `@${t.lang}`;
			}
			return `${subject} ${predicate} ${object} .`;
		})
		.join('\n');
}
