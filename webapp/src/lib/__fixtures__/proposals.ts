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
	neighborhood: [
		{ subject: 'msr:Graphite', predicate: 'rdf:type', object: 'owl:Class' },
		{ subject: 'msr:Coolant', predicate: 'rdf:type', object: 'owl:Class' }
	]
};

/** `GET /api/proposals[?status=]` queue rows backing the solubility/
 * graphite detail fixtures above, plus one already-approved and one
 * already-rejected row so the status filter has something to filter. */
export const proposalQueue: ProposalSummary[] = [
	{ id: 'solubility-1', kind: 'property', status: 'pending', term: 'solubility', docFrequency: 3 },
	{ id: 'graphite-1', kind: 'class', status: 'pending', term: 'graphite', docFrequency: 5 },
	{ id: 'thorium-1', kind: 'individual', status: 'approved', term: 'thorium', docFrequency: 12 },
	{ id: 'noise-1', kind: 'property', status: 'rejected', term: 'noise', docFrequency: 1 }
];
