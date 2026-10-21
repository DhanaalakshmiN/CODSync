<script setup>
import { computed, ref, watch } from "vue";
import { api } from "../api";
import { dShortTime, excKind, rs } from "../format";
import { closeDrawer, refresh, state, toast } from "../store";
import Badge from "./Badge.vue";
import Drawer from "./Drawer.vue";
import PageState from "./PageState.vue";
import SelectField from "./SelectField.vue";

const d = ref(null);
const loading = ref(true);
const error = ref("");
const action = ref("");
const note = ref("");
const claim = ref("");
const line = ref("");
const parcel = ref("");
const outcome = ref("");
const assignee = ref("");
const busy = ref("");
const formError = ref("");

const load = async () => {
	loading.value = true;
	error.value = "";
	try {
		d.value = await api.exception_detail({ name: state.drawer.name }, { silent: true });
		action.value = d.value.resolution_options.find((o) => o.default)?.key || "";
		claim.value = d.value.dispute.suggested_claim || "";
		assignee.value = d.value.header.assignee || "";
		note.value = line.value = parcel.value = outcome.value = formError.value = "";
	} catch (e) {
		d.value = null;
		error.value = e.message;
	}
	loading.value = false;
};
watch(() => state.drawer.name, load, { immediate: true });

const h = computed(() => d.value?.header);
const open = computed(() => d.value && d.value.header.status !== "Resolved");
const stageKind = (s) =>
	({ Open: "mis", "In review": "pend", Disputed: "info", Resolved: "ok" }[s] || "");
const lineOpts = computed(() =>
	(d.value?.candidate_lines || []).map((l) => ({
		value: l.name,
		label: `${l.awb} · ${l.batch} · row ${l.row} · ${rs(l.net)}`,
	}))
);
const parcelOpts = computed(() =>
	(d.value?.candidate_parcels || []).map((p) => ({
		value: p.name,
		label: `${p.name} · ${p.awb} · ${p.customer || "—"} · ${rs(p.amount)}`,
	}))
);
const userOpts = computed(() => [
	{ value: "", label: "Unassigned" },
	...(d.value?.assignable_users || []).map((u) => ({ value: u.name, label: u.label })),
]);
const matchByLine = computed(() => !!h.value?.order_id);

const LABELS = {
	raise_dispute: "Raise dispute",
	accept_deduction: "Accept deduction",
	match_line: "Match",
	resolve_manually: "Mark resolved",
};
const problem = computed(() => {
	if (!action.value) return "Choose how to resolve this";
	if (action.value === "raise_dispute" && !(Number(claim.value) > 0))
		return "Enter a claim amount above 0";
	if (action.value === "match_line" && !(matchByLine.value ? line.value : parcel.value))
		return matchByLine.value ? "Choose the settlement line" : "Choose the order";
	if (action.value === "resolve_manually" && !note.value.trim()) return "A note is required";
	return "";
});

const send = async (act, payload, msg) => {
	busy.value = act;
	formError.value = "";
	try {
		await api.resolve_exception(
			{ name: state.drawer.name, action: act, payload },
			{ silent: true }
		);
		toast(msg);
		refresh();
		return true;
	} catch (e) {
		formError.value = e.message;
		return false;
	} finally {
		busy.value = "";
	}
};
const submit = async () => {
	if (problem.value) return (formError.value = problem.value);
	const p = { note: note.value };
	if (action.value === "raise_dispute") p.claim_amount = Number(claim.value);
	if (action.value === "match_line")
		matchByLine.value ? (p.line = line.value) : (p.parcel = parcel.value);
	if (action.value === "resolve_manually" && outcome.value) p.dispute_outcome = outcome.value;
	if (await send(action.value, p, `${LABELS[action.value]}: done`)) closeDrawer();
};
const assign = async (u) => {
	assignee.value = u;
	if (await send("assign", { assignee: u }, u ? `Assigned to ${u}` : "Unassigned")) await load();
};
</script>

