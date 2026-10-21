<script setup>
// .empty with illustration tile; tone="ok" paints the tile green
defineProps({ title: String, text: String, tone: String });
</script>
<template>
	<div class="empty">
		<span
			class="ill"
			:style="tone === 'ok' ? { background: '#e4f5ec', color: '#0c5b3f' } : null"
			><slot name="icon"
		/></span>
		<h3>{{ title }}</h3>
		<p v-if="text">{{ text }}</p>
		<div style="display: flex; gap: 8px"><slot /></div>
	</div>
</template>
