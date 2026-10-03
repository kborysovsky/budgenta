<script setup>
import { computed } from 'vue'
import { t, categoryLabel, numberLocale } from '../../i18n.js'
import AppIcon from '../../components/AppIcon.vue'
const props = defineProps({ data: Object, editable: Boolean, showRates: { type: Boolean, default: true }, title: Boolean })
defineEmits(['edit'])
const money = (value, currency) => value == null ? '—' : `${new Intl.NumberFormat(numberLocale.value, { minimumFractionDigits: 2, maximumFractionDigits: ['BTC', 'ETH'].includes(currency) ? 8 : ['USDT', 'TRX'].includes(currency) ? 6 : 2 }).format(Number(value))} ${currency}`
const percentage = value => new Intl.NumberFormat(numberLocale.value, { maximumFractionDigits: 2 }).format(Number(value))
const quotes = computed(() => [...new Map((props.data?.budgets || []).flatMap(b => b.stats?.quotes || []).map(q => [q.currency, q])).values()])
</script>
<template>
  <section v-if="data?.budgets?.length" class="budget-usage">
    <h2 v-if="title">{{ t('Budget Limits') }} · {{ data.month }}</h2>
    <div class="budget-table-wrap">
      <table class="budget-table">
        <caption class="sr-only">{{ t('Monthly category budgets') }} · {{ data.month }}</caption>
        <thead><tr><th>{{ t('Category') }}</th><th>{{ t('Budget') }}</th><th>{{ t('Spent') }}</th><th>{{ t('Remaining') }}</th><th>{{ t('Usage') }}</th><th v-if="editable" class="budget-actions"><span class="sr-only">{{ t('MANAGE') }}</span></th></tr></thead>
        <tbody>
          <tr v-for="row in data.budgets" :key="row.id" :class="{ 'budget-exceeded': row.stats?.exceeded, 'budget-disabled': !row.enabled }">
            <th scope="row" class="budget-category"><span>{{ categoryLabel(row.category, 'expense') }}</span><small v-if="!row.enabled">{{ t('Disabled') }}</small><small v-if="row.native_spending?.length">{{ row.native_spending.map(n => money(n.amount, n.currency)).join(' + ') }}</small></th>
            <td><span class="budget-mobile-label">{{ t('Budget') }}</span>{{ money(row.amount, row.currency) }}</td>
            <td><span class="budget-mobile-label">{{ t('Spent') }}</span>{{ money(row.stats?.spent, row.currency) }}</td>
            <td><span class="budget-mobile-label">{{ t('Remaining') }}</span>{{ money(row.stats?.remaining, row.currency) }}</td>
            <td class="budget-progress">
              <template v-if="row.stats?.complete">
                <strong>{{ t('{percentage}% used', { percentage: percentage(row.stats.percentage) }) }}</strong>
                <progress max="100" :value="Math.min(100, Math.max(0, Number(row.stats.percentage)))" :aria-label="t('Budget usage for {category}', { category: categoryLabel(row.category, 'expense') })" :aria-valuetext="t('{percentage}% used', { percentage: percentage(row.stats.percentage) })"></progress>
                <span v-if="row.stats.exceeded" class="budget-status">{{ t('Over budget') }}</span><span v-else-if="Number(row.stats.remaining) === 0" class="budget-status">{{ t('Fully used') }}</span>
                <small v-if="row.stats.stale" class="rate-warning">{{ t('Cached exchange rates used; estimate may be out of date.') }}</small>
              </template>
              <span v-else-if="row.stats" class="rate-warning">{{ t('Budget usage unavailable: missing rates for {currencies}.', { currencies: row.stats.missing.join(', ') }) }}</span>
              <span v-else class="muted">{{ t('Budget tracking is disabled.') }}</span>
            </td>
            <td v-if="editable" class="budget-edit"><button class="settings-button" :aria-label="t('Edit budget for {category}', { category: categoryLabel(row.category, 'expense') })" @click="$emit('edit', row)"><AppIcon name="settings" /></button></td>
          </tr>
        </tbody>
        <tfoot v-if="data.settings.enabled"><tr v-for="total in data.totals" :key="total.currency"><th scope="row">{{ t('Total') }} · {{ total.currency }}</th><td><span class="budget-mobile-label">{{ t('Budget') }}</span>{{ money(total.limit, total.currency) }}</td><td><span class="budget-mobile-label">{{ t('Spent') }}</span>{{ money(total.spent, total.currency) }}</td><td><span class="budget-mobile-label">{{ t('Remaining') }}</span>{{ money(total.remaining, total.currency) }}</td><td :colspan="editable ? 2 : 1" class="muted">{{ t('Enabled budgets only') }}<small v-if="!total.complete">{{ t('Estimate temporarily unavailable') }}</small></td></tr></tfoot>
      </table>
    </div>
    <p v-if="data.settings.enabled" class="muted budget-help">{{ t('Currencies share one category limit. Totals stay separate when budget currencies differ.') }}</p>
    <details v-if="showRates && quotes.length" class="budget-quotes"><summary>{{ t('Budget exchange rates & sources') }}</summary><p v-for="q in quotes" :key="q.currency" class="muted">{{ $quote(q) }} · {{ $t(q.source) }} · {{ q.as_of }}{{ q.stale ? $t(' (cached)') : '' }}</p></details>
  </section>