<template>
	<Drawer @close="closeDrawer">
		<template #head>
			<template v-if="h">
				<div class="muted" style="font-size: 12px">
					{{ h.name }} · opened {{ dShortTime(h.opened_on) }}
				</div>
				<h2>
					{{ h.type }}<template v-if="h.order_id"> · {{ h.order_id }}</template>
				</h2>
			</template>
			<h2 v-else>{{ state.drawer.name }}</h2>
		</template>

		<PageState :loading="loading" :error="error" @retry="load">
			<template v-if="d">
				<div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center">
					<Badge :kind="excKind(h.type)">{{ h.type }}</Badge>
					<Badge :kind="stageKind(h.stage)"
						>{{ h.stage
						}}<template v-if="h.stage !== 'Resolved'">
							· {{ h.age_days }} day{{ h.age_days === 1 ? "" : "s" }}</template
						></Badge
					>
					<span class="muted"
						>{{ h.courier || "No courier"
						}}<template v-if="h.batch">
							· <span class="mono">{{ h.batch }}</span></template
						></span
					>
				</div>
				<p v-if="h.detail" style="margin: 0">{{ h.detail }}</p>

				<div class="cmp">
					<div class="cmpc">
						<div class="l">Expected</div>
						<div class="v">{{ rs(d.expected) }}</div>
					</div>
					<div class="cmpc">
						<div class="l">Actual</div>
						<div class="v">{{ rs(d.actual) }}</div>
					</div>
					<div class="cmpc" :style="d.difference ? { background: '#fff0ec' } : null">
						<div class="l" :style="d.difference ? { color: '#b42318' } : null">
							Difference
						</div>
						<div class="v" :class="{ neg: d.difference < 0 }">
							{{ rs(d.difference) }}
						</div>
					</div>
				</div>

				<dl class="kvl">
					<template v-for="r in d.kv" :key="r.label"
						><dt>{{ r.label }}</dt>
						<dd :class="{ mono: r.mono, neg: r.bad }">{{ r.value }}</dd></template
					>
					<template v-if="d.dispute.status !== 'Not raised'"
						><dt>Dispute</dt>
						<dd>
							{{ d.dispute.status }} · claim {{ rs(d.dispute.claim_amount) }} ·
							{{ d.dispute.raised_on }}
						</dd></template
					>
				</dl>

				<!-- assign -->
				<div>
					<div class="muted" style="font-size: 12px; margin-bottom: 4px">ASSIGNEE</div>
					<SelectField
						:model-value="assignee"
						:options="userOpts"
						placeholder="Unassigned"
						:disabled="!open || busy === 'assign'"
						aria-label="Assignee"
						@update:model-value="assign"
					/>
				</div>

				<!-- resolution -->
				<template v-if="open">
					<div class="muted" style="font-size: 12px; letter-spacing: 0.06em">
						RESOLUTION
					</div>
					<label
						v-for="o in d.resolution_options"
						:key="o.key"
						:class="['opt', { on: action === o.key }]"
					>
						<input v-model="action" type="radio" name="resolution" :value="o.key" />
						<span
							><strong>{{ o.label }}</strong
							><small>{{ o.description }}</small></span
						>
					</label>

					<label
						v-if="action === 'raise_dispute'"
						style="display: flex; flex-direction: column; gap: 4px"
					>
						<span class="muted">Claim amount (₹)</span>
						<input
							v-model="claim"
							class="inpl"
							type="number"
							min="0"
							step="0.01"
							style="max-width: 200px"
							aria-label="Claim amount"
						/>
					</label>
					<div
						v-if="action === 'match_line'"
						style="display: flex; flex-direction: column; gap: 4px"
					>
						<span class="muted">{{
							matchByLine ? "Unmatched payout line" : "Order to match"
						}}</span>
						<SelectField
							v-if="matchByLine"
							v-model="line"
							:options="lineOpts"
							placeholder="Choose a line"
							aria-label="Settlement line"
							style="max-width: none"
						/>
						<SelectField
							v-else
							v-model="parcel"
							:options="parcelOpts"
							placeholder="Choose an order"
							aria-label="Order"
							style="max-width: none"
						/>
						<span
							v-if="(matchByLine ? lineOpts : parcelOpts).length === 0"
							class="muted"
							>Nothing to match against right now.</span
						>
					</div>
					<div
						v-if="
							action === 'resolve_manually' &&
							d.dispute.status === 'Raised with Courier'
						"
						style="display: flex; flex-direction: column; gap: 4px"
					>
						<span class="muted">Dispute outcome</span>
						<SelectField
							v-model="outcome"
							:options="['Resolved', 'Rejected']"
							placeholder="Leave as raised"
							aria-label="Dispute outcome"
						/>
					</div>
					<label style="display: flex; flex-direction: column; gap: 4px">
						<span class="muted"
							>Note<template v-if="action === 'resolve_manually'">
								(required)</template
							></span
						>
						<textarea
							v-model="note"
							class="inpl"
							rows="3"
							style="padding: 8px 10px; height: auto"
							placeholder="Add context for your team or the courier"
							aria-label="Note"
						></textarea>
					</label>
					<div v-if="formError" class="imp-banner err" role="alert">
						<strong>{{ formError }}</strong>
					</div>
				</template>
				<div v-else class="imp-banner warn">
					<strong>Resolved: {{ d.resolution || "closed" }}</strong>
					<span v-if="d.resolution_note">{{ d.resolution_note }}</span>
				</div>

				<!-- activity -->
				<div>
					<div
						class="muted"
						style="font-size: 12px; letter-spacing: 0.06em; margin-bottom: 4px"
					>
						ACTIVITY
					</div>
					<ul class="tl" style="padding: 0">
						<li v-for="(a, i) in d.activity" :key="i">
							<span
								:class="[
									'm',
									a.kind === 'done' ? 'g' : a.kind === 'open' ? 'o' : '',
								]"
							></span>
							<div>
								<strong>{{ a.title }}</strong>
								<div v-if="a.detail" class="muted pre-wrap">{{ a.detail }}</div>
							</div>
							<span class="w">{{ dShortTime(a.event_time) }}</span>
						</li>
					</ul>
				</div>
			</template>
		</PageState>

		<template #footer>
			<button class="btn" @click="closeDrawer">{{ open ? "Cancel" : "Close" }}</button>
			<button
				v-if="open && d"
				class="btn pri"
				:disabled="!!problem || !!busy"
				:title="problem"
				@click="submit"
			>
				<span v-if="busy && busy !== 'assign'" class="spin"></span
				>{{ LABELS[action] || "Resolve" }}
			</button>
		</template>
	</Drawer>
</template>
