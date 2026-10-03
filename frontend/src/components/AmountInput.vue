<script setup>
import { computed, ref, useId, watch } from 'vue'
import { allAmount } from '../utils/amounts.js'
const props = defineProps({ modelValue: [String, Number], label: String, balance: [String, Number], accountId: [String, Number], limit: [String, Number], showAll: { type: Boolean, default: true }, required: { type: Boolean, default: true }, disabled: Boolean, hint: { type: String, default: 'Use the full available balance of the selected account and currency' } })
const emit = defineEmits(['update:modelValue'])
const id = useId(), filledAll = ref(false)
const available = computed(() => allAmount(props.balance, props.limit))
function fillAll() { if (!available.value || props.disabled) return; filledAll.value = true; emit('update:modelValue', available.value) }
function input(event) { filledAll.value = false; emit('update:modelValue', event.target.value) }
watch([() => props.accountId, () => props.balance, () => props.limit, () => props.showAll], () => {
  if (filledAll.value) { filledAll.value = false; emit('update:modelValue', '') }
})
</script>
<template>
  <div class="amount-field">
    <label :for="id">{{ $t(label) }}</label>
    <div class="amount-input-row">
      <input :id="id" :aria-label="$t(label)" type="number" min="0.00000001" step="any" :max="limit" :value="modelValue" :required="required" :disabled="disabled" placeholder="0.00" @input="input">
      <button v-if="showAll" type="button" class="secondary" :disabled="disabled || !available" :title="available ? $t(hint) : $t(&quot;No positive balance available in this account and currency&quot;)" @click="fillAll">{{ $t("All") }}</button>
    </div>
  </div>
</template>
<style scoped>
.amount-field { margin: 14px 0; min-width: 0; }
.amount-field label { margin: 0 0 7px; }
.amount-input-row { display: flex; align-items: stretch; gap: 8px; }
.amount-input-row input { flex: 1; width: 100%; min-width: 0; }
.amount-input-row button { flex-shrink: 0; min-width: 52px; }
</style>
