<script setup>
// "Deduction patterns" card: repeating unexplained deductions mined by the backend.
// Clicking a row tells the page (select) which parcels to filter its table to.
import { ref, watch } from "vue";
import { ScanSearch } from "lucide-vue-next";
import { api } from "../api";
import { num, rs } from "../format";
import Badge from "./Badge.vue";
import EmptyState from "./EmptyState.vue";
import PageState from "./PageState.vue";

const props = defineProps({ courier: { type: String, default: "" } });
const emit = defineEmits(["select"]);

const rows = ref(null);
const loading = ref(true);
const error = ref("");

const load = async () => {
	loading.value = !rows.value;
	error.value = "";
	try {
		rows.value = await api.deduction_patterns(
			{ courier: props.courier || null },
			{ silent: true }
		);
	} catch (e) {
		error.value = e.message;
	}
	loading.value = false;
};
watch(() => props.courier, load);
load();

const pct = (c) => `${Math.round(c * 100)}% consistent`;
</script>

<template>
	<PageState :loading="loading" :error="error" @retry="load">
		<section class="card">
			<div class="ch">
				<h2>Deduction patterns</h2>
				<Badge v-if="rows && rows.length" nd>{{ num(rows.length) }}</Badge>
			</div>
			<EmptyState
				v-if="rows && !rows.length"
				title="No repeating deductions found"
				text="Deductions that repeat across parcels of the same kind will show up here."
			>
				<template #icon><ScanSearch :size="20" :stroke-width="1.6" /></template>
			</EmptyState>
			<ul v-else-if="rows" class="pats">
				<li v-for="p in rows" :key="`${p.courier}-${p.feature}-${p.value}`">
					<button
						class="pat"
						:title="`Show the ${p.count} parcels behind this pattern`"
						@click="emit('select', p)"
					>
						<span class="sum">{{ p.summary }}</span>
						<span class="meta">
							<span class="tot" :class="{ neg: p.total < 0 }">{{
								rs(p.total)
							}}</span>
							<span class="muted">{{ num(p.count) }} parcels</span>
							<Badge :kind="p.consistency >= 0.9 ? 'ok' : 'info'" nd>{{
								pct(p.consistency)
							}}</Badge>
						</span>
					</button>
				</li>
			</ul>
		</section>
	</PageState>
</template>

<style scoped>
.pats {
	list-style: none;
	margin: 0;
	padding: 4px 0 8px;
}
.pat {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	width: 100%;
	padding: 10px 16px;
	border: 0;
	border-top: 1px solid rgb(238, 240, 242);
	background: none;
	font: inherit;
	color: inherit;
	text-align: left;
	cursor: pointer;
}
.pat:hover {
	background: rgb(249, 250, 251);
}
.pat .sum {
	flex: 1 1 auto;
	min-width: 0;
}
.pat .meta {
	display: flex;
	align-items: center;
	gap: 10px;
	flex-shrink: 0;
	font-size: 12px;
}
.pat .tot {
	font-weight: 600;
}
@media (max-width: 767px) {
	.pat {
		flex-direction: column;
		align-items: flex-start;
	}
}
</style>
