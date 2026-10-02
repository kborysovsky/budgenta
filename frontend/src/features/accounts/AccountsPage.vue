<script setup>
import AppIcon from '../../components/AppIcon.vue'
import { ref, computed, watch } from 'vue'
import AccountsPanel from './AccountsPanel.vue'
const props = defineProps({ groups: Array, allGroups: Array, settings: Object, currencies: Object, api: Function })
const emit = defineEmits(['changed', 'add-account', 'transfer', 'exchange'])
const configuring = ref(false), busy = ref(false), error = ref(''), draft = ref({})
const sections = [{ id: 'debit', label: 'Debit', description: 'Cash, debit cards, and wallets' }, { id: 'credit', label: 'Credit', description: 'Credit cards' }, { id: 'savings', label: 'Savings', description: 'Money set aside' }]
const sectionFor = group => group.kind === 'savings' ? 'savings' : group.kind === 'card' ? 'credit' : 'debit'
const defaults = { show_debit: true, show_credit: true, show_savings: true, order: [] }
const preference = computed(() => ({ ...defaults, ...props.settings }))
const sort = (groups, order) => [...groups].sort((a, b) => { const rank = id => order.includes(id) ? order.indexOf(id) : order.length; return rank(a.id) - rank(b.id) || a.id - b.id })
const ordered = computed(() => sort(props.groups, preference.value.order))
const draftGroups = computed(() => sort(props.allGroups || props.groups, draft.value.order || []))
const visibleSections = computed(() => sections.filter(section => preference.value[`show_${section.id}`] && ordered.value.some(g => sectionFor(g) === section.id)))
const activeCount = computed(() => ordered.value.filter(g => !g.archived && preference.value[`show_${sectionFor(g)}`]).length)
watch(() => props.settings, () => { if (!configuring.value) resetDraft() }, { immediate: true, deep: true })
function resetDraft() { draft.value = JSON.parse(JSON.stringify(preference.value)) }
function configure() { resetDraft(); error.value = ''; configuring.value = !configuring.value }
function move(group, direction) {
  const siblings = draftGroups.value.filter(g => !g.archived && sectionFor(g) === sectionFor(group))
  const index = siblings.findIndex(g => g.id === group.id), other = siblings[index + direction]
  if (!other) return
  const order = draftGroups.value.map(g => g.id), from = order.indexOf(group.id), to = order.indexOf(other.id)
  ;[order[from], order[to]] = [order[to], order[from]]
  draft.value.order = order
}
async function save() {
  busy.value = true; error.value = ''
  try { await props.api('/preferences/accounts-page', draft.value); configuring.value = false; emit('changed') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <section class="accounts-section">
    <div class="section-top"><h2>Your accounts <span class="count">{{ activeCount }}</span></h2><div class="page-controls"><button class="secondary" aria-label="Configure accounts page" :aria-expanded="configuring" @click="configure"><AppIcon name="settings" /> Page settings</button><button class="text-button" @click="$emit('add-account')"><AppIcon name="plus" /> Add account</button></div></div>
    <form v-if="configuring" class="accounts-page-settings" @submit.prevent="save"><h3>Account sections & order</h3><p class="muted">Hide sections you do not use. This changes the account list; balance totals and report filters have their own settings.</p><fieldset :disabled="busy">
      <label v-for="section in sections" :key="section.id" class="check-label"><input type="checkbox" v-model="draft[`show_${section.id}`]">Show {{ section.label }} section</label>
      <div v-for="section in sections" :key="section.id" class="order-section"><h4>{{ section.label }}</h4><p v-if="!draftGroups.some(g => !g.archived && sectionFor(g) === section.id)" class="muted">No active accounts in this section.</p><div v-for="(group, index) in draftGroups.filter(g => !g.archived && sectionFor(g) === section.id)" :key="group.id" class="account-order-row"><span>{{ group.name }}</span><div><button type="button" class="secondary order-button" :aria-label="`Move ${group.name} up`" :disabled="index === 0" @click="move(group, -1)"><AppIcon name="arrow-up" /></button><button type="button" class="secondary order-button" :aria-label="`Move ${group.name} down`" :disabled="index === draftGroups.filter(g => !g.archived && sectionFor(g) === section.id).length - 1" @click="move(group, 1)"><AppIcon name="arrow-down" /></button></div></div></div>
      <p class="muted">Accounts move within their section. Savings stays at the bottom. New accounts are added at the end.</p>
    </fieldset><p v-if="error" class="error" role="alert">{{ error }}</p><div class="form-actions"><button type="button" class="secondary" :disabled="busy" @click="configuring = false">Cancel</button><button class="primary" :disabled="busy">Save account layout</button></div></form>
    <p v-if="!visibleSections.length" class="empty">No accounts visible. Add an account or enable a section in Page settings.</p>
    <section v-for="section in visibleSections" :key="section.id" class="account-category" :aria-label="`${section.label} accounts`"><div class="section-top"><div><h3>{{ section.label }}</h3><p class="muted">{{ section.description }}</p></div></div><AccountsPanel :groups="ordered.filter(g => sectionFor(g) === section.id)" :all-groups="allGroups || groups" :currencies="currencies" :api="api" @changed="$emit('changed')" /></section>
    <div class="page-controls"><button class="secondary" @click="$emit('transfer')"><AppIcon name="transfer" /> Transfer between accounts</button><button class="secondary" @click="$emit('exchange')"><AppIcon name="exchange" /> Exchange currencies</button></div>
  </section>
</template>
