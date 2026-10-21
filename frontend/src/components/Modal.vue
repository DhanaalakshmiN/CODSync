<script setup>
import { onBeforeUnmount, onMounted } from "vue";
import { X } from "lucide-vue-next";

defineProps({
	title: String,
	width: { type: String, default: "" },
	pg: { type: String, default: "" },
});
const emit = defineEmits(["close"]);
const onKey = (e) => e.key === "Escape" && emit("close");
onMounted(() => document.addEventListener("keydown", onKey));
onBeforeUnmount(() => document.removeEventListener("keydown", onKey));
</script>
<template>
	<div :class="['ov', pg]" role="dialog" aria-modal="true" @mousedown.self="emit('close')">
		<div class="modal" :style="width ? { width } : null">
			<div class="mh">
				<h2>
					<slot name="title">{{ title }}</slot>
				</h2>
				<button class="xbtn" aria-label="Close" @click="emit('close')">
					<X :size="18" :stroke-width="1.6" />
				</button>
			</div>
			<slot name="header" />
			<div class="mb"><slot /></div>
			<div v-if="$slots.footer" class="mf"><slot name="footer" /></div>
		</div>
	</div>
</template>
