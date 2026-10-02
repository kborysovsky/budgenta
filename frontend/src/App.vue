<script setup>
import AppIcon from './components/AppIcon.vue'
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import SearchSelect from './components/SearchSelect.vue'
import AmountInput from './components/AmountInput.vue'
import BrandLogo from './components/BrandLogo.vue'
import RepositoryLink from './components/RepositoryLink.vue'
import { activityRows, activeTotals } from './utils/activity.js'
import MoneyMoveDialog from './features/transactions/MoneyMoveDialog.vue'
import PlanningPanel from './features/planning/PlanningPanel.vue'
import SavingsPanel from './features/savings/SavingsPanel.vue'
import ReportsPanel from './features/reports/ReportsPanel.vue'
import EstimatedBalance from './features/reports/EstimatedBalance.vue'
import AccountsPage from './features/accounts/AccountsPage.vue'
const today = new Date().toLocaleDateString('en-CA')
const month = ref(today.slice(0, 7)), view = ref('Overview'), user = ref(null), config = ref({ currencies: {} })
const groups = ref([]), dashboardReport = ref({ totals: [], transactions: [] })
const accounts = ref([]), report = ref({ totals: [], transactions: [] }), savings = ref([]), rules = ref([]), monthlyReport = ref({ totals: [], categories: [] }), reportSettings = ref({}), debts = ref([]), goals = ref([]), estimatedBalance = ref(null), balanceLoading = ref(false)
const error = ref(''), busy = ref(false), loading = ref(true), modal = ref(''), search = ref('')
const form = ref({}), dialog = ref(null), moneyMove = ref(null)
const categoryChoices = ref({ expense: [], income: [] })
const entryCategories = computed(() => categoryChoices.value[form.value.kind] || [])
const customCategory = computed(() => {
  const name = (form.value.category || '').trim().replace(/\s+/g, ' ').toLocaleLowerCase()
  return !!name && !entryCategories.value.some(c => c.toLocaleLowerCase() === name)
})
const loginChallenge = ref(null), approvedName = ref('')
let loginTimer, balanceRequest = 0, loginAttempt = 0
const currencies = ['USD', 'EUR', 'ARS', 'UAH', 'USDT', 'TRX', 'BTC', 'ETH']
const entryAccount = computed(() => accounts.value.find(a => a.id === Number(form.value.account_id)))
const paymentAccounts = computed(() => accounts.value.filter(a => a.currency === debts.value.find(d => d.id === form.value.debt_id)?.currency))
const goalSavings = computed(() => accounts.value.filter(a => a.kind === 'savings' && a.currency === form.value.currency))
function assignedGoal(accountId) { return goals.value.find(g => !g.archived && g.id !== form.value.edit_id && g.savings_account_ids?.includes(accountId)) }
const primaryAction = computed(() => view.value === 'Savings' ? 'savings_account' : view.value === 'Debts' ? 'debt' : view.value === 'Goals' ? 'goal' : view.value === 'Accounts' || !accounts.value.length ? 'account' : 'entry')
const actionLabels = { savings_account: 'Add savings account', debt: 'Add debt', goal: 'Add goal', account: 'Add account', entry: 'Add transaction' }
const modalTitles = { debt: 'Keep track of what you owe.', goal: 'Make room for a goal.', repay: 'Pay a debt.', progress: 'Update your progress.', account: 'A new home for your money.', entry: 'A little update.' }
const titles = { cash: 'Cash', debit: 'Debit card', card: 'Credit card', paypal: 'PayPal', crypto: 'Crypto', savings: 'Savings' }
const money = (amount, currency) => `${new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: ['BTC', 'ETH'].includes(currency) ? 8 : ['USDT', 'TRX'].includes(currency) ? 6 : 2 }).format(Number(amount))} ${currency}`
const totals = computed(() => {
  const result = {}
  dashboardAccounts.value.forEach(a => { result[a.currency] = (result[a.currency] || 0) + Number(a.balance) })
  return Object.entries(result)
})
const dashboardGroups = computed(() => groups.value.filter(g => !g.archived && (reportSettings.value.dashboard?.include_savings !== false || g.kind !== 'savings') && (reportSettings.value.dashboard?.account_ids == null || reportSettings.value.dashboard.account_ids.includes(g.id))).map(g => ({ ...g, balances: g.balances.filter(b => !reportSettings.value.dashboard?.excluded_currencies?.includes(b.currency)) })).filter(g => g.balances.length))
const dashboardAccounts = computed(() => dashboardGroups.value.flatMap(g => g.balances))
const shownGroups = computed(() => view.value === 'Overview' ? dashboardGroups.value : groups.value)
const filtered = computed(() => (view.value === 'Overview' ? dashboardReport.value : report.value).transactions.filter(t => view.value !== 'Transactions' || `${t.account} ${t.category} ${t.note}`.toLowerCase().includes(search.value.toLowerCase())))
const options = computed(() => config.value.currencies[form.value.kind] || [])
const monthLabel = computed(() => new Date(`${month.value}-02T12:00:00`).toLocaleDateString('en-US', { month: 'long', year: 'numeric' }))
async function api(path, body) {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
  const data = await response.json()
  if (!response.ok) {
    if (response.status === 401) user.value = null
    throw new Error(typeof data.detail === 'string' ? data.detail : data.detail?.map(e => `${e.loc.slice(1).join(' ')}: ${e.msg}`).join('; ') || 'Something went wrong. Please try again.')
  }
  return data
}
async function refresh() {
  const [a, r, s, d, g, sr, mr, rs, ag, dr, categories] = await Promise.all([api('/accounts'), api(`/months/${month.value}`), api('/savings'), api('/debts?include_archived=true'), api('/goals?include_archived=true'), api('/savings/rules?include_archived=true'), api(`/reports/${month.value}`), api('/preferences'), api('/account-groups?include_archived=true'), api(`/dashboard/${month.value}`), api('/categories')])
  accounts.value = a; report.value = r; savings.value = s; debts.value = d; goals.value = g; rules.value = sr; monthlyReport.value = mr; reportSettings.value = rs; groups.value = ag; dashboardReport.value = dr; categoryChoices.value = categories
  loadBalance()
}
async function loadBalance() {
  const request = ++balanceRequest
  balanceLoading.value = true
  try { const result = await api('/balance?dashboard=true'); if (request === balanceRequest) estimatedBalance.value = result }
  catch { if (request === balanceRequest) estimatedBalance.value = { unavailable: true } }
  finally { if (request === balanceRequest) balanceLoading.value = false }
}
async function startTelegramLogin() {
  await run(async () => {
    clearTimeout(loginTimer); approvedName.value = ''; const attempt = ++loginAttempt
    loginChallenge.value = await api('/auth/bot/start', {})
    loginTimer = setTimeout(() => pollLogin(attempt), 1500)
  })
}
async function pollLogin(attempt) {
  if (user.value || attempt !== loginAttempt) return
  try {
    const result = await api('/auth/bot/status')
    if (user.value || attempt !== loginAttempt) return
    if (result.approved) approvedName.value = result.name
    else loginTimer = setTimeout(() => pollLogin(attempt), 1500)
  } catch (e) { if (attempt === loginAttempt && !user.value) { error.value = e.message; loginChallenge.value = null } }
}
async function completeTelegramLogin() {
  await run(async () => {
    await api('/auth/bot/complete', {})
    clearTimeout(loginTimer); loginChallenge.value = null; approvedName.value = ''
    user.value = await api('/me'); await refresh()
  })
}
onUnmounted(() => clearTimeout(loginTimer))
async function run(task) {
  if (busy.value) return
  error.value = ''; busy.value = true
  try { await task() } catch (e) { error.value = e.message } finally { busy.value = false }
}
watch(user, value => { if (!value) { ++balanceRequest; estimatedBalance.value = null } else clearTimeout(loginTimer) })
watch(month, value => { if (value && user.value) run(refresh) })
watch(() => form.value.kind, () => { if (modal.value === 'entry') { form.value.category = ''; form.value.save_category = false }; if (modal.value === 'account') { form.value.currency = options.value[0]; form.value.extra_currencies = [] } })
watch(() => form.value.currency, value => { if (modal.value === 'account') form.value.extra_currencies = (form.value.extra_currencies || []).filter(c => c !== value); if (modal.value === 'goal') form.value.savings_account_ids = (form.value.savings_account_ids || []).filter(id => accounts.value.some(a => a.id === id && a.currency === value)) })
watch(() => form.value.category, () => { form.value.save_category = false })
function open(type, item) {
  if (['transfer', 'exchange'].includes(type)) { moneyMove.value.open(type); return }
  const editing = type.startsWith('edit_'); if (editing) type = type.slice(5)
  const isSavings = type === 'savings_account'; if (isSavings) type = 'account'
  error.value = ''; modal.value = type
  form.value = type === 'account' ? { name: '', kind: 'cash', currency: 'USD', opening_balance: '', extra_currencies: [], extra_balances: {}, date: today } : { account_id: accounts.value[0]?.id, kind: 'expense', amount: '', category: '', save_category: false, note: '', date: today }
  if (type === 'debt') form.value = { name: '', currency: 'USD', amount: '', due_date: '', note: '' }
  if (type === 'goal') form.value = { name: '', currency: 'USD', target: '', saved: '', savings_account_ids: [], due_date: '', note: '' }
  if (editing) form.value = { ...item, savings_account_ids: [...(item.savings_account_ids || [])], edit_id: item.id, due_date: item.due_date || '' }
  if (type === 'repay') form.value = { debt_id: item.id, account_id: accounts.value.find(a => a.currency === item.currency)?.id, amount: item.remaining, max_amount: item.remaining, date: today }
  if (type === 'progress') form.value = { goal_id: item.id, saved: item.saved }
  if (isSavings) form.value.kind = 'savings'
  nextTick(() => dialog.value.showModal())
}
function dismiss() { if (!busy.value) { dialog.value.close(); modal.value = ''; error.value = '' } }
async function submit() {
  await run(async () => {
    const paths = { account: '/account-groups', entry: '/entries', debt: '/debts', goal: '/goals', repay: `/debts/${form.value.debt_id}/payments`, progress: `/goals/${form.value.goal_id}/progress` }
    const payload = { ...form.value }; delete payload.debt_id; delete payload.goal_id; delete payload.edit_id; delete payload.id; delete payload.max_amount
    if (form.value.edit_id && ['goal','debt'].includes(modal.value)) paths[modal.value] = `/${modal.value === 'goal' ? 'goals' : 'debts'}/${form.value.edit_id}/edit`
    if (modal.value === 'account') { payload.balances = [{ currency: payload.currency, opening_balance: payload.opening_balance || '0' }, ...payload.extra_currencies.map(currency => ({ currency, opening_balance: payload.extra_balances[currency] || '0' }))]; delete payload.currency; delete payload.opening_balance; delete payload.extra_currencies; delete payload.extra_balances }
    if (modal.value === 'goal' && payload.saved === '') payload.saved = '0'
    if ('due_date' in payload && !payload.due_date) payload.due_date = null
    await api(paths[modal.value], payload)
    dialog.value.close(); modal.value = ''
    await refresh()
  })
}
async function deleteTransaction(entry) {
  if (!window.confirm(`Delete ${entry.category} (${entry.amount} ${entry.currency})? This reverses the entire operation, including linked transfers, exchanges, and debt repayments, and updates reports.`)) return
  await run(async () => { await api(`/entries/${entry.id}/delete`, {}); await refresh() })
}
async function closeMonth() {
  if (!window.confirm(`Close ${monthLabel.value}? Transactions through this month will be locked. New backdated entries will be blocked; corrections by deletion remain possible.`)) return
  await run(async () => { await api('/months/close', { month: month.value }); await refresh() })
}
onMounted(async () => {
  try { config.value = await api('/config'); try { user.value = await api('/me') } catch (e) { if (e.message !== 'Sign in to continue.') throw e }; if (user.value) await refresh() }
  catch (e) { error.value = e.message } finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="loading">Getting Budgenta ready…</div>
  <div v-else-if="!user" class="login-page">
    <div class="login-art"><div class="brand"><BrandLogo /></div><div><span class="eyebrow">YOUR BUDGET AGENT</span><h1>Big plans.<br>Small, simple<br>money habits.</h1><p>All your accounts. Every currency.<br>A little more peace of mind.</p></div><span class="login-foot">Budgenta · Your budget agent.</span></div>
    <section class="login-card"><span class="eyebrow">WELCOME TO BUDGENTA</span><h2>Make yourself at home.</h2><p>Sign in with Telegram to see your budget.</p><button class="primary telegram-button" :disabled="busy || !config.telegram_username" @click="startTelegramLogin"><AppIcon name="telegram" /> Log in with Telegram</button><div v-if="loginChallenge" class="login-challenge"><p>Match this code in Telegram: <strong>{{ loginChallenge.code }}</strong></p><a class="secondary" :href="loginChallenge.url" target="_blank" rel="noopener noreferrer">Open Telegram <AppIcon name="arrow-right" /></a><p v-if="!approvedName">Approve the request in the bot, then return here. This login expires in five minutes.</p><button v-else class="primary" :disabled="busy" @click="completeTelegramLogin">Continue as {{ approvedName }} <AppIcon name="arrow-right" /></button></div><p class="login-privacy">Free to use. Your first Telegram login creates your private account. Financial records are encrypted in the database.</p><p class="login-repository"><RepositoryLink /></p><p v-if="!config.telegram_username">Telegram sign-in is not configured yet. See the setup guide.</p><p v-if="error" class="error" role="alert">{{ error }}</p></section>
  </div>
  <div v-else class="shell">
    <aside class="sidebar"><a class="brand" aria-label="Budgenta home" href="#" @click.prevent="view = 'Overview'"><BrandLogo /></a><div class="workspace"><span class="avatar">{{ user.name.slice(0, 1) }}</span><div>Personal workspace<small>{{ user.name }}</small></div></div><span class="nav-label">YOUR FINANCES</span><nav><button v-for="(icon, title) in { Overview: 'overview', Accounts: 'card', Transactions: 'transfer', Savings: 'savings', Debts: 'debt', Goals: 'goal', Reports: 'report' }" :key="title" :title="title" :class="{ active: view === title }" @click="view = title"><span><AppIcon :name="icon" /></span>{{ title }}<b v-if="title === 'Accounts'">{{ groups.filter(g => !g.archived).length }}</b></button></nav><div class="side-note"><span><AppIcon name="star" /></span><h3>A little adds up.</h3><p>Check in with your money.<br>Make room for what matters.</p></div><button class="logout" title="Sign out" :disabled="busy" @click="run(async () => { await api('/auth/logout', {}); user = null })"><AppIcon name="logout" /> <span>Sign out</span></button></aside>
    <main><header><div class="breadcrumb">My workspace <span>/</span> {{ view }}</div><span class="private"><i></i> Private & personal</span></header>
      <div class="page-heading"><div><span class="eyebrow">LET’S MAKE ROOM FOR WHAT MATTERS</span><h1>{{ view === 'Overview' ? 'Your money, at a glance.' : view }}</h1><p>{{ view === 'Overview' ? 'A clear picture of where you are, and where you’re going.' : view === 'Savings' ? 'A home for what you set aside.' : view === 'Accounts' ? 'One account, all its currencies.' : view === 'Debts' ? 'What you owe, with a clear path forward.' : view === 'Goals' ? 'A little progress towards what matters.' : 'The little things that make up your month.' }}</p></div><button class="primary" :disabled="busy" @click="open(primaryAction)"><AppIcon name="plus" /> {{ actionLabels[primaryAction] }}</button></div>
      <p v-if="error && !modal" class="error" role="alert">{{ error }}</p>
      <div v-if="['Overview', 'Transactions', 'Reports'].includes(view)" class="toolbar"><div class="month-picker"><span><AppIcon name="calendar" /></span><input aria-label="Selected month" type="month" v-model="month" :max="today.slice(0, 7)" :disabled="busy" required></div><span class="muted"><AppIcon v-if="report.closed" name="check" />{{ report.closed ? 'Month closed' : 'Your monthly overview' }}</span></div>
      <template v-if="view === 'Overview'">
        <EstimatedBalance :balance="estimatedBalance" :loading="balanceLoading" :settings="reportSettings" :currencies="currencies" :api="api" @refresh="loadBalance" @changed="run(refresh)" @reports="view = 'Reports'" />
        <section class="overview-grid"><div class="balance-panel"><span class="eyebrow">TOTAL BALANCES</span><div v-if="totals.length" class="balance-values"><div v-for="[currency, amount] in totals" :key="currency"><strong>{{ money(amount, currency).replace(` ${currency}`, '') }}</strong><span>{{ currency }}</span></div></div><strong v-else class="blank-balance">A fresh start.</strong><p>{{ dashboardGroups.length }} {{ dashboardGroups.length === 1 ? 'account' : 'accounts' }} <span>·</span> Each currency kept separate</p><AppIcon class="balance-decoration" name="star" /></div><div class="monthly-panel"><div class="section-top"><h3>This month</h3><span class="pill">{{ monthLabel }}</span></div><p v-if="!activeTotals(dashboardReport.totals).length" class="muted">Add your first transaction to start seeing your monthly picture.</p><div v-for="t in activeTotals(dashboardReport.totals)" :key="t.currency" class="monthly-currency"><span class="currency-label">{{ t.currency }}</span><div v-for="row in activityRows(t)" :key="row.key"><span>{{ row.label }}</span><b>{{ money(row.amount, t.currency) }}</b></div><div v-if="Number(t.surplus) !== 0" class="surplus"><span>Income less expenses</span><b>{{ money(t.surplus, t.currency) }}</b></div></div></div></section>
      </template>
      <AccountsPage v-if="view === 'Overview' || view === 'Accounts'" :groups="shownGroups" :all-groups="groups" :settings="reportSettings.accounts_page" :currencies="config.currencies" :api="api" @changed="run(refresh)" @add-account="open('account')" @transfer="open('transfer')" @exchange="open('exchange')" />
      <div v-if="view === 'Transactions'" class="page-controls"><button class="secondary" @click="open('transfer')"><AppIcon name="transfer" /> Transfer</button><button class="secondary" @click="open('exchange')"><AppIcon name="exchange" /> Exchange</button></div><section v-if="view === 'Overview' || view === 'Transactions'" class="transactions-section"><div class="section-top"><h2>{{ view === 'Overview' ? 'Recent activity' : 'All transactions' }}</h2><button v-if="view === 'Overview'" class="text-button" @click="view = 'Transactions'">View all <AppIcon name="arrow-right" /></button><input v-else type="search" placeholder="Search transactions…" aria-label="Search transactions" v-model="search"></div><div v-if="!filtered.length" class="empty compact"><span><AppIcon name="transfer" /></span><h3>{{ search ? 'No matching transactions.' : 'Your story starts here.' }}</h3><p>{{ search ? 'Try another account or category.' : 'Add income or an expense to see your activity.' }}</p></div><div v-else class="table-scroll"><table><thead><tr><th>TRANSACTION</th><th>ACCOUNT</th><th>DATE</th><th class="align-right">AMOUNT</th><th>MANAGE</th></tr></thead><tbody><tr v-for="t in view === 'Overview' ? filtered.slice(0, 6) : filtered" :key="t.id"><td><div class="transaction-name"><span class="transaction-icon" :class="t.kind"><AppIcon :name="t.kind === 'income' ? 'arrow-down' : t.kind === 'expense' ? 'arrow-up' : 'transfer'" /></span><div><b>{{ t.category }}</b><small>{{ t.note || ({ income: 'Money in', expense: 'Money out', transfer: 'Between your accounts', exchange: 'Currency exchange', opening: 'Starting point', adjustment: 'Balance correction' }[t.kind]) }}</small></div></div></td><td>{{ t.account }}</td><td>{{ t.date }}</td><td class="align-right amount" :class="{ positive: Number(t.amount) > 0 }">{{ Number(t.amount) > 0 ? '+' : '' }}{{ money(t.amount, t.currency) }}</td><td><button class="text-button danger" :disabled="busy || !t.deletable" :title="t.deletion_issue || 'Delete and reverse this operation'" @click="deleteTransaction(t)">Delete</button></td></tr></tbody></table></div></section>
      <SavingsPanel v-if="view === 'Savings'" :accounts="accounts" :groups="groups" :goals="goals" :currencies="config.currencies" :rules="rules" :api="api" @changed="run(refresh)" @add-account="open('savings_account')" @goals="view = 'Goals'" />
      <ReportsPanel :currencies="currencies" v-if="view === 'Reports'" :report="monthlyReport" :settings="reportSettings" :groups="groups" :api="api" @changed="run(refresh)" @close-month="closeMonth" />
      <PlanningPanel v-if="view === 'Debts' || view === 'Goals'" :view="view" :debts="debts" :goals="goals" :api="api" @open="open" @changed="run(refresh)" @savings="view = 'Savings'" />
      <footer><span class="mini-brand"><BrandLogo compact /></span><RepositoryLink /><span>Your budget agent.</span></footer>
    </main>
    <MoneyMoveDialog ref="moneyMove" :accounts="accounts" :api="api" @changed="run(refresh)" />
    <dialog ref="dialog" @cancel="busy ? $event.preventDefault() : (modal = '')"><form @submit.prevent="submit"><div class="section-top"><h2>{{ form.edit_id ? (modal === 'goal' ? 'Edit goal & linked savings' : 'Edit debt') : modalTitles[modal] }}</h2><button type="button" aria-label="Close dialog" class="close" :disabled="busy" @click="dismiss"><AppIcon name="close" /></button></div><p class="muted">{{ modal === 'account' ? 'Start with what’s in your account today.' : 'Small details. A clearer picture.' }}</p><fieldset :disabled="busy"><template v-if="modal === 'debt' || modal === 'goal'"><label>Name<input v-model="form.name" required maxlength="80" :placeholder="modal === 'debt' ? 'e.g. Loan from Alex' : 'e.g. A home of my own'"></label><label>Currency<SearchSelect v-model="form.currency" :options="currencies" label="Currency" required /></label><label>{{ modal === 'debt' ? 'Amount owed' : 'Target amount' }}<input v-if="modal === 'debt'" v-model="form.amount" type="number" min="0.00000001" step="any" required><input v-else v-model="form.target" type="number" min="0.00000001" step="any" required></label><label v-if="modal === 'goal' && !form.savings_account_ids?.length">Already saved<input v-model="form.saved" type="number" min="0" step="any" placeholder="0.00"></label><div v-if="modal === 'goal'" class="goal-links"><h3>Attach savings</h3><p class="muted">Select savings balances in {{ form.currency }}. Linked progress follows their combined balance, replacing manual progress.</p><p v-if="!goalSavings.length" class="muted">Add a savings account in this currency first, or use manual progress.</p><label v-for="a in goalSavings" :key="a.id" class="check-label"><input type="checkbox" :value="a.id" v-model="form.savings_account_ids" :disabled="!!assignedGoal(a.id)">{{ a.name }} · {{ money(a.balance, a.currency) }}{{ assignedGoal(a.id) ? ` (linked to ${assignedGoal(a.id).name})` : '' }}</label><p v-if="form.edit_id && !form.savings_account_ids?.length" class="muted">Unlinking keeps the amount in Already saved as manual progress; your money stays in savings.</p></div><label>Due date (optional)<input v-model="form.due_date" type="date"></label><label>Note (optional)<input v-model="form.note" maxlength="300"></label><p class="muted">{{ modal === 'debt' ? 'Adding a debt does not change your account balances. Record repayments here to reduce the debt and log an expense.' : 'Linking savings tracks money already in your accounts. It does not transfer money or add to your total balance.' }}</p></template><template v-else-if="modal === 'repay'"><label>Pay from<SearchSelect v-model="form.account_id" :options="paymentAccounts" value-key="id" :option-label="a => `${a.name} · ${a.currency}`" label="Pay from" placeholder="Choose an account" required /></label><p v-if="!paymentAccounts.length" class="muted">Add an account in the debt currency first.</p><AmountInput v-model="form.amount" label="Repayment amount" :account-id="form.account_id" :balance="entryAccount?.balance" :limit="form.max_amount" hint="Use available funds, up to the remaining debt" /><p class="muted">This reduces your debt and records a Debts expense.</p></template><template v-else-if="modal === 'progress'"><label>Total saved so far<input v-model="form.saved" type="number" min="0" step="any" required></label><p class="muted">Sets your goal's progress without changing account balances.</p></template><template v-else-if="modal === 'account'"><label>Account name<input v-model="form.name" required maxlength="80" placeholder="e.g. Everyday cash" autofocus></label><div class="form-row"><label>Account type<SearchSelect v-model="form.kind" :options="Object.entries(titles).map(([value, label]) => ({ value, label }))" label="Account type" required /></label><label>Currency<SearchSelect v-model="form.currency" :options="options" label="Currency" required /></label></div><label>Opening balance<input v-model="form.opening_balance" type="number" min="0" step="any" placeholder="0.00"></label><div class="additional-currencies"><p class="muted">Add more currencies to this account</p><div v-for="c in options.filter(c => c !== form.currency)" :key="c"><label class="check-label"><input type="checkbox" :value="c" v-model="form.extra_currencies">{{ c }}</label><label v-if="form.extra_currencies.includes(c)">{{ c }} opening balance<input :aria-label="`${c} opening balance`" v-model="form.extra_balances[c]" type="number" min="0" step="any" placeholder="0"></label></div></div></template><template v-else><div class="segmented"><button type="button" :class="{ selected: form.kind === 'expense' }" @click="form.kind = 'expense'"><AppIcon name="arrow-up" /> Expense</button><button type="button" :class="{ selected: form.kind === 'income' }" @click="form.kind = 'income'"><AppIcon name="arrow-down" /> Income</button></div><label>Account<SearchSelect v-model="form.account_id" :options="accounts" value-key="id" :option-label="a => `${a.name} · ${a.currency}`" label="Account" placeholder="Choose an account" required /></label><AmountInput v-model="form.amount" label="Amount" :account-id="form.account_id" :balance="entryAccount?.balance" :show-all="form.kind === 'expense'" /><label>Category<SearchSelect v-model="form.category" :options="entryCategories" label="Category" :placeholder="form.kind === 'expense' ? 'Choose a category, e.g. Grocery' : 'Choose a category, e.g. Salary'" allow-custom required :maxlength="60" /></label><p class="muted">Choose a category or type your own purpose, such as Watches or Money from parents.</p><label v-if="customCategory" class="check-label"><input type="checkbox" v-model="form.save_category">Save category for future use</label><small v-if="customCategory" class="muted">Leave unchecked to use it only for this transaction.</small><label>Note <span class="muted">(optional)</span><input v-model="form.note" maxlength="300" placeholder="What was it for?"></label></template><label v-if="['account', 'entry', 'repay'].includes(modal)">Date<input type="date" v-model="form.date" :max="today" required></label></fieldset><p v-if="error" class="error" role="alert">{{ error }}</p><div class="form-actions"><button type="button" class="secondary" :disabled="busy" @click="dismiss">Cancel</button><button class="primary" :disabled="busy">{{ busy ? 'Saving…' : 'Save' }} <AppIcon name="arrow-right" /></button></div></form></dialog>
  </div>
</template>
