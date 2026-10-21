<script setup>
import { computed, ref, watch } from "vue";
import { RefreshCw } from "lucide-vue-next";
import { api } from "../api";
import { codKind, daysAgoIso, dShort, deliveryKind, reconKind, rs, saveCsv } from "../format";
import { refresh, state, toast } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import EmptyState from "../components/EmptyState.vue";
import FilterChip from "../components/FilterChip.vue";
import PageState from "../components/PageState.vue";
import Pager from "../components/Pager.vue";
import Tabs from "../components/Tabs.vue";

const PAGE_SIZE = 12;
const tab = ref("COD");
const search = ref("");
const page = ref(1);
const f = ref({
	date: "30",
	courier: "",
	delivery_status: "",
	cod_status: "",
	reconciliation: "",
});
const sort = ref("date desc");
const sortOpen = ref(false);
const res = ref(null);
const couriers = ref([]);
const loading = ref(true);
const error = ref("");
const syncing = ref(false);
const selected = ref([]);

const SORTS = [
	["date desc", "Newest"],
	["date asc", "Oldest"],
	["amount desc", "Amount: high to low"],
	["amount asc", "Amount: low to high"],
];
const DELIVERY = [
	"Unfulfilled",
	"Fulfilled",
	"Pickup scheduled",
	"In transit",
	"Out for delivery",
	"Delivered",
	"RTO initiated",
	"RTO delivered",
	"Cancelled",
];
const COD = [
	"Not applicable",
	"Awaiting shipment",
	"Not collected",
	"Collected",
	"Settled",
	"Unknown",
];
const RECON = ["Pending", "Reconciled", "Mismatch", "Exception"];
const DATES = [
	{ value: "7", label: "Last 7 days" },
	{ value: "30", label: "Last 30 days" },
	{ value: "90", label: "Last 90 days" },
	{ value: "3650", label: "All time" },
];

const args = (extra = {}) => ({
	tab: tab.value,
	courier: f.value.courier || null,
	delivery_status: f.value.delivery_status || null,
	cod_status: f.value.cod_status || null,
	reconciliation: f.value.reconciliation || null,
	from_date: daysAgoIso(Number(f.value.date || 3650)),
	search: search.value || null,
	sort: sort.value,
	page: page.value,
	page_size: PAGE_SIZE,
	...extra,
});

