<script setup>
// .b with kind ok / pend / mis / exc / info, or "" for the neutral grey badge; nd = no dot
defineProps({ kind: { type: String, default: "" }, nd: Boolean, out: Boolean });
</script>
<template>
	<span :class="['b', kind, { nd, out }]"><slot /></span>
</template>
