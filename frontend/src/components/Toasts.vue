<script setup>
import { dismissToast, state } from "../store";
</script>
<template>
	<div class="toasts" aria-live="polite">
		<div v-for="t in state.toasts" :key="t.id" :class="['toast', { e: t.kind === 'e' }]">
			<span>{{ t.message }}</span>
			<component
				:is="t.action.to ? 'router-link' : 'button'"
				v-if="t.action"
				class="btn sm"
				:to="t.action.to"
				@click="dismissToast(t.id)"
				>{{ t.action.label }}</component
			>
		</div>
	</div>
</template>
