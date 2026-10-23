<script setup>
import { computed, ref, watch } from "vue";
import { api } from "../api";
import { excKind, rs } from "../format";
import { openException, refresh, state, toast } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import EmptyState from "../components/EmptyState.vue";
import FilterChip from "../components/FilterChip.vue";
import PageState from "../components/PageState.vue";
import Pager from "../components/Pager.vue";
import Tabs from "../components/Tabs.vue";

const PAGE_SIZE = 12;
const STAGES = ["Open", "In review", "Disputed", "Resolved"];
const tab = ref("Open");
const search = ref("");
const page = ref(1);
const f = ref({ exception_type: "", courier: "" });
const res = ref(null);
const couriers = ref([]);
const selected = ref([]);
const sending = ref(false);
const loading = ref(true);
const error = ref("");

const load = async () => {
	loading.value = !res.value;
	error.value = "";
	try {
		res.value = await api.exceptions(
			{
				filters: {
					tab: tab.value,
					exception_type: f.value.exception_type || null,
					courier: f.value.courier || null,
					search: search.value || null,
				},
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
watch(
	[tab, f],
	() => {
		page.value = 1;
		selected.value = [];
		load();
	},
	{ deep: true }
);
watch([page, () => state.tick], load);
load();
api.couriers({ active_only: 0 }, { silent: true })
	.then((c) => (couriers.value = c.map((x) => x.name)))
	.catch(() => {});

const tabs = computed(() =>
	STAGES.map((k) => ({ key: k, label: k, count: res.value?.counts?.[k], red: k === "Open" }))
);
const columns = [
	{ key: "name", label: "ID" },
	{ key: "type", label: "Type" },
	{ key: "order", label: "Order / AWB" },
	{ key: "courier", label: "Courier" },
	{ key: "expected", label: "Expected", num: true },
	{ key: "actual", label: "Actual", num: true },
	{ key: "impact", label: "Impact", num: true },
	{ key: "age_days", label: "Age", num: true },
	{ key: "assignee", label: "Assignee" },
];
const sendClaims = async () => {
	sending.value = true;
	try {
		const names = selected.value;
		const pv = await api.preview_claim({ names }, { silent: true });
		const lines = pv.map((p) => `${p.courier}: ${p.count} claim(s), ${rs(p.total)} to ${p.to}`);
		if (!confirm(`Email these claims?\n\n${lines.join("\n")}`)) return;
		await api.send_claim({ names }, { silent: true });
		toast("Claims emailed");
		selected.value = [];
		refresh();
	} catch (e) {
		toast(e.message, "e");
	} finally {
		sending.value = false;
	}
};
const stageKind = (s) =>
	({ Open: "mis", "In review": "pend", Disputed: "info", Resolved: "ok" }[s] || "");
const filtered = computed(() => !!(search.value || f.value.exception_type || f.value.courier));
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<div>
				<h1>Exceptions</h1>
				<p class="muted" style="margin: 2px 0 0">
					Payouts and shipments that could not be reconciled automatically. Click a row
					to resolve it.
				</p>
			</div>
		</div>
		<section class="card">
			<Tabs v-model="tab" :tabs="tabs" />
			<div v-if="selected.length" class="tbar">
				<span class="muted">{{ selected.length }} selected</span>
				<button class="btn sm" :disabled="sending" @click="sendClaims">Send claim to courier</button>
			</div>
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
						placeholder="Exception, order or AWB"
						aria-label="Filter exceptions"
				/></label>
				<FilterChip v-model="f.exception_type" label="Type" :options="res?.types || []" />
				<FilterChip v-model="f.courier" label="Courier" :options="couriers" />
			</div>
			<PageState :loading="loading" :error="error" @retry="load">
				<template v-if="res">
					<EmptyState
						v-if="!res.rows.length"
						:title="
							filtered ? 'No exceptions match' : `No ${tab.toLowerCase()} exceptions`
						"
						:text="
							filtered
								? 'Try a different filter or search term.'
								: tab === 'Open'
								? 'Everything that can be reconciled automatically has been.'
								: 'Nothing here yet.'
						"
						:tone="!filtered && tab === 'Open' ? 'ok' : undefined"
					/>
					<DataTable
						v-else
						:columns="columns"
						v-model:selected="selected"
						:rows="res.rows"
						row-key="name"
						selectable
						clickable
						@row-click="(r) => openException(r.name)"
					>
						<template #cell-name="{ row }"
							><strong>{{ row.name }}</strong></template
						>
						<template #cell-type="{ row }"
							><Badge :kind="excKind(row.type)">{{ row.type }}</Badge></template
						>
						<template #cell-order="{ row }"
							><router-link
								v-if="row.order_id"
								:to="`/orders/${encodeURIComponent(row.order_id)}`"
								@click.stop
								>{{ row.order_id }}</router-link
							><span v-else class="muted">&mdash;</span>
							<div v-if="row.awb" class="mono muted">{{ row.awb }}</div></template
						>
						<template #cell-courier="{ row }"
							><template v-if="row.courier">{{ row.courier }}</template
							><span v-else class="muted">&mdash;</span></template
						>
						<template #cell-expected="{ row }">{{ rs(row.expected) }}</template>
						<template #cell-actual="{ row }">{{ rs(row.actual) }}</template>
						<template #cell-impact="{ row }"
							><span :class="{ neg: row.impact < 0 }">{{
								rs(row.impact)
							}}</span></template
						>
						<template #cell-age_days="{ row }"
							><Badge
								:kind="
									tab === 'Resolved'
										? ''
										: row.age_days > 7
										? 'mis'
										: row.age_days > 2
										? 'pend'
										: ''
								"
								nd
								>{{ row.age_days }}d</Badge
							></template
						>
						<template #cell-assignee="{ row }"
							><template v-if="row.assignee">{{ row.assignee }}</template
							><span v-else class="muted">Unassigned</span>
							<Badge
								v-if="tab === 'Disputed' || row.stage === 'Disputed'"
								:kind="stageKind(row.stage)"
								>{{ row.dispute_status === "Raised with Courier" ? "Disputed" : row.dispute_status }}</Badge
							>
							<Badge v-if="row.overdue" kind="mis" nd>Overdue</Badge></template
						>
					</DataTable>
					<Pager
						v-model:page="page"
						:page-size="PAGE_SIZE"
						:total="res.total"
						noun="exceptions"
					/>
				</template>
			</PageState>
		</section>
	</div>
</template>
