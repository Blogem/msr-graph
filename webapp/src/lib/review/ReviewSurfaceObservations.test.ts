// Tests for the proposal-observation-provenance review-ui changes (task
// 7.6): the queue renders exactly one row per proposal id with a
// cross-corpus indicator, and the detail drawer renders the observation
// breakdown grouped by corpus/document (review-ui spec "Proposal queue
// filtered by review status" + "Evidence panel shows source spans and
// document links", scenarios "Cross-corpus proposals render without
// duplicate rows" / "Observation breakdown is shown grouped by corpus").
//
// Kept in a SEPARATE file from `ReviewSurface.test.ts` (rather than
// appended to it) deliberately: that file already exists (pre-dates this
// change, built by a different wave) and still exercises the OLDER scalar
// `docFrequency` queue-row shape end-to-end (literal `docFrequency: N`
// fixtures, `humanizeDocFrequency`); editing it here would risk a merge
// conflict with whatever the review-ui coder (T7) does to it in parallel,
// and this suite's fixtures/assertions are shaped around the NEW
// `documentFrequency`/`corpusCount`/`corpora`/`observations` fields only.
//
// ASSUMPTIONS (pass-1, flagged for reconciliation at merge — the
// ReviewSurface.svelte visible in this worktree does not yet render any of
// this; task 6.1/6.2 land concurrently in a separate worktree):
//   - A cross-corpus proposal (`corpusCount` > 1) is marked in the queue
//     row with a `data-testid="cross-corpus-badge"` element (exact
//     placement/wording unpinned; this suite only asserts presence and that
//     it is scoped inside that proposal's own row, and that a single-corpus
//     row has none).
//   - The detail drawer renders the observation breakdown inside a
//     `data-testid="observation-breakdown"` container, with one
//     `data-testid="observation-corpus-group"` element per corpus (carrying
//     a `data-corpus` attribute equal to the corpus CURIE) and one
//     `data-testid="observation-document"` element per document within that
//     group, whose text content includes the document id and its latest
//     occurrence count.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { crossCorpusProposalQueue, moderatorProposal, proposalQueue } from '../__fixtures__/proposals';

const { listProposalsMock, getProposalMock, editProposalGraphMock, approveProposalMock, rejectProposalMock } =
	vi.hoisted(() => ({
		listProposalsMock: vi.fn(),
		getProposalMock: vi.fn(),
		editProposalGraphMock: vi.fn(),
		approveProposalMock: vi.fn(),
		rejectProposalMock: vi.fn()
	}));

vi.mock('$lib/api', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api')>();
	return {
		...actual,
		listProposals: listProposalsMock,
		getProposal: getProposalMock,
		editProposalGraph: editProposalGraphMock,
		approveProposal: approveProposalMock,
		rejectProposal: rejectProposalMock
	};
});

import ReviewSurface from './ReviewSurface.svelte';

function queueResponse(proposals: unknown[]) {
	return { proposals };
}

beforeEach(() => {
	listProposalsMock.mockReset().mockResolvedValue(queueResponse(crossCorpusProposalQueue));
	getProposalMock.mockReset();
	editProposalGraphMock.mockReset().mockResolvedValue({ status: 'ok' });
	approveProposalMock.mockReset().mockResolvedValue({ status: 'approved' });
	rejectProposalMock.mockReset().mockResolvedValue({ status: 'rejected' });
});

describe('ReviewSurface - cross-corpus queue rendering (task 7.6)', () => {
	it('renders exactly one row for a proposal attested in two corpora', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const rows = await screen.findAllByTestId('proposal-row');
		// crossCorpusProposalQueue has 2 distinct proposal ids (solubility-1,
		// moderator-1) -- never more rows than distinct ids, in particular
		// never two rows for moderator-1.
		expect(rows.length).toBe(crossCorpusProposalQueue.length);
		const moderatorRows = rows.filter((el) => el.getAttribute('data-id') === 'moderator-1');
		expect(moderatorRows.length).toBe(1);
	});

	it('shows a cross-corpus indicator on the multi-corpus row but not on the single-corpus row', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const rows = await screen.findAllByTestId('proposal-row');
		const moderatorRow = rows.find((el) => el.getAttribute('data-id') === 'moderator-1');
		const solubilityRow = rows.find((el) => el.getAttribute('data-id') === 'solubility-1');
		expect(moderatorRow).toBeTruthy();
		expect(solubilityRow).toBeTruthy();

		expect(
			within(moderatorRow as HTMLElement).queryByTestId('cross-corpus-badge')
		).toBeTruthy();
		expect(
			within(solubilityRow as HTMLElement).queryByTestId('cross-corpus-badge')
		).toBeFalsy();
	});

	// NOTE (pass-1): a companion test that fed the queue two rows sharing
	// the SAME id (simulating the pre-fix chunk-8/9 dup-id shape) was
	// tried here and removed -- Svelte 5's keyed `{#each ... (p.id)}`
	// throws `each_key_duplicate` from inside its own effect scheduling,
	// which surfaces as an async *unhandled rejection* rather than a
	// synchronous throw `expect(...).not.toThrow()` can observe, so that
	// version of the test passed spuriously while still logging a real
	// error. The `proposal-review-api` spec places the "exactly one row
	// per proposal id" guarantee on the SERVER (task 5.1/5.3: "never fans
	// out to multiple rows"), not on frontend defensiveness, so the
	// meaningful regression coverage is the "renders exactly one row for a
	// proposal attested in two corpora" test above, driven against the
	// server's actual (now-aggregating) response shape. Flagged for pass-2:
	// if the coder's queue rendering can be made to tolerate a duplicate id
	// defensively, a real (non-flaky) test for that would need to await the
	// component's own error boundary/rejection handling explicitly, not a
	// bare `render()` call.
});

