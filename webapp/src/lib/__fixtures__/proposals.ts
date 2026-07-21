// Shared proposal fixtures for the review-ui test suites (8.3, 8.4),
// mirroring the M6 acceptance scenarios named in design.md D5/D7 and the
// review-ui spec: the `solubility` proposal (a new datatype property) and
// the `graphite` proposal (a new `Moderator` class + `moderatedBy`
// relation). Shapes are typed exactly against `ProposalDetail`/
// `ProposalSummary` (src/lib/types.ts), which pin the concrete JSON the
// merged chunk-9 server emits (design D7) -- these fixtures are the
// client-side stand-in for that JSON, not independently invented shapes.
import type { ProposalDetail, ProposalSummary } from '../types';

const XSD_STRING = 'http://www.w3.org/2001/XMLSchema#string';

// Corpus IRIs mirror the real ontology's msr:inCorpus resources (design D7
// migration plan): the deterministic chemistry archive vs. the four safety
// documents.
const CORPUS_CHEMISTRY = 'https://w3id.org/msr-kg/data#corpus-chemistry';
const CORPUS_SAFETY = 'https://w3id.org/msr-kg/data#corpus-safety';

/** `GET /api/proposals/solubility-1` -- a new `msr:solubility` datatype
 * property, not present anywhere in the returned neighborhood (so a diff
 * view has nothing to overlay it against except by "it's new"). */
export const solubilityProposal: ProposalDetail = {
	id: 'solubility-1',
	triples: [
		{
			subject: 'msr:solubility',
			predicate: 'rdf:type',
			object: 'owl:DatatypeProperty',
			objectType: 'uri'
		},
		{
			subject: 'msr:solubility',
			predicate: 'rdfs:label',
			object: 'solubility',
			objectType: 'literal',
			datatype: XSD_STRING
		},
		{
			subject: 'msr:solubility',
			predicate: 'rdfs:domain',
			object: 'msr:Salt',
			objectType: 'uri'
		},
		{
			subject: 'msr:solubility',
			predicate: 'msr:hasUnit',
			object: 'msr:MassFraction',
			objectType: 'uri'
		}
	],
	evidence: [
		{
			text: 'The solubility of UF4 in FLiBe was measured at 600C.',
			citedIn: 'ORNL-TM-2316',
			startOffset: 120,
			endOffset: 174
		}
	],
	// Single-corpus observation breakdown (chemistry only) -- exercises the
	// non-empty, single-group rendering path (review-ui spec "Observation
	// breakdown is shown grouped by corpus").
	observations: [
		{
			corpus: CORPUS_CHEMISTRY,
			documents: [
				{
					documentId: 'ORNL-TM-2316',
					occurrenceCount: 3,
					firstObserved: '2026-01-05T00:00:00Z',
					lastObserved: '2026-01-12T00:00:00Z'
				}
			]
		}
	],
	neighborhood: [
		{ subject: 'msr:Salt', predicate: 'rdf:type', object: 'owl:Class' },
		{ subject: 'msr:density', predicate: 'rdf:type', object: 'owl:DatatypeProperty' },
		{ subject: 'msr:density', predicate: 'rdfs:domain', object: 'msr:Salt' }
	]
};

/** `GET /api/proposals/graphite-1` -- a new `msr:Moderator` class plus a
 * `msr:moderatedBy` relation from the existing `msr:Graphite` individual/
 * class, overlaid on a neighborhood that already has `msr:Graphite` and a
 * sibling `msr:Coolant` class but no `Moderator`/`moderatedBy` at all. */
export const graphiteProposal: ProposalDetail = {
	id: 'graphite-1',
	triples: [
		{ subject: 'msr:Moderator', predicate: 'rdf:type', object: 'owl:Class', objectType: 'uri' },
		{
			subject: 'msr:Moderator',
			predicate: 'rdfs:label',
			object: 'Moderator',
			objectType: 'literal',
			datatype: XSD_STRING
		},
		{
			subject: 'msr:Graphite',
			predicate: 'msr:moderatedBy',
			object: 'msr:Moderator',
			objectType: 'uri'
		}
	],
	evidence: [
		{
			text: 'Graphite serves as the neutron moderator in this reactor design.',
			citedIn: 'ORNL-TM-2316',
			startOffset: 45,
			endOffset: 111
		}
	],
	// Multi-corpus observation breakdown (chemistry + safety) -- exercises
	// the cross-corpus grouped rendering path (review-ui spec "Observation
	// breakdown is shown grouped by corpus").
	observations: [
		{
			corpus: CORPUS_CHEMISTRY,
			documents: [
				{
					documentId: 'ORNL-TM-2316',
					occurrenceCount: 5,
					firstObserved: '2026-01-03T00:00:00Z',
					lastObserved: '2026-01-10T00:00:00Z'
				}
			]
		},
		{
			corpus: CORPUS_SAFETY,
			documents: [
				{
					documentId: 'IAEA-SAFETY-1',
					occurrenceCount: 2,
					firstObserved: '2026-02-01T00:00:00Z',
					lastObserved: '2026-02-01T00:00:00Z'
				},
				{
					documentId: 'IAEA-SAFETY-2',
					occurrenceCount: 4,
					firstObserved: '2026-02-02T00:00:00Z',
					lastObserved: '2026-02-06T00:00:00Z'
				}
			]
		}
	],
	neighborhood: [
		{ subject: 'msr:Graphite', predicate: 'rdf:type', object: 'owl:Class' },
		{ subject: 'msr:Coolant', predicate: 'rdf:type', object: 'owl:Class' }
	]
};

/** `GET /api/proposals[?status=]` queue rows backing the solubility/
 * graphite detail fixtures above, plus one already-approved and one
 * already-rejected row so the status filter has something to filter.
 * `graphite-1` is the cross-corpus fixture (`corpusCount: 2`), matching
 * its multi-corpus `observations` breakdown above (review-ui spec
 * "Cross-corpus proposals render without duplicate rows"). */
export const proposalQueue: ProposalSummary[] = [
	{
		id: 'solubility-1',
		kind: 'property',
		status: 'pending',
		term: 'solubility',
		documentFrequency: 3,
		totalOccurrences: 3,
		corpusCount: 1,
		corpora: [CORPUS_CHEMISTRY]
	},
	{
		id: 'graphite-1',
		kind: 'class',
		status: 'pending',
		term: 'graphite',
		documentFrequency: 3,
		totalOccurrences: 11,
		corpusCount: 2,
		corpora: [CORPUS_CHEMISTRY, CORPUS_SAFETY]
	},
	{
		id: 'thorium-1',
		kind: 'individual',
		status: 'approved',
		term: 'thorium',
		documentFrequency: 12,
		totalOccurrences: 12,
		corpusCount: 1,
		corpora: [CORPUS_CHEMISTRY]
	},
	{
		id: 'noise-1',
		kind: 'property',
		status: 'rejected',
		term: 'noise',
		documentFrequency: 1,
		totalOccurrences: 1,
		corpusCount: 1,
		corpora: [CORPUS_CHEMISTRY]
	}
];
