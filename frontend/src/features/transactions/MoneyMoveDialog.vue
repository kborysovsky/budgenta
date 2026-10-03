<script setup>
import AppIcon from '../../components/AppIcon.vue'
import { computed, nextTick, ref, watch } from 'vue'
import SearchSelect from '../../components/SearchSelect.vue'
import AmountInput from '../../components/AmountInput.vue'

const props = defineProps({ accounts: Array, api: Function })
const emit = defineEmits(['changed'])
const dialog = ref(null), mode = ref('transfer'), form = ref({}), review = ref(null)
const busy = ref(false), error = ref('')
const exchangeInput = ref('rate')
const today = () => new Date().toLocaleDateString('en-CA')
const source = computed(() => props.accounts.find(a => a.id === Number(form.value.source_id)))
const destination = computed(() => props.accounts.find(a => a.id === Number(form.value.destination_id)))
const destinations = computed(() => props.accounts.filter(a => a.id !== source.value?.id &&
  (mode.value === 'transfer' ? a.currency === source.value?.currency : a.currency !== source.value?.currency)))
const accountLabel = a => `${a.name} · ${a.currency}`
watch(() => form.value.source_id, () => { form.value.destination_id = ''; form.value.rate = ''; form.value.received = ''; review.value = null })
watch(() => form.value.destination_id, () => { form.value.rate = ''; form.value.received = ''; review.value = null })
watch(form, () => { review.value = null }, { deep: true })
watch(exchangeInput, () => { review.value = null; error.value = '' })

function open(action) {
  mode.value = action; error.value = ''; review.value = null
  exchangeInput.value = 'rate'
  form.value = { source_id: props.accounts[0]?.id, destination_id: '', amount: '', rate: '', received: '', date: today() }
  nextTick(() => dialog.value.showModal())
}
function close() { if (!busy.value) dialog.value.close() }
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const payload = { ...form.value }
    if (mode.value === 'transfer') { delete payload.rate; delete payload.received }
    else delete payload[exchangeInput.value === 'rate' ? 'received' : 'rate']
    if (!review.value) {
      review.value = mode.value === 'exchange'
        ? await props.api('/exchanges/preview', payload)
        : { source: source.value.name, destination: destination.value.name, source_currency: source.value.currency,
            destination_currency: destination.value.currency, amount: payload.amount, received: payload.amount, date: payload.date }
      return
    }
    await props.api(mode.value === 'exchange' ? '/exchanges' : '/transfers', payload)
    dialog.value.close(); emit('changed')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
defineExpose({ open })
</script>

