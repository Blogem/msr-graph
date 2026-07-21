// Tests for the review surface (review-ui spec, tasks 8.3/8.4), mounting
// the top-level `$lib/review/ReviewSurface.svelte` component and driving it
// against a mocked `$lib/api` module.
//
// NOTE (pass 1): ReviewSurface.svelte does not exist yet -- it is built
// concurrently by the wave-2 review-ui coder in a separate worktree. This
// suite is written directly against the review-ui spec's acceptance
// scenarios and the pinned testids in the task contract (proposal-row,
// diff-added, evidence-item, shacl-error, ...); it is expected to fail to
// resolve/compile until the merge, and is reconciled in pass 2.
//
// Assumptions made about a component we cannot see yet (documented for
// pass-2 reconciliation):
//   - ReviewSurface owns both the queue and the detail view; selecting a
//     `proposal-row` loads and renders that proposal's `proposal-detail`.
//   - `status-filter` is a control (e.g. a <select>) whose change fires
//     `listProposals(status)`; an "all" option/clearing it fires
//     `listProposals()` with no status.
//   - Approve/reject success updates the row/detail's visible status
//     in-place (no page reload); a 422 on approve/edit leaves the proposal
//     showing as pending.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { graphiteProposal, proposalQueue, solubilityProposal } from '../__fixtures__/proposals';
import type { ProposalDetail, ProposalSummary } from '../types';

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

import { ApiError } from '$lib/api';
// The shared toast display is mounted once app-wide in `+layout.svelte`
// (design D5), not inside ReviewSurface itself -- ReviewSurface only calls
// `pushToast(...)` into the shared `$lib/ui/toast.svelte` store. Rendering
// ReviewSurface alone therefore never puts a `toast-region`/`toast` node in
// the DOM even though the push happens correctly. The toast-feedback tests
// below additionally render `Toaster` (via the same `$lib` alias
// ReviewSurface itself already imports it through) alongside ReviewSurface
// so the real region and its testids are exercised, mirroring how the app
// shell composes them in production.
import Toaster from '$lib/ui/Toaster.svelte';
import { toasts } from '$lib/ui/toast.svelte';
import ReviewSurface from './ReviewSurface.svelte';

function queueResponse(proposals: ProposalSummary[]) {
	return { proposals };
}

beforeEach(() => {
	listProposalsMock.mockReset().mockResolvedValue(queueResponse(proposalQueue));
	getProposalMock.mockReset();
	editProposalGraphMock.mockReset().mockResolvedValue({ status: 'ok' });
	approveProposalMock.mockReset().mockResolvedValue({ status: 'approved' });
	rejectProposalMock.mockReset().mockResolvedValue({ status: 'rejected' });
});

async function openProposal(detail: ProposalDetail) {
	getProposalMock.mockResolvedValue(detail);
	const rows = await screen.findAllByTestId('proposal-row');
	const target = rows.find((el) => el.getAttribute('data-id') === detail.id);
	if (!target) throw new Error(`no proposal-row found for id ${detail.id}`);
	await fireEvent.click(target);
	return screen.findByTestId('proposal-detail');
}

describe('ReviewSurface - queue', () => {
	it('loads the queue on mount', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());
		expect(await screen.findByTestId('proposal-queue')).toBeInTheDocument();
		expect(screen.getAllByTestId('proposal-row').length).toBe(proposalQueue.length);
	});

	it('requests the pending status filter', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const filter = screen.getByTestId('status-filter') as HTMLSelectElement;
		await fireEvent.change(filter, { target: { value: 'pending' } });

		await waitFor(() => expect(listProposalsMock).toHaveBeenCalledWith('pending'));
	});

	it('requests all statuses when the filter is cleared', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());
		listProposalsMock.mockClear();

		const filter = screen.getByTestId('status-filter') as HTMLSelectElement;
		await fireEvent.change(filter, { target: { value: '' } });

		await waitFor(() => expect(listProposalsMock).toHaveBeenCalledWith(undefined));
	});
});

