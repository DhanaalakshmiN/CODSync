<script setup>
// Dashed chip -> solid ".chip.set" with "Label: value" and an x once a value is chosen.
// options = [{ value, label }] or plain strings
import { computed, ref } from "vue";
import { X } from "lucide-vue-next";

const props = defineProps({
	label: String,
	modelValue: { type: [String, Number], default: "" },
	options: Array,
});
const emit = defineEmits(["update:modelValue"]);
const open = ref(false);
const opts = computed(() =>
	(props.options || []).map((o) => (typeof o === "object" ? o : { value: o, label: o }))
);
const current = computed(() =>
	opts.value.find((o) => String(o.value) === String(props.modelValue))
);
const pick = (v) => {
	emit("update:modelValue", v);
	open.value = false;
};
</script>
<template>
	<span class="chipw" @keydown.esc="open = false">
		<button
			v-if="modelValue === '' || modelValue === null || modelValue === undefined"
			class="chip"
			@click="open = !open"
		>
			{{ label }} +
		</button>
		<button v-else class="chip set" @click="open = !open">
			{{ label }}: {{ current ? current.label : modelValue }}
			<X :size="12" :stroke-width="2" @click.stop="pick('')" />
		</button>
		<div v-if="open" class="pop" @mouseleave="open = false">
			<button v-for="o in opts" :key="o.value" @click="pick(o.value)">{{ o.label }}</button>
		</div>
	</span>
</template>
