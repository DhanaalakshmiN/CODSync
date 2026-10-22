<script setup>
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Check, TriangleAlert } from "lucide-vue-next";
import { api } from "../api";
import { dFull, dShortTime, dTime, deliveryKind, formatMoney, kg, reconKind, rs } from "../format";
import { refresh, state, toast } from "../store";
import Badge from "../components/Badge.vue";
import EmptyState from "../components/EmptyState.vue";
import Modal from "../components/Modal.vue";
import PageState from "../components/PageState.vue";

const route = useRoute();
const id = computed(() => route.params.id);
const d = ref(null);
const loading = ref(true);
const error = ref("");
const busy = ref("");
const noteOpen = ref(false);
const noteText = ref("");

const load = async () => {
	loading.value = !d.value || d.value.header.order_id !== id.value;
	error.value = "";
	try {
		d.value = await api.order_detail({ order_id: id.value }, { silent: true });
	} catch (e) {
		d.value = null;
		error.value = e.message;
	}
	loading.value = false;
};
watch([id, () => state.tick], load, { immediate: true });

const can = (a) => !!d.value?.actions.includes(a);
const h = computed(() => d.value?.header);
const s = computed(() => d.value?.settlement);
const diffBad = computed(
	() => s.value && Math.abs(s.value.difference || 0) > (state.boot?.tolerance ?? 1)
);

const run = async (key, fn, msg) => {
	busy.value = key;
	try {
		await fn();
		toast(msg);
		refresh();
	} catch (e) {
		/* api.js already toasted */
	}
	busy.value = "";
};
const dispute = () =>
	run("dispute", () => api.raise_dispute({ order_id: id.value }), "Dispute raised");
const resolve = () =>
	run("resolve", () => api.resolve_order({ order_id: id.value }), "Marked resolved");
const saveNote = async () => {
	if (!noteText.value.trim()) return;
	await run(
		"note",
		() => api.add_note({ order_id: id.value, text: noteText.value }),
		"Note added"
	);
	noteText.value = "";
	noteOpen.value = false;
};

const activity = computed(() => [...(d.value?.activity || [])].reverse());
const dot = (k) => (k === "done" ? "g" : k === "warn" ? "o" : "");
const cell = (v) => (v === null || v === undefined ? "—" : rs(v));
</script>

