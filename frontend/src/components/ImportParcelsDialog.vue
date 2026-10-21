<script setup>
import { computed, ref } from "vue";
import { FileSpreadsheet, X } from "lucide-vue-next";
import { api, upload } from "../api";
import { refresh, toast } from "../store";
import Modal from "./Modal.vue";

const emit = defineEmits(["close"]);
const STEPS = ["Upload", "Map & preview", "Result"];
const step = ref(1);
const courier = ref("");
const couriers = ref([]);
const file = ref(null);
const fileUrl = ref("");
const fileInput = ref(null);
const over = ref(false);
const busy = ref("");
const error = ref("");
const pv = ref(null);
const edit = ref({});
const result = ref(null);
let committing = false;

api.couriers({ active_only: 1 }, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch((e) => (error.value = e.message));

const mappingArg = () => {
	const m = {};
	Object.entries(edit.value).forEach(([h, f]) => f && (m[h] = f));
	return m;
};
const kb = (n) => (n < 1024 * 100 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`);
const choose = (f) => {
	if (!f) return;
	if (!/\.(xlsx|csv)$/i.test(f.name)) {
		error.value = "Only .xlsx or .csv files are supported.";
		return;
	}
	error.value = "";
	file.value = f;
	fileUrl.value = "";
};
const removeFile = () => {
	file.value = null;
	fileUrl.value = "";
	if (fileInput.value) fileInput.value.value = "";
};
const onDrop = (e) => {
	over.value = false;
	choose(e.dataTransfer.files[0]);
};

const preview = async (useEdits) => {
	pv.value = await api.parcels_import_preview(
		{ file_url: fileUrl.value, courier: courier.value, mapping: useEdits ? mappingArg() : null },
		{ silent: true }
	);
	edit.value = Object.fromEntries(pv.value.mapping.map((m) => [m.header, m.field || ""]));
};

// Step 1 -> 2: upload, then run the preview automatically
const next = async () => {
	if (busy.value) return;
	busy.value = "next";
	error.value = "";
	try {
		if (!fileUrl.value) fileUrl.value = (await upload(file.value)).file_url;
		await preview(false);
		step.value = 2;
	} catch (e) {
		error.value = e.message;
		toast(e.message, "e");
	} finally {
		busy.value = "";
	}
};
const repreview = async () => {
	if (busy.value) return;
	busy.value = "preview";
	error.value = "";
	try {
		await preview(true);
	} catch (e) {
		error.value = e.message;
		toast(e.message, "e");
	} finally {
		busy.value = "";
	}
};
const commit = async () => {
	if (committing || busy.value) return;
	committing = true;
	busy.value = "commit";
	error.value = "";
	try {
		result.value = await api.parcels_import_commit(
			{ file_url: fileUrl.value, courier: courier.value, mapping: mappingArg() },
			{ silent: true }
		);
		step.value = 3;
	} catch (e) {
		error.value = e.message;
		toast(`Import failed: ${e.message}`, "e");
		committing = false;
	} finally {
		busy.value = "";
	}
};
const done = () => {
	if (result.value) refresh();
	emit("close");
};
const close = () => (busy.value ? null : done());

const step1Ok = computed(() => !!courier.value && !!file.value);
const canImport = computed(() => pv.value && pv.value.valid_count > 0);
const previewCols = computed(() => (pv.value?.fields || []).filter((f, i, a) => a.indexOf(f) === i));
const label = (f) => f.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
</script>

<template>
	<Modal title="Import parcels" width="760px" @close="close">
		<div class="muted" style="margin-bottom: 12px">
			Step {{ step }} of 3: {{ STEPS[step - 1] }}
		</div>
		<p v-if="error" class="neg" role="alert">{{ error }}</p>

		<template v-if="step === 1">
			<label class="fld-col">
				<span>Courier</span>
				<select v-model="courier" class="sel" aria-label="Courier">
					<option value="" disabled>Choose a courier</option>
					<option v-for="c in couriers" :key="c" :value="c">{{ c }}</option>
				</select>
			</label>
			<label class="fld-col" style="margin-top: 12px">
				<span>Platform</span>
				<select class="sel" disabled aria-label="Platform"><option>Excel</option></select>
			</label>
			<div
				class="drop"
				:class="{ over }"
				style="margin-top: 12px"
				@dragover.prevent="over = true"
				@dragleave="over = false"
				@drop.prevent="onDrop"
			>
				<template v-if="file">
					<FileSpreadsheet :size="22" :stroke-width="1.6" />
					<strong>{{ file.name }}</strong>
					<span class="muted">{{ kb(file.size) }}</span>
					<button class="btn sm" :disabled="!!busy" @click="removeFile">
						<X :size="14" :stroke-width="1.6" />Remove
					</button>
				</template>
				<template v-else>
					<FileSpreadsheet :size="22" :stroke-width="1.6" />
					<span>Drop a .xlsx or .csv file here</span>
					<button class="btn sm" @click="fileInput.click()">Choose file</button>
				</template>
				<input
					ref="fileInput"
					type="file"
					accept=".xlsx,.csv"
					hidden
					@change="choose($event.target.files[0])"
				/>
			</div>
		</template>

		<template v-else-if="step === 2 && pv">
			<p>
				<strong>{{ pv.valid_count }}</strong> valid,
				<strong :class="{ neg: pv.invalid_count }">{{ pv.invalid_count }}</strong> invalid of
				{{ pv.row_count }} rows.
			</p>
			<h3>Column mapping</h3>
			<table class="tbl">
				<thead>
					<tr><th>File column</th><th>Field</th></tr>
				</thead>
				<tbody>
					<tr v-for="m in pv.mapping" :key="m.header">
						<td>{{ m.header }}</td>
						<td>
							<select v-model="edit[m.header]" class="sel" :aria-label="`Field for ${m.header}`" @change="repreview">
								<option value="">Ignore this column</option>
								<option v-for="f in pv.all_fields" :key="f" :value="f">{{ label(f) }}</option>
							</select>
						</td>
					</tr>
				</tbody>
			</table>
			<h3 style="margin-top: 16px">First {{ pv.preview.length }} rows</h3>
			<div style="overflow-x: auto">
				<table class="tbl">
					<thead>
						<tr><th>Row</th><th v-for="f in previewCols" :key="f">{{ label(f) }}</th></tr>
					</thead>
					<tbody>
						<tr v-for="r in pv.preview" :key="r.row">
							<td>{{ r.row }}</td>
							<td v-for="f in previewCols" :key="f">{{ r[f] }}</td>
						</tr>
					</tbody>
				</table>
			</div>
			<template v-if="pv.invalid_rows.length">
				<h3 style="margin-top: 16px">Invalid rows</h3>
				<ul>
					<li v-for="r in pv.invalid_rows" :key="r.row">
						<strong>Row {{ r.row }}:</strong> <span class="neg">{{ r.reason }}</span>
					</li>
				</ul>
			</template>
		</template>

		<template v-else-if="step === 3 && result">
			<p><strong>Import finished.</strong></p>
			<p>
				Created <strong>{{ result.created }}</strong>, skipped
				<strong>{{ result.skipped }}</strong
				>, failed <strong :class="{ neg: result.errors?.length }">{{ result.errors?.length || 0 }}</strong>
				<span v-if="result.updated"> ({{ result.updated }} updated)</span>.
			</p>
			<ul v-if="result.errors?.length">
				<li v-for="r in result.errors" :key="r.row">
					<strong>Row {{ r.row }}:</strong> <span class="neg">{{ r.reason }}</span>
				</li>
			</ul>
			<a href="/app/sync-log" target="_blank" rel="noopener">View the Sync Log</a>
		</template>

		<template #footer>
			<div class="acts" style="margin-left: auto">
				<template v-if="step < 3">
					<button v-if="step === 2" class="btn" :disabled="!!busy" @click="step = 1">Back</button>
					<button v-if="step === 1" class="btn primary" :disabled="!step1Ok || !!busy" @click="next">
						<span v-if="busy === 'next'" class="spin"></span>Next
					</button>
					<button v-else class="btn primary" :disabled="!canImport || !!busy" @click="commit">
						<span v-if="busy === 'commit' || busy === 'preview'" class="spin"></span>Import
					</button>
				</template>
				<button v-else class="btn primary" @click="done">Done</button>
			</div>
		</template>
	</Modal>
</template>