describe('ReviewSurface - diff render (task 8.3)', () => {
	it('highlights the new solubility property as added', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		const diffView = within(detail).getByTestId('diff-view');
		const added = within(diffView)
			.getAllByTestId('diff-added')
			.filter((el) => el.getAttribute('data-added') === 'true');

		expect(added.length).toBeGreaterThan(0);
		expect(added.some((el) => el.textContent?.includes('solubility'))).toBe(true);
	});

	it('highlights the new Moderator class and moderatedBy relation as added', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(graphiteProposal);
		const diffView = within(detail).getByTestId('diff-view');
		const added = within(diffView)
			.getAllByTestId('diff-added')
			.filter((el) => el.getAttribute('data-added') === 'true');

		expect(added.some((el) => el.textContent?.includes('Moderator'))).toBe(true);
		expect(added.some((el) => el.textContent?.includes('moderatedBy'))).toBe(true);
	});

	it('shows a not-found state when the proposal 404s', async () => {
		listProposalsMock.mockResolvedValue(
			queueResponse([
				{
					id: 'missing-1',
					kind: 'property',
					status: 'pending',
					term: 'missing',
					documentFrequency: 1,
					totalOccurrences: 1,
					corpusCount: 1,
					corpora: ['https://w3id.org/msr-kg/data#corpus-chemistry']
				}
			])
		);
		getProposalMock.mockRejectedValue(new ApiError(404, { error: 'not_found', message: 'proposal not found' }));

		render(ReviewSurface);
		const row = await screen.findByTestId('proposal-row');
		await fireEvent.click(row);

		expect(await screen.findByTestId('not-found')).toBeInTheDocument();
	});

	it('shows the evidence panel with sentence, citation, and offsets', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		const evidencePanel = within(detail).getByTestId('evidence-panel');
		const items = within(evidencePanel).getAllByTestId('evidence-item');
		expect(items.length).toBe(solubilityProposal.evidence.length);
		expect(evidencePanel).toHaveTextContent(solubilityProposal.evidence[0].text);
		expect(evidencePanel).toHaveTextContent(solubilityProposal.evidence[0].citedIn);
	});

	it('shows the raw-triples advanced view', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		await fireEvent.click(within(detail).getByTestId('raw-toggle'));

		const raw = within(detail).getByTestId('raw-triples');
		expect(raw).toHaveTextContent('solubility');
	});
});

describe('ReviewSurface - edit/approve/reject flows (task 8.4)', () => {
	it('saves an edited unit as a full-graph PUT', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		const unitField = within(detail).getByTestId('edit-unit');
		await fireEvent.change(unitField, { target: { value: 'mole fraction' } });
		await fireEvent.click(within(detail).getByTestId('edit-save'));

		await waitFor(() => expect(editProposalGraphMock).toHaveBeenCalled());
		const [id, triples] = editProposalGraphMock.mock.calls[0];
		expect(id).toBe('solubility-1');
		expect(typeof triples).toBe('string');
		expect(triples.trim().length).toBeGreaterThan(0);
	});

	it('approves a proposal with a reviewer/timestamp body and marks it approved', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		await fireEvent.click(within(detail).getByTestId('approve-btn'));

		await waitFor(() => expect(approveProposalMock).toHaveBeenCalled());
		const [id, reviewer, timestamp] = approveProposalMock.mock.calls[0];
		expect(id).toBe('solubility-1');
		expect(typeof reviewer).toBe('string');
		expect(reviewer.length).toBeGreaterThan(0);
		expect(typeof timestamp).toBe('string');
		expect(timestamp.length).toBeGreaterThan(0);

		await waitFor(() => expect(detail).toHaveTextContent(/approved/i));
	});

	it('rejects a proposal and marks it rejected', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(graphiteProposal);
		await fireEvent.click(within(detail).getByTestId('reject-btn'));

		await waitFor(() => expect(rejectProposalMock).toHaveBeenCalledWith('graphite-1'));
		await waitFor(() => expect(detail).toHaveTextContent(/rejected/i));
	});

	it('surfaces a 422 SHACL error on approve and leaves the proposal pending', async () => {
		approveProposalMock.mockRejectedValue(
			new ApiError(422, {
				error: 'validation',
				message: 'SHACL validation failed',
				violations: [
					{
						focusNode: 'msr:solubility',
						constraint: 'sh:datatype',
						shape: 'msr:PropertyShape',
						path: 'msr:hasUnit',
						message: 'value does not conform to expected datatype'
					}
				]
			})
		);

		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		await fireEvent.click(within(detail).getByTestId('approve-btn'));

		const shaclError = await screen.findByTestId('shacl-error');
		const violations = within(shaclError).getAllByTestId('violation');
		expect(violations.length).toBeGreaterThan(0);
		expect(shaclError).toHaveTextContent('sh:datatype');
		expect(shaclError).toHaveTextContent('does not conform to expected datatype');

		// Proposal must remain pending -- approve/reject controls should
		// still be present (not swapped for an "approved" state).
		expect(within(detail).getByTestId('approve-btn')).toBeInTheDocument();
	});
});

