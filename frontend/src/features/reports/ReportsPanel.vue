<script setup>
import { t, numberLocale } from '../../i18n.js'
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
watch(() => props.settings, value => { draft.value = { main_currency: 'USD', ...JSON.parse(JSON.stringify(value)) } }, { immediate: true, deep: true })
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
      <h2>{{ $t("Reports & dashboard settings") }}</h2><p class="muted">{{ $t("Choose what arrives in Telegram and what appears on your dashboard. Times follow your selected timezone, including daylight saving changes.") }}</p>
      <fieldset :disabled="busy">
        <label>{{ $t("Main currency") }}<SearchSelect v-model="draft.main_currency" :options="currencies" :label="$t(&quot;Main currency&quot;)" required /></label>
        <p class="muted">{{ $t("Shared with the dashboard estimate and all Telegram report totals. Account balances keep their original currencies.") }}</p>
        <label>{{ $t("Timezone") }}<SearchSelect v-model="draft.timezone" :options="timezones" :label="$t(&quot;Report timezone&quot;)" :placeholder="$t(&quot;Choose or type an IANA timezone&quot;)" allow-custom required /></label>
        <div class="segmented report-tabs with-current-state"><button v-for="(label, frequency) in tabs" type="button" :key="frequency" :class="{ selected: selected === frequency }" @click="selected = frequency; preview = ''">{{ $t(label) }}</button></div>
        <template v-if="['daily', 'weekly', 'monthly'].includes(selected)">
          <label class="check-label"><input type="checkbox" v-model="draft[selected].enabled"> {{ $t('Enable {report}', { report: $t(tabs[selected]) }) }}</label>
          <div class="form-row"><label>{{ $t("Delivery time") }}<input :aria-label="$t(&quot;Delivery time&quot;)" type="time" required v-model="draft[selected].time"></label><label v-if="selected === 'weekly'">{{ $t("Day of week") }}<SearchSelect v-model="draft.weekly.weekday" :options="weekdays.map((label, value) => ({ label: t(label), value }))" :label="$t(&quot;Day of week&quot;)" required /></label><label v-if="selected === 'monthly'">{{ $t("Day of month") }}<SearchSelect v-model="draft.monthly.month_day" :options="Array.from({ length: 31 }, (_, i) => i + 1)" :label="$t(&quot;Day of month&quot;)" required /></label></div>
          <p class="muted">{{ $t("Current balance in") }} {{ draft.main_currency || 'USD' }}{{ $t(", plus") }} {{ selected === 'daily' ? $t("yesterday's expenses") : selected === 'weekly' ? $t("expenses from the previous seven days") : $t("expenses from the previous calendar month") }}{{ $t(", plus income and transfers (including exchanges). Monthly days 29–31 use the last day in shorter months.") }}</p>
          <label class="check-label"><input type="checkbox" v-model="draft[selected].include_categories"> {{ $t("Include expenses by category") }}</label>
        </template>
        <template v-if="selected === 'current_state'">
          <h3>{{ $t("Telegram · Current state") }}</h3><p class="muted">{{ $t("Choose what appears when you press Current state in the bot. Balances stay in their original currencies with two decimal places. Only the total is converted to") }} {{ draft.main_currency || 'USD' }}{{ $t(". Accounts are sorted by their USD value, highest first. Accounts with unavailable rates appear last.") }}</p>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_debts">{{ $t("Show debts") }}</label>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_goals">{{ $t("Show goals") }}</label>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_monthly_summary">{{ $t("Show this month's income, expenses, and transfers") }}</label>
          <label class="check-label"><input type="checkbox" v-model="draft.current_state.include_categories" :disabled="!draft.current_state.include_monthly_summary">{{ $t("Include expenses by category") }}</label>
        </template>
        <label class="check-label"><input type="checkbox" v-model="draft[selected].include_rates">{{ $t("Show exchange-rate details") }}</label>
        <p class="muted">{{ $t("Conversion stays active for estimated totals and account sorting when rate details are hidden. Missing or outdated rate warnings remain visible.") }}</p>
        <div class="account-choices"><h4>{{ $t("Excluded currencies") }}</h4><p class="muted" v-if="selected === 'current_state'">{{ $t("Exclude currencies from Current state's total, account order, debts, goals, and monthly summary.") }}</p><p class="muted" v-else-if="selected === 'dashboard'">{{ $t("Exclude currencies from dashboard balances, account cards, income, expenses, and recent activity.") }}</p><p class="muted" v-else>{{ $t("Exclude currencies from this report's balances, estimated total, income, expenses, and category breakdown.") }}</p><p class="muted">{{ $t("Each tab has its own exclusions. Accounts and transactions remain available on their pages.") }}</p><label v-for="currency in currencies" :key="currency" class="check-label"><input type="checkbox" :value="currency" v-model="draft[selected].excluded_currencies">{{ $t("Exclude") }} {{ currency }}</label></div>
        <label class="check-label"><input type="checkbox" v-model="draft[selected].include_savings"> {{ $t("Include savings in") }} {{ selected === 'dashboard' ? $t("dashboard") : selected === 'current_state' ? $t("Current state") : $t("report") }}</label>
        <label class="check-label"><input type="checkbox" :checked="draft[selected].account_ids === null" @change="draft[selected].account_ids = $event.target.checked ? null : []"> {{ $t("All accounts (including future accounts)") }}</label>
        <div v-if="draft[selected].account_ids !== null" class="account-choices"><p class="muted">{{ $t("Select accounts to include. Selecting none gives an empty report.") }}</p><label v-for="g in groups" :key="g.id" class="check-label"><input type="checkbox" :value="g.id" v-model="draft[selected].account_ids">{{ g.name }} · {{ g.balances.map(b => b.currency).join(', ') }}{{ g.kind === 'savings' ? $t(" · savings") : '' }}</label></div>
      </fieldset>
      <p v-if="error" class="error" role="alert">{{ $error(error) }}</p><p v-if="saved" class="success" role="status">{{ $t(saved) }}</p>
      <div class="form-actions"><button v-if="selected !== 'dashboard'" class="secondary" type="button" :disabled="busy" @click="showPreview">{{ $t("Preview saved report") }}</button><button class="primary" :disabled="busy">{{ busy ? $t("Saving…") : $t("Save settings") }}</button></div>
      <pre v-if="preview" class="report-preview">{{ preview }}</pre>
      <p class="muted">{{ $t("Scheduled reports need the bot service running. TRX prices refresh daily at 10:00 in your selected timezone; the quote date is shown with every estimate.") }}</p>
    </form>
    <h2 class="rules-heading">{{ $t("Monthly report") }}</h2><p class="muted">{{ $t("Uses the saved monthly account, currency, savings, and category filters. Percentages show each category’s share of total expenses across all included currencies, converted to USD at current rates. Categories combine spending in different currencies. Rounding may make the total differ slightly from 100%.") }}</p>
    <p class="muted">{{ $t("Transferred out and received from transfers include exchanges and savings moves. They are separate from income and expenses. Zero amounts are hidden.") }}</p><div class="planning-grid"><article v-for="total in activeTotals(report.totals)" :key="total.currency" class="planning-card activity-card"><h3>{{ total.currency }}</h3><div v-for="row in activityRows(total)" :key="row.key" class="category-row"><span>{{ $t(row.label) }}</span><b>{{ activityAmount(row.amount, numberLocale) }}</b></div><p v-if="Number(total.surplus) !== 0" class="muted">{{ $t("Income less expenses:") }} {{ activityAmount(total.surplus, numberLocale) }}</p></article></div>
    <article v-if="report.category_totals?.length" class="planning-card category-summary">
      <h3>{{ $t("Expenses by category · all currencies") }}</h3>
      <p v-if="report.expense_valuation?.complete" class="muted">{{ $t("Total expenses:") }} {{ Number(report.expense_valuation.total_usd).toLocaleString(numberLocale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }} {{ $t("USD (estimated)") }}</p>
      <p v-else class="rate-warning">{{ $t("Percentages unavailable: missing exchange rates for") }} {{ report.expense_valuation?.missing.join(', ') }}.</p>
      <p v-if="report.expense_valuation?.stale" class="rate-warning">{{ $t("Expense percentages use cached exchange rates; estimates may be out of date.") }}</p>
      <div v-for="row in report.category_totals" :key="row.category" class="category-row"><span>{{ $category(row.category, 'expense') }}</span><b class="category-amount"><span v-for="amount in row.amounts" :key="amount.currency" class="category-native-amount">{{ Number(amount.amount).toLocaleString(numberLocale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }} {{ amount.currency }}</span><small>{{ row.percentage == null ? $t("Percentage unavailable") : $t("{v0}% of total expenses", { v0: row.percentage }) }}</small></b></div>
      <details v-if="settings.monthly?.include_rates && report.expense_valuation?.quotes?.some(q => q.currency !== 'USD')"><summary>{{ $t("Expense exchange rates & sources") }}</summary><p v-for="q in report.expense_valuation.quotes.filter(q => q.currency !== 'USD')" :key="q.currency" class="muted">{{ $quote(q) }} · {{ $t(q.source) }} · {{ q.as_of }}{{ q.stale ? $t(" (cached)") : '' }}</p></details>
    </article>
    <p v-if="!activeTotals(report.totals).length" class="empty">{{ $t("No activity for these accounts this month.") }}</p>
    <div class="savings-banner"><div><h3>{{ $t("Close a completed month") }}</h3><p>{{ $t("Closing prevents new backdated entries. Deleting a mistaken transaction still updates balances and this report.") }}</p></div><button class="secondary" :disabled="report.closed || report.month >= new Date().toLocaleDateString('en-CA').slice(0, 7)" @click="$emit('close-month')">{{ report.closed ? $t("Month closed") : $t("Close month") }}<AppIcon v-if="report.closed" name="check" /></button></div>
  </section>
</template>

<style scoped>
.category-summary { margin-top: 20px; }
.category-native-amount { display: block; }
.category-summary details { margin-top: 16px; }
</style>
