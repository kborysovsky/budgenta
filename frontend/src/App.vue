<script setup>
import { t, numberLocale, setLanguage, categoryLabel } from './i18n.js'
import LanguageSelector from './components/LanguageSelector.vue'
import CategoriesPanel from './features/transactions/CategoriesPanel.vue'
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
import BudgetLimitsPanel from './features/budgets/BudgetLimitsPanel.vue'
import BudgetUsage from './features/budgets/BudgetUsage.vue'
import AccountsPage from './features/accounts/AccountsPage.vue'
const today = new Date().toLocaleDateString('en-CA')
const month = ref(today.slice(0, 7)), view = ref('Overview'), user = ref(null), config = ref({ currencies: {} })
const groups = ref([]), dashboardReport = ref({ totals: [], transactions: [] })
const accounts = ref([]), report = ref({ totals: [], transactions: [] }), savings = ref([]), rules = ref([]), monthlyReport = ref({ totals: [], categories: [] }), reportSettings = ref({}), debts = ref([]), goals = ref([]), estimatedBalance = ref(null), balanceLoading = ref(false)
const error = ref(''), busy = ref(false), loading = ref(true), modal = ref(''), search = ref('')
const form = ref({}), dialog = ref(null), moneyMove = ref(null)
const managingCategories = ref(false)
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
const money = (amount, currency) => `${new Intl.NumberFormat(numberLocale.value, { minimumFractionDigits: 2, maximumFractionDigits: ['BTC', 'ETH'].includes(currency) ? 8 : ['USDT', 'TRX'].includes(currency) ? 6 : 2 }).format(Number(amount))} ${currency}`
const totals = computed(() => {
  const result = {}
  dashboardAccounts.value.forEach(a => { result[a.currency] = (result[a.currency] || 0) + Number(a.balance) })
  return Object.entries(result)
})
const dashboardGroups = computed(() => groups.value.filter(g => !g.archived && (reportSettings.value.dashboard?.include_savings !== false || g.kind !== 'savings') && (reportSettings.value.dashboard?.account_ids == null || reportSettings.value.dashboard.account_ids.includes(g.id))).map(g => ({ ...g, balances: g.balances.filter(b => !reportSettings.value.dashboard?.excluded_currencies?.includes(b.currency)) })).filter(g => g.balances.length))
const dashboardAccounts = computed(() => dashboardGroups.value.flatMap(g => g.balances))
const shownGroups = computed(() => view.value === 'Overview' ? dashboardGroups.value : groups.value)
const filtered = computed(() => (view.value === 'Overview' ? dashboardReport.value : report.value).transactions.filter(t => view.value !== 'Transactions' || `${t.account} ${categoryLabel(t.category, t.kind)} ${t.category} ${t.note}`.toLowerCase().includes(search.value.toLowerCase())))
const options = computed(() => config.value.currencies[form.value.kind] || [])
const monthLabel = computed(() => new Date(`${month.value}-02T12:00:00`).toLocaleDateString(numberLocale.value, { month: 'long', year: 'numeric' }))
async function api(path, body) {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
  const data = await response.json()
  if (!response.ok) {
    if (response.status === 401) user.value = null
    throw new Error(typeof data.detail === 'string' ? data.detail : (Array.isArray(data.detail) ? 'Check the amount, date, and required fields.' : '') || 'Something went wrong. Please try again.')
  }
  return data
}
async function refresh() {
  const [a, r, s, d, g, sr, mr, rs, ag, dr, categories] = await Promise.all([api('/accounts'), api(`/months/${month.value}`), api('/savings'), api('/debts?include_archived=true'), api('/goals?include_archived=true'), api('/savings/rules?include_archived=true'), api(`/reports/${month.value}`), api('/preferences'), api('/account-groups?include_archived=true'), api(`/dashboard/${month.value}`), api('/categories')])
  accounts.value = a; report.value = r; savings.value = s; debts.value = d; goals.value = g; rules.value = sr; monthlyReport.value = mr; reportSettings.value = rs; setLanguage(rs.language || 'en'); groups.value = ag; dashboardReport.value = dr; categoryChoices.value = categories
  loadBalance()
}
async function changeLanguage(language) {
  if (user.value) {
    await run(async () => { const prefs = await api('/preferences/language', { language }); reportSettings.value = prefs; setLanguage(language) })
  } else setLanguage(language)
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
  if (!window.confirm(t("Delete {v0} ({v1} {v2})? This reverses the entire operation, including linked transfers, exchanges, and debt repayments, and updates reports.", { v0: categoryLabel(entry.category, entry.kind), v1: entry.amount, v2: entry.currency }))) return
  await run(async () => { await api(`/entries/${entry.id}/delete`, {}); await refresh() })
}
async function closeMonth() {
  if (!window.confirm(t("Close {v0}? Transactions through this month will be locked. New backdated entries will be blocked; corrections by deletion remain possible.", { v0: monthLabel.value }))) return
  await run(async () => { await api('/months/close', { month: month.value }); await refresh() })
}
onMounted(async () => {
  try { config.value = await api('/config'); try { user.value = await api('/me') } catch (e) { if (e.message !== 'Sign in to continue.') throw e }; if (user.value) await refresh() }
  catch (e) { error.value = e.message } finally { loading.value = false }
})
</script>

