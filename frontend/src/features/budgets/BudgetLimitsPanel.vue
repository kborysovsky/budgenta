<script setup>
import { ref, watch, computed, nextTick } from 'vue'
import { t, categoryLabel } from '../../i18n.js'
import SearchSelect from '../../components/SearchSelect.vue'
import AppIcon from '../../components/AppIcon.vue'
import BudgetUsage from './BudgetUsage.vue'
const props = defineProps({ month: String, api: Function, currencies: Array, categories: Array })
const emit = defineEmits(['changed'])
const data = ref(null), settings = ref({ enabled: false, notifications_enabled: true }), busy = ref(false), loading = ref(false), error = ref(''), editing = ref(false), form = ref({}), editor = ref(null)
let request = 0
const choices = computed(() => [...new Set([...(props.categories || []), ...(data.value?.budgets || []).map(b => b.category)])])
async function load() {
  const current = ++request; loading.value = true
  try { const result = await props.api(`/budget-limits?month=${props.month}`); if (current === request) { data.value = result; settings.value = { ...result.settings } } }
  catch (e) { if (current === request) error.value = e.message }
  finally { if (current === request) loading.value = false }
}
watch(() => props.month, () => { editing.value = false; error.value = ''; load() }, { immediate: true })
async function run(task) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await task(); await load(); emit('changed') } catch (e) { error.value = e.message } finally { busy.value = false }
}
function open(row) {
  error.value = ''; editing.value = true
  form.value = row ? { ...row, all_currencies: row.expense_currencies === null, expense_currencies: [...(row.expense_currencies || [])] } : { id: null, category: '', amount: '', currency: 'USD', enabled: true, all_currencies: true, expense_currencies: [] }
  nextTick(() => { editor.value?.scrollIntoView({ behavior: 'smooth', block: 'center' }); editor.value?.querySelector('input')?.focus({ preventScroll: true }) })
}
async function save() {
  await run(async () => {
    if (!form.value.all_currencies && !form.value.expense_currencies.length) throw new Error('Choose at least one currency, without duplicates.')
    const payload = { category: form.value.category, amount: form.value.amount, currency: form.value.currency, enabled: form.value.enabled, expense_currencies: form.value.all_currencies ? null : form.value.expense_currencies }
    await props.api(form.value.id ? `/budget-limits/${form.value.id}/edit` : '/budget-limits', payload)
    editing.value = false
  })
}
async function remove() {
  if (!window.confirm(t('Remove this budget? Transactions and categories stay unchanged.'))) return
  await run(async () => { await props.api(`/budget-limits/${form.value.id}/delete`, {}); editing.value = false })
}
async function reset() {
  if (!window.confirm(t('Reset alerts for this month? Existing spending stays counted. A reached threshold may notify you again.'))) return
  await run(async () => { await props.api(`/budget-limits/${form.value.id}/reset-alerts`, {}); editing.value = false })
}
</script>
<template>
  <section>
    <p class="muted">{{ t('Set optional monthly category limits. Going over a limit is allowed and never blocks an expense.') }}</p>
    <form class="budget-settings report-settings" @submit.prevent="run(() => api('/budget-limits/settings', settings))">
      <fieldset :disabled="busy || loading"><label class="check-label"><input type="checkbox" v-model="settings.enabled">{{ t('Enable Budget Limits') }}</label><label class="check-label"><input type="checkbox" v-model="settings.notifications_enabled" :disabled="!settings.enabled">{{ t('Telegram threshold notifications') }}</label><p class="muted">{{ t('Alerts at 25%, 15%, 10%, 5%, and 0% remaining. If several thresholds are crossed together, one alert shows the most urgent level.') }}</p></fieldset><button class="secondary" :disabled="busy || loading">{{ t('Save settings') }}</button>
    </form>
    <p v-if="error" class="error" role="alert">{{ $error(error) }}</p>
    <p v-if="loading" class="muted" role="status">{{ t('Loading budgets…') }}</p>
    <template v-if="data">
      <p v-if="!data.settings.enabled" class="budget-notice">{{ t('Budget tracking is disabled. You can prepare limits now and enable the feature when ready.') }}</p>
      <div class="section-top budget-heading"><h2>{{ t('Monthly category budgets') }} · {{ month }}</h2><button class="primary" :disabled="busy || loading" @click="open()"><AppIcon name="plus" />{{ t('Add budget') }}</button></div>
      <form v-if="editing" ref="editor" class="savings-form budget-editor" @submit.prevent="save">
        <h3>{{ t(form.id ? 'Edit budget' : 'Add budget') }}</h3>
        <fieldset :disabled="busy || loading">
          <label>{{ t('Category') }}<SearchSelect v-model="form.category" :options="choices" :option-label="name => categoryLabel(name, 'expense')" :label="t('Budget category')" :placeholder="t('Choose a category or type your own purpose.')" allow-custom required :maxlength="60" /></label>
          <div class="form-row"><label>{{ t('Monthly limit') }}<input :aria-label="t('Monthly limit')" type="number" min="0.00000001" step="any" :value="form.amount" @input="form.amount = $event.target.value" placeholder="0.00" required></label><label>{{ t('Budget currency') }}<SearchSelect v-model="form.currency" :options="currencies" :label="t('Budget currency')" required /></label></div>
          <label class="check-label"><input type="checkbox" v-model="form.enabled">{{ t('Enable this budget') }}</label>
          <label class="check-label"><input type="checkbox" v-model="form.all_currencies">{{ t('Count expenses in all currencies') }}</label>
          <div v-if="!form.all_currencies" class="budget-currencies"><label v-for="currency in currencies" :key="currency" class="check-label"><input type="checkbox" :value="currency" v-model="form.expense_currencies">{{ currency }}</label></div>
          <p class="muted">{{ t('Included currencies share this one limit, using current exchange rates. Transfers, exchanges, and income do not count as spending.') }}</p>
          <p class="muted">{{ t('Limits repeat monthly. Editing a limit updates comparisons for past months too; transactions are never changed.') }}</p>
        </fieldset>
        <p v-if="error" class="error" role="alert">{{ $error(error) }}</p>
        <div class="form-actions"><button type="button" class="secondary" :disabled="busy" @click="editing = false">{{ t('Cancel') }}</button><button class="primary" :disabled="busy || loading">{{ t('Save budget') }}</button></div>
        <div v-if="form.id" class="budget-maintenance"><button type="button" class="text-button" :disabled="busy || !data.settings.enabled || !form.enabled || data.current_month !== month" @click="reset">{{ t('Reset this month’s alerts') }}</button><button type="button" class="text-button danger" :disabled="busy" @click="remove">{{ t('Remove budget') }}</button></div>
      </form>
      <BudgetUsage :data="data" :editable="!busy && !loading" @edit="open" />
      <p v-if="!data.budgets.length" class="empty">{{ t('No budget limits yet. Add a category to start tracking.') }}</p>
      <p class="muted">{{ t('All your accounts contribute, including archived accounts. Deleted expenses are excluded. Missing or stale rates pause threshold alerts.') }}</p>
      <p class="muted">{{ t('Budget details in reports are optional. Configure each report and the dashboard on the Reports page.') }}</p>
    </template>
  </section>
</template>
<style scoped>
.budget-settings { margin-top: 20px; }
.budget-settings fieldset { margin: 0 0 16px; }
.budget-heading { margin-top: 28px; gap: 16px; flex-wrap: wrap; }
.budget-heading h2 { font-size: 19px; }
.budget-notice { margin: 20px 0; padding: 16px; border-radius: 8px; background: #f2f4e9; font-size: 13px; }
.budget-currencies { display: flex; gap: 0 18px; flex-wrap: wrap; }
.budget-editor { margin: 20px 0; }
.budget-maintenance { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 18px; border-top: 1px solid #e4e7df; padding-top: 20px; margin-top: 20px; }
.budget-editor .muted { margin-top: 12px; line-height: 1.6; font-size: 12px; }
</style>
