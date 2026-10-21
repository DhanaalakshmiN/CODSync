<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
	Bell,
	CircleAlert,
	House,
	Landmark,
	Link2,
	Receipt,
	Search,
	SlidersHorizontal,
	Truck,
	ArrowLeftRight,
	TriangleAlert,
	ChartColumn,
} from "lucide-vue-next";
import { api } from "./api";
import { ago, initials, rs } from "./format";
import { openException, state, refresh } from "./store";
import Toasts from "./components/Toasts.vue";
import ImportModal from "./components/ImportModal.vue";
import ConnectModal from "./components/ConnectModal.vue";
import ExceptionDrawer from "./components/ExceptionDrawer.vue";

const route = useRoute();
const router = useRouter();

const nav = [
	{ key: "overview", label: "Overview", to: "/", icon: House },
	{ key: "orders", label: "Orders", to: "/orders", icon: Receipt },
	{ key: "shipments", label: "Shipments", to: "/shipments", icon: Truck },
	{
		key: "reconciliation",
		label: "Reconciliation",
		to: "/reconciliation",
		icon: ArrowLeftRight,
	},
	{ key: "settlements", label: "Settlements", to: "/settlements", icon: Landmark },
	{
		key: "exceptions",
		label: "Exceptions",
		to: "/exceptions",
		icon: TriangleAlert,
		count: true,
	},
	{ key: "couriers", label: "Couriers", to: "/couriers", icon: Link2 },
	{ key: "reports", label: "Reports", to: "/reports", icon: ChartColumn },
	{ key: "settings", label: "Settings", to: "/settings", icon: SlidersHorizontal },
];
const pg = computed(() => "pg-" + (route.meta.pg || "overview"));

// ---- boot (store name, sync time, exception count) ----
const loadBoot = async () => {
	try {
		state.boot = await api.boot({}, { silent: true });
	} catch (e) {
		/* page calls will show their own errors */
	}
};
onMounted(loadBoot);
watch(() => state.tick, loadBoot);
const now = ref(Date.now());
const timer = setInterval(() => (now.value = Date.now()), 30000);
onBeforeUnmount(() => clearInterval(timer));
const syncedText = computed(() => {
	now.value; // re-evaluate every 30s
	return state.boot?.last_synced_at
		? `Synced ${ago(state.boot.last_synced_at)}`
		: "Not synced yet";
});
const excCount = computed(() => state.boot?.open_exception_count || 0);
const store = computed(() => state.boot?.store_name || "Vanam Organics");

// ---- global search ----
const q = ref("");
const results = ref([]);
const showResults = ref(false);
let t = null;
watch(q, (v) => {
	clearTimeout(t);
	if (v.trim().length < 2) {
		results.value = [];
		return;
	}
	t = setTimeout(async () => {
		try {
			results.value = await api.global_search({ q: v }, { silent: true });
			showResults.value = true;
		} catch (e) {
			results.value = [];
		}
	}, 220);
});
const go = (r) => {
	showResults.value = false;
	q.value = "";
	router.push(r.route);
};

// ---- bell ----
const bell = ref(false);
const bellRows = ref([]);
const toggleBell = async () => {
	bell.value = !bell.value;
	if (bell.value)
		bellRows.value = (
			await api.exceptions({ page_size: 6, sort: "age_days desc" }, { silent: true })
		).rows;
};
const openExc = (e) => {
	bell.value = false;
	openException(e.name);
};
const closePops = (e) => {
	if (!e.target.closest(".search, .bellw")) showResults.value = bell.value = false;
};
onMounted(() => document.addEventListener("click", closePops));
onBeforeUnmount(() => document.removeEventListener("click", closePops));
watch(
	() => route.fullPath,
	() => (showResults.value = bell.value = false)
);
</script>

<template>
	<div :class="['app', pg]">
		<header class="topbar">
			<div class="brand">
				<span class="logo"
					><svg
						width="16"
						height="16"
						viewBox="0 0 20 20"
						fill="none"
						stroke="#fff"
						stroke-width="2"
					>
						<path d="M4 5h12M4 10h6M4 15h5" />
						<path d="m12 14 2 2 4-4" /></svg
				></span>
				<span>COD Ledger</span>
			</div>
			<label class="search">
				<Search :size="16" :stroke-width="1.6" />
				<input
					v-model="q"
					type="search"
					placeholder="Search order, AWB or UTR"
					aria-label="Search order, AWB or UTR"
					@focus="showResults = results.length > 0"
				/>
				<div v-if="showResults" class="pop">
					<div v-if="!results.length" class="sub">No matches</div>
					<a
						v-for="r in results"
						:key="r.type + r.route + r.label"
						@click.prevent="go(r)"
						>{{ r.label }}<span class="tag">{{ r.type }}</span></a
					>
				</div>
			</label>
			<div class="topr">
				<span class="sync"><span class="dot"></span>{{ syncedText }}</span>
				<span class="bellw">
					<button class="ibtn" aria-label="Notifications" @click="toggleBell">
						<Bell :size="18" :stroke-width="1.6" />
						<span v-if="excCount" class="bell-n">{{ excCount }}</span>
					</button>
					<div v-if="bell" class="pop">
						<div class="sub">
							{{ excCount }} open exception{{ excCount === 1 ? "" : "s" }}
						</div>
						<button v-for="e in bellRows" :key="e.name" @click="openExc(e)">
							<span
								><strong>{{ e.order_id || e.awb }}</strong> · {{ e.type
								}}<br /><span class="muted">{{ e.detail }}</span></span
							>
							<span :class="['tag', { neg: e.impact < 0 }]">{{ rs(e.impact) }}</span>
						</button>
						<router-link to="/exceptions" class="hl" @click="bell = false"
							>View all exceptions</router-link
						>
					</div>
				</span>
				<router-link class="store" to="/settings" aria-label="Store menu"
					><span class="avatar">{{ initials(store) }}</span
					>{{ store }}</router-link
				>
			</div>
		</header>
		<div class="shell">
			<nav class="side" aria-label="COD Ledger">
				<router-link
					v-for="n in nav"
					:key="n.key"
					:to="n.to"
					:class="['nav', { on: route.meta.nav === n.key }]"
				>
					<component :is="n.icon" :size="18" :stroke-width="1.6" />{{ n.label
					}}<span v-if="n.count && excCount" class="cnt">{{ excCount }}</span>
				</router-link>
			</nav>
			<main class="main">
				<router-view :key="route.fullPath" />
			</main>
		</div>
		<ImportModal v-if="state.importModal.open" />
		<ConnectModal v-if="state.connectModal.open" />
		<ExceptionDrawer v-if="state.drawer.open" />
		<Toasts />
	</div>
</template>
