<script setup>
import { computed, ref, watch } from "vue";
import { RefreshCw } from "lucide-vue-next";
import { api, call } from "../api";
import { ago, dShort, dShortTime, deliveryKind, kg, rs } from "../format";
import { refresh, state, toast } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import Drawer from "../components/Drawer.vue";
import EmptyState from "../components/EmptyState.vue";
import FilterChip from "../components/FilterChip.vue";
import PageState from "../components/PageState.vue";
import Pager from "../components/Pager.vue";
import Tabs from "../components/Tabs.vue";

const PAGE_SIZE = 12;
const status = ref("All");
const search = ref("");
const courier = ref("");
const sort = ref("last_event_at desc");
const sortOpen = ref(false);
const page = ref(1);
const res = ref(null);
const couriers = ref([]);
const loading = ref(true);
const error = ref("");
const syncingAll = ref(false);

// drawer
const openId = ref(null);
const detail = ref(null);
const detailLoading = ref(false);
const detailError = ref("");
const syncing = ref(false);

const SORTS = [
	["last_event_at desc", "Latest event"],
	["last_event_at asc", "Oldest event"],
	["awb asc", "AWB A–Z"],
	["delivered_date desc", "Latest delivery"],
];
const STATUSES = ["Booked", "In Transit", "Delivered", "RTO", "Cancelled"];
const statusKind = (s) =>
	({ Delivered: "ok", "In Transit": "info", Booked: "pend", RTO: "mis", Cancelled: "exc" }[s] ||
	"");

