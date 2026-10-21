<script setup>
import { state } from "../store";
import Modal from "./Modal.vue";
</script>
<template>
	<Modal title="Import settlement" @close="state.importModal.open = false"
		><p class="muted">The import wizard is coming in the next build.</p></Modal
	>
</template>
