<script setup>
import AppIcon from '../../components/AppIcon.vue'
import SearchSelect from '../../components/SearchSelect.vue'
import { activityRows, activeTotals, activityAmount } from '../../utils/activity.js'
import { ref, watch } from 'vue'
const props = defineProps({ report: Object, settings: Object, groups: Array, currencies: Array, api: Function })
const emit = defineEmits(['changed', 'close-month'])
const busy = ref(false), error = ref(''), saved = ref(''), preview = ref(''), selected = ref('current_state'), draft = ref(null)
const tabs = { current_state: 'Current state', daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly', dashboard: 'Dashboard' }
const timezones = [...new Set(['America/Argentina/Buenos_Aires', 'America/New_York', 'Europe/London', 'Europe/Kyiv', 'UTC', ...(Intl.supportedValuesOf ? Intl.supportedValuesOf('timeZone') : [])])].sort()
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
watch(() => props.settings, value => { draft.value = JSON.parse(JSON.stringify(value)) }, { immediate: true, deep: true })
async function save() {
  busy.value = true; error.value = ''; saved.value = ''; preview.value = ''
  try { await props.api('/preferences', draft.value); saved.value = 'Settings saved.'; emit('changed') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
async function showPreview() {
  busy.value = true; error.value = ''
  try { preview.value = (await props.api(`/report-preview/${selected.value === 'current_state' ? 'current-state' : selected.value}`)).text }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <section>
    <form v-if="draft?.daily" class="report-settings" @submit.prevent="save">
      <h2>Reports & dashboard settings</h2><p class="muted">Choose what arrives in Telegram and what appears on your dashboard. Times follow your selected timezone, including daylight saving changes.</p>
      <fieldset :disabled="busy">
        <label>Timezone<SearchSelect v-model="draft.timezone" :options="timezones" label="Report timezone" placeholder="Choose or type an IANA timezone" allow-custom required /></label>
        <div class="segmented report-tabs with-current-state"><button v-for="(label, frequency) in tabs" type="button" :key="frequency" :class="{ selected: selected === frequency }" @click="selected = frequency; preview = ''">{{ label }}</button></div>
        <template v-if="['daily', 'weekly', 'monthly'].includes(selected)">
          <label class="check-label"><input type="checkbox" v-model="draft[selected].enabled"> Enable {{ selected }} report</label>
          <div class="form-row"><label>Delivery time<input aria-label="Delivery time" type="time" required v-model="draft[selected].time"></label><label v-if="selected === 'weekly'">Day of week<SearchSelect v-model="draft.weekly.weekday" :options="weekdays.map((label, value) => ({ label, value }))" label="Day of week" required /></label><label v-if="selected === 'monthly'">Day of month<SearchSelect v-model="draft.monthly.month_day" :options="Array.from({ length: 31 }, (_, i) => i + 1)" label="Day of month" required /></label></div>
          <p class="muted">Current balance in USD, plus {{ selected === 'daily' ? "yesterday's expenses" : selected === 'weekly' ? 'expenses from the previous seven days' : 'expenses from the previous calendar month' }}, plus income and transfers (including exchanges). Monthly days 29–31 use the last day in shorter months.</p>
          <label class="check-label"><input type="checkbox" v-model="draft[selected].include_categories"> Include expenses by category</label>
        </template>
        <template v-if="selected === 'current_state'">
          <h3>Telegram · Current state</h3><p class="muted">Choose what appears when you press Current state in the bot. Balances stay in their original currencies with two decimal places. Only the total is converted to USD. Accounts are sorted by their USD value, highest first. Accounts with unavailable rates appear last.</p>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_debts">Show debts</label>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_goals">Show goals</label>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_monthly_summary">Show this month's income, expenses, and transfers</label>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_categories" :disabled="!draft.current_state.include_monthly_summary">Include expenses by category</label>
        </template>
        <label class="check-label"><input type="checkbox" v-model="draft[selected].include_rates">Show exchange-rate details</label>
        <p class="muted">Conversion stays active for USD totals and account sorting when rate details are hidden. Missing or outdated rate warnings remain visible.</p>
        <div class="account-choices"><h4>Excluded currencies</h4><p class="muted" v-if="selected === 'current_state'">Exclude currencies from Current state's total, account order, debts, goals, and monthly summary.</p><p class="muted" v-else-if="selected === 'dashboard'">Exclude currencies from dashboard balances, account cards, income, expenses, and recent activity.</p><p class="muted" v-else>Exclude currencies from this report's balances, USD total, income, expenses, and category breakdown.</p><p class="muted">Each tab has its own exclusions. Accounts and transactions remain available on their pages.</p><label v-for="currency in currencies" :key="currency" class="check-label"><input type="checkbox" :value="currency" v-model="draft[selected].excluded_currencies">Exclude {{ currency }}</label></div>
        <label class="check-label"><input type="checkbox" v-model="draft[selected].include_savings"> Include savings in {{ selected === 'dashboard' ? 'dashboard' : selected === 'current_state' ? 'Current state' : 'report' }}</label>
        <label class="check-label"><input type="checkbox" :checked="draft[selected].account_ids === null" @change="draft[selected].account_ids = $event.target.checked ? null : []"> All accounts (including future accounts)</label>
        <div v-if="draft[selected].account_ids !== null" class="account-choices"><p class="muted">Select accounts to include. Selecting none gives an empty report.</p><label v-for="g in groups" :key="g.id" class="check-label"><input type="checkbox" :value="g.id" v-model="draft[selected].account_ids">{{ g.name }} · {{ g.balances.map(b => b.currency).join(', ') }}{{ g.kind === 'savings' ? ' · savings' : '' }}</label></div>
      </fieldset>
      <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="saved" class="success" role="status">{{ saved }}</p>
      <div class="form-actions"><button v-if="selected !== 'dashboard'" class="secondary" type="button" :disabled="busy" @click="showPreview">Preview saved report</button><button class="primary" :disabled="busy">{{ busy ? 'Saving…' : 'Save settings' }}</button></div>
      <pre v-if="preview" class="report-preview">{{ preview }}</pre>
      <p class="muted">Scheduled reports need the bot service running. TRX prices refresh daily at 10:00 in your selected timezone; the quote date is shown with every estimate.</p>
    </form>
    <h2 class="rules-heading">Monthly report</h2><p class="muted">Uses the saved monthly account, currency, savings, and category filters. Percentages show each category’s share of total expenses across all included currencies, converted to USD at current rates. Categories combine spending in different currencies. Rounding may make the total differ slightly from 100%.</p>
    <p class="muted">Transferred out and received from transfers include exchanges and savings moves. They are separate from income and expenses. Zero amounts are hidden.</p><div class="planning-grid"><article v-for="total in activeTotals(report.totals)" :key="total.currency" class="planning-card activity-card"><h3>{{ total.currency }}</h3><div v-for="row in activityRows(total)" :key="row.key" class="category-row"><span>{{ row.label }}</span><b>{{ activityAmount(row.amount) }}</b></div><p v-if="Number(total.surplus) !== 0" class="muted">Income less expenses: {{ activityAmount(total.surplus) }}</p></article></div>
    <article v-if="report.category_totals?.length" class="planning-card category-summary">
      <h3>Expenses by category · all currencies</h3>
      <p v-if="report.expense_valuation?.complete" class="muted">Total expenses: {{ Number(report.expense_valuation.total_usd).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }} USD (estimated)</p>
      <p v-else class="rate-warning">Percentages unavailable: missing exchange rates for {{ report.expense_valuation?.missing.join(', ') }}.</p>
      <p v-if="report.expense_valuation?.stale" class="rate-warning">Expense percentages use cached exchange rates; estimates may be out of date.</p>
      <div v-for="row in report.category_totals" :key="row.category" class="category-row"><span>{{ row.category }}</span><b class="category-amount"><span v-for="amount in row.amounts" :key="amount.currency" class="category-native-amount">{{ Number(amount.amount).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }} {{ amount.currency }}</span><small>{{ row.percentage == null ? 'Percentage unavailable' : `${row.percentage}% of total expenses` }}</small></b></div>
      <details v-if="settings.monthly?.include_rates && report.expense_valuation?.quotes?.some(q => q.currency !== 'USD')"><summary>Expense exchange rates & sources</summary><p v-for="q in report.expense_valuation.quotes.filter(q => q.currency !== 'USD')" :key="q.currency" class="muted">{{ q.display_rate }} · {{ q.source }} · {{ q.as_of }}{{ q.stale ? ' (cached)' : '' }}</p></details>
    </article>
    <p v-if="!activeTotals(report.totals).length" class="empty">No activity for these accounts this month.</p>
    <div class="savings-banner"><div><h3>Close a completed month</h3><p>Closing prevents new backdated entries. Deleting a mistaken transaction still updates balances and this report.</p></div><button class="secondary" :disabled="report.closed || report.month >= new Date().toLocaleDateString('en-CA').slice(0, 7)" @click="$emit('close-month')">{{ report.closed ? 'Month closed' : 'Close month' }}<AppIcon v-if="report.closed" name="check" /></button></div>
  </section>
</template>

<style scoped>
.category-summary { margin-top: 20px; }
.category-native-amount { display: block; }
.category-summary details { margin-top: 16px; }
</style>