const load = async () => {
	loading.value = !res.value;
	error.value = "";
	try {
		res.value = await api.shipments(
			{
				status: status.value,
				courier: courier.value || null,
				search: search.value || null,
				sort: sort.value,
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
watch([status, courier, sort], () => {
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
	return ["All", ...STATUSES].map((k) => ({
		key: k,
		label: k === "All" ? "All shipments" : k,
		count: c[k],
	}));
});
const sortLabel = computed(() => SORTS.find((s) => s[0] === sort.value)[1]);
const columns = [
	{ key: "awb", label: "AWB" },
	{ key: "order_id", label: "Order" },
	{ key: "courier", label: "Courier" },
	{ key: "status", label: "Status" },
	{ key: "last_event", label: "Last event" },
	{ key: "weights", label: "Charged / declared wt" },
	{ key: "delivered_date", label: "Delivered" },
];

const openShipment = async (row) => {
	openId.value = row.order_id;
	detail.value = null;
	detailError.value = "";
	detailLoading.value = true;
	try {
		detail.value = await api.shipment_detail({ order_id: row.order_id }, { silent: true });
	} catch (e) {
		detailError.value = e.message;
	}
	detailLoading.value = false;
};
const events = computed(() => [...(detail.value?.tracking_events || [])].reverse());
const dot = (s) => (String(s).toLowerCase() === "delivered" ? "g" : "");

const syncOne = async () => {
	syncing.value = true;
	try {
		const r = await call(
			"codsync.codsync.tracking.sync_tracking",
			{ parcel: openId.value },
			{ silent: true }
		);
		toast(
			`Tracking sync: ${r.checked} checked, ${r.updated} updated, ${r.failed} failed`,
			r.failed ? "e" : ""
		);
		const d = await api.shipment_detail({ order_id: openId.value }, { silent: true });
		detail.value = d;
		load();
	} catch (e) {
		toast(e.message, "e");
	} finally {
		syncing.value = false;
	}
};
const syncAll = async () => {
	syncingAll.value = true;
	try {
		const n = await api.sync_tracking({}, { silent: true });
		toast(`${n} shipment${n === 1 ? "" : "s"} refreshed`);
		refresh();
	} catch (e) {
		toast(e.message, "e");
	} finally {
		syncingAll.value = false;
	}
};
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<h1>Shipments</h1>
			<div class="acts">
				<span v-if="res?.last_synced" class="muted" style="font-size: 12px"
					>Tracking synced {{ ago(res.last_synced) }}</span
				>
				<button class="btn" :disabled="syncingAll" @click="syncAll">
					<span v-if="syncingAll" class="spin"></span
					><RefreshCw v-else :size="16" :stroke-width="1.6" />Sync Tracking
				</button>
			</div>
		</div>
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
						placeholder="AWB or order"
						aria-label="Filter shipments"
				/></label>
				<FilterChip v-model="courier" label="Courier" :options="couriers" />
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
						title="No shipments match"
						text="Try a different status, courier or search term."
					/>
					<DataTable
						v-else
						:columns="columns"
						:rows="res.rows"
						row-key="order_id"
						clickable
						@row-click="openShipment"
					>
						<template #cell-awb="{ row }"
							><span class="mono">{{ row.awb }}</span></template
						>
						<template #cell-order_id="{ row }"
							><router-link
								:to="`/orders/${encodeURIComponent(row.order_id)}`"
								@click.stop
								><strong>{{ row.order_id }}</strong></router-link
							></template
						>
						<template #cell-courier="{ row }"
							><template v-if="row.courier">{{ row.courier }}</template
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-status="{ row }"
							><Badge v-if="row.status" :kind="statusKind(row.status)">{{
								row.status
							}}</Badge
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-last_event="{ row }">
							<strong>{{ row.last_event || "—" }}</strong>
							<div class="muted" style="font-size: 12px">
								{{
									row.last_event_at
										? `${dShortTime(row.last_event_at)} · ${ago(
												row.last_event_at
										  )}`
										: "No events yet"
								}}
							</div>
						</template>
						<template #cell-weights="{ row }">
							<span
								:class="{
									neg:
										row.charged_weight &&
										row.declared_weight &&
										row.charged_weight > row.declared_weight,
								}"
							>
								{{ row.charged_weight ? kg(row.charged_weight) : "—" }}</span
							>
							<span class="muted"> / {{ kg(row.declared_weight) }}</span>
						</template>
						<template #cell-delivered_date="{ row }"
							><span class="muted">{{
								row.delivered_date ? dShort(row.delivered_date) : "—"
							}}</span></template
						>
					</DataTable>
					<Pager
						v-model:page="page"
						:page-size="PAGE_SIZE"
						:total="res.total"
						noun="shipments"
					/>
				</template>
			</PageState>
		</section>

		<Drawer v-if="openId" pg="pg-shipments" @close="openId = null">
			<template #head>
				<div>
					<div class="mono" style="font-weight: 600">{{ detail?.awb || openId }}</div>
					<div class="muted" style="font-size: 12px">
						<router-link
							:to="`/orders/${encodeURIComponent(openId)}`"
							@click="openId = null"
							>{{ openId }}</router-link
						>
						<template v-if="detail"> · {{ detail.courier || "No courier" }}</template>
					</div>
				</div>
				<Badge v-if="detail" :kind="statusKind(detail.status)" style="margin-left: 8px">{{
					detail.status
				}}</Badge>
			</template>
			<div v-if="detailLoading" class="muted" style="padding: 16px">Loading shipment…</div>
			<div v-else-if="detailError" class="err-state">
				<strong>Could not load this shipment</strong>
				<span class="muted">{{ detailError }}</span>
			</div>
			<template v-else-if="detail">
				<dl class="kvl cols" style="padding: 16px 16px 0">
					<div>
						<dt>Delivery status</dt>
						<dd>
							<Badge :kind="deliveryKind(detail.delivery_status)">{{
								detail.delivery_status
							}}</Badge>
						</dd>
					</div>
					<div>
						<dt>Charged / declared wt</dt>
						<dd>
							{{ detail.charged_weight ? kg(detail.charged_weight) : "—" }} /
							{{ kg(detail.declared_weight) }}
						</dd>
					</div>
					<div>
						<dt>Delivered on</dt>
						<dd>{{ detail.delivered_date ? dShort(detail.delivered_date) : "—" }}</dd>
					</div>
					<div>
						<dt>COD amount</dt>
						<dd>
							{{
								detail.payment_mode === "Prepaid"
									? "Prepaid"
									: rs(detail.cod_amount)
							}}
						</dd>
					</div>
					<div>
						<dt>Payout status</dt>
						<dd>{{ detail.payout_status || "—" }}</dd>
					</div>
				</dl>
				<h3 style="padding: 16px 16px 4px; font-size: 14px">Tracking events</h3>
				<EmptyState
					v-if="!events.length"
					title="No tracking events yet"
					text="Run Sync Tracking to pull the latest scans from the courier."
				/>
				<ul v-else class="tl">
					<li v-for="(e, i) in events" :key="i">
						<span :class="['m', dot(e.status)]"></span>
						<div>
							<strong>{{ e.status || "Event" }}</strong>
							<div v-if="e.location" class="muted">{{ e.location }}</div>
						</div>
						<span class="w">{{ e.event_time ? dShortTime(e.event_time) : "—" }}</span>
					</li>
				</ul>
			</template>
			<template #footer>
				<button class="btn" :disabled="syncing || !detail?.awb" @click="syncOne">
					<span v-if="syncing" class="spin"></span
					><RefreshCw v-else :size="16" :stroke-width="1.6" />Sync Tracking
				</button>
				<router-link
					v-if="detail"
					class="btn link"
					:to="`/orders/${encodeURIComponent(openId)}`"
					@click="openId = null"
					>Open order</router-link
				>
			</template>
		</Drawer>
	</div>
</template>
