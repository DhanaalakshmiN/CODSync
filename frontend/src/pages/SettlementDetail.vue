<script setup>
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ArrowLeftRight, Check, Copy, Download } from "lucide-vue-next";
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
// Summary-card tone for the Difference tile: red for shortfalls, green at zero,
// neutral for positive (matches the app's .neg / .pos tokens).
const diffTone = computed(() => {
	const x = d.value?.totals?.difference;
	if (x === null || x === undefined || x === "") return "neutral";
	if (x < 0) return "diff-neg";
	if (x === 0) return "diff-zero";
	return "neutral";
});
// Copy the UTR to the clipboard (same pattern as Settings > webhook URL).
const copiedUtr = ref(false);
const copyUtr = async () => {
	const text = d.value?.utr || "";
	if (!text) return;
	try {
		await navigator.clipboard.writeText(text);
	} catch (e) {
		const t = document.createElement("textarea");
		t.value = text;
		document.body.appendChild(t);
		t.select();
		document.execCommand("copy");
		t.remove();
	}
	copiedUtr.value = true;
	toast("UTR copied");
	setTimeout(() => (copiedUtr.value = false), 2000);
};

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

				<section
					class="card sm-summary"
					:class="'sm-' + (batchKind(d.status) || 'none')"
					aria-label="Batch summary"
				>
					<div class="sm-meta">
						<span class="sm-chip"
							><span class="sm-chip-l">Courier</span>{{ d.courier }}</span
						>
						<span class="sm-chip"
							><span class="sm-chip-l">Date</span>{{ d.date || "—" }}</span
						>
						<span class="sm-chip">
							<span class="sm-chip-l">UTR</span>
							<span v-if="d.utr" class="sm-utr">{{ d.utr }}</span
							><span v-else class="muted">—</span>
							<button
								v-if="d.utr"
								class="sm-copy"
								type="button"
								aria-label="Copy UTR"
								:title="'Copy UTR'"
								@click="copyUtr"
							>
								<Copy v-if="!copiedUtr" :size="13" :stroke-width="1.8" />
								<Check v-else :size="13" :stroke-width="2.2" />
							</button>
						</span>
					</div>
					<div class="kpis sm-kpis">
						<div class="sm-tile">
							<span class="sm-l">Orders</span>
							<span class="sm-v num">{{ num(d.orders) }}</span>
						</div>
						<div class="sm-tile">
							<span class="sm-l">Gross COD</span>
							<span class="sm-v num">{{ rs(d.totals.cod) }}</span>
						</div>
						<div class="sm-tile amber">
							<span class="sm-l">Deductions</span>
							<span class="sm-v num">{{ rs(d.totals.deductions) }}</span>
						</div>
						<div class="sm-tile green">
							<span class="sm-l">Net paid</span>
							<span class="sm-v num">{{ rs(d.totals.net) }}</span>
						</div>
						<div class="sm-tile" :class="diffTone">
							<span class="sm-l">Difference</span>
							<span class="sm-v num">{{ rs(d.totals.difference) }}</span>
						</div>
					</div>
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

<style scoped>
/* Summary card: thin status accent matching the batch badge (ok/mis/pend). */
.sm-summary { position: relative; }
.sm-summary::before {
	content: "";
	position: absolute;
	top: 0;
	left: 0;
	right: 0;
	height: 3px;
	background: rgb(174, 180, 189); /* neutral slate for unknown/other status */
}
.sm-ok::before { background: rgb(14, 122, 95); } /* Matched / Reconciled */
.sm-mis::before { background: rgb(180, 35, 24); } /* Mismatch */
.sm-pend::before { background: rgb(232, 116, 59); } /* Pending review */

/* Meta strip: small pills for Courier / Date / UTR (mono + copy). */
.sm-meta {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	padding: 16px 16px 12px;
}
.sm-chip {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	padding: 4px 10px;
	border-radius: 999px;
	background: rgb(244, 245, 247);
	font-size: 12px;
	font-weight: 500;
	color: rgb(48, 54, 63);
	white-space: nowrap;
}
.sm-chip-l {
	font-size: 10.5px;
	font-weight: 600;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	color: rgb(92, 100, 112);
}
.sm-utr {
	font-family: "IBM Plex Mono", ui-monospace, Menlo, monospace;
	font-size: 12px;
}
.sm-copy {
	display: grid;
	place-items: center;
	width: 22px;
	height: 22px;
	padding: 0;
	border: 0;
	border-radius: 6px;
	background: transparent;
	color: rgb(92, 100, 112);
	cursor: pointer;
}
.sm-copy:hover { background: rgb(232, 233, 236); color: rgb(20, 23, 28); }

/* KPI tiles: tinted background + colored left border per metric. */
.sm-kpis { gap: 10px; padding: 4px 16px 16px; }
.sm-tile {
	display: flex;
	flex-direction: column;
	min-width: 0;
	padding: 14px 16px;
	border-radius: 10px;
	background: rgb(244, 245, 247); /* neutral */
	border-left: 4px solid rgb(174, 180, 189);
}
.sm-tile.amber { background: rgb(255, 248, 230); border-left-color: rgb(232, 116, 59); }
.sm-tile.green { background: rgb(234, 247, 240); border-left-color: rgb(31, 157, 115); }
.sm-tile.diff-neg { background: rgb(255, 240, 236); border-left-color: rgb(180, 35, 24); }
.sm-tile.diff-neg .sm-v { color: rgb(180, 35, 24); font-weight: 700; }
.sm-tile.diff-zero { background: rgb(234, 247, 240); border-left-color: rgb(31, 157, 115); }
.sm-tile.diff-zero .sm-v { color: rgb(12, 91, 63); font-weight: 700; }
.sm-l {
	font-size: 11px;
	font-weight: 600;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	color: rgb(92, 100, 112);
}
.sm-v {
	margin-top: 2px;
	font-size: 20px;
	font-weight: 700;
	letter-spacing: -0.01em;
	font-variant-numeric: tabular-nums;
	text-align: right;
}

@media (max-width: 640px) {
	.sm-meta { padding: 14px 12px 10px; }
	.sm-kpis { padding: 2px 12px 12px; gap: 8px; }
	.sm-tile { padding: 12px 14px; }
}
</style>
