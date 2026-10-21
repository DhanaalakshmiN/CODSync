import { reactive } from "vue";

// Shared UI state: toasts, boot data, global modals/drawer and a refresh tick.
export const state = reactive({
	boot: null,
	toasts: [],
	tick: 0, // bump after any write so pages and the sidebar reload
	importModal: { open: false, courier: null },
	connectModal: { open: false, courier: null },
	drawer: { open: false, name: null },
});

let toastId = 0;
export function toast(message, kind = "", action = null, ms = 4500) {
	const t = { id: ++toastId, message, kind, action };
	state.toasts.push(t);
	setTimeout(() => dismissToast(t.id), ms);
}
export function dismissToast(id) {
	state.toasts = state.toasts.filter((t) => t.id !== id);
}

export function refresh() {
	state.tick++;
}
export function openImport(courier = null) {
	state.importModal = { open: true, courier };
}
export function openConnect(courier) {
	state.connectModal = { open: true, courier };
}
export function openException(name) {
	state.drawer = { open: true, name };
}
export function closeDrawer() {
	state.drawer = { open: false, name: null };
}
