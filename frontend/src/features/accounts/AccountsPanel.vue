<script setup>
import { t, numberLocale } from '../../i18n.js'
import AppIcon from '../../components/AppIcon.vue'
import SearchSelect from '../../components/SearchSelect.vue'
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
const props = defineProps({ groups: Array, allGroups: Array, currencies: Object, api: Function, manage: { type: Boolean, default: true } })
const emit = defineEmits(['changed'])
const menuId = ref(null), editForm = ref(null)
const action = ref(''), selected = ref(null), busy = ref(false), error = ref(''), form = ref({}), showArchived = ref(false)
const names = { cash: 'Cash', debit: 'Debit card', card: 'Credit card', paypal: 'PayPal', crypto: 'Crypto', savings: 'Savings' }
const icons = { cash: 'cash', debit: 'card', card: 'card', paypal: 'wallet', crypto: 'crypto', savings: 'savings' }
const visible = computed(() => props.groups.filter(g => showArchived.value || !g.archived))
const available = computed(() => (props.currencies[selected.value?.kind] || []).filter(c => !selected.value.balances.some(b => b.currency === c)))
const targets = computed(() => (props.allGroups || props.groups).filter(g => !g.archived && g.id !== selected.value?.id && g.kind === selected.value?.kind))
const wallet = computed(() => selected.value?.balances.find(b => b.id === Number(form.value.account_id)))
const headings = { merge: 'Merge account', currency: 'Add a currency', edit: 'Edit account', balance: 'Correct a balance' }
const money = (value, currency) => new Intl.NumberFormat(numberLocale.value, { minimumFractionDigits: 2, maximumFractionDigits: ['BTC', 'ETH'].includes(currency) ? 8 : ['TRX', 'USDT'].includes(currency) ? 6 : 2 }).format(Number(value))
function dismissMenu(event) {
  if (event.type === 'keydown') {
    if (event.key !== 'Escape' || menuId.value === null) return
    const trigger = document.getElementById(`account-settings-${menuId.value}`)
    menuId.value = null; trigger?.focus(); event.stopPropagation()
  } else if (event.target.closest('.account-settings')?.dataset.accountId !== String(menuId.value)) menuId.value = null
}
onMounted(() => { document.addEventListener('click', dismissMenu); document.addEventListener('keydown', dismissMenu) })
onUnmounted(() => { document.removeEventListener('click', dismissMenu); document.removeEventListener('keydown', dismissMenu) })
const fullGroup = group => (props.allGroups || props.groups).find(g => g.id === group.id) || group
function open(value, group) {
  group = fullGroup(group)
  menuId.value = null; selected.value = group; action.value = value; error.value = ''
  nextTick(() => { editForm.value?.scrollIntoView({ block: 'center', behavior: 'smooth' }); editForm.value?.querySelector('input, select')?.focus({ preventScroll: true }) })
  form.value = { name: group.name, kind: group.kind, currency: available.value[0], opening_balance: '', date: new Date().toLocaleDateString('en-CA'), destination_id: '', account_id: group.balances[0]?.id, balance: group.balances[0]?.balance || '0', note: '' }
}
async function archive(group) {
  menuId.value = null
  if (!window.confirm(group.archived ? t("Restore {v0}? Savings rules stay paused until you resume them.", { v0: group.name }) : t("Archive {v0}? Every currency must have a zero balance. Transaction history stays available; connected savings rules will be paused.", { v0: group.name }))) return
  busy.value = true; error.value = ''
  try { await props.api(`/account-groups/${group.id}/archive`, { archived: !group.archived }); emit('changed') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
async function submit() {
  busy.value = true; error.value = ''
  try {
    if (action.value === 'merge') await props.api('/account-groups/merge', { source_id: selected.value.id, destination_id: Number(form.value.destination_id) })
    else if (action.value === 'edit') await props.api(`/account-groups/${selected.value.id}/edit`, { name: form.value.name, kind: form.value.kind })
    else if (action.value === 'balance') await props.api(`/accounts/${form.value.account_id}/balance`, { balance: form.value.balance, date: form.value.date, note: form.value.note })
    else await props.api(`/account-groups/${selected.value.id}/currencies`, { currency: form.value.currency, opening_balance: form.value.opening_balance || '0', date: form.value.date })
    action.value = ''; emit('changed')
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <label v-if="manage && groups.some(g => g.archived)" class="check-label"><input type="checkbox" v-model="showArchived">{{ $t("Show archived accounts") }}</label>
  <div class="account-grid grouped-accounts">
    <article v-for="group in visible" :key="group.id" class="account-card" :class="{ archived: group.archived }">
      <div class="account-top"><span class="account-icon" :class="group.kind"><AppIcon :name="icons[group.kind]" /></span>
        <div v-if="manage" class="account-settings" :data-account-id="group.id">
          <button type="button" class="settings-button" :id="`account-settings-${group.id}`" :aria-label="$t(&quot;Settings for {v0}&quot;, { v0: group.name })" :title="$t(&quot;Settings for {v0}&quot;, { v0: group.name })" :aria-expanded="menuId === group.id" :aria-controls="`account-menu-${group.id}`" @click="menuId = menuId === group.id ? null : group.id">
            <AppIcon name="settings" />
          </button>
          <div v-if="menuId === group.id" :id="`account-menu-${group.id}`" class="account-menu" role="group" :aria-label="$t(&quot;Actions for {v0}&quot;, { v0: group.name })">
            <template v-if="!group.archived"><button type="button" :disabled="busy" @click="open('edit', group)">{{ $t("Edit account") }}</button><button type="button" :disabled="busy" @click="open('balance', group)">{{ $t("Correct balance") }}</button><button type="button" :disabled="busy || fullGroup(group).balances.length >= (currencies[group.kind]?.length || 0)" @click="open('currency', group)">{{ $t("Add currency") }}</button><button type="button" :disabled="busy || !(allGroups || groups).some(g => !g.archived && g.id !== group.id && g.kind === group.kind)" @click="open('merge', group)">{{ $t("Merge accounts") }}</button></template><button type="button" :disabled="busy" @click="archive(group)">{{ group.archived ? $t("Restore account") : $t("Archive account") }}</button>
          </div>
        </div>
      </div><h3>{{ group.name }}</h3><span class="muted">{{ group.archived ? $t("Archived") : $t(names[group.kind]) }}</span>
      <div class="currency-balance" v-for="b in group.balances" :key="b.id"><span>{{ b.currency }}</span><strong>{{ money(b.balance, b.currency) }}</strong></div>
    </article>
  </div>
  <form v-if="action" ref="editForm" class="savings-form account-edit-form" @submit.prevent="submit"><h2>{{ $t(headings[action]) }} · {{ selected.name }}</h2><fieldset :disabled="busy">
    <template v-if="action === 'merge'"><label>{{ $t("Merge into") }}<SearchSelect v-model="form.destination_id" :options="targets" :label="$t(&quot;Merge into&quot;)" required value-key="id" :option-label="g => g.name" :placeholder="$t(&quot;Choose an account&quot;)" /></label><p class="muted">{{ $t("Keeps the destination name, combines matching currencies, and preserves transactions and savings rules. Savings attached to different goals must be unlinked before merging. This cannot be split automatically afterwards.") }}</p></template>
    <template v-else-if="action === 'edit'"><label>{{ $t("Account name") }}<input :aria-label="$t(&quot;Edit account name&quot;)" v-model="form.name" maxlength="80" required></label><label>{{ $t("Account type") }}<SearchSelect v-model="form.kind" :options="Object.entries(names).map(([value, label]) => ({ value, label: t(label) }))" :label="$t(&quot;Edit account type&quot;)" required  /></label></template>
    <template v-else-if="action === 'balance'"><label>{{ $t("Currency balance") }}<SearchSelect v-model="form.account_id" :options="selected.balances" :label="$t(&quot;Currency balance&quot;)" required value-key="id" :option-label="b => $t('{currency} · current {amount}', { currency: b.currency, amount: money(b.balance, b.currency) })" @change="form.balance = wallet.balance" /></label><label>{{ $t("Correct balance") }}<input :aria-label="$t(&quot;Correct balance&quot;)" v-model="form.balance" type="number" step="any" :min="selected.kind === 'card' ? undefined : 0" required></label><label>{{ $t("Reason (optional)") }}<input :aria-label="$t(&quot;Correction reason&quot;)" v-model="form.note" maxlength="300"></label><p class="muted">{{ $t("Sets today's balance with a visible correction transaction. It does not count as income or an expense. Linked goals update automatically.") }}</p></template>
    <template v-else><label>{{ $t("New currency") }}<SearchSelect v-model="form.currency" :options="available" :label="$t(&quot;New currency&quot;)" required  /></label><label>{{ $t("Opening balance") }}<input :aria-label="$t(&quot;Currency opening balance&quot;)" v-model="form.opening_balance" type="number" step="any" min="0" placeholder="0.00"></label><label>{{ $t("Date") }}<input :aria-label="$t(&quot;Currency start date&quot;)" v-model="form.date" type="date" :max="new Date().toLocaleDateString('en-CA')" required></label></template>
  </fieldset><div class="form-actions"><button type="button" class="secondary" :disabled="busy" @click="action = ''; error = ''">{{ $t("Cancel") }}</button><button class="primary" :disabled="busy">{{ action === 'merge' ? $t("Confirm merge") : action === 'currency' ? $t("Add currency") : $t("Save changes") }}</button></div></form>
  <p v-if="error" class="error" role="alert">{{ $error(error) }}</p>
</template>
