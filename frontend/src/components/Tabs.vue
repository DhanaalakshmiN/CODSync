<script setup>
// Tabs with counts: tabs = [{ key, label, count, red }]
defineProps({ tabs: { type: Array, required: true }, modelValue: String });
defineEmits(["update:modelValue"]);
</script>
<template>
	<div class="tabs" role="tablist">
		<button
			v-for="t in tabs"
			:key="t.key"
			:class="['tab', { on: modelValue === t.key }]"
			role="tab"
			:aria-selected="modelValue === t.key"
			@click="$emit('update:modelValue', t.key)"
		>
			{{ t.label
			}}<span
				v-if="t.count !== undefined && t.count !== null"
				:class="['tc', { r: t.red }]"
				>{{ t.count.toLocaleString("en-IN") }}</span
			>
		</button>
	</div>
</template>
