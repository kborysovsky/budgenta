<script setup>
import { t, numberLocale } from '../../i18n.js'
import AppIcon from '../../components/AppIcon.vue'
import { ref, computed } from 'vue'
const props = defineProps({ view: String, debts: Array, goals: Array, api: Function })
const emit = defineEmits(['open', 'changed', 'savings'])
const showArchived = ref(false), busy = ref(false), error = ref('')
const allItems = computed(() => props.view === 'Debts' ? props.debts : props.goals)
const items = computed(() => allItems.value.filter(item => showArchived.value || !item.archived))
const money = (value, currency) => `${new Intl.NumberFormat(numberLocale.value, { maximumFractionDigits: ['BTC', 'ETH'].includes(currency) ? 8 : ['USDT', 'TRX'].includes(currency) ? 6 : 2, minimumFractionDigits: 2 }).format(Number(value))} ${currency}`
const progress = item => Math.min(100, Math.round(Number(props.view === 'Debts' ? item.paid : item.saved) / Number(props.view === 'Debts' ? item.amount : item.target) * 100))
async function archive(item) {
  const hint = props.view === 'Goals' ? 'Linked savings will be released and progress saved as a snapshot. The money stays in your accounts.' : 'The debt and repayment history stay recorded, but are hidden from the active debt list.'
  if (!window.confirm(item.archived ? t("Restore {v0}?", { v0: item.name }) : t("Archive {v0}? {v1}", { v0: item.name, v1: t(hint) }))) return
  busy.value = true; error.value = ''
  try { await props.api(`/${props.view.toLowerCase()}/${item.id}/archive`, { archived: !item.archived }); emit('changed') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <section class="planning-section">
    <p class="muted planning-note">{{ view === 'Debts' ? $t("Pay a debt from a chosen account to reduce what you owe and record the expense together.") : $t("Attach savings in the goal’s currency to track real progress. Each savings balance can fund one goal; deposits and withdrawals update it automatically.") }}</p>
    <label v-if="allItems.some(i => i.archived)" class="check-label"><input type="checkbox" v-model="showArchived">{{ $t('Show archived: {section}', { section: $t(view) }) }}</label><p v-if="error" class="error" role="alert">{{ $error(error) }}</p>
    <div v-if="!items.length" class="empty"><h3>{{ view === 'Debts' ? $t("A clearer view of what you owe.") : $t("Something worth saving for.") }}</h3><p>{{ view === 'Debts' ? $t("Add a debt to track its balance and repayments.") : $t("Add a goal and attach your savings.") }}</p></div>
    <div class="planning-grid"><article v-for="item in items" :key="item.id" class="planning-card" :class="{ archived: item.archived }"><div class="section-top"><h2>{{ item.name }}</h2><span class="pill">{{ item.archived ? $t("Archived") : progress(item) >= 100 ? (view === 'Debts' ? $t("Paid off") : $t("Goal reached")) : item.currency }}<AppIcon v-if="!item.archived && progress(item) >= 100" name="check" /></span></div><strong>{{ money(view === 'Debts' ? item.remaining : item.saved, item.currency) }}</strong><p class="muted">{{ view === 'Debts' ? $t("remaining of") : $t("saved of") }} {{ money(view === 'Debts' ? item.amount : item.target, item.currency) }}</p><progress :value="progress(item)" max="100" :aria-label="$t(&quot;{v0} progress&quot;, { v0: item.name })"></progress><div class="progress-caption"><span>{{ progress(item) }}% {{ view === 'Debts' ? $t("repaid") : $t("saved") }}</span><span>{{ item.due_date ? $t("Due {v0}", { v0: item.due_date }) : $t("No due date") }}</span></div><p v-if="item.note" class="planning-description">{{ item.note }}</p>
      <p v-if="item.linked_savings?.length" class="muted">{{ $t("Linked savings:") }} {{ item.linked_savings.map(a => `${a.name} · ${a.currency}`).join(', ') }}</p>
      <div class="record-actions"><template v-if="!item.archived"><button v-if="view === 'Debts'" class="primary" :disabled="busy || Number(item.remaining) <= 0" @click="$emit('open', 'repay', item)">{{ $t("Pay debt") }}</button><button v-else-if="item.linked_savings?.length" class="secondary" @click="$emit('savings')">{{ $t("Manage savings") }}</button><button v-else class="secondary" @click="$emit('open', 'progress', item)">{{ $t("Update progress") }}</button><button class="secondary" :disabled="busy" @click="$emit('open', view === 'Debts' ? 'edit_debt' : 'edit_goal', item)">{{ view === 'Debts' ? $t("Edit") : $t("Edit / link savings") }}</button></template><button class="secondary" :disabled="busy" @click="archive(item)">{{ item.archived ? $t("Restore") : $t("Archive") }}</button></div>
    </article></div>
  </section>
</template>
