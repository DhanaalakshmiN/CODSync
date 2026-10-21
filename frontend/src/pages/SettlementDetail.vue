<script setup>
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ArrowLeftRight, Download } from "lucide-vue-next";
import { api, call, download } from "../api";
import { batchKind, num, rs } from "../format";
import { toast } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import EmptyState from "../components/EmptyState.vue";
import PageState from "../components/PageState.vue";

const route = useRoute();
const batch = computed(() => route.params.batch);
const d = ref(null);
const loading = ref(true);
const error = ref("");
const running = ref(false);

const load = async () => {
	loading.value = !d.value;
	error.value = "";
	try {
		d.value = await api.settlement_detail({ batch: batch.value }, { silent: true });
	} catch (e) {
		error.value = e.message;
	}
	loading.value = false;
};
watch(
	batch,
	() => {
		d.value = null;
		load();
	},
	{ immediate: true }
);

const matchKind = (s) => ({ Paid: "ok", "Short-paid": "mis", Unknown: "exc" }[s] || "");
const counts = computed(() => {
	const c = { Paid: 0, "Short-paid": 0, Unknown: 0 };
	(d.value?.lines || []).forEach((l) => {
		if (c[l.status] !== undefined) c[l.status] += 1;
	});
	return c;
});

const columns = [
	{ key: "row_no", label: "#" },
	{ key: "awb", label: "AWB" },
	{ key: "order_id", label: "Order" },
	{ key: "cod_amount", label: "COD amount", num: true },
	{ key: "deductions", label: "Deductions", num: true },
	{ key: "net", label: "Net paid", num: true },
	{ key: "expected", label: "Expected", num: true },
	{ key: "difference", label: "Difference", num: true },
	{ key: "status", label: "Match" },
];

const runMatching = async () => {
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
		d.value = null;
		await load();
	} catch (e) {
		toast(e.message, "e");
	} finally {
		running.value = false;
	}
};
const downloadCsv = async () => {
	try {
		await download("settlement_lines_csv", { batch: batch.value });
	} catch (e) {
		toast(e.message, "e");
	}
};
</script>

<template>
	<div class="wrap">
		<div class="crumb">
			<router-link to="/settlements">Settlements</router-link> / <span>{{ batch }}</span>
		</div>
		<PageState :loading="loading" :error="error" @retry="load">
			<template v-if="d">
				<div class="ph pg-detail">
					<h1>{{ d.batch }}</h1>
					<Badge :kind="batchKind(d.status)">{{ d.status || "Pending review" }}</Badge>
					<Badge nd :out="d.source === 'Excel'">{{ d.source }}</Badge>
					<div class="acts">
						<button class="btn" :disabled="running" @click="runMatching">
							<span v-if="running" class="spin"></span
							><ArrowLeftRight v-else :size="16" :stroke-width="1.6" />Run Matching
						</button>
						<button class="btn" @click="downloadCsv">
							<Download :size="16" :stroke-width="1.6" />Download CSV
						</button>
					</div>
				</div>

				<section class="card" aria-label="Batch summary">
					<dl class="kvl" style="padding: 16px">
						<div>
							<dt>Courier</dt>
							<dd>{{ d.courier }}</dd>
						</div>
						<div>
							<dt>Date</dt>
							<dd>{{ d.date || "—" }}</dd>
						</div>
						<div>
							<dt>UTR</dt>
							<dd>
								<span v-if="d.utr" class="mono">{{ d.utr }}</span
								><span v-else class="muted">—</span>
							</dd>
						</div>
						<div>
							<dt>Orders</dt>
							<dd>{{ num(d.orders) }}</dd>
						</div>
						<div>
							<dt>Gross COD</dt>
							<dd>{{ rs(d.totals.cod) }}</dd>
						</div>
						<div>
							<dt>Deductions</dt>
							<dd>{{ rs(d.totals.deductions) }}</dd>
						</div>
						<div>
							<dt>Net paid</dt>
							<dd>{{ rs(d.totals.net) }}</dd>
						</div>
						<div>
							<dt>Difference</dt>
							<dd :class="{ neg: d.totals.difference < 0 }">
								{{ rs(d.totals.difference) }}
							</dd>
						</div>
					</dl>
				</section>

				<section class="card">
					<div class="ch">
						<h2>Lines</h2>
						<span class="muted" style="font-size: 12px">
							{{ counts.Paid }} paid · {{ counts["Short-paid"] }} short-paid ·
							{{ counts.Unknown }} unknown
						</span>
					</div>
					<EmptyState
						v-if="!d.lines.length"
						title="No lines in this batch"
						text="Run matching or re-import the settlement file."
					/>
					<DataTable v-else :columns="columns" :rows="d.lines" row-key="row_no">
						<template #cell-row_no="{ row }"
							><span class="muted">{{ row.row_no }}</span></template
						>
						<template #cell-awb="{ row }"
							><span class="mono">{{ row.awb }}</span></template
						>
						<template #cell-order_id="{ row }">
							<router-link
								v-if="row.order_id"
								:to="`/orders/${encodeURIComponent(row.order_id)}`"
								><strong>{{ row.order_id }}</strong></router-link
							>
							<span v-else class="muted">Unknown AWB</span>
						</template>
						<template #cell-cod_amount="{ row }">{{ rs(row.cod_amount) }}</template>
						<template #cell-deductions="{ row }">
							{{ rs(row.deductions) }}
							<div v-if="row.unexpected" class="neg" style="font-size: 12px">
								incl. {{ rs(row.unexpected) }} unexpected
							</div>
						</template>
						<template #cell-net="{ row }">{{ rs(row.net) }}</template>
						<template #cell-expected="{ row }"
							><span class="muted">{{
								row.expected ? rs(row.expected) : "—"
							}}</span></template
						>
						<template #cell-difference="{ row }">
							<span v-if="row.difference" :class="{ neg: row.difference < 0 }">{{
								rs(row.difference)
							}}</span>
							<span v-else class="muted">—</span>
						</template>
						<template #cell-status="{ row }"
							><Badge :kind="matchKind(row.status)">{{
								row.status || "—"
							}}</Badge></template
						>
					</DataTable>
				</section>
			</template>
		</PageState>
	</div>
</template>
