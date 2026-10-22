<script setup>
import { computed, ref } from "vue";
import { Plus, Plug, RefreshCw, Pencil, X } from "lucide-vue-next";
import { api, call } from "../api";
import { ago, dShortTime } from "../format";
import { refresh, toast } from "../store";
import Badge from "../components/Badge.vue";
import Drawer from "../components/Drawer.vue";
import EmptyState from "../components/EmptyState.vue";
import PageState from "../components/PageState.vue";
import SelectField from "../components/SelectField.vue";
import CourierPerformance from "../components/CourierPerformance.vue";
import Tabs from "../components/Tabs.vue";

const pageTab = ref("Couriers");
const PAGE_TABS = [
	{ key: "Couriers", label: "Couriers" },
	{ key: "Performance", label: "Performance" },
];
const rows = ref(null);
const loading = ref(true);
const error = ref("");
const busy = ref(""); // "<action>:<courier>"
const banner = ref(null);

const load = async () => {
	loading.value = !rows.value;
	error.value = "";
	try {
		rows.value = await api.couriers({}, { silent: true });
	} catch (e) {
		error.value = e.message;
	}
	loading.value = false;
};
load();

const kind = (s) => ({ Connected: "ok", "Action needed": "exc", Syncing: "info" }[s] || "");
const isBusy = (a, c) => busy.value === `${a}:${c}`;

const test = async (c) => {
	busy.value = `test:${c.name}`;
	banner.value = null;
	try {
		const r = await api.test_courier({ name: c.name }, { silent: true });
		banner.value = { ok: r.ok, text: `${c.display_name}: ${r.message}` };
		await load();
	} catch (e) {
		banner.value = { ok: false, text: `${c.display_name}: ${e.message}` };
	} finally {
		busy.value = "";
	}
};
const syncTracking = async (c) => {
	busy.value = `sync:${c.name}`;
	banner.value = null;
	try {
		const r = await call(
			"codsync.codsync.tracking.sync_tracking",
			{ courier: c.name },
			{ silent: true }
		);
		banner.value = {
			ok: !r.failed,
			text: `${c.display_name}: ${r.checked} checked, ${r.updated} updated, ${r.failed} failed`,
		};
		await load();
		refresh();
	} catch (e) {
		banner.value = { ok: false, text: `${c.display_name}: ${e.message}` };
	} finally {
		busy.value = "";
	}
};

// ---- drawer (edit / add)
const PROVIDERS = ["Mock", "Ship24"];
const VIA = [{ value: "", label: "Not set" }, "API", "Excel"];
const NUM = [
	"payout_cycle_days",
	"cod_fee_percent",
	"gst_percent",
	"base_weight_kg",
	"base_freight",
	"additional_freight_per_kg",
	"tracking_interval_min",
];
const editing = ref(null); // courier card or { new: true }
const form = ref(null);
const key = ref("");
const maps = ref({ parcels: [], remittance: [] });
const saveErr = ref("");
const saving = ref(false);

const toRows = (o) =>
	Object.entries(o || {}).map(([file_column, field]) => ({ file_column, field }));
const toObj = (r) =>
	Object.fromEntries(
		r
			.filter((x) => x.file_column.trim() && x.field.trim())
			.map((x) => [x.file_column.trim(), x.field.trim()])
	);
