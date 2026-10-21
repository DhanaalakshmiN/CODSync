<script setup>
// Wraps page content: skeleton while loading, error state with Retry, else the slot.
import SkTable from "./SkTable.vue";

defineProps({ loading: Boolean, error: String });
defineEmits(["retry"]);
</script>
<template>
	<section v-if="loading" class="card"><SkTable :rows="6" /></section>
	<section v-else-if="error" class="card">
		<div class="err-state">
			<strong>Could not load this page</strong>
			<span class="muted">{{ error }}</span>
			<button class="btn" @click="$emit('retry')">Retry</button>
		</div>
	</section>
	<slot v-else />
</template>