<template>
	<div class="wrap">
		<div class="crumb">
			<router-link to="/orders">Orders</router-link> / <span>{{ id }}</span>
		</div>
		<PageState :loading="loading" :error="error" @retry="load">
			<template v-if="d">
				<div class="ph pg-detail">
					<h1>{{ h.order_id }}</h1>
					<Badge nd :out="h.badges.payment_mode === 'COD'">{{
						h.badges.payment_mode
					}}</Badge>
					<Badge :kind="deliveryKind(h.badges.delivery_status)">{{
						h.badges.delivery_status
					}}</Badge>
					<Badge
						v-if="h.badges.reconciliation_status"
						:kind="reconKind(h.badges.reconciliation_status)"
						>{{ h.badges.reconciliation_status }}</Badge
					>
					<span class="muted">{{ dTime(h.placed_at) }} · {{ h.channel }}</span>
					<div class="acts">
						<a
							v-if="h.order_url"
							class="btn"
							:href="h.order_url"
							target="_blank"
							rel="noopener"
							>Open in Shopify</a
						>
						<button
							v-else
							class="btn"
							disabled
							title="No platform link for this order"
						>
							Open in Shopify
						</button>
						<button
							class="btn"
							:disabled="!can('raise_dispute') || busy === 'dispute'"
							@click="dispute"
						>
							Raise dispute
						</button>
						<button
							class="btn pri"
							:disabled="!can('resolve_exception') || busy === 'resolve'"
							@click="resolve"
						>
							Mark resolved
						</button>
					</div>
				</div>

				<section class="card">
					<div class="ch"><h2>COD journey</h2></div>
					<div class="steps">
						<div
							v-for="st in d.journey"
							:key="st.key"
							:class="['stp', { warn: st.state === 'warn' }]"
							:style="st.state === 'pending' ? { borderTopColor: '#c9cdd3' } : null"
						>
							<div class="t">
								<Check
									v-if="st.state === 'done'"
									:size="14"
									:stroke-width="2"
									color="#1f9d73"
								/>
								<TriangleAlert
									v-else-if="st.state === 'warn'"
									:size="14"
									:stroke-width="2"
									color="#e8743b"
								/>
								{{ st.title }}
							</div>
							<div
								v-for="(l, i) in st.lines"
								:key="i"
								:class="['d', { neg: st.state === 'warn' && i === 0 }]"
								v-show="l"
							>
								{{ l }}
							</div>
						</div>
					</div>
				</section>

				<div style="display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-start">
					<div class="colm">
						<section class="card">
							<div class="ch"><h2>Expected vs actual settlement</h2></div>
							<div class="cb">
								<EmptyState
									v-if="!s"
									title="Nothing to settle"
									text="Prepaid orders are not reconciled."
								/>
								<template v-else>
									<div class="cmp">
										<div class="cmpc">
											<div class="l">Expected settlement</div>
											<div class="v">{{ rs(s.expected) }}</div>
										</div>
										<div class="cmpc">
											<div class="l">Actual settlement</div>
											<div class="v">
												{{ s.actual === null ? "Awaiting" : rs(s.actual) }}
											</div>
										</div>
										<div
											class="cmpc"
											:style="
												diffBad
													? {
															background: '#fff0ec',
															boxShadow: 'inset 0 0 0 1px #f3b9a8',
													  }
													: null
											"
										>
											<div
												class="l"
												:style="diffBad ? { color: '#b42318' } : null"
											>
												Difference
											</div>
											<div class="v" :class="{ neg: diffBad }">
												{{
													s.difference === null ? "—" : rs(s.difference)
												}}
											</div>
										</div>
									</div>
									<div
										class="tw"
										style="
											margin-top: 12px;
											border: 1px solid #e3e5e8;
											border-radius: 10px;
										"
									>
										<table>
											<thead>
												<tr>
													<th>Line</th>
													<th class="num">Expected</th>
													<th class="num">Actual</th>
													<th class="num">Difference</th>
												</tr>
											</thead>
											<tbody>
												<tr
													v-for="(l, i) in s.lines"
													:key="i"
													:style="
														l.unexpected
															? { background: '#fff5f2' }
															: null
													"
												>
													<td
														:style="
															i === s.lines.length - 1
																? { fontWeight: 600 }
																: null
														"
													>
														<strong v-if="l.unexpected">{{
															l.label
														}}</strong
														><template v-else>{{ l.label }}</template>
														<span
															v-if="
																l.note &&
																!l.unexpected &&
																i < s.lines.length - 1
															"
															class="muted"
														>
															({{ l.note }})</span
														>
														<Badge
															v-if="l.unexpected"
															kind="mis"
															style="margin-left: 6px"
															>Unexpected</Badge
														>
													</td>
													<td class="num">
														{{
															l.expected === 0 && l.unexpected
																? "—"
																: cell(l.expected)
														}}
													</td>
													<td class="num">{{ cell(l.actual) }}</td>
													<td
														:class="[
															'num',
															{ neg: (l.difference || 0) < 0 },
														]"
													>
														{{ cell(l.difference) }}
													</td>
												</tr>
											</tbody>
										</table>
									</div>
									<div
										v-if="d.weight_callout"
										class="two"
										style="
											margin-top: 12px;
											padding: 12px 14px;
											border: 1px solid #f0d98c;
											background: #fff9e6;
											border-radius: 10px;
											grid-template-columns: 1fr auto;
											align-items: center;
										"
									>
										<div>
											<TriangleAlert
												:size="14"
												style="vertical-align: -2px"
											/>
											{{ d.weight_callout.text }}
										</div>
										<button
											class="btn sm"
											:disabled="!can('raise_dispute') || busy === 'dispute'"
											@click="dispute"
										>
											Raise weight dispute
										</button>
									</div>
								</template>
							</div>
						</section>

						<section class="card">
							<div class="ch">
								<h2>Activity</h2>
								<button
									class="btn link mr"
									:disabled="!can('add_note')"
									@click="noteOpen = true"
								>
									Add note
								</button>
							</div>
							<EmptyState
								v-if="!activity.length"
								title="No activity yet"
								text="Events appear here as the order moves."
							/>
							<ul v-else class="tl">
								<li v-for="(a, i) in activity" :key="i">
									<span :class="['m', dot(a.kind)]"></span>
									<div>
										<strong>{{ a.title }}</strong>
										<div v-if="a.detail" class="muted pre-wrap">
											{{ a.detail }}
										</div>
									</div>
									<span class="w">{{ dShortTime(a.event_time) }}</span>
								</li>
							</ul>
						</section>
					</div>

					<section v-if="h.order_currency && h.order_currency !== 'INR'" class="card">
						<div class="ch"><h2>Currency</h2></div>
						<div class="cb">
							<dl class="kvl">
								<dt>Original amount</dt>
								<dd>{{ formatMoney(h.original_amount, h.order_currency) }}</dd>
								<dt>Exchange rate</dt>
								<dd>
									{{ h.exchange_rate }}
									<Badge
										v-if="['Fallback', 'Manual'].includes(h.rate_source)"
										:kind="h.rate_source === 'Fallback' ? 'pend' : ''"
										nd
										>{{ h.rate_source }}</Badge
									>
								</dd>
								<dt>COD (INR)</dt>
								<dd>{{ rs(h.amount) }}</dd>
							</dl>
						</div>
					</section>

					<div class="cols2">
						<section class="card">
							<div class="ch"><h2>Customer</h2></div>
							<div class="cb">
								<div>
									<strong>{{ d.customer.name || "—" }}</strong>
								</div>
								<div class="muted">{{ d.customer.phone || "No phone" }}</div>
								<div class="muted">{{ d.customer.address || "No address" }}</div>
							</div>
						</section>
						<section class="card">
							<div class="ch"><h2>Shipment</h2></div>
							<div class="cb">
								<dl v-if="d.shipment.awb || d.shipment.courier" class="kvl">
									<dt>Courier</dt>
									<dd>{{ d.shipment.courier || "—" }}</dd>
									<dt>AWB</dt>
									<dd class="mono">{{ d.shipment.awb || "—" }}</dd>
									<dt>Declared weight</dt>
									<dd>{{ kg(d.shipment.declared_weight) }}</dd>
									<dt>Charged weight</dt>
									<dd
										:class="{
											neg:
												d.shipment.charged_weight >
												d.shipment.declared_weight,
										}"
									>
										{{ kg(d.shipment.charged_weight) }}
									</dd>
									<dt>Delivery</dt>
									<dd>
										<Badge :kind="deliveryKind(d.shipment.delivery_status)">{{
											d.shipment.delivery_status
										}}</Badge>
									</dd>
								</dl>
								<span v-else class="muted">Not shipped yet.</span>
							</div>
						</section>
						<section class="card">
							<div class="ch">
								<h2>Settlement</h2>
								<router-link
									v-if="d.settlement_card"
									class="btn link mr"
									:to="`/settlements/${encodeURIComponent(
										d.settlement_card.batch
									)}`"
									>View batch</router-link
								>
							</div>
							<div class="cb">
								<dl v-if="d.settlement_card" class="kvl">
									<dt>Batch</dt>
									<dd class="mono">{{ d.settlement_card.batch }}</dd>
									<dt>Settled on</dt>
									<dd>{{ dFull(d.settlement_card.settled_on) }}</dd>
									<dt>UTR</dt>
									<dd class="mono">{{ d.settlement_card.utr || "—" }}</dd>
									<dt>Source</dt>
									<dd>{{ d.settlement_card.source }}</dd>
									<dt>Status</dt>
									<dd>
										<Badge :kind="reconKind(d.settlement_card.status)">{{
											d.settlement_card.status
										}}</Badge>
									</dd>
								</dl>
								<span v-else class="muted">Not settled yet.</span>
							</div>
						</section>
					</div>
				</div>
			</template>
		</PageState>

		<Modal v-if="noteOpen" title="Add note" width="480px" @close="noteOpen = false">
			<textarea
				v-model="noteText"
				class="inpl"
				rows="4"
				style="padding: 8px 10px"
				placeholder="Write a note for this order"
				aria-label="Note"
			></textarea>
			<template #footer>
				<button class="btn" @click="noteOpen = false">Cancel</button>
				<button
					class="btn pri"
					:disabled="!noteText.trim() || busy === 'note'"
					@click="saveNote"
				>
					Save note
				</button>
			</template>
		</Modal>
	</div>
</template>
