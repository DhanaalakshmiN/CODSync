<script setup>
import { state } from "../store";
import Modal from "./Modal.vue";
</script>
<template>
	<Modal title="Connect courier" @close="state.connectModal.open = false"
		><p class="muted">Courier connection is coming in the next build.</p></Modal
	>
</template>
