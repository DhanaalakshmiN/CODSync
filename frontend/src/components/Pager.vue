<script setup>
// .tfoot: "Showing 1–12 of N <noun>" with prev / next
import { computed } from "vue";
import { num } from "../format";

const props = defineProps({
	page: Number,
	pageSize: Number,
	total: Number,
	noun: { type: String, default: "orders" },
});
const emit = defineEmits(["update:page"]);
const from = computed(() => (props.total ? (props.page - 1) * props.pageSize + 1 : 0));
const to = computed(() => Math.min(props.page * props.pageSize, props.total));
const last = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
</script>
<template>
	<div class="tfoot">
		<span>Showing {{ num(from) }}–{{ num(to) }} of {{ num(total) }} {{ noun }}</span>
		<slot />
		<div class="acts">
			<button
				class="btn sm"
				:disabled="page <= 1"
				aria-label="Previous page"
				@click="emit('update:page', page - 1)"
			>
				‹
			</button>
			<button
				class="btn sm"
				:disabled="page >= last"
				aria-label="Next page"
				@click="emit('update:page', page + 1)"
			>
				›
			</button>
		</div>
	</div>
</template>