<template>
  <div v-if="loading" class="loading">{{ $t("Getting Budgenta ready…") }}</div>
  <div v-else-if="!user" class="login-page">
    <div class="login-language"><LanguageSelector :disabled="busy" @change="changeLanguage" /></div><div class="login-art"><div class="brand"><BrandLogo /></div><div><span class="eyebrow">{{ $t("YOUR BUDGET AGENT") }}</span><h1>{{ $t("Big plans.") }}<br>{{ $t("Small, simple") }}<br>{{ $t("money habits.") }}</h1><p>{{ $t("All your accounts. Every currency.") }}<br>{{ $t("A little more peace of mind.") }}</p></div><span class="login-foot">{{ $t("Budgenta · Your budget agent.") }}</span></div>
    <section class="login-card"><span class="eyebrow">{{ $t("WELCOME TO BUDGENTA") }}</span><h2>{{ $t("Make yourself at home.") }}</h2><p>{{ $t("Sign in with Telegram to see your budget.") }}</p><button class="primary telegram-button" :disabled="busy || !config.telegram_username" @click="startTelegramLogin"><AppIcon name="telegram" /> {{ $t("Log in with Telegram") }}</button><div v-if="loginChallenge" class="login-challenge"><p>{{ $t("Match this code in Telegram:") }} <strong>{{ loginChallenge.code }}</strong></p><div class="telegram-login-links">
          <a class="secondary" :href="loginChallenge.url" target="_blank" rel="noopener noreferrer">{{ $t("Open Telegram app") }} <AppIcon name="arrow-right" /></a>
          <a class="secondary" :href="loginChallenge.web_a_url" target="_blank" rel="noopener noreferrer">{{ $t("Open Telegram Web") }} <AppIcon name="arrow-right" /></a>
        </div><p v-if="!approvedName">{{ $t("Choose your Telegram app or web version. Press Start if prompted, approve the matching code, then return to this tab. This login expires in five minutes.") }}</p><button v-else class="primary" :disabled="busy" @click="completeTelegramLogin">{{ $t("Continue as") }} {{ approvedName }} <AppIcon name="arrow-right" /></button></div><p class="login-privacy">{{ $t("Free to use. Your first Telegram login creates your private account. Financial records are encrypted in the database.") }}</p><p class="login-repository"><RepositoryLink /></p><p v-if="!config.telegram_username">{{ $t("Telegram sign-in is not configured yet. See the setup guide.") }}</p><p v-if="error" class="error" role="alert">{{ $error(error) }}</p></section>
  </div>
  <div v-else class="shell">
    <aside class="sidebar"><a class="brand" :aria-label="$t(&quot;Budgenta home&quot;)" href="#" @click.prevent="view = 'Overview'"><BrandLogo /></a><div class="workspace"><span class="avatar">{{ user.name.slice(0, 1) }}</span><div>{{ $t("Personal workspace") }}<small>{{ user.name }}</small></div></div><span class="nav-label">{{ $t("YOUR FINANCES") }}</span><nav><button v-for="(icon, title) in { Overview: 'overview', Accounts: 'card', Transactions: 'transfer', Savings: 'savings', Debts: 'debt', Goals: 'goal', Budgets: 'report', Reports: 'report' }" :key="title" :title="$t(title)" :class="{ active: view === title }" @click="view = title"><span><AppIcon :name="icon" /></span>{{ $t(title) }}<b v-if="title === 'Accounts'">{{ groups.filter(g => !g.archived).length }}</b></button></nav><div class="side-note"><span><AppIcon name="star" /></span><h3>{{ $t("A little adds up.") }}</h3><p>{{ $t("Check in with your money.") }}<br>{{ $t("Make room for what matters.") }}</p></div><button class="logout" :title="$t(&quot;Sign out&quot;)" :disabled="busy" @click="run(async () => { await api('/auth/logout', {}); user = null })"><AppIcon name="logout" /> <span>{{ $t("Sign out") }}</span></button></aside>
    <main><header><div class="breadcrumb">{{ $t("My workspace") }} <span>/</span> {{ $t(view) }}</div><div class="header-tools"><span class="private"><i></i> {{ $t("Private & personal") }}</span><LanguageSelector :disabled="busy" @change="changeLanguage" /></div></header>
      <div class="page-heading"><div><span class="eyebrow">{{ $t("LET’S MAKE ROOM FOR WHAT MATTERS") }}</span><h1>{{ view === 'Overview' ? $t("Your money, at a glance.") : $t(view) }}</h1><p>{{ view === 'Budgets' ? $t('Your monthly spending limits.') : view === 'Overview' ? $t("A clear picture of where you are, and where you’re going.") : view === 'Savings' ? $t("A home for what you set aside.") : view === 'Accounts' ? $t("One account, all its currencies.") : view === 'Debts' ? $t("What you owe, with a clear path forward.") : view === 'Goals' ? $t("A little progress towards what matters.") : $t("The little things that make up your month.") }}</p></div><button v-if="view !== 'Budgets'" class="primary" :disabled="busy" @click="open(primaryAction)"><AppIcon name="plus" /> {{ $t(actionLabels[primaryAction]) }}</button></div>
      <p v-if="error && !modal" class="error" role="alert">{{ $error(error) }}</p>
      <div v-if="['Overview', 'Transactions', 'Reports', 'Budgets'].includes(view)" class="toolbar"><div class="month-picker"><span><AppIcon name="calendar" /></span><input :aria-label="$t(&quot;Selected month&quot;)" type="month" v-model="month" :max="today.slice(0, 7)" :disabled="busy" required></div><span class="muted"><AppIcon v-if="report.closed" name="check" />{{ report.closed ? $t("Month closed") : $t("Your monthly overview") }}</span></div>
      <template v-if="view === 'Overview'">
        <EstimatedBalance :balance="estimatedBalance" :loading="balanceLoading" :settings="reportSettings" :currencies="currencies" :api="api" @refresh="loadBalance" @changed="run(refresh)" @reports="view = 'Reports'" />
        <section class="overview-grid"><div class="balance-panel"><span class="eyebrow">{{ $t("TOTAL BALANCES") }}</span><div v-if="totals.length" class="balance-values"><div v-for="[currency, amount] in totals" :key="currency"><strong>{{ money(amount, currency).replace(` ${currency}`, '') }}</strong><span>{{ currency }}</span></div></div><strong v-else class="blank-balance">{{ $t("A fresh start.") }}</strong><p>{{ $t('Accounts: {count}', { count: dashboardGroups.length }) }} <span>·</span> {{ $t("Each currency kept separate") }}</p><AppIcon class="balance-decoration" name="star" /></div><div class="monthly-panel"><div class="section-top"><h3>{{ $t("This month") }}</h3><span class="pill">{{ monthLabel }}</span></div><p v-if="!activeTotals(dashboardReport.totals).length" class="muted">{{ $t("Add your first transaction to start seeing your monthly picture.") }}</p><div v-for="t in activeTotals(dashboardReport.totals)" :key="t.currency" class="monthly-currency"><span class="currency-label">{{ t.currency }}</span><div v-for="row in activityRows(t)" :key="row.key"><span>{{ $t(row.label) }}</span><b>{{ money(row.amount, t.currency) }}</b></div><div v-if="Number(t.surplus) !== 0" class="surplus"><span>{{ $t("Income less expenses") }}</span><b>{{ money(t.surplus, t.currency) }}</b></div></div></div></section>
      </template>
      <BudgetLimitsPanel v-if="view === 'Budgets'" :api="api" :month="month" :currencies="currencies" :categories="categoryChoices.expense" @changed="run(refresh)" />
      <BudgetUsage v-if="view === 'Overview'" :data="dashboardReport.budgets" :show-rates="reportSettings.dashboard?.include_rates" title />
      <AccountsPage v-if="view === 'Overview' || view === 'Accounts'" :groups="shownGroups" :all-groups="groups" :settings="reportSettings.accounts_page" :currencies="config.currencies" :api="api" @changed="run(refresh)" @add-account="open('account')" @transfer="open('transfer')" @exchange="open('exchange')" />
      <CategoriesPanel v-if="view === 'Transactions' && managingCategories" :api="api" @changed="run(refresh)" @close="managingCategories = false" /><div v-if="view === 'Transactions'" class="page-controls"><button class="secondary" @click="managingCategories = !managingCategories">{{ $t("Manage categories") }}</button><button class="secondary" @click="open('transfer')"><AppIcon name="transfer" /> {{ $t("Transfer") }}</button><button class="secondary" @click="open('exchange')"><AppIcon name="exchange" /> {{ $t("Exchange") }}</button></div><section v-if="view === 'Overview' || view === 'Transactions'" class="transactions-section"><div class="section-top"><h2>{{ view === 'Overview' ? $t("Recent activity") : $t("All transactions") }}</h2><button v-if="view === 'Overview'" class="text-button" @click="view = 'Transactions'">{{ $t("View all") }} <AppIcon name="arrow-right" /></button><input v-else type="search" :placeholder="$t(&quot;Search transactions…&quot;)" :aria-label="$t(&quot;Search transactions&quot;)" v-model="search"></div><div v-if="!filtered.length" class="empty compact"><span><AppIcon name="transfer" /></span><h3>{{ search ? $t("No matching transactions.") : $t("Your story starts here.") }}</h3><p>{{ search ? $t("Try another account or category.") : $t("Add income or an expense to see your activity.") }}</p></div><div v-else class="table-scroll"><table><thead><tr><th>{{ $t("TRANSACTION") }}</th><th>{{ $t("ACCOUNT") }}</th><th>{{ $t("DATE") }}</th><th class="align-right">{{ $t("AMOUNT") }}</th><th>{{ $t("MANAGE") }}</th></tr></thead><tbody><tr v-for="t in view === 'Overview' ? filtered.slice(0, 6) : filtered" :key="t.id"><td><div class="transaction-name"><span class="transaction-icon" :class="t.kind"><AppIcon :name="t.kind === 'income' ? 'arrow-down' : t.kind === 'expense' ? 'arrow-up' : 'transfer'" /></span><div><b>{{ ['income', 'expense'].includes(t.kind) ? $category(t.category, t.kind) : $t(t.category) }}</b><small>{{ t.note || ({ income: $t("Money in"), expense: $t("Money out"), transfer: $t("Between your accounts"), exchange: $t("Currency exchange"), opening: $t("Starting point"), adjustment: $t("Balance correction") }[t.kind]) }}</small></div></div></td><td>{{ t.account }}</td><td>{{ t.date }}</td><td class="align-right amount" :class="{ positive: Number(t.amount) > 0 }">{{ Number(t.amount) > 0 ? '+' : '' }}{{ money(t.amount, t.currency) }}</td><td><button class="text-button danger" :disabled="busy || !t.deletable" :title="t.deletion_issue || $t(&quot;Delete and reverse this operation&quot;)" @click="deleteTransaction(t)">{{ $t("Delete") }}</button></td></tr></tbody></table></div></section>
      <SavingsPanel v-if="view === 'Savings'" :accounts="accounts" :groups="groups" :goals="goals" :currencies="config.currencies" :rules="rules" :api="api" @changed="run(refresh)" @add-account="open('savings_account')" @goals="view = 'Goals'" />
      <ReportsPanel :currencies="currencies" v-if="view === 'Reports'" :report="monthlyReport" :settings="reportSettings" :groups="groups" :api="api" @changed="run(refresh)" @close-month="closeMonth" />
      <PlanningPanel v-if="view === 'Debts' || view === 'Goals'" :view="view" :debts="debts" :goals="goals" :api="api" @open="open" @changed="run(refresh)" @savings="view = 'Savings'" />
      <footer><span class="mini-brand"><BrandLogo compact /></span><RepositoryLink /><span>{{ $t("Your budget agent.") }}</span></footer>
    </main>
    <MoneyMoveDialog ref="moneyMove" :accounts="accounts" :api="api" @changed="run(refresh)" />
    <dialog ref="dialog" @cancel="busy ? $event.preventDefault() : (modal = '')"><form @submit.prevent="submit"><div class="section-top"><h2>{{ form.edit_id ? (modal === 'goal' ? $t("Edit goal & linked savings") : $t("Edit debt")) : $t(modalTitles[modal]) }}</h2><button type="button" :aria-label="$t(&quot;Close dialog&quot;)" class="close" :disabled="busy" @click="dismiss"><AppIcon name="close" /></button></div><p class="muted">{{ modal === 'account' ? $t("Start with what’s in your account today.") : $t("Small details. A clearer picture.") }}</p><fieldset :disabled="busy"><template v-if="modal === 'debt' || modal === 'goal'"><label>{{ $t("Name") }}<input v-model="form.name" required maxlength="80" :placeholder="modal === 'debt' ? $t(&quot;e.g. Loan from Alex&quot;) : $t(&quot;e.g. A home of my own&quot;)"></label><label>{{ $t("Currency") }}<SearchSelect v-model="form.currency" :options="currencies" :label="$t(&quot;Currency&quot;)" required /></label><label>{{ modal === 'debt' ? $t("Amount owed") : $t("Target amount") }}<input v-if="modal === 'debt'" v-model="form.amount" type="number" min="0.00000001" step="any" required><input v-else v-model="form.target" type="number" min="0.00000001" step="any" required></label><label v-if="modal === 'goal' && !form.savings_account_ids?.length">{{ $t("Already saved") }}<input v-model="form.saved" type="number" min="0" step="any" placeholder="0.00"></label><div v-if="modal === 'goal'" class="goal-links"><h3>{{ $t("Attach savings") }}</h3><p class="muted">{{ $t("Select savings balances in") }} {{ form.currency }}{{ $t(". Linked progress follows their combined balance, replacing manual progress.") }}</p><p v-if="!goalSavings.length" class="muted">{{ $t("Add a savings account in this currency first, or use manual progress.") }}</p><label v-for="a in goalSavings" :key="a.id" class="check-label"><input type="checkbox" :value="a.id" v-model="form.savings_account_ids" :disabled="!!assignedGoal(a.id)">{{ a.name }} · {{ money(a.balance, a.currency) }}{{ assignedGoal(a.id) ? $t(" (linked to {v0})", { v0: assignedGoal(a.id).name }) : '' }}</label><p v-if="form.edit_id && !form.savings_account_ids?.length" class="muted">{{ $t("Unlinking keeps the amount in Already saved as manual progress; your money stays in savings.") }}</p></div><label>{{ $t("Due date (optional)") }}<input v-model="form.due_date" type="date"></label><label>{{ $t("Note (optional)") }}<input v-model="form.note" maxlength="300"></label><p class="muted">{{ modal === 'debt' ? $t("Adding a debt does not change your account balances. Record repayments here to reduce the debt and log an expense.") : $t("Linking savings tracks money already in your accounts. It does not transfer money or add to your total balance.") }}</p></template><template v-else-if="modal === 'repay'"><label>{{ $t("Pay from") }}<SearchSelect v-model="form.account_id" :options="paymentAccounts" value-key="id" :option-label="a => `${a.name} · ${a.currency}`" :label="$t(&quot;Pay from&quot;)" :placeholder="$t(&quot;Choose an account&quot;)" required /></label><p v-if="!paymentAccounts.length" class="muted">{{ $t("Add an account in the debt currency first.") }}</p><AmountInput v-model="form.amount" :label="$t(&quot;Repayment amount&quot;)" :account-id="form.account_id" :balance="entryAccount?.balance" :limit="form.max_amount" :hint="$t(&quot;Use available funds, up to the remaining debt&quot;)" /><p class="muted">{{ $t("This reduces your debt and records a Debts expense.") }}</p></template><template v-else-if="modal === 'progress'"><label>{{ $t("Total saved so far") }}<input v-model="form.saved" type="number" min="0" step="any" required></label><p class="muted">{{ $t("Sets your goal's progress without changing account balances.") }}</p></template><template v-else-if="modal === 'account'"><label>{{ $t("Account name") }}<input v-model="form.name" required maxlength="80" :placeholder="$t(&quot;e.g. Everyday cash&quot;)" autofocus></label><div class="form-row"><label>{{ $t("Account type") }}<SearchSelect v-model="form.kind" :options="Object.entries(titles).map(([value, label]) => ({ value, label: t(label) }))" :label="$t(&quot;Account type&quot;)" required /></label><label>{{ $t("Currency") }}<SearchSelect v-model="form.currency" :options="options" :label="$t(&quot;Currency&quot;)" required /></label></div><label>{{ $t("Opening balance") }}<input v-model="form.opening_balance" type="number" min="0" step="any" placeholder="0.00"></label><div class="additional-currencies"><p class="muted">{{ $t("Add more currencies to this account") }}</p><div v-for="c in options.filter(c => c !== form.currency)" :key="c"><label class="check-label"><input type="checkbox" :value="c" v-model="form.extra_currencies">{{ c }}</label><label v-if="form.extra_currencies.includes(c)">{{ c }} {{ $t("opening balance") }}<input :aria-label="$t(&quot;{v0} opening balance&quot;, { v0: c })" v-model="form.extra_balances[c]" type="number" min="0" step="any" placeholder="0"></label></div></div></template><template v-else><div class="segmented"><button type="button" :class="{ selected: form.kind === 'expense' }" @click="form.kind = 'expense'"><AppIcon name="arrow-up" /> {{ $t("Expense") }}</button><button type="button" :class="{ selected: form.kind === 'income' }" @click="form.kind = 'income'"><AppIcon name="arrow-down" /> {{ $t("Income") }}</button></div><label>{{ $t("Account") }}<SearchSelect v-model="form.account_id" :options="accounts" value-key="id" :option-label="a => `${a.name} · ${a.currency}`" :label="$t(&quot;Account&quot;)" :placeholder="$t(&quot;Choose an account&quot;)" required /></label><AmountInput v-model="form.amount" :label="$t(&quot;Amount&quot;)" :account-id="form.account_id" :balance="entryAccount?.balance" :show-all="form.kind === 'expense'" /><label>{{ $t("Category") }}<SearchSelect v-model="form.category" :options="entryCategories" :option-label="name => categoryLabel(name, form.kind)" :label="$t(&quot;Category&quot;)" :placeholder="form.kind === 'expense' ? $t(&quot;Choose a category, e.g. Grocery&quot;) : $t(&quot;Choose a category, e.g. Salary&quot;)" allow-custom required :maxlength="60" /></label><p class="muted">{{ $t("Choose a category or type your own purpose, such as Watches or Money from parents.") }}</p><label v-if="customCategory" class="check-label"><input type="checkbox" v-model="form.save_category">{{ $t("Save category for future use") }}</label><small v-if="customCategory" class="muted">{{ $t("Leave unchecked to use it only for this transaction.") }}</small><label>{{ $t("Note") }} <span class="muted">{{ $t("(optional)") }}</span><input v-model="form.note" maxlength="300" :placeholder="$t(&quot;What was it for?&quot;)"></label></template><label v-if="['account', 'entry', 'repay'].includes(modal)">{{ $t("Date") }}<input type="date" v-model="form.date" :max="today" required></label></fieldset><p v-if="error" class="error" role="alert">{{ $error(error) }}</p><div class="form-actions"><button type="button" class="secondary" :disabled="busy" @click="dismiss">{{ $t("Cancel") }}</button><button class="primary" :disabled="busy">{{ busy ? $t("Saving…") : $t("Save") }} <AppIcon name="arrow-right" /></button></div></form></dialog>
  </div>
</template>