<template>
  <dialog ref="dialog" @cancel="busy && $event.preventDefault()">
    <form @submit.prevent="submit">
      <div class="section-top"><h2>{{ mode === 'exchange' ? $t("Exchange currencies") : $t("Transfer between accounts") }}</h2><button type="button" class="close" :aria-label="$t(&quot;Close dialog&quot;)" :disabled="busy" @click="close"><AppIcon name="close" /></button></div>
      <p class="muted">{{ mode === 'exchange' ? $t("Record an exchange using your rate or the final amount received. Crypto, cash, cards, and savings can be exchanged with each other.") : $t("Move the same currency between your accounts, including savings.") }}</p>
      <fieldset :disabled="busy" v-if="!review">
        <label>{{ $t("From") }}<SearchSelect v-model="form.source_id" :options="accounts" value-key="id" :option-label="accountLabel" :label="$t(&quot;From&quot;)" :placeholder="$t(&quot;Choose an account&quot;)" required /></label>
        <p v-if="source" class="muted">{{ $t("Available:") }} {{ source.balance }} {{ source.currency }}</p>
        <label>{{ $t("To") }}<SearchSelect v-model="form.destination_id" :options="destinations" value-key="id" :option-label="accountLabel" :label="$t(&quot;To&quot;)" :placeholder="$t(&quot;Choose an account&quot;)" required /></label>
        <p v-if="!destinations.length" class="muted">{{ $t("Add") }} {{ mode === 'exchange' ? $t("a different currency") : $t("another account in this currency") }} {{ $t("on the Accounts page, or choose a different source.") }}</p>
        <AmountInput v-model="form.amount" :label="source ? $t(&quot;Amount to send ({v0})&quot;, { v0: source.currency }) : $t(&quot;Amount to send&quot;)" :account-id="form.source_id" :balance="source?.balance" />
        <template v-if="mode === 'exchange'">
          <div class="segmented" role="group" :aria-label="$t(&quot;Exchange input&quot;)"><button type="button" :class="{ selected: exchangeInput === 'rate' }" :aria-pressed="exchangeInput === 'rate'" @click="exchangeInput = 'rate'">{{ $t("Enter rate") }}</button><button type="button" :class="{ selected: exchangeInput === 'received' }" :aria-pressed="exchangeInput === 'received'" @click="exchangeInput = 'received'">{{ $t("Enter amount received") }}</button></div>
          <template v-if="exchangeInput === 'rate'">
            <label>{{ $t("Custom exchange rate") }}<input v-model="form.rate" type="number" min="0.000000000000000001" step="any" :placeholder="$t(&quot;Enter your actual rate&quot;)" required></label>
            <p class="muted" v-if="source && destination">1 {{ source.currency }} = {{ form.rate || '…' }} {{ destination.currency }}{{ $t(". Enter") }} {{ destination.currency }} {{ $t("received per 1") }} {{ source.currency }} {{ $t("sent.") }}</p>
            <p class="muted">{{ $t("The next step shows the exact received amount, rounded to the destination currency precision.") }}</p>
          </template>
          <template v-else>
            <label>{{ $t("Amount received") }}{{ destination ? ` (${destination.currency})` : '' }}<input v-model="form.received" type="number" min="0.00000001" step="any" :placeholder="$t(&quot;Final amount you received&quot;)" required></label>
            <p class="muted">{{ $t("The rate is calculated automatically on review: amount received ÷ amount sent. Your exact received amount is saved.") }}</p>
          </template>
        </template>
        <label>{{ $t("Date") }}<input v-model="form.date" type="date" :max="today()" required></label>
      </fieldset>
      <div v-else class="movement-review" aria-live="polite">
        <h3>{{ $t("Review") }} {{ $t(mode) }}</h3>
        <p><strong>{{ $t("From") }} {{ review.source }}</strong><br>−{{ review.amount }} {{ review.source_currency }}</p>
        <p><strong>{{ $t("To") }} {{ review.destination }}</strong><br>+{{ review.received }} {{ review.destination_currency }}</p>
        <p v-if="mode === 'exchange'">{{ review.rate_calculated ? $t("Calculated rate: ") : '' }}1 {{ review.source_currency }} {{ review.rate_approximate ? '≈' : '=' }} {{ review.rate }} {{ review.destination_currency }}</p>
        <p v-if="review.rate_approximate" class="muted">{{ $t("The displayed rate is rounded. The received amount above stays exact.") }}</p>
        <p>{{ review.date }}</p>
        <p class="muted">{{ $t("Both balances update together. This does not count as income or an expense. Deleting either entry reverses the whole operation.") }}</p>
      </div>
      <p v-if="error" class="error" role="alert">{{ $error(error) }}</p>
      <div class="form-actions"><button v-if="review" type="button" class="secondary" :disabled="busy" @click="review = null; error = ''"><AppIcon name="arrow-left" /> {{ $t("Edit") }}</button><button v-else type="button" class="secondary" :disabled="busy" @click="close">{{ $t("Cancel") }}</button><button class="primary" :disabled="busy || !source || !destination">{{ busy ? $t("Please wait…") : review ? $t("Confirm {v0}", { v0: $t(mode) }) : $t("Review {v0}", { v0: $t(mode) }) }} <AppIcon name="arrow-right" /></button></div>
    </form>
  </dialog>
</template>
