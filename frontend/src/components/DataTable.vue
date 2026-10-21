<script setup>
// Generic table: columns = [{ key, label, num, width, cls }]; per-cell slot #cell-<key>="{ row, value }".
import { computed } from "vue";

const props = defineProps({
	columns: { type: Array, required: true },
	rows: { type: Array, default: () => [] },
	rowKey: { type: String, default: "id" },
	selectable: Boolean,
	selected: { type: Array, default: () => [] },
	clickable: Boolean,
	rowClass: Function,
});
const emit = defineEmits(["update:selected", "row-click"]);
const allOn = computed(
	() =>
		props.rows.length > 0 && props.rows.every((r) => props.selected.includes(r[props.rowKey]))
);
const toggleAll = (e) =>
	emit("update:selected", e.target.checked ? props.rows.map((r) => r[props.rowKey]) : []);
const toggle = (r, e) => {
	const k = r[props.rowKey];
	emit(
		"update:selected",
		e.target.checked ? [...props.selected, k] : props.selected.filter((x) => x !== k)
	);
};
</script>
<template>
	<div class="tw">
		<table>
			<thead>
				<tr>
					<th v-if="selectable" style="width: 32px">
						<input
							type="checkbox"
							aria-label="Select all"
							:checked="allOn"
							@change="toggleAll"
						/>
					</th>
					<th
						v-for="c in columns"
						:key="c.key"
						:class="{ num: c.num }"
						:style="c.width ? { width: c.width } : null"
					>
						{{ c.label }}
					</th>
				</tr>
			</thead>
			<tbody>
				<tr
					v-for="r in rows"
					:key="r[rowKey]"
					:class="[
						{ clk: clickable, sel: selectable && selected.includes(r[rowKey]) },
						rowClass ? rowClass(r) : '',
					]"
					@click="clickable && emit('row-click', r)"
				>
					<td v-if="selectable" @click.stop>
						<input
							type="checkbox"
							:aria-label="`Select ${r[rowKey]}`"
							:checked="selected.includes(r[rowKey])"
							@change="toggle(r, $event)"
						/>
					</td>
					<td v-for="c in columns" :key="c.key" :class="[{ num: c.num }, c.cls]">
						<slot :name="`cell-${c.key}`" :row="r" :value="r[c.key]">{{
							r[c.key]
						}}</slot>
					</td>
				</tr>
			</tbody>
		</table>
	</div>
</template>
