<script setup>
// Loading skeleton for tables (design "Loading · table")
defineProps({ rows: { type: Number, default: 5 } });
const w = ["100%", "80%", "70%", "100%", "60%", "85%"];
</script>
<template>
	<div aria-busy="true" aria-label="Loading">
		<div v-for="i in rows" :key="i" class="skr">
			<span
				v-for="(x, j) in w"
				:key="j"
				class="sk"
				:style="{ width: w[(i + j) % w.length] }"
			></span>
		</div>
	</div>
</template>