</template>
<style scoped>
.budget-usage { margin: 24px 0; min-width: 0; }
.budget-usage h2 { margin-bottom: 16px; }
.budget-table-wrap { border: 1px solid #dde5d7; border-radius: 10px; background: white; overflow: hidden; }
.budget-table { width: 100%; table-layout: fixed; }
.budget-table th, .budget-table td { padding: 16px 10px; white-space: normal; overflow-wrap: anywhere; vertical-align: middle; }
.budget-table th { text-align: left; }
.budget-table thead th { font-size: 11px; }
.budget-table .budget-actions { width: 56px; }
.budget-table tbody td, .budget-table tbody th, .budget-table tfoot th { color: #385346; font-size: 13px; }
.budget-table tbody th, .budget-table tfoot th { background: transparent; letter-spacing: normal; }
.budget-table .budget-category { font-size: 13px; font-weight: 600; }
.budget-category small { display: block; margin-top: 8px; color: #7d8f7b; font-size: 11px; font-weight: 400; line-height: 1.5; }
.budget-table .budget-edit { width: 46px; }
.budget-progress strong { font-size: 12px; }
.budget-progress progress { display: block; width: 100%; height: 8px; margin: 9px 0; accent-color: #52734d; }
.budget-exceeded { background: #fff6f2; }
.budget-exceeded progress { accent-color: #b04f38; }
.budget-exceeded progress::-webkit-progress-value { background: #b04f38; }
.budget-status { display: block; color: #a1442f; font-size: 11px; font-weight: 600; }
.budget-disabled { opacity: .7; }
.budget-table tfoot { background: #f4f7ef; font-weight: 600; }
.budget-table tfoot small { display: block; }
.budget-help, .budget-quotes { margin-top: 12px; font-size: 12px; line-height: 1.6; }
.budget-mobile-label { display: none; }
@media (max-width: 760px) {
  .budget-table, .budget-table tbody, .budget-table tfoot { display: block; }
  .budget-table thead { display: none; }
  .budget-table tr { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 16px; border-bottom: 1px solid #e4e7df; position: relative; }
  .budget-table th, .budget-table td { display: block; padding: 0; border: 0; font-size: 12px; }
  .budget-table .budget-category, .budget-table .budget-progress, .budget-table tfoot th, .budget-table tfoot td:last-child { grid-column: 1 / -1; }
  .budget-table .budget-category { padding-right: 38px; font-size: 14px; }
  .budget-table .budget-edit { position: absolute; top: 12px; right: 8px; }
  .budget-mobile-label { display: block; color: #7d8f7b; font-size: 10px; margin-bottom: 4px; }
}
</style>
