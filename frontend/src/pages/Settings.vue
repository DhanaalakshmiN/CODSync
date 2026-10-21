<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Copy, Plus, X } from "lucide-vue-next";
import { api } from "../api";
import { ago, dShortTime } from "../format";
import { refresh, state, toast } from "../store";
import Badge from "../components/Badge.vue";
import DataTable from "../components/DataTable.vue";
import EmptyState from "../components/EmptyState.vue";
import FilterChip from "../components/FilterChip.vue";
import PageState from "../components/PageState.vue";
import Pager from "../components/Pager.vue";
import SelectField from "../components/SelectField.vue";

const s = ref(null);
const loading = ref(true);
const error = ref("");
const form = ref(null);
const secrets = ref({});
const orig = ref("");
const busy = ref("");
const banner = ref(null); // { ok, text } from the last test / save error
const fetching = ref(false);

const snapshot = () => JSON.stringify(form.value);
const apply = (data) => {
	s.value = data;
	form.value = JSON.parse(
		JSON.stringify({ ...data.store, courier_mapping: data.courier_mapping })
	);
	secrets.value = {};
	orig.value = snapshot();
	fetching.value = data.fetching;
};
const load = async () => {
	loading.value = !s.value;
	error.value = "";
	try {
		apply(await api.settings({}, { silent: true }));
	} catch (e) {
		error.value = e.message;
	}
	loading.value = false;
};
load();

const dirty = computed(
	() =>
		!!form.value && (snapshot() !== orig.value || Object.values(secrets.value).some((v) => v))
);
const platform = computed(() => form.value?.platform);
const SECRET_LABELS = {
	Shopify: [
		["shopify_client_id", "Client ID"],
		["shopify_client_secret", "Client secret"],
	],
	WooCommerce: [
		["woo_consumer_key", "Consumer key"],
		["woo_consumer_secret", "Consumer secret"],
	],
	Odoo: [["odoo_api_key", "API key"]],
};
const versionField = computed(
	() => ({ Shopify: "shopify_api_version", WooCommerce: "woo_api_version" }[platform.value])
);
const canEdit = computed(() => s.value?.can_edit);

const discard = () => apply(s.value && { ...s.value });
const save = async () => {
	busy.value = "save";
	banner.value = null;
	try {
		const values = { ...form.value };
		Object.entries(secrets.value).forEach(([k, v]) => v && (values[k] = v));
		apply(await api.save_settings({ values }, { silent: true }));
		toast("Settings saved");
		refresh();
	} catch (e) {
		banner.value = { ok: false, text: e.message };
	} finally {
		busy.value = "";
	}
};

const test = async () => {
	busy.value = "test";
	banner.value = null;
	try {
		const r = await api.test_connection({}, { silent: true });
		banner.value = { ok: r.ok, text: r.message };
		s.value.status = r.status;
		loadLog();
	} catch (e) {
		banner.value = { ok: false, text: e.message };
	} finally {
		busy.value = "";
	}
};

let poll = null;
const stopPoll = () => clearInterval(poll);
onBeforeUnmount(stopPoll);
const startPoll = () => {
	stopPoll();
	let n = 0;
	poll = setInterval(async () => {
		n++;
		try {
			const d = await api.settings({}, { silent: true });
			s.value.status = d.status;
			loadLog();
			if (!d.fetching || n > 60) {
				stopPoll();
				fetching.value = false;
				toast(
					d.fetching
						? "Order fetch is still running; check the sync log"
						: "Order fetch finished, see the sync log"
				);
				refresh();
			}
		} catch (e) {
			/* keep polling; the next tick may succeed */
		}
	}, 4000);
};
watch(fetching, (v) => v && startPoll());
const fetchOrders = async () => {
	busy.value = "fetch";
	banner.value = null;
	try {
		const r = await api.fetch_orders({}, { silent: true });
		fetching.value = true;
		toast(
			r.queued ? "Fetching orders in the background" : "An order fetch is already running"
		);
	} catch (e) {
		banner.value = { ok: false, text: e.message };
	} finally {
		busy.value = "";
	}
};