describe('ReviewSurface - observation breakdown in the detail drawer (task 7.6)', () => {
	async function openModerator() {
		getProposalMock.mockResolvedValue(moderatorProposal);
		const rows = await screen.findAllByTestId('proposal-row');
		const target = rows.find((el) => el.getAttribute('data-id') === 'moderator-1');
		if (!target) throw new Error('no proposal-row found for moderator-1');
		await fireEvent.click(target);
		return screen.findByTestId('proposal-detail');
	}

	it('groups the observation breakdown by corpus, one group per corpus', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openModerator();
		const breakdown = await within(detail).findByTestId('observation-breakdown');
		const groups = within(breakdown).getAllByTestId('observation-corpus-group');

		expect(groups.length).toBe(moderatorProposal.observations.length);
		const corpora = groups.map((g) => g.getAttribute('data-corpus'));
		expect(corpora).toEqual(
			expect.arrayContaining(moderatorProposal.observations.map((o) => o.corpus))
		);
	});

	it('lists each document with its latest occurrence count within its corpus group', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openModerator();
		const breakdown = await within(detail).findByTestId('observation-breakdown');

		const chemistryGroup = within(breakdown)
			.getAllByTestId('observation-corpus-group')
			.find((g) => g.getAttribute('data-corpus') === 'msrd:corpus-chemistry');
		expect(chemistryGroup).toBeTruthy();

		const documents = within(chemistryGroup as HTMLElement).getAllByTestId('observation-document');
		expect(documents.length).toBe(2);
		expect(documents.some((el) => el.textContent?.includes('ORNL-TM-2316'))).toBe(true);
		expect(documents.some((el) => el.textContent?.includes('12'))).toBe(true);
		expect(documents.some((el) => el.textContent?.includes('ORNL-TM-3999'))).toBe(true);
		expect(documents.some((el) => el.textContent?.includes('5'))).toBe(true);
	});

	it('keeps the evidence panel alongside the observation breakdown (both present, not one replacing the other)', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openModerator();
		expect(await within(detail).findByTestId('evidence-panel')).toBeInTheDocument();
		expect(await within(detail).findByTestId('observation-breakdown')).toBeInTheDocument();
	});
});

// Sanity check that `proposalQueue` (the shared fixture also used by
// `ReviewSurface.test.ts`) is untouched by this suite's own additions to
// the fixture module. Reconciled at pass 2: the review-ui coder (T7)
// legitimately rewrote `proposalQueue` from the old scalar `docFrequency`
// shape to the new observation-aggregate shape (`documentFrequency`/
// `totalOccurrences`/`corpusCount`/`corpora`) and made `graphite-1` its own
// cross-corpus row -- this assertion is updated to match that real,
// now-merged shape rather than the pass-1 assumption.
describe('sanity', () => {
	it('does not mutate the pre-existing proposalQueue fixture', () => {
		expect(proposalQueue.length).toBe(4);
		expect(
			proposalQueue.every((p) => typeof (p as unknown as { documentFrequency?: number }).documentFrequency === 'number')
		).toBe(true);
		expect(
			proposalQueue.every((p) => Array.isArray((p as unknown as { corpora?: string[] }).corpora))
		).toBe(true);

		const graphite = proposalQueue.find((p) => p.id === 'graphite-1') as unknown as {
			corpusCount: number;
		};
		expect(graphite?.corpusCount).toBe(2);
	});
});
