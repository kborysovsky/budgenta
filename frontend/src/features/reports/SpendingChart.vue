<script setup>
import { computed } from 'vue'
import { t, categoryLabel, numberLocale } from '../../i18n.js'
const props = defineProps({ report: Object })
const rows = computed(() => props.report.category_totals || [])
const share = value => new Intl.NumberFormat(numberLocale.value, { maximumFractionDigits: 2 }).format(Number(value))
</script>
<template>
  <figure v-if="rows.length && report.expense_valuation?.complete" class="spending-chart">
    <figcaption>{{ t('Spending by category') }}</figcaption>
    <p class="muted">{{ t('Share of total expenses across all included currencies.') }}</p>
    <div v-for="row in rows" :key="row.category" class="spending-bar-row">
      <div class="spending-bar-label"><span>{{ categoryLabel(row.category, 'expense') }}</span><strong>{{ share(row.percentage) }}%</strong></div>
      <div class="spending-bar-track" role="img" :aria-label="`${categoryLabel(row.category, 'expense')}: ${share(row.percentage)}%`"><span :style="{ width: `${Math.min(100, Math.max(0, Number(row.percentage)))}%` }"></span></div>
    </div>
  </figure>
</template>
<style scoped>
.spending-chart { margin: 24px 0; padding: 24px; border: 1px solid #dde5d7; border-radius: 10px; background: white; }
.spending-chart figcaption { font-size: 18px; font-weight: 600; }
.spending-chart .muted { margin: 10px 0 22px; font-size: 12px; }
.spending-bar-row + .spending-bar-row { margin-top: 18px; }
.spending-bar-label { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 8px; font-size: 13px; overflow-wrap: anywhere; }
.spending-bar-label strong { white-space: nowrap; }
.spending-bar-track { height: 12px; border-radius: 6px; background: #edf1e7; overflow: hidden; }
.spending-bar-track span { display: block; height: 100%; border-radius: 6px; background: #52734d; }
</style>