// ---- webhook url
const copied = ref(false);
const copy = async () => {
	const text = s.value.webhook_url;
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
	copied.value = true;
	toast("Webhook URL copied");
	setTimeout(() => (copied.value = false), 2000);
};

// ---- courier mapping
const addRow = () => form.value.courier_mapping.push({ source_name: "", courier: "" });
const delRow = (i) => form.value.courier_mapping.splice(i, 1);

// ---- sync log
const log = ref(null);
const logPage = ref(1);
const logErr = ref("");
const logLoading = ref(true);
const lf = ref({ status: "", operation: "" });
const loadLog = async () => {
	logErr.value = "";
	try {
		log.value = await api.sync_log(
			{
				page: logPage.value,
				page_size: 8,
				status: lf.value.status || null,
				operation: lf.value.operation || null,
			},
			{ silent: true }
		);
	} catch (e) {
		logErr.value = e.message;
	}
	logLoading.value = false;
};
loadLog();
watch(lf, () => ((logPage.value = 1), loadLog()), { deep: true });
watch([logPage, () => state.tick], loadLog);
const statusKind = (v) => ({ Success: "ok", Failed: "exc", Retrying: "pend" }[v] || "");
const cols = [
	{ key: "time", label: "Time" },
	{ key: "status", label: "Status" },
	{ key: "operation", label: "Operation" },
	{ key: "platform", label: "Platform" },
	{ key: "error", label: "Message" },
];
const blocked = computed(() => dirty.value || !!busy.value || fetching.value);
</script>

