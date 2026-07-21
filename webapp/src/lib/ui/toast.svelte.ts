// Shared, non-blocking toast notifications (frontend-design-system spec
// "Toast notifications for actions"). A Svelte 5 runes store: module-level
// `$state` so any surface can `pushToast(...)` from a plain event handler
// (approve/reject in review-ui, create/restore in admin-ui, …) without
// threading props through the component tree. `Toaster.svelte` is the single
// place that renders `toasts` and should be mounted once, in the app shell.

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
	id: number;
	message: string;
	kind: ToastKind;
}

const DEFAULT_DISMISS_MS = 4000;

let nextId = 0;

// Exported as a live binding (standard Svelte 5 "`.svelte.ts` module state"
// pattern): consumers `import { toasts } from '$lib/ui/toast.svelte'` and
// read it reactively. Mutated in place (push/splice) rather than reassigned,
// so the reactive array proxy notifies readers without needing a setter.
export const toasts: Toast[] = $state([]);

/** Adds a toast; it auto-dismisses after a timeout unless dismissed sooner.
 * `kind` defaults to 'info'. */
export function pushToast(opts: { message: string; kind?: ToastKind }): number {
	const id = nextId++;
	toasts.push({ id, message: opts.message, kind: opts.kind ?? 'info' });
	if (typeof setTimeout === 'function') {
		setTimeout(() => dismissToast(id), DEFAULT_DISMISS_MS);
	}
	return id;
}

/** Removes a toast immediately (manual dismiss, e.g. a close button). No-op
 * if it was already dismissed (auto-dismiss race). */
export function dismissToast(id: number): void {
	const index = toasts.findIndex((toast) => toast.id === id);
	if (index !== -1) {
		toasts.splice(index, 1);
	}
}