const load = async () => {
	loading.value = !res.value;
	error.value = "";
	try {
		res.value = await api.orders(args(), { silent: true });
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
watch(
	[tab, f, sort],
	() => {
		page.value = 1;
		selected.value = [];
		load();
	},
	{ deep: true }
);
watch([page, () => state.tick], load);
load();
api.couriers({}, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch(() => {});

const tabs = computed(() => {
	const c = res.value?.counts || {};
	return ["All", "COD", "Prepaid", "Unreconciled", "Exceptions"].map((k) => ({
		key: k,
		label: k,
		count: c[k],
	}));
});
const noun = computed(() =>
	tab.value === "All"
		? "orders"
		: tab.value === "Unreconciled" || tab.value === "Exceptions"
		? `${tab.value.toLowerCase()} orders`
		: `${tab.value} orders`
);
const sortLabel = computed(() => SORTS.find((s) => s[0] === sort.value)[1]);

const columns = [
	{ key: "order_id", label: "Order" },
	{ key: "date", label: "Date" },
	{ key: "customer", label: "Customer" },
	{ key: "amount", label: "Amount", num: true },
	{ key: "payment_mode", label: "Payment" },
	{ key: "awb", label: "AWB" },
	{ key: "courier", label: "Courier" },
	{ key: "delivery_status", label: "Delivery" },
	{ key: "cod_status", label: "COD status" },
	{ key: "reconciliation_status", label: "Reconciliation" },
];

const exporting = ref(false);
const exportCsv = async () => {
	exporting.value = true;
	try {
		const all = await api.orders(args({ page: 1, page_size: 100000 }), { silent: true });
		saveCsv("orders.csv", columns, all.rows);
	} catch (e) {
		toast(e.message, "e");
	} finally {
		exporting.value = false;
	}
};
const syncShopify = async () => {
	syncing.value = true;
	try {
		const r = await api.fetch_orders({}, { silent: true });
		toast(
			r.queued
				? "Fetching orders in the background. Refresh in a moment."
				: "An order fetch is already running"
		);
		refresh();
	} catch (e) {
		toast(e.message, "e");
	} finally {
		syncing.value = false;
	}
};
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<h1>Orders</h1>
			<div class="acts">
				<button class="btn" :disabled="exporting" @click="exportCsv">Export</button>
				<button class="btn" :disabled="syncing" @click="syncShopify">
					<span v-if="syncing" class="spin"></span
					><RefreshCw v-else :size="16" :stroke-width="1.6" />Sync orders
				</button>
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
						placeholder="Order, customer or AWB"
						aria-label="Filter orders"
				/></label>
				<FilterChip v-model="f.date" label="Date" :options="DATES" />
				<FilterChip v-model="f.courier" label="Courier" :options="couriers" />
				<FilterChip
					v-model="f.delivery_status"
					label="Delivery status"
					:options="DELIVERY"
				/>
				<FilterChip v-model="f.cod_status" label="COD status" :options="COD" />
				<FilterChip v-model="f.reconciliation" label="Reconciliation" :options="RECON" />
				<div class="acts chipw">
					<button class="btn sm" @click="sortOpen = !sortOpen">
						Sort: {{ sortLabel }}
					</button>
					<div
						v-if="sortOpen"
						class="pop"
						style="right: 0; left: auto"
						@mouseleave="sortOpen = false"
					>
						<button
							v-for="s in SORTS"
							:key="s[0]"
							@click="(sort = s[0]), (sortOpen = false)"
						>
							{{ s[1] }}
						</button>
					</div>
				</div>
			</div>
			<PageState :loading="loading" :error="error" @retry="load">
				<template v-if="res">
					<EmptyState
						v-if="!res.rows.length"
						title="No orders match"
						text="Try a different tab, filter or search term."
					/>
					<DataTable
						v-else
						v-model:selected="selected"
						:columns="columns"
						:rows="res.rows"
						row-key="order_id"
						selectable
					>
						<template #cell-order_id="{ row }"
							><router-link :to="`/orders/${encodeURIComponent(row.order_id)}`"
								><strong>{{ row.order_id }}</strong></router-link
							></template
						>
						<template #cell-date="{ row }"
							><span class="muted">{{ dShort(row.date) }}</span></template
						>
						<template #cell-amount="{ row }">{{ rs(row.amount) }}</template>
						<template #cell-payment_mode="{ row }"
							><Badge nd :out="row.payment_mode === 'COD'">{{
								row.payment_mode
							}}</Badge></template
						>
						<template #cell-awb="{ row }"
							><span v-if="row.awb" class="mono">{{ row.awb }}</span
							><span v-else-if="row.awb_missing" class="neg">Missing</span
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-courier="{ row }"
							><template v-if="row.courier">{{ row.courier }}</template
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-delivery_status="{ row }"
							><Badge :kind="deliveryKind(row.delivery_status)">{{
								row.delivery_status
							}}</Badge></template
						>
						<template #cell-cod_status="{ row }"
							><span v-if="row.cod_status === 'Not applicable'" class="muted"
								>Not applicable</span
							><Badge v-else :kind="codKind(row.cod_status)">{{
								row.cod_status
							}}</Badge></template
						>
						<template #cell-reconciliation_status="{ row }"
							><Badge
								v-if="row.reconciliation_status"
								:kind="reconKind(row.reconciliation_status)"
								>{{ row.reconciliation_status }}</Badge
							><span v-else class="muted">&mdash;</span></template
						>
					</DataTable>
					<Pager
						v-model:page="page"
						:page-size="PAGE_SIZE"
						:total="res.total"
						:noun="noun"
					/>
				</template>
			</PageState>
		</section>
	</div>
</template>
