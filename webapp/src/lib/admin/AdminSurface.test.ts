// Tests for the admin surface (admin-ui spec, task 8.5), mounting the
// top-level `$lib/admin/AdminSurface.svelte` component and driving it
// against a mocked `$lib/api` module.
//
// NOTE (pass 1): AdminSurface.svelte does not exist yet -- it is built
// concurrently by the wave-2 admin-ui coder in a separate worktree. This
// suite is written directly against the admin-ui spec's acceptance
// scenarios and the pinned testids in the task contract; it is expected to
// fail to resolve/compile until the merge, and is reconciled in pass 2.
//
// Assumption made about a component we cannot see yet: each `checkpoint-
// item` carries its own `checkpoint-restore` trigger and, on click, a
// `restore-confirm` control appears (scoped to that item, or a single
// shared confirm dialog) that must itself be clicked before
// `restoreCheckpoint` fires (admin-ui spec "Restore is confirmed before
// firing").
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { checkpointList, preDemoCheckpoint } from '../__fixtures__/checkpoints';

const { listCheckpointsMock, createCheckpointMock, restoreCheckpointMock } = vi.hoisted(() => ({
	listCheckpointsMock: vi.fn(),
	createCheckpointMock: vi.fn(),
	restoreCheckpointMock: vi.fn()
}));

vi.mock('$lib/api', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/api')>();
	return {
		...actual,
		listCheckpoints: listCheckpointsMock,
		createCheckpoint: createCheckpointMock,
		restoreCheckpoint: restoreCheckpointMock
	};
});

import { ApiError } from '$lib/api';
import AdminSurface from './AdminSurface.svelte';

beforeEach(() => {
	listCheckpointsMock.mockReset().mockResolvedValue(checkpointList);
	createCheckpointMock.mockReset();
	restoreCheckpointMock.mockReset().mockResolvedValue({ status: 'restored' });
});

describe('AdminSurface - checkpoint list', () => {
	it('loads and lists existing checkpoints', async () => {
		render(AdminSurface);

		await waitFor(() => expect(listCheckpointsMock).toHaveBeenCalled());
		const list = await screen.findByTestId('checkpoint-list');
		const items = within(list).getAllByTestId('checkpoint-item');
		expect(items.length).toBe(checkpointList.checkpoints.length);
		expect(list).toHaveTextContent(preDemoCheckpoint.label);
	});
});

describe('AdminSurface - create checkpoint', () => {
	it('creates a checkpoint and lists it on success', async () => {
		createCheckpointMock.mockResolvedValue({ label: 'demo', ontology_version: 'v1.2.0' });

		render(AdminSurface);
		await waitFor(() => expect(listCheckpointsMock).toHaveBeenCalled());

		await fireEvent.input(screen.getByTestId('checkpoint-label-input'), { target: { value: 'demo' } });
		await fireEvent.click(screen.getByTestId('checkpoint-create'));

		await waitFor(() => expect(createCheckpointMock).toHaveBeenCalledWith('demo'));

		const list = await screen.findByTestId('checkpoint-list');
		await waitFor(() => expect(list).toHaveTextContent('demo'));
	});

	it('surfaces a rejected-label error and adds nothing to the list', async () => {
		createCheckpointMock.mockRejectedValue(
			new ApiError(400, { error: 'invalid_label', message: 'label contains invalid characters' })
		);

		render(AdminSurface);
		await waitFor(() => expect(listCheckpointsMock).toHaveBeenCalled());
		const initialCount = within(await screen.findByTestId('checkpoint-list')).getAllByTestId(
			'checkpoint-item'
		).length;

		await fireEvent.input(screen.getByTestId('checkpoint-label-input'), {
			target: { value: '../etc/passwd' }
		});
		await fireEvent.click(screen.getByTestId('checkpoint-create'));

		const error = await screen.findByTestId('checkpoint-error');
		expect(error).toHaveTextContent(/invalid/i);

		const list = await screen.findByTestId('checkpoint-list');
		expect(within(list).getAllByTestId('checkpoint-item').length).toBe(initialCount);
	});
});

describe('AdminSurface - restore checkpoint', () => {
	it('requires confirmation before calling restoreCheckpoint', async () => {
		render(AdminSurface);
		const list = await screen.findByTestId('checkpoint-list');
		const items = within(list).getAllByTestId('checkpoint-item');
		const preDemoItem = items.find((el) => el.textContent?.includes(preDemoCheckpoint.label));
		if (!preDemoItem) throw new Error('pre-demo checkpoint item not found');

		await fireEvent.click(within(preDemoItem).getByTestId('checkpoint-restore'));

		// Not yet fired -- a confirmation is required first.
		expect(restoreCheckpointMock).not.toHaveBeenCalled();
		const confirm = await screen.findByTestId('restore-confirm');

		await fireEvent.click(confirm);

		await waitFor(() =>
			expect(restoreCheckpointMock).toHaveBeenCalledWith(preDemoCheckpoint.label)
		);
	});
});
