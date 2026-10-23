<script setup>
import { computed, ref, watch } from "vue";
import { CircleAlert } from "lucide-vue-next";
import { api } from "../api";
import { ago, batchKind, dFull, excKind, num, reconKind, rs } from "../format";
import { openConnect, openException, state } from "../store";
import Badge from "../components/Badge.vue";
import PageState from "../components/PageState.vue";

const period = ref("30d");
const courier = ref("");
const data = ref(null);
const couriers = ref([]);
const loading = ref(true);
const error = ref("");

const load = async () => {
	loading.value = !data.value;
	error.value = "";
	try {
		data.value = await api.overview(
			{ period: period.value, courier: courier.value || null },
			{ silent: true }
		);
	} catch (e) {
		error.value = e.message;
	}
	loading.value = false;
};
api.couriers({}, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch(() => {});
watch([period, courier, () => state.tick], load, { immediate: true });

const k = computed(() => data.value?.kpis || {});
const sum = computed(() => data.value?.summary || {});
const pipe = computed(() => [
	["Orders", sum.value.orders],
	["AWB assigned", sum.value.awb_assigned],
	["Delivered", sum.value.delivered],
	["COD collected", sum.value.cod_collected],
	["Settled", sum.value.settled],
	["Reconciled", sum.value.reconciled],
]);
const COLORS = {
	Reconciled: "#1f9d73",
	Pending: "#e3b341",
	Mismatch: "#e8743b",
	Exception: "#b42318",
};
const bars = computed(() => {
	const rows = data.value?.status_table || [];
	const total = rows.reduce((a, r) => a + r.orders, 0) || 1;
	return rows.map((r) => ({
		status: r.status,
		width: (r.orders * 100) / total,
		color: COLORS[r.status],
	}));
});
const barLabel = computed(() =>
	bars.value.map((b) => `${b.status} ${Math.round(b.width)}%`).join(", ")
);
const diffCell = (r) =>
	r.status === "Pending" ? "—" : r.status === "Exception" ? "Needs review" : rs(r.difference);
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<h1>Overview</h1>
			<div class="acts">
				<label class="muted" style="display: flex; align-items: center; gap: 6px">
					Period
					<select v-model="period" class="sel" aria-label="Period">
						<option value="30d">Last 30 days</option>
						<option value="7d">Last 7 days</option>
						<option value="90d">Last 90 days</option>
						<option value="month">This month</option>
					</select>
				</label>
				<select v-model="courier" class="sel" aria-label="Courier">
					<option value="">All couriers</option>
					<option v-for="c in couriers" :key="c" :value="c">{{ c }}</option>
				</select>
				<router-link class="btn pri" to="/settlements/import"
					>Import settlement</router-link
				>
			</div>
		</div>

		<PageState :loading="loading" :error="error" @retry="load">
			<template v-if="data">
				<div v-for="b in data.banner" :key="b.courier" class="ban err" role="alert">
					<CircleAlert :size="18" :stroke-width="1.6" color="#B42318" />
					<div style="flex: 1 1 300px">
						<strong
							>{{ b.courier }}
							{{ b.settlement_via === "API" ? "settlement" : "tracking" }} sync failed<template v-if="b.time">
								{{ ago(b.time).replace(" ago", "") }} ago</template
							>.
						</strong>
						<span class="muted"
							>{{ b.last_error }}
							<template v-if="b.settlement_via === 'API'"
								>Tracking is still syncing; new settlements won't import until you
								reconnect.</template
							><template v-else
								>Settlements are imported from Excel and are not affected; tracking
								updates resume once you reconnect.</template
							></span
						>
					</div>
					<div class="acts">
						<button class="btn sm" @click="openConnect(b.courier)">Reconnect</button>
					</div>
				</div>

				<div class="stats" aria-label="COD totals">
					<router-link class="stat" to="/orders"
						><div class="kl">COD orders</div>
						<div class="kv">{{ num(k.cod_orders) }}</div>
						<div class="kd">of {{ num(k.total_orders) }} orders</div></router-link
					>
					<div class="stat">
						<div class="kl">Expected COD</div>
						<div class="kv">{{ rs(k.expected_cod, false) }}</div>
						<div class="kd">order value</div>
					</div>
					<div class="stat">
						<div class="kl">Collected</div>
						<div class="kv">{{ rs(k.collected_amount, false) }}</div>
						<div class="kd">{{ num(k.delivered_count) }} delivered</div>
					</div>
					<router-link class="stat" to="/settlements"
						><div class="kl">Settled</div>
						<div class="kv">{{ rs(k.settled_amount, false) }}</div>
						<div class="kd">{{ num(k.settled_orders) }} orders</div></router-link
					>
					<div class="stat">
						<div class="kl">Pending settlement</div>
						<div class="kv">{{ rs(k.pending_amount, false) }}</div>
						<div class="kd">
							{{ num(k.pending_orders) }} orders · oldest
							{{ k.oldest_pending_days }}d
						</div>
					</div>
					<router-link class="stat" to="/reconciliation"
						><div class="kl">Reconciled</div>
						<div class="kv" style="color: #0c5b3f">{{ num(k.reconciled_count) }}</div>
						<div class="kd">
							{{ Math.round(k.reconciled_pct) }}% of COD orders
						</div></router-link
					>
					<router-link class="stat" to="/reconciliation"
						><div class="kl">Unreconciled</div>
						<div class="kv" style="color: #962d0e">
							{{ num(k.unreconciled_count) }}
						</div>
						<div class="kd">
							{{ num(k.mismatch_count) }} mismatch ·
							{{ num(k.exception_count) }} exceptions
						</div></router-link
					>
				</div>

				<div class="grid2">
					<section class="card">
						<div class="ch">
							<h2>Reconciliation summary</h2>
							<div class="acts">
								<router-link class="btn link sm" to="/reconciliation"
									>View all</router-link
								>
							</div>
						</div>
						<div class="cb" style="display: flex; flex-direction: column; gap: 16px">
							<div class="pipe" aria-label="COD pipeline">
								<div
									v-for="(p, i) in pipe"
									:key="p[0]"
									class="ps"
									:style="i === 5 ? { background: '#e4f5ec' } : null"
								>
									<b :style="i === 5 ? { color: '#0c5b3f' } : null">{{
										num(p[1])
									}}</b
									><span>{{ p[0] }}</span>
								</div>
							</div>
							<div class="bar" role="img" :aria-label="barLabel">
								<div
									v-for="b in bars"
									:key="b.status"
									:style="{ width: b.width + '%', background: b.color }"
								></div>
							</div>
							<table>
								<thead>
									<tr>
										<th>Status</th>
										<th class="num">Orders</th>
										<th class="num">COD value</th>
										<th class="num">Difference</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="r in data.status_table" :key="r.status">
										<td>
											<Badge :kind="reconKind(r.status)">{{
												r.status
											}}</Badge>
										</td>
										<td class="num">{{ num(r.orders) }}</td>
										<td class="num">{{ rs(r.cod_value) }}</td>
										<td
											:class="[
												'num',
												r.status === 'Mismatch' && r.difference < 0
													? 'neg'
													: 'muted',
											]"
										>
											{{ diffCell(r) }}
										</td>
									</tr>
								</tbody>
							</table>
						</div>
					</section>

					<section class="card">
						<div class="ch">
							<h2>Open exceptions</h2>
							<Badge kind="mis"
								>{{ num(data.open_exceptions.total_open) }} open</Badge
							>
							<div class="acts">
								<router-link class="btn link sm" to="/exceptions"
									>View all</router-link
								>
							</div>
						</div>
						<div v-if="!data.open_exceptions.rows.length" class="loading">
							No open exceptions
						</div>
						<div v-else class="tw">
							<table>
								<thead>
									<tr>
										<th>Type</th>
										<th>Order</th>
										<th>Detail</th>
										<th class="num">Impact</th>
										<th class="num">Age</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="e in data.open_exceptions.rows" :key="e.name">
										<td>
											<Badge :kind="excKind(e.type)">{{ e.type }}</Badge>
										</td>
										<td>
											<a v-if="e.order_id" @click="openException(e.name)">{{
												e.order_id
											}}</a
											><span v-else class="mono">{{ e.awb }}</span>
										</td>
										<td class="muted">{{ e.detail }}</td>
										<td :class="['num', { neg: e.impact < 0 }]">
											{{ rs(e.impact) }}
										</td>
										<td class="num muted">{{ e.age_days }}d</td>
									</tr>
								</tbody>
							</table>
						</div>
					</section>
				</div>

				<section class="card">
					<div class="ch">
						<h2>Recent settlements</h2>
						<div class="acts">
							<router-link class="btn link sm" to="/settlements"
								>View all</router-link
							>
						</div>
					</div>
					<div class="tw">
						<table>
							<thead>
								<tr>
									<th>Batch</th>
									<th>Courier</th>
									<th>Date</th>
									<th class="num">Orders</th>
									<th class="num">COD amount</th>
									<th class="num">Deductions</th>
									<th class="num">Net settlement</th>
									<th>UTR</th>
									<th>Status</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="b in data.recent_settlements" :key="b.batch">
									<td>
										<router-link
											class="mono"
											:to="`/settlements/${b.batch}`"
											>{{ b.batch }}</router-link
										>
									</td>
									<td>{{ b.courier }}</td>
									<td>{{ dFull(b.date) }}</td>
									<td class="num">{{ num(b.orders) }}</td>
									<td class="num">{{ rs(b.cod_amount) }}</td>
									<td class="num">{{ rs(b.deductions) }}</td>
									<td class="num">
										<strong>{{ rs(b.net) }}</strong>
									</td>
									<td class="mono">{{ b.utr }}</td>
									<td>
										<Badge :kind="batchKind(b.status)">{{ b.status }}</Badge>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</section>
			</template>
		</PageState>
	</div>
</template>

<style scoped>
.stats {
	display: grid;
	grid-template-columns: repeat(7, minmax(0, 1fr));
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
	display: flex;
	flex-direction: column;
	text-decoration: none;
	color: inherit;
}
.stat:hover {
	background: #fff;
	color: inherit;
}
.stat .kl,
.stat .kd {
	color: rgb(92, 100, 112);
	font-size: 12px;
	overflow-wrap: anywhere;
}
.stat .kv {
	font-size: 20px;
	font-weight: 600;
	margin-top: 4px;
}
.stat .kd {
	margin-top: 2px;
}
@media (max-width: 1279px) {
	.stats {
		grid-template-columns: repeat(4, minmax(0, 1fr));
	}
}
@media (max-width: 767px) {
	.stats {
		grid-template-columns: repeat(2, minmax(0, 1fr));
	}
}
</style>
