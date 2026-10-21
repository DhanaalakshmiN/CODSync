<script setup>
// Form select that matches the app's inputs (.inpl) and popups (.pop). No value is chosen until the user picks one.
// options = plain strings or [{ value, label }]
import { computed, ref } from "vue";
import { ChevronDown } from "lucide-vue-next";

const props = defineProps({
	modelValue: { type: String, default: "" },
	options: { type: Array, default: () => [] },
	placeholder: { type: String, default: "Choose" },
	disabled: Boolean,
	ariaLabel: String,
});
const emit = defineEmits(["update:modelValue"]);
const open = ref(false);
const opts = computed(() =>
	props.options.map((o) => (typeof o === "object" ? o : { value: o, label: o }))
);
const current = computed(() => opts.value.find((o) => o.value === props.modelValue));
const pick = (v) => {
	emit("update:modelValue", v);
	open.value = false;
};
</script>
<template>
	<span class="chipw selw" @keydown.esc="open = false">
		<button
			type="button"
			class="inpl selb"
			:disabled="disabled"
			:aria-label="ariaLabel"
			aria-haspopup="listbox"
			:aria-expanded="open"
			@click="open = !open"
		>
			<span :class="{ muted: !current }">{{ current ? current.label : placeholder }}</span>
			<ChevronDown :size="16" :stroke-width="1.6" />
		</button>
		<div v-if="open" class="pop selp" role="listbox" @mouseleave="open = false">
			<button
				v-for="o in opts"
				:key="o.value"
				role="option"
				:aria-selected="o.value === modelValue"
				@click="pick(o.value)"
			>
				{{ o.label }}
			</button>
			<div v-if="!opts.length" class="muted" style="padding: 8px 12px">
				Nothing to choose
			</div>
		</div>
	</span>
</template>