<template>
	<div class="wrap">
		<div class="ph">
			<h1>Settings</h1>
			<div v-if="s" class="acts">
				<span v-if="dirty" class="muted">Unsaved changes</span>
				<button class="btn" :disabled="!dirty || !!busy" @click="discard">Discard</button>
				<button
					class="btn pri"
					:disabled="!dirty || !!busy || !canEdit"
					:title="canEdit ? '' : 'Only a CODSync Manager can change settings'"
					@click="save"
				>
					<span v-if="busy === 'save'" class="spin"></span>Save changes
				</button>
			</div>
		</div>

		<PageState :loading="loading" :error="error" @retry="load">
			<template v-if="s && form">
				<div v-if="banner" :class="['imp-banner', banner.ok ? 'ok' : 'err']" role="alert">
					<strong>{{ banner.ok ? "Connection OK" : "Something went wrong" }}</strong
					><span>{{ banner.text }}</span>
				</div>

				<!-- store connection -->
				<div class="setrow">
					<div class="setl">
						<h3>Store connection</h3>
						<p>
							The store COD orders come from. Credentials are write-only: they are
							never shown again after saving.
						</p>
					</div>
					<section class="card">
						<div class="setgrid">
							<label
								><span class="lab2">Platform</span
								><SelectField
									v-model="form.platform"
									:options="s.platforms"
									:disabled="!canEdit"
									aria-label="Platform"
									style="max-width: none"
							/></label>
							<label class="chk" style="align-self: end; min-height: 32px"
								><input
									v-model="form.enabled"
									type="checkbox"
									:disabled="!canEdit"
								/>
								Connection enabled</label
							>
							<label
								><span class="lab2">Store URL</span
								><input
									v-model="form.store_url"
									class="inp"
									placeholder="your-store.myshopify.com"
									:disabled="!canEdit"
							/></label>
							<label
								><span class="lab2">Store name</span
								><input v-model="form.store_name" class="inp" :disabled="!canEdit"
							/></label>
							<template v-if="platform === 'Odoo'">
								<label
									><span class="lab2">Database</span
									><input
										v-model="form.odoo_database"
										class="inp"
										:disabled="!canEdit"
								/></label>
								<label
									><span class="lab2">Username</span
									><input
										v-model="form.odoo_username"
										class="inp"
										:disabled="!canEdit"
								/></label>
							</template>
							<label
								v-for="[key, label] in SECRET_LABELS[platform] || []"
								:key="key"
							>
								<span class="lab2"
									>{{ label }}
									<Badge v-if="s.saved[key]" kind="ok">Saved</Badge></span
								>
								<input
									v-model="secrets[key]"
									class="inp"
									type="password"
									autocomplete="new-password"
									:placeholder="
										s.saved[key] ? 'Saved (type to replace)' : 'Not set'
									"
									:disabled="!canEdit"
								/>
							</label>
							<label v-if="versionField"
								><span class="lab2">API version</span
								><input
									v-model="form[versionField]"
									class="inp"
									:disabled="!canEdit"
							/></label>
							<label
								><span class="lab2"
									>Webhook secret
									<Badge v-if="s.saved.webhook_secret" kind="ok">Saved</Badge
									><Badge v-else kind="pend">Not set</Badge></span
								>
								<input
									v-model="secrets.webhook_secret"
									class="inp"
									type="password"
									autocomplete="new-password"
									:placeholder="
										s.saved.webhook_secret
											? 'Saved (type to replace)'
											: 'Paste the signing secret'
									"
									:disabled="!canEdit"
							/></label>
							<label
								><span class="lab2">COD keyword</span
								><input
									v-model="form.cod_keyword"
									class="inp"
									:disabled="!canEdit"
								/><span class="hint"
									>A payment gateway name containing this counts as COD.</span
								></label
							>
							<label
								><span class="lab2">COD tag</span
								><input
									v-model="form.cod_tag"
									class="inp"
									:disabled="!canEdit"
								/><span class="hint">An order tag that counts as COD.</span></label
							>
						</div>
						<div class="setstat">
							<div>
								<Badge
									v-if="s.status.last_test_status"
									:kind="s.status.last_test_status === 'Success' ? 'ok' : 'exc'"
									>Last test: {{ s.status.last_test_status }}</Badge
								>
								<Badge v-else>Not tested yet</Badge>
								<span v-if="s.status.last_tested_on" class="muted">
									{{ ago(s.status.last_tested_on) }}</span
								>
								<span class="muted">
									· Orders last fetched:
									{{
										s.status.last_synced_on
											? ago(s.status.last_synced_on)
											: "never"
									}}</span
								>
							</div>
							<div class="acts" style="margin-left: 0">
								<button
									class="btn"
									:disabled="blocked || !canEdit"
									:title="dirty ? 'Save your changes first' : ''"
									@click="test"
								>
									<span v-if="busy === 'test'" class="spin"></span>Test
									connection
								</button>
								<button
									class="btn"
									:disabled="blocked || !canEdit"
									:title="dirty ? 'Save your changes first' : ''"
									@click="fetchOrders"
								>
									<span v-if="busy === 'fetch' || fetching" class="spin"></span
									>{{ fetching ? "Fetching..." : "Fetch orders" }}
								</button>
							</div>
						</div>
					</section>
				</div>

				<!-- webhook url -->
				<div class="setrow">
					<div class="setl">
						<h3>Webhook URL</h3>
						<p>
							Paste this into your store's webhook settings so new orders arrive
							instantly.
						</p>
					</div>
					<section class="card">
						<div style="display: flex; gap: 8px; align-items: center; flex-wrap: wrap">
							<input
								class="inp mono"
								style="flex: 1 1 260px"
								:value="s.webhook_url"
								readonly
								aria-label="Webhook URL"
								@focus="$event.target.select()"
							/>
							<button class="btn" @click="copy">
								<Copy :size="14" :stroke-width="1.8" />{{
									copied ? "Copied" : "Copy"
								}}
							</button>
						</div>
						<span class="hint"
							>The URL is built from this site's address. It must be reachable from
							the internet for the store to call it.</span
						>
					</section>
				</div>

				<!-- reconciliation + mapping -->
				<div class="setrow">
					<div class="setl">
						<h3>Reconciliation</h3>
						<p>
							How much a payout may differ, how long couriers take to pay, and how
							store courier names map to your couriers.
						</p>
					</div>
					<section class="card">
						<div class="setgrid">
							<label
								><span class="lab2">Difference tolerance (₹)</span
								><input
									v-model.number="form.tolerance"
									class="inp"
									type="number"
									min="0"
									step="0.01"
									:disabled="!canEdit"
								/><span class="hint"
									>Within this, orders reconcile automatically.</span
								></label
							>
							<label
								><span class="lab2">Default payout cycle (days)</span
								><input
									v-model.number="form.default_payout_cycle_days"
									class="inp"
									type="number"
									min="1"
									step="1"
									:disabled="!canEdit"
								/><span class="hint"
									>Used when a courier has no cycle of its own.</span
								></label
							>
							<label
								><span class="lab2">Default courier</span
								><SelectField
									v-model="form.default_courier"
									:options="
										['', ...s.couriers].map((c) => ({
											value: c,
											label: c || 'None',
										}))
									"
									placeholder="None"
									:disabled="!canEdit"
									aria-label="Default courier"
									style="max-width: none"
								/><span class="hint"
									>Used when the store's courier name is not mapped.</span
								></label
							>
						</div>
						<div>
							<span class="lab2">Courier mapping</span>
							<div
								v-if="!form.courier_mapping.length"
								class="muted"
								style="padding: 6px 0"
							>
								No mappings yet. Add one to turn a store courier name into one of
								your couriers.
							</div>
							<div v-for="(r, i) in form.courier_mapping" :key="i" class="maprow">
								<input
									v-model="r.source_name"
									class="inp"
									placeholder="Name used by the store"
									aria-label="Source name"
									:disabled="!canEdit"
								/>
								<SelectField
									v-model="r.courier"
									:options="s.couriers"
									placeholder="Courier"
									:disabled="!canEdit"
									aria-label="Courier"
									style="max-width: none"
								/>
								<button
									class="btn sm"
									aria-label="Remove mapping"
									:disabled="!canEdit"
									@click="delRow(i)"
								>
									<X :size="14" :stroke-width="1.8" />
								</button>
							</div>
							<button
								class="btn sm"
								style="margin-top: 8px"
								:disabled="!canEdit"
								@click="addRow"
							>
								<Plus :size="14" :stroke-width="1.8" />Add mapping
							</button>
						</div>
					</section>
				</div>
			</template>
		</PageState>

		<!-- sync log -->
		<div class="setrow">
			<div class="setl">
				<h3>Sync log</h3>
				<p>
					Recent webhook, order sync, import and matching events, with any error message.
				</p>
			</div>
			<section class="card" style="padding: 0">
				<div class="tbar">
					<FilterChip
						v-model="lf.status"
						label="Status"
						:options="['Success', 'Failed', 'Retrying']"
					/>
					<FilterChip
						v-model="lf.operation"
						label="Operation"
						:options="log?.operations || []"
					/>
				</div>
				<PageState :loading="logLoading" :error="logErr" @retry="loadLog">
					<template v-if="log">
						<EmptyState
							v-if="!log.rows.length"
							title="No sync events"
							:text="
								lf.status || lf.operation
									? 'Try removing a filter.'
									: 'Events appear here as orders, imports and syncs run.'
							"
						/>
						<DataTable v-else :columns="cols" :rows="log.rows" row-key="name">
							<template #cell-time="{ row }"
								><span class="muted">{{ dShortTime(row.time) }}</span></template
							>
							<template #cell-status="{ row }"
								><Badge :kind="statusKind(row.status)">{{
									row.status
								}}</Badge></template
							>
							<template #cell-error="{ row }"
								><span
									v-if="row.error"
									class="neg"
									style="white-space: normal; font-weight: 400"
									>{{ row.error }}</span
								><span v-else class="muted">{{
									row.reference || "—"
								}}</span></template
							>
						</DataTable>
						<Pager
							v-model:page="logPage"
							:page-size="8"
							:total="log.total"
							noun="events"
						/>
					</template>
				</PageState>
			</section>
		</div>
	</div>
</template>
