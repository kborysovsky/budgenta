<script setup>
import { computed, ref, useId, nextTick, watch } from 'vue'
const props = defineProps({ modelValue: [String, Number], options: { type: Array, default: () => [] }, label: String, placeholder: { type: String, default: 'Choose an option' }, valueKey: { type: String, default: 'value' }, optionLabel: Function, allowCustom: Boolean, required: Boolean, disabled: Boolean, maxlength: Number })
const emit = defineEmits(['update:modelValue', 'change'])
const id = useId(), input = ref(null), opened = ref(false), query = ref(''), active = ref(-1)
const rows = computed(() => props.options.map(option => ({ value: typeof option === 'object' ? option[props.valueKey] : option, label: String(props.optionLabel ? props.optionLabel(option) : typeof option === 'object' ? option.label : option) })))
const chosen = computed(() => rows.value.find(row => row.value === props.modelValue))
const hasValue = computed(() => props.modelValue !== '' && props.modelValue !== undefined && props.modelValue !== null)
const hint = computed(() => chosen.value?.label || (hasValue.value && props.allowCustom ? props.modelValue : props.placeholder))
const filtered = computed(() => rows.value.filter(row => row.label.toLocaleLowerCase().includes(query.value.toLocaleLowerCase())))
watch([() => props.modelValue, () => props.required, query], () => {
  input.value?.setCustomValidity(props.required && !hasValue.value && !props.allowCustom ? 'Choose an option from the list.' : '')
}, { flush: 'post' })
function open() { if (!props.disabled && !opened.value) { query.value = ''; active.value = -1; opened.value = true } }
function changeQuery(event) { query.value = event.target.value; opened.value = true; active.value = -1; if (props.allowCustom) emit('update:modelValue', query.value) }
function choose(row) { emit('update:modelValue', row.value); emit('change', row.value); opened.value = false; query.value = ''; active.value = -1 }
function blur() { opened.value = false; query.value = ''; active.value = -1 }
function keydown(event) {
  if (event.key === 'Escape' && opened.value) { event.preventDefault(); event.stopPropagation(); blur(); return }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault(); open()
    const count = filtered.value.length
    if (!count) return
    active.value = (active.value + (event.key === 'ArrowDown' ? 1 : active.value < 0 ? 0 : -1) + count) % count
    nextTick(() => document.getElementById(`${id}-${active.value}`)?.scrollIntoView({ block: 'nearest' }))
  } else if (event.key === 'Enter' && opened.value) {
    event.preventDefault()
    if (active.value >= 0 && filtered.value[active.value]) choose(filtered.value[active.value])
    else if (props.allowCustom && query.value.trim()) choose({ value: query.value.trim() })
    else if (filtered.value.length === 1) choose(filtered.value[0])
  }
}
</script>
<template>
  <div class="search-select">
    <input ref="input" type="text" role="combobox" :aria-label="label" aria-autocomplete="list" aria-haspopup="listbox" :aria-expanded="opened" :aria-controls="`${id}-options`" :aria-activedescendant="opened && active >= 0 ? `${id}-${active}` : undefined" :aria-required="required" :placeholder="hint" :value="query" :required="required && !hasValue" :disabled="disabled" :maxlength="maxlength" autocomplete="off" @focus="open" @click="open" @input="changeQuery" @blur="blur" @keydown="keydown">
    <span class="select-chevron" aria-hidden="true">⌄</span>
    <ul v-if="opened" :id="`${id}-options`" role="listbox" :aria-label="`${label} options`" class="select-options">
      <!-- Keep focus until click: iOS can still blur after a canceled pointerdown.
           Cancel mousedown instead, leaving touch scrolling uninterrupted. -->
      <li v-for="(row, index) in filtered" :id="`${id}-${index}`" :key="row.value" role="option" :aria-selected="row.value === modelValue" :class="{ highlighted: index === active }" @mousedown.prevent @click.prevent="choose(row)">{{ row.label }}<span v-if="row.value === modelValue" aria-hidden="true">✓</span></li>
      <li v-if="!filtered.length" class="select-empty" role="presentation">{{ allowCustom ? 'Custom value — type your own or choose another.' : 'No matching options.' }}</li>
    </ul>
  </div>
</template>