// ---------------------------------------------------------------------
// Tests below this line are pass-1 additions for the redesign-web-frontend-ux
// change (review-ui spec: "legible information hierarchy", "keyboard-
// navigable" queue, "toast feedback"; tasks 5.3). Written against the
// PINNED contract in the task-5 delegation prompt, not against the current
// (pre-redesign) ReviewSurface.svelte visible in this worktree -- the row
// here still renders bare `docFrequency` numbers and has no keyboard
// handling or toasts, so these are expected to fail until the review-ui
// coder's branch merges. Pinned hooks used: the five existing `.field.*`
// classes/`proposal-row`/`data-id` (kept), humanized "seen in N
// document(s)" text, `j`/`ArrowDown`/`k`/`ArrowUp`/`a`/`r` keyboard
// handling, and the shared `toast-region`/`toast` (already defined in
// `$lib/ui/Toaster.svelte`, merged in the foundation wave). Reconciled in
// pass 2.
// ---------------------------------------------------------------------

describe('ReviewSurface - legible row hierarchy (redesign 5.3)', () => {
	it('shows the term prominently with all five fields present, and humanizes a single-document frequency', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const rows = await screen.findAllByTestId('proposal-row');
		const solubilityRow = rows.find((el) => el.getAttribute('data-id') === 'solubility-1');
		expect(solubilityRow).toBeTruthy();
		const row = solubilityRow as HTMLElement;

		// All five fields remain present.
		expect(row.querySelector('.field.id')).toBeTruthy();
		expect(row.querySelector('.field.kind')).toBeTruthy();
		expect(row.querySelector('.field.status')).toBeTruthy();
		expect(row.querySelector('.field.term')).toBeTruthy();
		expect(row.querySelector('.field.doc-frequency')).toBeTruthy();

		// The term is present and textually part of the row; docFrequency 3
		// -- plural humanized wording, not a bare "3".
		expect(row).toHaveTextContent('solubility');
		expect(row.querySelector('.field.doc-frequency')?.textContent).toMatch(/seen in 3 documents/i);
		expect(row.querySelector('.field.doc-frequency')?.textContent).not.toBe('3');
	});

	it('humanizes a document frequency of 1 as singular ("seen in 1 document")', async () => {
		listProposalsMock.mockResolvedValue(
			queueResponse([
				{
					id: 'single-doc-1',
					kind: 'property',
					status: 'pending',
					term: 'viscosity',
					documentFrequency: 1,
					totalOccurrences: 1,
					corpusCount: 1,
					corpora: ['https://w3id.org/msr-kg/data#corpus-chemistry']
				}
			])
		);

		render(ReviewSurface);
		const row = await screen.findByTestId('proposal-row');

		expect(row.querySelector('.field.doc-frequency')?.textContent).toMatch(/seen in 1 document\b/i);
		expect(row.querySelector('.field.doc-frequency')?.textContent).not.toMatch(/documents/i);
	});

	it('humanizes a large document frequency as plural ("seen in 47 documents")', async () => {
		listProposalsMock.mockResolvedValue(
			queueResponse([
				{
					id: 'many-doc-1',
					kind: 'property',
					status: 'pending',
					term: 'conductivity',
					documentFrequency: 47,
					totalOccurrences: 47,
					corpusCount: 1,
					corpora: ['https://w3id.org/msr-kg/data#corpus-chemistry']
				}
			])
		);

		render(ReviewSurface);
		const row = await screen.findByTestId('proposal-row');

		expect(row.querySelector('.field.doc-frequency')?.textContent).toMatch(/seen in 47 documents/i);
	});
});

describe('ReviewSurface - keyboard navigation (redesign 5.3)', () => {
	// Dispatched on the `proposal-queue` container rather than `document`:
	// this is the superset-safe target -- it satisfies a listener attached
	// directly to the queue container (event originates there) as well as a
	// listener attached to `window`/`document` (the event still bubbles up
	// through the DOM tree to reach them), without assuming which one the
	// coder picked. See report for this assumption.
	it('moves the selection to the next row on ArrowDown/j and to the previous on ArrowUp/k', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());
		const rows = await screen.findAllByTestId('proposal-row');
		expect(rows.length).toBe(proposalQueue.length);
		const queue = screen.getByTestId('proposal-queue');

		// Select the first row, then move forward with ArrowDown.
		await fireEvent.click(rows[0]);
		await fireEvent.keyDown(queue, { key: 'ArrowDown' });

		await waitFor(() => {
			const updatedRows = screen.getAllByTestId('proposal-row');
			expect(updatedRows[1].className).toMatch(/selected/);
		});

		// Move back with 'k'.
		await fireEvent.keyDown(queue, { key: 'k' });
		await waitFor(() => {
			const updatedRows = screen.getAllByTestId('proposal-row');
			expect(updatedRows[0].className).toMatch(/selected/);
		});

		// Move forward again with 'j'.
		await fireEvent.keyDown(queue, { key: 'j' });
		await waitFor(() => {
			const updatedRows = screen.getAllByTestId('proposal-row');
			expect(updatedRows[1].className).toMatch(/selected/);
		});
	});

	it('fires approve on the "a" key and reject on the "r" key for the selected proposal', async () => {
		render(ReviewSurface);
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());
		const queue = screen.getByTestId('proposal-queue');

		await openProposal(solubilityProposal);
		await fireEvent.keyDown(queue, { key: 'a' });
		await waitFor(() => expect(approveProposalMock).toHaveBeenCalledWith('solubility-1', expect.any(String), expect.any(String)));

		await openProposal(graphiteProposal);
		await fireEvent.keyDown(queue, { key: 'r' });
		await waitFor(() => expect(rejectProposalMock).toHaveBeenCalledWith('graphite-1'));
	});
});

