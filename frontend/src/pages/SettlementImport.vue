<script setup>
import { computed, ref } from "vue";
import { Check, FileSpreadsheet, X } from "lucide-vue-next";
import { api, upload } from "../api";
import { rs } from "../format";
import { refresh, toast } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import EmptyState from "../components/EmptyState.vue";
import SelectField from "../components/SelectField.vue";
import Tabs from "../components/Tabs.vue";

const STEPS = ["Upload", "Map columns", "Preview & validate", "Import"];
const step = ref(1);
const courier = ref("");
const couriers = ref([]);
const file = ref(null); // the chosen File object (not yet uploaded)
const fileUrl = ref(""); // set once uploaded
const fileInput = ref(null);
const over = ref(false);
const busy = ref("");
const error = ref("");
const pv = ref(null);
const edit = ref({});
const saveBack = ref(false);
const tab = ref("Issues first");
const result = ref(null);
const loadingCouriers = ref(true);

api.couriers({ active_only: 1 }, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch((e) => (error.value = e.message))
	.finally(() => (loadingCouriers.value = false));

const mappingArg = () => {
	const m = {};
	Object.entries(edit.value).forEach(([h, f]) => f && (m[h] = f));
	return m;
};

const preview = async (useEdits = false) => {
	busy.value = "preview";
	error.value = "";
	try {
		pv.value = await api.import_preview(
			{
				file_url: fileUrl.value,
				courier: courier.value,
				mapping: useEdits ? mappingArg() : null,
			},
			{ silent: true }
		);
		edit.value = Object.fromEntries(pv.value.mapping.map((m) => [m.header, m.field || ""]));
		saveBack.value = pv.value.mapping_source !== "saved";
		return true;
	} catch (e) {
		error.value = e.message;
		return false;
	} finally {
		busy.value = "";
	}
};

const kb = (n) =>
	n < 1024 * 100 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(2)} MB`;
const choose = (f) => {
	if (!f) return;
	if (!/\.(xlsx|xls|csv)$/i.test(f.name)) {
		error.value = "Only .xlsx, .xls or .csv files are supported.";
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
const toMap = async () => {
	error.value = "";
	busy.value = "upload";
	try {
		if (!fileUrl.value) fileUrl.value = (await upload(file.value)).file_url;
	} catch (e) {
		error.value = e.message;
		busy.value = "";
		return;
	}
	if (await preview(false)) step.value = 2;
};

const reset = () => {
	step.value = 1;
	pv.value = null;
	removeFile();
	result.value = null;
	error.value = "";
};

const nextToPreview = async () => {
	if (await preview(true)) step.value = 3;
};

const step1Ok = computed(() => !!courier.value && !!file.value);
const step2Ok = computed(
	() =>
		Object.values(edit.value).includes("awb") && Object.values(edit.value).includes("net_paid")
);
const dupBatches = computed(() => pv.value?.duplicate_batches || []);
const allDup = computed(
	() =>
		pv.value &&
		pv.value.batches.length > 0 &&
		dupBatches.value.length === pv.value.batches.length
);
const importable = computed(
	() =>
		(pv.value?.valid_count || 0) -
		(pv.value?.rows || []).filter((r) => r.validation === "Already imported").length
);
const canImport = computed(
	() => pv.value && pv.value.valid_count > 0 && !allDup.value && busy.value !== "commit"
);

const commit = async () => {
	busy.value = "commit";
	error.value = "";
	try {
		const res = await api.import_commit({
			file_url: fileUrl.value,
			courier: courier.value,
			mapping: mappingArg(),
			save_mapping: saveBack.value ? 1 : 0,
		});
		result.value = res;
		step.value = 4;
		refresh();
	} catch (e) {
		error.value = e.message;
	} finally {
		busy.value = "";
	}
};

const tabs = computed(() => [
	{
		key: "Issues first",
		label: "Issues first",
		count: (pv.value?.rows || []).filter((r) => r.validation !== "Matched").length,
	},
	{ key: "All rows", label: "All rows", count: pv.value?.row_count },
]);
const shown = computed(() =>
	tab.value === "All rows"
		? [...(pv.value?.rows || [])].sort((a, b) => a.row - b.row)
		: pv.value?.rows || []
);
const kind = (v) =>
	({
		Matched: "ok",
		Invalid: "exc",
		"AWB not found": "exc",
		"Duplicate AWB": "mis",
		"Ambiguous AWB": "mis",
	}[v] || "");
const columns = [
	{ key: "row", label: "Row" },
	{ key: "awb", label: "AWB" },
	{ key: "order", label: "Order" },
	{ key: "cod_amount", label: "COD amount", num: true },
	{ key: "deductions", label: "Deductions", num: true },
	{ key: "net", label: "Net", num: true },
	{ key: "validation", label: "Validation" },
];
const FIELD_LABEL = {
	remittance_id: "Remittance ID",
	remittance_date: "Remittance date",
	utr_number: "UTR",
	awb: "AWB",
	cod_amount: "COD amount",
	freight_charge: "Freight",
	cod_fee: "COD fee",
	gst: "GST",
	net_paid: "Net paid",
	charged_weight: "Charged weight",
	rto_charge: "RTO charge",
	weight_charge: "Weight charge",
	other_charge: "Other charge",
	row_no: "Row no",
};
const label = (f) => FIELD_LABEL[f] || f;
const m = computed(() => result.value?.matching || {});
</script>

<template>
	<div class="wrap">
		<div class="crumb">
			<router-link to="/settlements">Settlements</router-link> /
			<span>Import settlement file</span>
		</div>
		<div class="ph"><h1>Import settlement file</h1></div>

		<section class="card">
			<div class="ch">
				<div class="stepper">
					<template v-for="(s, i) in STEPS" :key="s">
						<span v-if="i" class="sep"></span>
						<span :class="['st', { done: step > i + 1, cur: step === i + 1 }]"
							><span class="n"
								><Check
									v-if="step > i + 1"
									:size="12"
									:stroke-width="2.4"
								/><template v-else>{{ i + 1 }}</template></span
							>{{ s }}</span
						>
					</template>
				</div>
			</div>
			<div class="cb" style="display: flex; flex-direction: column; gap: 14px">
				<div v-if="error" class="imp-banner err" role="alert">
					<strong>{{ error }}</strong>
				</div>

				<!-- 1 upload -->
				<template v-if="step === 1">
					<div style="display: flex; flex-direction: column; gap: 4px">
						<span class="muted">Courier <b class="neg">*</b></span>
						<SelectField
							v-model="courier"
							:options="couriers"
							:disabled="loadingCouriers"
							placeholder="Choose a courier"
							aria-label="Courier"
						/>
						<span v-if="!loadingCouriers && !couriers.length" class="muted"
							>No active couriers. Create or activate a Courier in the Desk
							first.</span
						>
					</div>
					<div
						v-if="!file"
						:class="['drop', { over }]"
						@dragover.prevent="over = true"
						@dragleave="over = false"
						@drop.prevent="onDrop"
					>
						<FileSpreadsheet :size="28" :stroke-width="1.4" />
						<strong>Drop the courier's payout file here</strong>
						<span class="muted">.xlsx, .xls or .csv</span>
						<label class="btn"
							>Choose file<input
								ref="fileInput"
								type="file"
								accept=".xlsx,.xls,.csv"
								hidden
								@change="choose($event.target.files[0])"
						/></label>
					</div>
					<div v-else class="imp-file">
						<span class="fi"><FileSpreadsheet :size="18" :stroke-width="1.6" /></span>
						<div>
							<strong>{{ file.name }}</strong>
							<div class="muted">{{ kb(file.size) }}</div>
						</div>
						<div class="acts">
							<button
								class="btn sm"
								:disabled="!!busy"
								aria-label="Remove file"
								@click="removeFile"
							>
								<X :size="14" :stroke-width="1.8" />Remove
							</button>
						</div>
					</div>
				</template>

				<!-- 2 map -->
				<template v-if="step === 2 && pv">
					<div class="file">
						<span class="fi"><FileSpreadsheet :size="18" :stroke-width="1.6" /></span>
						<div>
							<strong>{{ pv.file.name }}</strong>
							<div class="muted">
								{{ pv.row_count }} rows<template v-if="pv.file.size_kb">
									· {{ pv.file.size_kb }} KB</template
								>
								· mapping
								{{
									pv.mapping_source === "saved"
										? "saved on courier"
										: "auto-detected"
								}}
							</div>
						</div>
						<div class="acts">
							<button class="btn sm" @click="reset">Replace file</button>
						</div>
					</div>
					<EmptyState
						v-if="!pv.headers.length"
						title="The file has no header row"
						text="Add a header row and upload again."
					/>
					<div v-else class="tw">
						<table>
							<thead>
								<tr>
									<th>File column</th>
									<th>Maps to</th>
									<th>Sample</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="h in pv.headers" :key="h">
									<td>
										<span class="mono">{{ h }}</span>
									</td>
									<td>
										<select
											v-model="edit[h]"
											class="inpl"
											style="max-width: 220px"
											:aria-label="`Field for ${h}`"
										>
											<option value="">Ignore this column</option>
											<option v-for="f in pv.fields" :key="f" :value="f">
												{{ label(f) }}
											</option>
										</select>
									</td>
									<td class="muted">
										{{ pv.preview[0] && pv.preview[0][edit[h]] }}
									</td>
								</tr>
							</tbody>
						</table>
					</div>
					<label class="chk"
						><input v-model="saveBack" type="checkbox" /> Save this mapping on
						{{ courier }} for next time</label
					>
				</template>

				<!-- 3 preview -->
				<template v-if="step === 3 && pv">
					<div class="file">
						<span class="fi"><FileSpreadsheet :size="18" :stroke-width="1.6" /></span>
						<div>
							<strong>{{ pv.file.name }}</strong>
							<div class="muted">
								{{ pv.row_count }} rows<template v-if="pv.file.size_kb">
									· {{ pv.file.size_kb }} KB</template
								>
								· {{ courier }}
							</div>
						</div>
						<div class="acts">
							<button class="btn sm" @click="reset">Replace file</button>
						</div>
					</div>
					<div v-if="dupBatches.length" class="imp-banner warn">
						<strong
							>Remittance {{ dupBatches.join(", ") }} was already imported.</strong
						>
						<span>{{
							allDup
								? "Nothing will be created for this file."
								: "Rows of that batch will be skipped."
						}}</span>
					</div>
					<div class="vsum">
						<div class="vs" style="background: #e4f5ec">
							<b>{{ pv.tiles.matched }}</b
							><span><i class="dot g"></i>Matched to orders</span>
						</div>
						<div class="vs" style="background: #fff0ec">
							<b>{{ pv.tiles.awb_not_found }}</b
							><span><i class="dot r"></i>AWB not found</span>
						</div>
						<div class="vs">
							<b>{{ pv.tiles.duplicate }}</b
							><span>Duplicates / already imported</span>
						</div>
						<div class="vs" style="background: #fff0ec">
							<b>{{ pv.tiles.invalid }}</b
							><span><i class="dot r"></i>Rows with errors</span>
						</div>
					</div>
					<div class="maps">
						<span class="muted">Columns:</span>
						<span
							v-for="x in pv.mapping.filter((q) => q.field)"
							:key="x.header"
							class="map"
							>{{ x.header }} <i>→</i> {{ label(x.field) }}</span
						>
						<button class="btn link sm" @click="step = 2">Edit mapping</button>
					</div>
					<Tabs v-model="tab" :tabs="tabs" />
					<EmptyState
						v-if="!shown.length"
						title="No rows to show"
						text="The file has no data rows."
					/>
					<DataTable
						v-else
						:columns="columns"
						:rows="shown"
						row-key="row"
						:row-class="
							(r) =>
								['Invalid', 'AWB not found'].includes(r.validation) ? 'bad' : ''
						"
					>
						<template #cell-awb="{ row }"
							><span class="mono">{{ row.awb || "—" }}</span></template
						>
						<template #cell-order="{ row }">{{ row.order || "No match" }}</template>
						<template #cell-cod_amount="{ row }">{{ rs(row.cod_amount) }}</template>
						<template #cell-deductions="{ row }">{{ rs(row.deductions) }}</template>
						<template #cell-net="{ row }">{{ rs(row.net) }}</template>
						<template #cell-validation="{ row }"
							><Badge :kind="kind(row.validation)">{{ row.validation }}</Badge>
							<span v-if="row.detail" class="muted">{{ row.detail }}</span></template
						>
					</DataTable>
					<p v-if="pv.rows_truncated" class="muted">
						Showing the first {{ pv.rows.length }} rows; all valid rows are imported.
					</p>
					<p class="muted">
						File total: COD {{ rs(pv.totals.cod) }} · Deductions
						{{ rs(pv.totals.deductions) }} ·
						<strong>Net {{ rs(pv.totals.net) }}</strong>
					</p>
					<p class="muted">
						Rows with errors, and rows of an already imported batch, are skipped.
						{{ pv.tiles.awb_not_found }} unknown AWB(s) become exceptions.
					</p>
				</template>

				<!-- 4 result -->
				<template v-if="step === 4 && result">
					<EmptyState
						v-if="result.queued"
						title="Import running in the background"
						:text="`${result.rows} rows are being imported. Check Settlements in a few minutes; the Sync Log has the outcome.`"
					>
						<router-link class="btn pri" to="/settlements"
							>Go to settlements</router-link
						>
					</EmptyState>
					<template v-else>
						<div v-if="result.message" class="imp-banner warn">
							<strong>{{ result.message }}</strong>
						</div>
						<div class="vsum">
							<div class="vs" style="background: #e4f5ec">
								<b>{{ (result.remittances || []).length }}</b
								><span>Batches created</span>
							</div>
							<div class="vs">
								<b>{{ result.lines || 0 }}</b
								><span>Lines imported</span>
							</div>
							<div class="vs">
								<b>{{ m.matched || 0 }}</b
								><span>Matched</span>
							</div>
							<div class="vs">
								<b>{{ m["short-paid"] || 0 }}</b
								><span>Short-paid</span>
							</div>
							<div class="vs">
								<b>{{ m.unknown || 0 }}</b
								><span>Unknown AWB</span>
							</div>
							<div class="vs" style="background: #fff0ec">
								<b>{{ m.exceptions || 0 }}</b
								><span>Exceptions opened</span>
							</div>
						</div>
						<div
							v-if="result.remittances && result.remittances.length"
							style="display: flex; gap: 8px; flex-wrap: wrap"
						>
							<router-link
								v-for="b in result.remittances"
								:key="b"
								class="btn"
								:to="`/settlements/${encodeURIComponent(b)}`"
								>Open batch {{ b }}</router-link
							>
						</div>
						<div v-if="result.errors && result.errors.length" class="tw">
							<table>
								<thead>
									<tr>
										<th>Row</th>
										<th>Skipped because</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="e in result.errors" :key="e.row + e.reason">
										<td>{{ e.row }}</td>
										<td>{{ e.reason }}</td>
									</tr>
								</tbody>
							</table>
						</div>
						<EmptyState
							v-if="
								!result.remittances.length &&
								!result.message &&
								!(result.errors || []).length
							"
							title="Nothing was imported"
							text="The file produced no new batches."
						/>
					</template>
				</template>
			</div>

			<div v-if="step < 4" class="mf">
				<span class="muted">{{
					step === 1
						? "Choose the courier and its payout file."
						: step === 2
						? "Check how each file column maps to a field."
						: "Review the validation, then import."
				}}</span>
				<div class="acts">
					<button
						v-if="step > 1"
						class="btn"
						:disabled="!!busy"
						@click="step = step - 1"
					>
						Back
					</button>
					<button
						v-if="step === 1"
						class="btn pri"
						:disabled="!step1Ok || !!busy"
						@click="toMap"
					>
						<span v-if="busy" class="spin"></span
						>{{
							busy === "upload"
								? "Uploading..."
								: busy === "preview"
								? "Reading file..."
								: "Next: Map columns"
						}}
					</button>
					<button
						v-else-if="step === 2"
						class="btn pri"
						:disabled="!step2Ok || !!busy"
						:title="step2Ok ? '' : 'Map at least AWB and Net paid'"
						@click="nextToPreview"
					>
						<span v-if="busy === 'preview'" class="spin"></span>Next: Preview &amp;
						validate
					</button>
					<button v-else class="btn pri" :disabled="!canImport" @click="commit">
						<span v-if="busy === 'commit'" class="spin"></span
						>{{ busy === "commit" ? "Importing..." : `Import ${importable} rows` }}
					</button>
				</div>
			</div>
			<div v-if="step === 4" class="mf">
				<div class="acts" style="margin-left: 0">
					<router-link class="btn" to="/exceptions">View exceptions</router-link>
					<router-link class="btn" to="/settlements">All settlements</router-link>
					<button class="btn pri" @click="reset">Import another file</button>
				</div>
			</div>
		</section>
	</div>
</template>
