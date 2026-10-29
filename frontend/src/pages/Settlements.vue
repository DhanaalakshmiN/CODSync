<script setup>
import { computed, ref, watch } from "vue";
import { Upload } from "lucide-vue-next";
import { api } from "../api";
import { batchKind, num, rs } from "../format";
import { state } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import EmptyState from "../components/EmptyState.vue";
import FilterChip from "../components/FilterChip.vue";
import PageState from "../components/PageState.vue";
import Pager from "../components/Pager.vue";
import Tabs from "../components/Tabs.vue";

const PAGE_SIZE = 10;
const tab = ref("All batches");
const search = ref("");
const courier = ref("");
const source = ref("");
const page = ref(1);
const res = ref(null);
const couriers = ref([]);
const loading = ref(true);
const error = ref("");

const load = async () => {
	loading.value = !res.value;
	error.value = "";
	try {
		res.value = await api.settlements(
			{
				status: tab.value,
				courier: courier.value || null,
				source: source.value || null,
				search: search.value || null,
				page: page.value,
				page_size: PAGE_SIZE,
			},
			{ silent: true }
		);
	} catch (e) {
		error.value = e.message;
	}
	loading.value = false;
};
let t = null;
watch(search, () => {
	clearTimeout(t);
	t = setTimeout(() => {
		page.value = 1;
		load();
	}, 250);
});
watch([tab, courier, source], () => {
	page.value = 1;
	load();
});
watch([page, () => state.tick], load);
load();
api.couriers({}, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch(() => {});

const tabs = computed(() => {
	const c = res.value?.counts || {};
	return ["All batches", "Mismatch", "Pending review"].map((k) => ({
		key: k,
		label: k,
		count: c[k],
	}));
});
const s = computed(() => res.value?.stats || {});
const columns = [
	{ key: "batch", label: "Batch" },
	{ key: "courier", label: "Courier" },
	{ key: "date", label: "Date" },
	{ key: "orders", label: "Orders", num: true },
	{ key: "cod_amount", label: "COD amount", num: true },
	{ key: "deductions", label: "Deductions", num: true },
	{ key: "net", label: "Net", num: true },
	{ key: "utr", label: "UTR" },
	{ key: "source", label: "Source" },
	{ key: "status", label: "Status" },
];
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<h1>Settlements</h1>
			<div class="acts">
				<router-link class="btn" to="/settlements/import"
					><Upload :size="16" :stroke-width="1.6" />Import settlement</router-link
				>
			</div>
		</div>

		<div class="stats" aria-label="Settlement totals">
			<div class="stat">
				<div class="kl">Settled (30d)</div>
				<div class="kv">{{ rs(s.settled_30d, false) }}</div>
				<div class="kd">
					{{ num(s.batches_30d) }} batches · {{ num(s.orders_30d) }} orders
				</div>
			</div>
			<div class="stat">
				<div class="kl">Deductions (30d)</div>
				<div class="kv">{{ rs(s.deductions_30d, false) }}</div>
				<div class="kd">{{ s.deductions_pct }}% of COD</div>
			</div>
		</div>

		<section class="card">
			<Tabs v-model="tab" :tabs="tabs" />
			<div class="tbar">
				<label class="fld"
					><svg
						width="16"
						height="16"
						viewBox="0 0 20 20"
						fill="none"
						stroke="currentColor"
						stroke-width="1.6"
						stroke-linecap="round"
					>
						<circle cx="9" cy="9" r="5.5" />
						<path d="m13 13 4 4" /></svg
					><input
						v-model="search"
						type="search"
						placeholder="Batch, courier or UTR"
						aria-label="Filter settlements"
				/></label>
				<FilterChip v-model="courier" label="Courier" :options="couriers" />
				<FilterChip v-model="source" label="Source" :options="['Excel', 'API']" />
			</div>
			<PageState :loading="loading" :error="error" @retry="load">
				<template v-if="res">
					<EmptyState
						v-if="!res.rows.length"
						title="No settlement batches"
						text="Import a courier payout file to see batches here."
					/>
					<DataTable v-else :columns="columns" :rows="res.rows" row-key="batch">
						<template #cell-batch="{ row }"
							><router-link :to="`/settlements/${encodeURIComponent(row.batch)}`"
								><strong>{{ row.batch }}</strong></router-link
							>
							<div v-if="row.file_name" class="muted" style="font-size: 12px">
								{{ row.file_name }}
							</div>
						</template>
						<template #cell-courier="{ row }">{{ row.courier }}</template>
						<template #cell-date="{ row }"
							><span class="muted">{{ row.date || "—" }}</span></template
						>
						<template #cell-orders="{ row }">{{ num(row.orders) }}</template>
						<template #cell-cod_amount="{ row }">{{ rs(row.cod_amount) }}</template>
						<template #cell-deductions="{ row }">{{ rs(row.deductions) }}</template>
						<template #cell-net="{ row }">{{ rs(row.net) }}</template>
						<template #cell-utr="{ row }"
							><span v-if="row.utr" class="mono">{{ row.utr }}</span
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-source="{ row }"
							><Badge nd :out="row.source === 'Excel'">{{
								row.source || "—"
							}}</Badge></template
						>
						<template #cell-status="{ row }"
							><Badge :kind="batchKind(row.status)">{{
								row.status || "Pending review"
							}}</Badge></template
						>
					</DataTable>
					<Pager
						v-model:page="page"
						:page-size="PAGE_SIZE"
						:total="res.total"
						noun="batches"
					/>
				</template>
			</PageState>
		</section>
	</div>
</template>

<style scoped>
.stats {
	display: grid;
	grid-template-columns: repeat(2, minmax(0, 1fr));
	gap: 12px;
	align-items: stretch;
	width: 100%;
	box-sizing: border-box;
}
.stat {
	background: #fff;
	border: 1px solid rgb(227, 229, 232);
	border-radius: 8px;
	padding: 16px;
	box-sizing: border-box;
	min-width: 0;
	height: 100%;
	font: inherit;
	color: inherit;
	display: flex;
	flex-direction: column;
}
.stat .kl,
.stat .kd {
	color: rgb(92, 100, 112);
	font-size: 12px;
}
.stat .kv {
	font-size: 20px;
	font-weight: 600;
	margin-top: 4px;
}
.stat .kd {
	margin-top: 2px;
}
@media (max-width: 767px) {
	.stats {
		grid-template-columns: repeat(1, minmax(0, 1fr));
	}
}
</style>