describe('ReviewSurface - toast feedback (redesign 5.3)', () => {
	// `toasts` (the `$lib/ui/toast.svelte` module-level `$state` array) is
	// shared, live, singleton state across the whole test file/process --
	// it is not reset by `@testing-library/svelte`'s `cleanup()` (that only
	// unmounts DOM, it does not touch application-level stores). Without
	// clearing it, a toast pushed by one test would still be present (and
	// not yet auto-dismissed -- the default dismiss delay is 4s, far longer
	// than a test) when the next test asserts, breaking the "exactly one
	// toast" queries below. Clear it before each test in this block so every
	// test starts from an empty toast region.
	beforeEach(() => {
		toasts.splice(0, toasts.length);
	});

	/** Renders ReviewSurface alongside the shared `Toaster` display
	 * component. In the real app `Toaster` is mounted once in
	 * `+layout.svelte` (design D5), not inside ReviewSurface -- ReviewSurface
	 * only pushes into the shared store. `@testing-library/svelte`'s
	 * `render()` appends into `document.body`, and `screen` queries against
	 * `document.body`, so two separate `render()` calls compose exactly like
	 * the real app shell does: `Toaster` renders whatever `ReviewSurface`'s
	 * `pushToast(...)` calls push into the shared store. */
	function renderWithToaster() {
		render(Toaster);
		return render(ReviewSurface);
	}

	it('shows a success toast when approve succeeds', async () => {
		renderWithToaster();
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		await fireEvent.click(within(detail).getByTestId('approve-btn'));

		await waitFor(() => expect(approveProposalMock).toHaveBeenCalled());
		const region = await screen.findByTestId('toast-region');
		const toast = await within(region).findByTestId('toast');
		expect(toast).toBeInTheDocument();
		expect(toast.getAttribute('data-kind')).toBe('success');
		expect(toast).toHaveTextContent(/approved|success/i);
	});

	it('shows a failure toast when approve fails (non-validation error) and the proposal stays pending', async () => {
		approveProposalMock.mockRejectedValue(new Error('network error'));

		renderWithToaster();
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(solubilityProposal);
		await fireEvent.click(within(detail).getByTestId('approve-btn'));

		await waitFor(() => expect(approveProposalMock).toHaveBeenCalled());
		const region = await screen.findByTestId('toast-region');
		const toast = await within(region).findByTestId('toast');
		expect(toast).toBeInTheDocument();
		expect(toast.getAttribute('data-kind')).toBe('error');
		expect(toast).toHaveTextContent(/fail|error/i);

		// Prior state preserved -- still pending, approve control still present.
		expect(within(detail).getByTestId('approve-btn')).toBeInTheDocument();
	});

	it('shows a failure toast when reject fails and the proposal stays in its prior state', async () => {
		rejectProposalMock.mockRejectedValue(new Error('network error'));

		renderWithToaster();
		await waitFor(() => expect(listProposalsMock).toHaveBeenCalled());

		const detail = await openProposal(graphiteProposal);
		await fireEvent.click(within(detail).getByTestId('reject-btn'));

		await waitFor(() => expect(rejectProposalMock).toHaveBeenCalled());
		const region = await screen.findByTestId('toast-region');
		const toast = await within(region).findByTestId('toast');
		expect(toast).toBeInTheDocument();
		expect(toast.getAttribute('data-kind')).toBe('error');
		expect(toast).toHaveTextContent(/fail|error/i);
		expect(within(detail).getByTestId('reject-btn')).toBeInTheDocument();
	});
});
