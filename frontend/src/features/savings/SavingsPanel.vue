<script setup>
import { t, numberLocale } from '../../i18n.js'
import AppIcon from '../../components/AppIcon.vue'
import SearchSelect from '../../components/SearchSelect.vue'
import AmountInput from '../../components/AmountInput.vue'
import { ref, computed } from 'vue'
import AccountsPanel from '../accounts/AccountsPanel.vue'
const props = defineProps({ accounts: Array, groups: Array, goals: Array, currencies: Object, rules: Array, api: Function })
const emit = defineEmits(['changed', 'add-account', 'goals'])
const editId = ref(null), showArchived = ref(false)
const visibleRules = computed(() => props.rules.filter(r => showArchived.value || !r.archived))
const linkedGoals = computed(() => props.goals.filter(g => !g.archived && g.savings_account_ids?.length))
const action = ref(''), busy = ref(false), error = ref(''), form = ref({})
const saved = computed(() => props.accounts.filter(a => a.kind === 'savings'))
const source = computed(() => props.accounts.find(a => a.id === Number(form.value.source_id)))
const sources = computed(() => props.accounts.filter(a => (a.kind === 'savings') === (action.value === 'withdraw')))
const destinations = computed(() => props.accounts.filter(a => a.id !== Number(form.value.source_id) && a.currency === props.accounts.find(s => s.id === Number(form.value.source_id))?.currency && (a.kind === 'savings') !== (action.value === 'withdraw')))
const money = (value, currency) => `${new Intl.NumberFormat(numberLocale.value, { maximumFractionDigits: ['BTC', 'ETH'].includes(currency) ? 8 : ['TRX', 'USDT'].includes(currency) ? 6 : 2 }).format(Number(value))} ${currency}`
function open(value) {
  action.value = value; editId.value = null; error.value = ''
  form.value = { source_id: sources.value[0]?.id, destination_id: '', mode: 'fixed', amount: '', day: 10, date: new Date().toLocaleDateString('en-CA') }
}
async function submit() {
  error.value = ''; busy.value = true
  try {
    const data = { ...form.value, amount: form.value.mode === 'remainder' ? null : form.value.amount }
    if (action.value === 'rule') delete data.date
    else delete data.day
    await props.api(action.value === 'rule' ? (editId.value ? `/savings/rules/${editId.value}/edit` : '/savings/rules') : '/savings/move', data)
    action.value = ''; emit('changed')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
function editRule(rule) {
  open('rule'); editId.value = rule.id
  form.value = { source_id: rule.source_id, destination_id: rule.destination_id, mode: rule.mode, amount: rule.amount || '', day: rule.day }
}
async function archiveRule(rule) {
  if (!window.confirm(rule.archived ? t("Restore this savings rule in a paused state?") : t("Remove this savings rule? Past transfers stay recorded and future transfers stop."))) return
  busy.value = true; error.value = ''
  try { await props.api(`/savings/rules/${rule.id}/archive`, { archived: !rule.archived }); emit('changed') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
async function toggle(rule) {
  busy.value = true; error.value = ''
  try { await props.api(`/savings/rules/${rule.id}`, { enabled: !rule.active }); emit('changed') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <section>
    <p class="muted planning-note">{{ $t("Savings are your own accounts. Deposits and withdrawals move money between accounts in the same currency; they do not count as income or spending.") }}</p>
    <div class="saving-actions"><button class="secondary" @click="$emit('add-account')"><AppIcon name="plus" /> {{ $t("Savings account") }}</button><button class="primary" :disabled="busy || !saved.length" @click="open('deposit')">{{ $t("Deposit") }}</button><button class="secondary" :disabled="busy || !saved.length" @click="open('withdraw')">{{ $t("Withdraw") }}</button><button class="secondary" :disabled="busy || !saved.length" @click="open('rule')"><AppIcon name="plus" /> {{ $t("Monthly rule") }}</button></div>
    <div v-if="!saved.length" class="empty"><h3>{{ $t("A place for your savings.") }}</h3><p>{{ $t("Add a savings account in the currency you want to save.") }}</p></div>
    <AccountsPanel :groups="groups.filter(g => g.kind === 'savings')" :all-groups="groups" :currencies="currencies" :api="api" @changed="$emit('changed')" />
    <div class="linked-goals"><p v-for="goal in linkedGoals" :key="goal.id" class="muted">{{ goal.name }}: {{ money(goal.saved, goal.currency) }} / {{ money(goal.target, goal.currency) }} · {{ goal.linked_savings.map(a => a.name).join(', ') }}</p><button class="text-button" @click="$emit('goals')">{{ $t("Attach savings to a goal") }} <AppIcon name="arrow-right" /></button></div>
    <form v-if="action" class="savings-form" @submit.prevent="submit"><h2>{{ action === 'rule' ? (editId ? $t("Edit monthly savings rule") : $t("Save a little, every month.")) : action === 'withdraw' ? $t("Withdraw from savings") : $t("Add to savings") }}</h2><fieldset :disabled="busy"><div class="form-row"><label>{{ $t("From") }}<SearchSelect v-model="form.source_id" :options="sources" :label="$t(&quot;From&quot;)" required value-key="id" :option-label="a => `${a.name} · ${a.currency}`" @change="form.destination_id = ''" /></label><label>{{ $t("To") }}<SearchSelect v-model="form.destination_id" :options="destinations" :label="$t(&quot;To&quot;)" required value-key="id" :option-label="a => `${a.name} · ${a.currency}`" :placeholder="$t(&quot;Choose an account&quot;)" /></label></div><label>{{ $t("Amount to move") }}<SearchSelect v-model="form.mode" :options="[{ value: 'fixed', label: $t('A fixed amount') }, { value: 'remainder', label: $t('All remaining balance') }]" :label="$t(&quot;Amount to move&quot;)" required  /></label><AmountInput v-if="form.mode === 'fixed'" v-model="form.amount" :label="$t(&quot;Amount&quot;)" :account-id="form.source_id" :balance="source?.balance" :show-all="action !== 'rule'" /><label v-if="action === 'rule'">{{ $t("Every month on") }}<SearchSelect v-model="form.day" :options="[...Array.from({ length: 31 }, (_, i) => ({ value: i + 1, label: $t('Day {day} · 09:00', { day: i + 1 }) })), { value: 0, label: $t('Last day · 23:59') }]" :label="$t(&quot;Every month on&quot;)" required  /></label><label v-else>{{ $t("Date") }}<input :aria-label="$t(&quot;Date&quot;)" type="date" v-model="form.date" :max="new Date().toLocaleDateString('en-CA')" required></label><p v-if="action === 'rule'" class="muted">{{ $t("Buenos Aires time. Days 29–31 use the last day in shorter months. Fixed deposits are skipped if funds are insufficient. Rules can be paused at any time.") }}</p></fieldset><div class="form-actions"><button type="button" class="secondary" :disabled="busy" @click="action = ''">{{ $t("Cancel") }}</button><button class="primary" :disabled="busy">{{ busy ? $t("Saving…") : action === 'rule' ? (editId ? $t("Save rule changes") : $t("Create monthly rule")) : $t("Confirm transfer") }}</button></div></form>
    <p v-if="error" class="error" role="alert">{{ $error(error) }}</p>
    <div class="section-top rules-heading"><h2>{{ $t("Monthly savings rules") }}</h2></div><p v-if="!rules.length" class="muted">{{ $t("Save a fixed amount, such as 100 USD on the 10th, or move all the balance left in a spending account.") }}</p>
    <label v-if="rules.some(r => r.archived)" class="check-label"><input type="checkbox" v-model="showArchived">{{ $t("Show removed rules") }}</label>
    <article v-for="rule in visibleRules" :key="rule.id" class="savings-row"><div><h3>{{ rule.source }} <span class="sr-only">{{ $t("to") }}</span><AppIcon name="arrow-right" /> {{ rule.destination }}</h3><strong>{{ rule.mode === 'fixed' ? money(rule.amount, rule.currency) : $t("All remaining {v0}", { v0: rule.currency }) }}</strong><small>{{ rule.day === 0 ? $t("Last day at 23:59") : $t("Day {v0} at 09:00", { v0: rule.day }) }} {{ $t("· next") }} {{ rule.next_run }}</small><small v-for="run in rule.recent_runs" :key="run.date">{{ run.date }} · {{ $t(run.result) }}</small></div><div class="record-actions"><template v-if="!rule.archived"><button class="secondary" :disabled="busy" @click="toggle(rule)">{{ rule.active ? $t("Pause") : $t("Resume") }}</button><button class="secondary" :disabled="busy" @click="editRule(rule)">{{ $t("Edit rule") }}</button></template><button class="text-button" :disabled="busy" @click="archiveRule(rule)">{{ rule.archived ? $t("Restore rule") : $t("Remove rule") }}</button></div></article>
  </section>
</template>
