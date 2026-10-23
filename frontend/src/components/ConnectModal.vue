<script setup>
import { computed, ref } from "vue";
import { api } from "../api";
import { refresh, state, toast } from "../store";
import Badge from "./Badge.vue";
import Modal from "./Modal.vue";

const name = state.connectModal.courier;
const courier = ref(null);
const key = ref("");
const busy = ref(false);
const result = ref(null); // { ok, message }
const loadErr = ref("");

const close = () => !busy.value && (state.connectModal.open = false);
const needsKey = computed(() => courier.value?.tracking_provider === "Ship24");

(async () => {
	try {
		const rows = await api.couriers({}, { silent: true });
		courier.value = rows.find((c) => c.name === name) || null;
		if (!courier.value) loadErr.value = `Courier ${name} not found`;
	} catch (e) {
		loadErr.value = e.message;
	}
})();

const connect = async () => {
	busy.value = true;
	result.value = null;
	try {
		if (key.value.trim()) {
			await api.save_courier({ name, values: {}, api_key: key.value }, { silent: true });
			key.value = "";
		}
		const r = await api.test_courier({ name }, { silent: true });
		result.value = r;
		if (r.ok) {
			toast(`${courier.value?.display_name || name} connected`);
			refresh();
			state.connectModal.open = false;
		}
	} catch (e) {
		result.value = { ok: false, message: e.message };
	} finally {
		busy.value = false;
	}
};
</script>
<template>
	<Modal title="Reconnect courier" width="480px" pg="pg-settings" @close="close">
		<p v-if="loadErr" class="muted">{{ loadErr }}</p>
		<template v-else-if="courier">
			<p>
				<strong>{{ courier.display_name || courier.name }}</strong>
				<span class="muted"> · tracking via {{ courier.tracking_provider }}</span>
			</p>
			<p v-if="courier.last_error" class="muted">Last error: {{ courier.last_error }}</p>
			<label v-if="needsKey" style="display: block; margin-top: 12px"
				><span class="lab2"
					>API key
					<Badge v-if="courier.api_key_saved" kind="ok">Saved</Badge
					><Badge v-else kind="pend">Not set</Badge></span
				>
				<input
					v-model="key"
					class="inp"
					type="password"
					autocomplete="new-password"
					:placeholder="courier.api_key_saved ? 'Saved (type to replace)' : 'Paste the API key'"
					@keyup.enter="connect"
			/></label>
			<p v-else class="muted">This courier needs no API key. Test the connection to clear the alert.</p>
			<p v-if="result" role="alert" :style="{ color: result.ok ? '#067647' : '#b42318' }">
				{{ result.message }}
			</p>
		</template>
		<p v-else class="muted">Loading…</p>
		<template #footer>
			<button class="btn" :disabled="busy" @click="close">Cancel</button>
			<button class="btn pri" :disabled="busy || !courier" @click="connect">
				{{ busy ? "Testing…" : key.trim() ? "Save & test" : "Test connection" }}
			</button>
		</template>
	</Modal>
</template>
