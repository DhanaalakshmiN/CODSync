<script setup>
import { computed, ref, watch } from "vue";
import { Banknote, Download, Landmark, Clock, SearchX } from "lucide-vue-next";
import { api, downloadReportCsv } from "../api";
import { num, rs } from "../format";
import { state } from "../store";
import DataTable from "../components/DataTable.vue";
import EmptyState from "../components/EmptyState.vue";
import FilterChip from "../components/FilterChip.vue";
import PageState from "../components/PageState.vue";

const ICONS = {
	"COD Aging": Clock,
	"Courier Outstanding": Banknote,
	"Payout Reconciliation": Landmark,
	"Unmatched Payout Lines": SearchX,
};
const list = ref([]);
const current = ref("");
const courier = ref("");
const fromDate = ref("");
const toDate = ref("");
const couriers = ref([]);
const res = ref(null);
const loading = ref(true);
const error = ref("");
const downloading = ref(false);

const meta = computed(() => list.value.find((r) => r.name === current.value));
const supports = (f) => !!meta.value?.filters.includes(f);
const filters = () => ({
	courier: supports("courier") ? courier.value || null : null,
	from_date: supports("from_date") ? fromDate.value || null : null,
	to_date: supports("to_date") ? toDate.value || null : null,
});
const badRange = computed(() => fromDate.value && toDate.value && fromDate.value > toDate.value);

let seq = 0;
const load = async () => {
	if (!current.value || badRange.value) return;
	const mine = ++seq;
	loading.value = !res.value;
	error.value = "";
	try {
		const r = await api.run_report(
			{ name: current.value, filters: filters() },
			{ silent: true }
		);
		if (mine === seq) res.value = r;
	} catch (e) {
		if (mine === seq) error.value = e.message;
	}
	if (mine === seq) loading.value = false;
};
const start = async () => {
	loading.value = true;
	error.value = "";
	try {
		list.value = await api.reports_list({}, { silent: true });
		if (!current.value && list.value.length) current.value = list.value[0].name;
	} catch (e) {
		error.value = e.message;
		loading.value = false;
	}
};
watch([current, courier, fromDate, toDate], () => {
	res.value = null;
	load();
});
watch(() => state.tick, load);
start();
api.couriers({}, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch(() => {});

const columns = computed(() =>
	(res.value?.columns || []).map((c) => ({
		key: c.key,
		label: c.label,
		num: c.type === "Currency",
	}))
);
const rows = computed(() => (res.value?.rows || []).map((r, i) => ({ ...r, _i: i })));
const downloadCsv = () => {
	downloading.value = true;
	downloadReportCsv(current.value, filters());
	setTimeout(() => (downloading.value = false), 1500);
};
</script>

<template>
	<div class="wrap">
		<div class="ph"><h1>Reports</h1></div>

		<div class="rgrid">
			<section
				v-for="r in list"
				:key="r.name"
				class="card rc"
				:class="{ on: r.name === current }"
			>
				<div class="ri">
					<component :is="ICONS[r.name] || Clock" :size="16" :stroke-width="1.6" />
				</div>
				<h3>{{ r.name }}</h3>
				<p class="muted" style="margin: 0; font-size: 13px">{{ r.description }}</p>
				<div class="acts">
					<button
						class="btn"
						:class="{ pri: r.name === current }"
						:aria-pressed="r.name === current"
						@click="current = r.name"
					>
						{{ r.name === current ? "Viewing" : "View" }}
					</button>
				</div>
			</section>
		</div>

		<section v-if="meta" class="card">
			<div class="tbar">
				<label v-if="supports('from_date')" class="fld" style="flex: 0 0 auto"
					><span style="font-size: 12px">From</span
					><input v-model="fromDate" type="date" aria-label="From date"
				/></label>
				<label v-if="supports('to_date')" class="fld" style="flex: 0 0 auto"
					><span style="font-size: 12px">To</span
					><input v-model="toDate" type="date" aria-label="To date"
				/></label>
				<FilterChip v-model="courier" label="Courier" :options="couriers" />
				<span v-if="!supports('from_date')" class="muted" style="font-size: 12px"
					>This report is as of today; date range does not apply.</span
				>
				<div class="acts" style="margin-left: auto">
					<button
						class="btn"
						:disabled="downloading || loading || !!error || !!badRange"
						@click="downloadCsv"
					>
						<Download :size="16" :stroke-width="1.6" />Download CSV
					</button>
				</div>
			</div>
			<p v-if="badRange" class="muted" style="color: #b42318; margin: 8px 16px">
				From date cannot be after To date.
			</p>
		</section>

		<PageState :loading="loading" :error="error" @retry="res ? load() : start().then(load)">
			<section v-if="res" class="card">
				<EmptyState
					v-if="!rows.length"
					title="No rows"
					text="This report has nothing for the selected filters."
				/>
				<template v-else>
					<DataTable :columns="columns" :rows="rows" row-key="_i">
						<template
							v-for="c in res.columns"
							:key="c.key"
							#[`cell-${c.key}`]="{ value }"
						>
							<template v-if="c.type === 'Currency'">{{ rs(value) }}</template>
							<template v-else>{{ value ?? "—" }}</template>
						</template>
					</DataTable>
					<div class="muted" style="padding: 10px 16px; font-size: 12px">
						{{ num(res.total) }} rows
					</div>
				</template>
			</section>
		</PageState>
	</div>
</template>
