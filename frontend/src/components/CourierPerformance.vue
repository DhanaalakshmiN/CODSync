<script setup>
// "Performance" tab: per courier (or courier + zone) delivery, RTO, payout and cost metrics.
// Arrows compare each metric with the previous period of equal length; green = better.
import { computed, ref, watch } from "vue";
import { ArrowDown, ArrowUp, Gauge } from "lucide-vue-next";
import { api } from "../api";
import { num, rs } from "../format";
import Badge from "./Badge.vue";
import EmptyState from "./EmptyState.vue";
import PageState from "./PageState.vue";
import Tabs from "./Tabs.vue";

const PERIODS = [
	{ key: "7", label: "7 days" },
	{ key: "30", label: "30 days" },
	{ key: "90", label: "90 days" },
];
const VIEWS = [
	{ key: "courier", label: "By courier" },
	{ key: "courier_zone", label: "By zone" },
];
// metric -> [label, higher is better, formatter]
const pct = (v) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);
const days = (v) => (v === null || v === undefined ? "—" : `${v} d`);
const METRICS = [
	{ key: "score", label: "Score", up: true, fmt: (v) => (v === null ? "—" : v) },
	{ key: "delivery_rate", label: "Delivery rate", up: true, fmt: pct },
	{ key: "rto_rate", label: "RTO rate", up: false, fmt: pct },
	{ key: "avg_delivery_days", label: "Avg delivery", up: false, fmt: days },
	{ key: "avg_payout_lag_days", label: "Payout lag", up: false, fmt: days },
	{ key: "short_pay_rate", label: "Short-pay rate", up: false, fmt: pct },
	{ key: "cost_per_delivered", label: "Cost / delivered", up: false, fmt: (v) => (v === null ? "—" : rs(v)) },
	{ key: "cash_locked", label: "Cash locked", up: false, fmt: (v) => rs(v) },
];

const period = ref("30");
const view = ref("courier");
const res = ref(null);
const loading = ref(true);
const error = ref("");

const load = async () => {
	loading.value = !res.value;
	error.value = "";
	try {
		const end = new Date();
		const start = new Date(end.getTime() - (Number(period.value) - 1) * 86400000);
		const iso = (d) => d.toISOString().slice(0, 10);
		res.value = await api.courier_performance(
			{ from_date: iso(start), to_date: iso(end), group_by: view.value },
			{ silent: true }
		);
	} catch (e) {
		error.value = e.message;
	}
	loading.value = false;
};
watch([period, view], load);
load();

const rows = computed(() => res.value?.rows || []);

// arrow vs previous period: { dir: "up" | "down", good: bool } or null when unchanged / unknown
const trend = (row, m) => {
	const cur = row[m.key];
	const prev = row.previous?.[m.key];
	if (cur === null || cur === undefined || prev === null || prev === undefined || cur === prev)
		return null;
	const dir = cur > prev ? "up" : "down";
	return { dir, good: (dir === "up") === m.up };
};

// plain-language insight generated from the data (no AI service)
const insight = computed(() => {
	const ranked = rows.value.filter((r) => !r.low_sample);
	if (!ranked.length) return "";
	const label = (r) => (r.zone ? `${r.courier} (zone ${r.zone})` : r.courier);
	const pick = (key, max) =>
		ranked.reduce((a, b) => ((b[key] ?? -Infinity) > (a[key] ?? -Infinity) === max ? b : a));
	const parts = [];
	const best = ranked.find((r) => r.score !== null);
	if (best) parts.push(`Top score: ${label(best)} at ${best.score}`);
	const rto = pick("rto_rate", true);
	if (rto.rto_rate) parts.push(`Highest RTO rate: ${label(rto)} at ${pct(rto.rto_rate)}`);
	const lock = pick("cash_locked", true);
	if (lock.cash_locked) parts.push(`Most cash locked: ${label(lock)} at ${rs(lock.cash_locked)}`);
	return parts.join(". ");
});
</script>

<template>
	<PageState :loading="loading" :error="error" @retry="load">
		<section class="card">
			<div class="ch">
				<h2>Courier performance</h2>
				<div class="acts">
					<Tabs v-model="view" :tabs="VIEWS" />
					<select v-model="period" class="sel" aria-label="Period">
						<option v-for="p in PERIODS" :key="p.key" :value="p.key">
							Last {{ p.label }}
						</option>
					</select>
				</div>
			</div>
			<EmptyState
				v-if="!rows.length"
				title="No dispatched parcels in this period"
				text="Parcels with an AWB and a courier show up here once they are ordered in the selected period."
			>
				<template #icon><Gauge :size="20" :stroke-width="1.6" /></template>
			</EmptyState>
			<template v-else>
				<p v-if="insight" class="insight">{{ insight }}</p>
				<div class="tw">
					<table class="tbl">
						<thead>
							<tr>
								<th>Courier</th>
								<th v-if="view === 'courier_zone'">Zone</th>
								<th v-for="m in METRICS" :key="m.key" class="num">{{ m.label }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="r in rows" :key="`${r.courier}-${r.zone}`">
								<td>
									<strong>{{ r.courier }}</strong>
									<Badge v-if="r.is_best" kind="ok" nd>Best</Badge>
									<Badge v-if="r.low_sample" nd>Low sample</Badge>
									<div class="muted">{{ num(r.dispatched) }} dispatched</div>
								</td>
								<td v-if="view === 'courier_zone'">{{ r.zone }}</td>
								<td v-for="m in METRICS" :key="m.key" class="num">
									{{ m.fmt(r[m.key]) }}
									<template v-if="trend(r, m)">
										<ArrowUp
											v-if="trend(r, m).dir === 'up'"
											:size="12"
											:stroke-width="2"
											:class="trend(r, m).good ? 'good' : 'bad'"
											aria-label="Up vs previous period"
										/>
										<ArrowDown
											v-else
											:size="12"
											:stroke-width="2"
											:class="trend(r, m).good ? 'good' : 'bad'"
											aria-label="Down vs previous period"
										/>
									</template>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<p class="muted note">
					Arrows compare with the previous {{ period }} days. Rows under
					{{ res.min_parcels }} parcels are not ranked.
				</p>
			</template>
		</section>
	</PageState>
</template>

<style scoped>
.insight {
	margin: 0;
	padding: 10px 16px;
	border-bottom: 1px solid rgb(238, 240, 242);
}
.tw {
	overflow-x: auto;
}
.note {
	margin: 0;
	padding: 10px 16px;
}
.good {
	color: rgb(22, 128, 61);
}
.bad {
	color: rgb(185, 28, 28);
}
</style>
