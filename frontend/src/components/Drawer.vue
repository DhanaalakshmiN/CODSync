<script setup>
import { onBeforeUnmount, onMounted } from "vue";
import { X } from "lucide-vue-next";

defineProps({ pg: { type: String, default: "pg-exceptions" } });
const emit = defineEmits(["close"]);
const onKey = (e) => e.key === "Escape" && emit("close");
onMounted(() => document.addEventListener("keydown", onKey));
onBeforeUnmount(() => document.removeEventListener("keydown", onKey));
</script>
<template>
	<div :class="['ov', pg]" role="dialog" aria-modal="true" @mousedown.self="emit('close')">
		<aside class="drawer">
			<div class="dh">
				<div style="flex: 1 1 0%"><slot name="head" /></div>
				<button class="xbtn" aria-label="Close" @click="emit('close')">
					<X :size="18" :stroke-width="1.6" />
				</button>
			</div>
			<div class="db"><slot /></div>
			<div class="df"><slot name="footer" /></div>
		</aside>
	</div>
</template>