const open = (c) => {
	saveErr.value = "";
	key.value = "";
	editing.value = c || { new: true };
	form.value = c
		? {
				courier_name: c.name,
				is_active: c.is_active,
				tracking_provider: c.tracking_provider || "Mock",
				tracking_sync_enabled: c.tracking_enabled,
				tracking_interval_min: c.tracking_interval_min,
				settlement_via: c.settlement_via || "",
				settlement_sync_enabled: c.settlement_enabled,
				settlement_sync_time: c.settlement_time,
				...Object.fromEntries(NUM.filter((k) => k in c).map((k) => [k, c[k]])),
		  }
		: {
				courier_name: "",
				is_active: true,
				tracking_provider: "Mock",
				tracking_sync_enabled: false,
				tracking_interval_min: 30,
				settlement_via: "Excel",
				settlement_sync_enabled: false,
				settlement_sync_time: "09:00",
				payout_cycle_days: 7,
				cod_fee_percent: 0,
				gst_percent: 0,
				base_weight_kg: 0.5,
				base_freight: 0,
				additional_freight_per_kg: 0,
		  };
	maps.value = {
		parcels: toRows(c?.parcels_mapping),
		remittance: toRows(c?.remittance_mapping),
	};
};
const close = () => !saving.value && (editing.value = null);
const save = async () => {
	saving.value = true;
	saveErr.value = "";
	try {
		const values = {
			...form.value,
			parcels_mapping: toObj(maps.value.parcels),
			remittance_mapping: toObj(maps.value.remittance),
		};
		if (!editing.value.new) delete values.courier_name;
		await api.save_courier(
			{ name: editing.value.new ? null : editing.value.name, values, api_key: key.value },
			{ silent: true }
		);
		toast(editing.value.new ? "Courier added" : "Courier saved");
		editing.value = null;
		await load();
		refresh();
	} catch (e) {
		saveErr.value = e.message;
	} finally {
		saving.value = false;
	}
};
const title = computed(() =>
	editing.value?.new ? "Add courier" : `Edit ${editing.value?.display_name}`
);
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<h1>Couriers</h1>
			<div class="acts">
				<button class="btn pri" @click="open()">
					<Plus :size="16" :stroke-width="1.8" />Add courier
				</button>
			</div>
		</div>

		<div v-if="banner" :class="['imp-banner', banner.ok ? 'ok' : 'err']" role="alert">
			<span>{{ banner.text }}</span>
		</div>

		<Tabs v-model="pageTab" :tabs="PAGE_TABS" />
		<CourierPerformance v-if="pageTab === 'Performance'" />

		<PageState v-else :loading="loading" :error="error" @retry="load">
			<section v-if="rows && !rows.length" class="card">
				<EmptyState
					title="No couriers yet"
					text="Add the couriers that deliver and settle your COD orders."
				>
					<button class="btn pri" @click="open()">
						<Plus :size="16" :stroke-width="1.8" />Add courier
					</button>
				</EmptyState>
			</section>
			<div v-else-if="rows" class="grid2">
				<section
					v-for="c in rows"
					:key="c.name"
					class="card"
					style="padding: 16px; gap: 12px"
				>
					<div style="display: flex; gap: 10px; align-items: center">
						<strong style="font-size: 16px; flex: 1">{{ c.display_name }}</strong>
						<Badge v-if="!c.is_active">Inactive</Badge>
						<Badge :kind="kind(c.status)">{{ c.status }}</Badge>
					</div>
					<div class="setgrid" style="font-size: 13px">
						<div>
							<span class="lab2">Tracking provider</span
							>{{ c.tracking_provider || "—" }}
						</div>
						<div>
							<span class="lab2">Settlement via</span>{{ c.settlement_via || "—" }}
						</div>
						<div>
							<span class="lab2">Payout cycle</span>{{ c.payout_cycle_days }} days
						</div>
						<div>
							<span class="lab2">API key</span
							><Badge v-if="c.api_key_saved" kind="ok">Saved</Badge
							><span v-else class="muted">Not set</span>
						</div>
						<div>
							<span class="lab2">Last tracking sync</span
							>{{ c.last_tracking ? ago(c.last_tracking) : "Never" }}
						</div>
						<div>
							<span class="lab2">Last settlement sync</span
							>{{ c.last_settlement ? ago(c.last_settlement) : "Never" }}
						</div>
					</div>
					<div v-if="c.error" class="neg" style="white-space: normal; font-size: 13px">
						<strong>Last error:</strong> {{ c.error }}
					</div>
					<div class="acts" style="margin-left: 0; flex-wrap: wrap">
						<button class="btn" @click="open(c)">
							<Pencil :size="14" :stroke-width="1.8" />Edit
						</button>
						<button class="btn" :disabled="!!busy" @click="test(c)">
							<span v-if="isBusy('test', c.name)" class="spin"></span
							><Plug v-else :size="14" :stroke-width="1.8" />Test connection
						</button>
						<button class="btn" :disabled="!!busy" @click="syncTracking(c)">
							<span v-if="isBusy('sync', c.name)" class="spin"></span
							><RefreshCw v-else :size="14" :stroke-width="1.8" />Sync Tracking
						</button>
					</div>
				</section>
			</div>
		</PageState>

		<Drawer v-if="editing" pg="pg-couriers" @close="close">
			<template #head
				><h2 style="margin: 0; font-size: 17px">{{ title }}</h2></template
			>
			<div v-if="form" style="display: flex; flex-direction: column; gap: 18px">
				<div v-if="saveErr" class="imp-banner err" role="alert">
					<strong>Could not save</strong><span>{{ saveErr }}</span>
				</div>
				<div class="setgrid">
					<label
						><span class="lab2">Courier name</span
						><input v-model="form.courier_name" class="inp" :disabled="!editing.new"
					/></label>
					<label class="chk" style="align-self: end; min-height: 32px"
						><input v-model="form.is_active" type="checkbox" /> Active</label
					>
					<label
						><span class="lab2">Payout cycle (days)</span
						><input
							v-model.number="form.payout_cycle_days"
							class="inp"
							type="number"
							min="1"
					/></label>
				</div>
				<div>
					<h3 class="lab2">Expected charges</h3>
					<div class="setgrid">
						<label
							><span class="lab2">COD fee (% of COD amount)</span
							><input
								v-model.number="form.cod_fee_percent"
								class="inp"
								type="number"
								min="0"
								step="0.01"
						/></label>
						<label
							><span class="lab2">GST (% of fee + freight)</span
							><input
								v-model.number="form.gst_percent"
								class="inp"
								type="number"
								min="0"
								step="0.01"
						/></label>
						<label
							><span class="lab2">Base weight (kg)</span
							><input
								v-model.number="form.base_weight_kg"
								class="inp"
								type="number"
								min="0"
								step="0.1"
						/></label>
						<label
							><span class="lab2">Base freight (₹)</span
							><input
								v-model.number="form.base_freight"
								class="inp"
								type="number"
								min="0"
								step="0.01"
						/></label>
						<label
							><span class="lab2">Extra freight per kg (₹)</span
							><input
								v-model.number="form.additional_freight_per_kg"
								class="inp"
								type="number"
								min="0"
								step="0.01"
						/></label>
					</div>
				</div>
				<div>
					<h3 class="lab2">Tracking</h3>
					<div class="setgrid">
						<label
							><span class="lab2">Provider</span
							><SelectField
								v-model="form.tracking_provider"
								:options="PROVIDERS"
								aria-label="Tracking provider"
								style="max-width: none"
						/></label>
						<label
							><span class="lab2"
								>API key <Badge v-if="editing.api_key_saved" kind="ok">Saved</Badge
								><Badge v-else kind="pend">Not set</Badge></span
							>
							<input
								v-model="key"
								class="inp"
								type="password"
								autocomplete="new-password"
								:placeholder="
									editing.api_key_saved
										? 'Saved (type to replace)'
										: 'Paste the API key'
								"
						/></label>
						<label class="chk"
							><input v-model="form.tracking_sync_enabled" type="checkbox" />
							Automatic tracking sync</label
						>
						<label
							><span class="lab2">Interval (min)</span
							><input
								v-model.number="form.tracking_interval_min"
								class="inp"
								type="number"
								min="1"
						/></label>
					</div>
				</div>
				<div>
					<h3 class="lab2">Settlement</h3>
					<div class="setgrid">
						<label
							><span class="lab2">Settlement via</span
							><SelectField
								v-model="form.settlement_via"
								:options="VIA"
								aria-label="Settlement via"
								style="max-width: none"
						/></label>
						<label class="chk"
							><input v-model="form.settlement_sync_enabled" type="checkbox" />
							Automatic settlement sync</label
						>
						<label
							><span class="lab2">Daily sync time</span
							><input v-model="form.settlement_sync_time" class="inp" type="time"
						/></label>
					</div>
				</div>
				<div
					v-for="[k, label] in [
						['remittance', 'Settlement file mapping'],
						['parcels', 'Parcels file mapping'],
					]"
					:key="k"
				>
					<h3 class="lab2">{{ label }}</h3>
					<div v-if="!maps[k].length" class="muted">
						No saved mapping. Columns are auto-detected on import.
					</div>
					<div v-for="(r, i) in maps[k]" :key="i" class="maprow">
						<input
							v-model="r.file_column"
							class="inp"
							placeholder="File column"
							:aria-label="`${label} file column`"
						/>
						<input
							v-model="r.field"
							class="inp mono"
							placeholder="field"
							:aria-label="`${label} field`"
						/>
						<button
							class="btn sm"
							aria-label="Remove row"
							@click="maps[k].splice(i, 1)"
						>
							<X :size="14" :stroke-width="1.8" />
						</button>
					</div>
					<button
						class="btn sm"
						style="margin-top: 8px"
						@click="maps[k].push({ file_column: '', field: '' })"
					>
						<Plus :size="14" :stroke-width="1.8" />Add column
					</button>
				</div>
			</div>
			<template #footer>
				<button class="btn" :disabled="saving" @click="close">Cancel</button>
				<button class="btn pri" :disabled="saving" @click="save">
					<span v-if="saving" class="spin"></span
					>{{ editing.new ? "Add courier" : "Save changes" }}
				</button>
			</template>
		</Drawer>
	</div>
</template>
