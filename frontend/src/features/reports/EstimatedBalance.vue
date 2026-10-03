<script setup>
import { numberLocale } from '../../i18n.js'
import { computed, ref, useId } from 'vue'
import AppIcon from '../../components/AppIcon.vue'
import SearchSelect from '../../components/SearchSelect.vue'

const props = defineProps({ balance: Object, loading: Boolean, settings: Object, currencies: Array, api: Function })
const emit = defineEmits(['refresh', 'changed', 'reports'])
const id = useId(), configuring = ref(false), draft = ref('USD'), saving = ref(false), error = ref('')
const currency = computed(() => props.settings.main_currency || 'USD')
const pending = computed(() => props.loading && (!props.balance || props.balance.currency !== currency.value))
const displayQuotes = computed(() => props.balance?.display_quotes || [])
const amount = computed(() => {
  if (pending.value) return 'Fetching exchange rates…'
  if (!props.balance || props.balance.unavailable || props.balance.currency !== currency.value || props.balance.total == null) return 'Estimate temporarily unavailable'
  const precision = ['BTC', 'ETH'].includes(currency.value) ? 8 : ['USDT', 'TRX'].includes(currency.value) ? 6 : 2
  return `${new Intl.NumberFormat(numberLocale.value, { minimumFractionDigits: 2, maximumFractionDigits: precision }).format(Number(props.balance.total))} ${currency.value}`
})
function configure() { draft.value = currency.value; error.value = ''; configuring.value = !configuring.value }
async function save() {
  saving.value = true; error.value = ''
  try {
    await props.api('/preferences/main-currency', { currency: draft.value })
    configuring.value = false; emit('changed')
  } catch (e) { error.value = e.message }
  finally { saving.value = false }
}
</script>

<template>
  <section class="usd-summary estimated-balance" :aria-label="$t(&quot;Estimated balance&quot;)">
    <div class="estimate-content">
      <span class="eyebrow">{{ $t("ESTIMATED BALANCE IN") }} {{ currency }}</span>
      <h2>{{ $t(amount) }} <span v-if="balance && !pending && !balance.complete && !balance.unavailable" class="pill">{{ $t("Partial total") }}</span></h2>
      <p class="muted">{{ settings.dashboard?.include_savings ? $t("Savings included.") : $t("Savings excluded.") }} <button class="text-button" @click="$emit('reports')">{{ $t("Report & dashboard settings") }}</button></p>
      <p class="muted">{{ $t("ARS uses the blue-dollar selling rate. UAH uses the official NBU rate. Separate debt records are not deducted.") }}</p>
      <p v-if="!pending && balance?.missing?.length" class="rate-warning">{{ $t("Rates unavailable:") }} {{ balance.missing.join(', ') }}. {{ balance.unavailable ? $t("The converted total cannot be calculated.") : $t("Unpriced balances are excluded from this partial total.") }}</p>
      <p v-if="!pending && balance?.stale" class="rate-warning">{{ $t("Cached rates: a provider is unavailable.") }}</p>
    </div>
    <div class="estimate-actions">
      <button class="secondary" :disabled="loading || saving" @click="$emit('refresh')">{{ loading ? $t("Refreshing…") : $t("Refresh rates") }}</button>
      <button class="settings-button" :aria-label="$t(&quot;Estimated balance settings&quot;)" :title="$t(&quot;Estimated balance settings&quot;)" :aria-expanded="configuring" :aria-controls="id" :disabled="saving" @click="configure"><AppIcon name="settings" /></button>
    </div>
    <form v-if="configuring" :id="id" class="estimate-settings" @submit.prevent="save">
      <h3>{{ $t("Estimated balance settings") }}</h3>
      <p class="muted">{{ $t("Choose the main currency for the dashboard estimate and all Telegram report totals. Accounts and transactions keep their original currencies.") }}</p>
      <fieldset :disabled="saving"><label>{{ $t("Main currency") }}<SearchSelect v-model="draft" :options="currencies" :label="$t(&quot;Main currency&quot;)" required /></label></fieldset>
      <p class="muted">{{ $t("Rates update automatically. UAH uses the National Bank of Ukraine's official exchange rate.") }}</p>
      <p v-if="error" class="error" role="alert">{{ $error(error) }}</p>
      <div class="form-actions"><button type="button" class="secondary" :disabled="saving" @click="configuring = false">{{ $t("Cancel") }}</button><button class="primary" :disabled="saving">{{ saving ? $t("Saving…") : $t("Save currency") }}</button></div>
    </form>
    <details v-if="!pending && settings.dashboard?.include_rates !== false && (displayQuotes.length || balance?.unavailable_reference_rates?.length)">
      <summary>{{ $t("Exchange rates & sources") }}</summary><p v-for="q in displayQuotes" :key="q.currency">{{ $quote(q) }} · <a :href="q.url" target="_blank" rel="noopener noreferrer">{{ $t(q.source) }}</a> · {{ q.as_of }}{{ q.stale ? $t(" (cached)") : '' }}</p>
      <p v-if="balance?.unavailable_reference_rates?.length" class="rate-warning">{{ $t("Reference rates temporarily unavailable:") }} {{ balance.unavailable_reference_rates.join(', ') }}.</p>
      <small>{{ $t("Estimate only; quotes may reflect the last trading day. Cross-currency estimates use these USD reference rates.") }}</small>
    </details>
  </section>
</template>

<style scoped>
.estimate-content { flex: 1; min-width: 0; }
.estimate-content h2 { overflow-wrap: anywhere; }
.estimate-actions { display: flex; align-items: center; align-self: flex-start; gap: 10px; }
.estimate-actions .settings-button { width: 42px; height: 42px; flex-shrink: 0; }
.estimate-settings { width: 100%; padding: 20px; border: 1px solid #dce6d2; border-radius: 9px; background: #fff; }
.estimate-settings p { margin-top: 8px; }
.estimate-settings fieldset { margin: 0; max-width: 320px; }
@media (max-width: 600px) { .estimate-content { flex-basis: 100%; } .estimate-settings { padding: 16px; } }
</style>
