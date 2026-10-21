<script setup>
import { computed, ref, watch } from "vue";
import { ArrowLeftRight, X } from "lucide-vue-next";
import { api, call } from "../api";
import { num, reconKind, rs } from "../format";
import { refresh, state, toast } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import DeductionPatterns from "../components/DeductionPatterns.vue";
import EmptyState from "../components/EmptyState.vue";
import FilterChip from "../components/FilterChip.vue";
import PageState from "../components/PageState.vue";
import Pager from "../components/Pager.vue";
import Tabs from "../components/Tabs.vue";

const PAGE_SIZE = 12;
const status = ref("All");
const search = ref("");
const courier = ref("");
const batch = ref("");
const diffOnly = ref(false);
const page = ref(1);
const res = ref(null);
const couriers = ref([]);
const batches = ref([]);
const loading = ref(true);
const error = ref("");
const running = ref(false);
const patternParcels = ref(null);
const patternLabel = ref("");

const STATES = ["Paid", "Short-paid", "Awaiting payout", "Missing", "Unknown"];
const payoutKind = (s) =>
	({
		Paid: "ok",
		"Short-paid": "mis",
		"Awaiting payout": "pend",
		Missing: "exc",
		Unknown: "exc",
	}[s] || "");

const load = async () => {
	loading.value = !res.value;
	error.value = "";
	try {
		res.value = await api.reconciliation(
			{
				status: status.value,
				courier: courier.value || null,
				batch: batch.value || null,
				difference_not_zero: diffOnly.value ? 1 : 0,
				parcels: patternParcels.value,
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
watch([status, courier, batch, diffOnly], () => {
	patternParcels.value = null;
	patternLabel.value = "";
	page.value = 1;
	load();
});
watch([page, () => state.tick], load);
load();
api.couriers({}, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch(() => {});

const loadBatches = () =>
	api
		.remittance_batches({}, { silent: true })
		.then((b) => (batches.value = b))
		.catch(() => {});
loadBatches();

const tabs = computed(() => {
	const c = res.value?.counts || {};
	return ["All", ...STATES].map((k) => ({ key: k, label: k, count: c[k] }));
});
const batchOptions = computed(() =>
	batches.value.map((b) => ({ value: b.name, label: `${b.name} · ${b.courier} · ${b.date}` }))
);
const netDifference = computed(() => res.value?.stats?.net_difference || 0);

const applyPattern = (p) => {
	if (patternLabel.value === p.summary) {
		clearPattern();
		return;
	}
	patternParcels.value = p.parcels;
	patternLabel.value = p.summary;
	page.value = 1;
	load();
};
const clearPattern = () => {
	patternParcels.value = null;
	patternLabel.value = "";
	page.value = 1;
	load();
};

const columns = [
	{ key: "order_id", label: "Order" },
	{ key: "courier", label: "Courier" },
	{ key: "cod_amount", label: "COD amount", num: true },
	{ key: "expected_settlement", label: "Expected", num: true },
	{ key: "actual_settlement", label: "Actual", num: true },
	{ key: "difference", label: "Difference", num: true },
	{ key: "status", label: "Status" },
	{ key: "settlement_batch", label: "Settlement" },
];

const runMatching = async () => {
	if (!batch.value) {
		toast("Pick a settlement batch first", "e");
		return;
	}
	running.value = true;
	try {
		const c = await call(
			"codsync.codsync.matching.run_matching",
			{ remittance: batch.value },
			{ silent: true }
		);
		toast(
			`Matching: ${c.matched} matched, ${c["short-paid"]} short-paid, ${c.unknown} unknown, ${c.exceptions} exceptions`,
			c.exceptions ? "e" : ""
		);
		refresh();
		loadBatches();
	} catch (e) {
		toast(e.message, "e");
	} finally {
		running.value = false;
	}
};
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<h1>Reconciliation</h1>
			<div class="acts">
				<span class="muted" style="font-size: 12px"
					>Net difference {{ rs(netDifference) }}</span
				>
				<FilterChip v-model="batch" label="Batch" :options="batchOptions" />
				<button class="btn" :disabled="running || !batch" @click="runMatching">
					<span v-if="running" class="spin"></span
					><ArrowLeftRight v-else :size="16" :stroke-width="1.6" />Run Matching
				</button>
			</div>
		</div>

		<div class="stats" aria-label="Payout summary">
			<button
				v-for="c in res?.cards || []"
				:key="c.key"
				class="stat"
				:style="status === c.key ? { outline: '2px solid #1f9d73' } : null"
				style="text-align: left; cursor: pointer"
				@click="status = status === c.key ? 'All' : c.key"
			>
				<div class="kl">{{ c.label }}</div>
				<div class="kv">{{ num(c.count) }}</div>
				<div class="kd">{{ rs(c.amount, false) }} COD</div>
			</button>
		</div>

		<DeductionPatterns :courier="courier" @select="applyPattern" />

		<section class="card">
			<Tabs v-model="status" :tabs="tabs" />
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
						placeholder="Order, courier or UTR"
						aria-label="Filter reconciliation"
				/></label>
				<FilterChip v-model="courier" label="Courier" :options="couriers" />
				<button class="btn sm" :class="{ on: diffOnly }" @click="diffOnly = !diffOnly">
					Only with difference
				</button>
				<button
					v-if="patternLabel"
					class="btn sm on"
					:title="patternLabel"
					@click="clearPattern"
				>
					<X :size="12" :stroke-width="2" />Pattern
				</button>
			</div>
			<PageState :loading="loading" :error="error" @retry="load">
				<template v-if="res">
					<EmptyState
						v-if="!res.rows.length"
						title="Nothing to reconcile"
						text="Import a courier settlement or fetch orders to see reconciliation here."
					/>
					<DataTable v-else :columns="columns" :rows="res.rows" row-key="order_id">
						<template #cell-order_id="{ row }"
							><router-link :to="`/orders/${encodeURIComponent(row.order_id)}`"
								><strong>{{ row.order_id }}</strong></router-link
							>
							<div class="muted" style="font-size: 12px">
								<Badge :kind="payoutKind(row.payout_status)" nd>{{
									row.payout_status
								}}</Badge>
							</div>
						</template>
						<template #cell-courier="{ row }"
							><template v-if="row.courier">{{ row.courier }}</template
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-cod_amount="{ row }">{{ rs(row.cod_amount) }}</template>
						<template #cell-expected_settlement="{ row }">{{
							rs(row.expected_settlement)
						}}</template>
						<template #cell-actual_settlement="{ row }"
							><span :class="{ muted: typeof row.actual_settlement === 'string' }">{{
								typeof row.actual_settlement === "number"
									? rs(row.actual_settlement)
									: row.actual_settlement
							}}</span></template
						>
						<template #cell-difference="{ row }">
							<span
								v-if="typeof row.actual_settlement === 'number'"
								:class="{
									neg: row.difference < 0 && !row.within_tolerance,
									okc: row.within_tolerance,
								}"
								>{{ rs(row.difference) }}</span
							>
							<span v-else class="muted">&mdash;</span>
						</template>
						<template #cell-status="{ row }"
							><Badge v-if="row.status" :kind="reconKind(row.status)">{{
								row.status
							}}</Badge
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-settlement_batch="{ row }">
							<template v-if="row.settlement_batch">
								<router-link
									:to="`/settlements/${encodeURIComponent(
										row.settlement_batch
									)}`"
									>{{ row.settlement_batch }}</router-link
								>
								<div class="muted" style="font-size: 12px">
									{{ row.utr || "No UTR" }}
								</div>
							</template>
							<span v-else class="muted">&mdash;</span>
						</template>
					</DataTable>
					<Pager
						v-model:page="page"
						:page-size="PAGE_SIZE"
						:total="res.total"
						noun="orders"
					/>
				</template>
			</PageState>
		</section>
	</div>
</template>

<style scoped>
.stats {
	display: grid;
	grid-template-columns: repeat(5, minmax(0, 1fr));
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
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
}
</style>
