<script setup>
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
const money = (value, currency) => `${new Intl.NumberFormat('en-US', { maximumFractionDigits: ['BTC', 'ETH'].includes(currency) ? 8 : ['TRX', 'USDT'].includes(currency) ? 6 : 2 }).format(Number(value))} ${currency}`
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
  if (!window.confirm(rule.archived ? 'Restore this savings rule in a paused state?' : 'Remove this savings rule? Past transfers stay recorded and future transfers stop.')) return
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
    <p class="muted planning-note">Savings are your own accounts. Deposits and withdrawals move money between accounts in the same currency; they do not count as income or spending.</p>
    <div class="saving-actions"><button class="secondary" @click="$emit('add-account')">＋ Savings account</button><button class="primary" :disabled="busy || !saved.length" @click="open('deposit')">Deposit</button><button class="secondary" :disabled="busy || !saved.length" @click="open('withdraw')">Withdraw</button><button class="secondary" :disabled="busy || !saved.length" @click="open('rule')">＋ Monthly rule</button></div>
    <div v-if="!saved.length" class="empty"><h3>A place for your savings.</h3><p>Add a savings account in the currency you want to save.</p></div>
    <AccountsPanel :groups="groups.filter(g => g.kind === 'savings')" :all-groups="groups" :currencies="currencies" :api="api" @changed="$emit('changed')" />
    <div class="linked-goals"><p v-for="goal in linkedGoals" :key="goal.id" class="muted">{{ goal.name }}: {{ money(goal.saved, goal.currency) }} / {{ money(goal.target, goal.currency) }} · {{ goal.linked_savings.map(a => a.name).join(', ') }}</p><button class="text-button" @click="$emit('goals')">Attach savings to a goal →</button></div>
    <form v-if="action" class="savings-form" @submit.prevent="submit"><h2>{{ action === 'rule' ? (editId ? 'Edit monthly savings rule' : 'Save a little, every month.') : action === 'withdraw' ? 'Withdraw from savings' : 'Add to savings' }}</h2><fieldset :disabled="busy"><div class="form-row"><label>From<SearchSelect v-model="form.source_id" :options="sources" label="From" required value-key="id" :option-label="a => `${a.name} · ${a.currency}`" @change="form.destination_id = ''" /></label><label>To<SearchSelect v-model="form.destination_id" :options="destinations" label="To" required value-key="id" :option-label="a => `${a.name} · ${a.currency}`" placeholder="Choose an account" /></label></div><label>Amount to move<SearchSelect v-model="form.mode" :options="[{ value: 'fixed', label: 'A fixed amount' }, { value: 'remainder', label: 'All remaining balance' }]" label="Amount to move" required  /></label><AmountInput v-if="form.mode === 'fixed'" v-model="form.amount" label="Amount" :account-id="form.source_id" :balance="source?.balance" :show-all="action !== 'rule'" /><label v-if="action === 'rule'">Every month on<SearchSelect v-model="form.day" :options="[...Array.from({ length: 31 }, (_, i) => ({ value: i + 1, label: `Day ${i + 1} · 09:00` })), { value: 0, label: 'Last day · 23:59' }]" label="Every month on" required  /></label><label v-else>Date<input aria-label="Date" type="date" v-model="form.date" :max="new Date().toLocaleDateString('en-CA')" required></label><p v-if="action === 'rule'" class="muted">Buenos Aires time. Days 29–31 use the last day in shorter months. Fixed deposits are skipped if funds are insufficient. Rules can be paused at any time.</p></fieldset><div class="form-actions"><button type="button" class="secondary" :disabled="busy" @click="action = ''">Cancel</button><button class="primary" :disabled="busy">{{ busy ? 'Saving…' : action === 'rule' ? (editId ? 'Save rule changes' : 'Create monthly rule') : 'Confirm transfer' }}</button></div></form>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <div class="section-top rules-heading"><h2>Monthly savings rules</h2></div><p v-if="!rules.length" class="muted">Save a fixed amount, such as 100 USD on the 10th, or move all the balance left in a spending account.</p>
    <label v-if="rules.some(r => r.archived)" class="check-label"><input type="checkbox" v-model="showArchived">Show removed rules</label>
    <article v-for="rule in visibleRules" :key="rule.id" class="savings-row"><div><h3>{{ rule.source }} → {{ rule.destination }}</h3><strong>{{ rule.mode === 'fixed' ? money(rule.amount, rule.currency) : `All remaining ${rule.currency}` }}</strong><small>{{ rule.day === 0 ? 'Last day at 23:59' : `Day ${rule.day} at 09:00` }} · next {{ rule.next_run }}</small><small v-for="run in rule.recent_runs" :key="run.date">{{ run.date }} · {{ run.result }}</small></div><div class="record-actions"><template v-if="!rule.archived"><button class="secondary" :disabled="busy" @click="toggle(rule)">{{ rule.active ? 'Pause' : 'Resume' }}</button><button class="secondary" :disabled="busy" @click="editRule(rule)">Edit rule</button></template><button class="text-button" :disabled="busy" @click="archiveRule(rule)">{{ rule.archived ? 'Restore rule' : 'Remove rule' }}</button></div></article>
  </section>
</template>
