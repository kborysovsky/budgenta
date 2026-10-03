<script setup>
import { ref, onMounted } from 'vue'
import { t, categoryLabel } from '../../i18n.js'
const props = defineProps({ api: Function })
const emit = defineEmits(['changed', 'close'])
const categories = ref({ expense: [], income: [] }), busy = ref(false), error = ref('')
onMounted(async () => { try { categories.value = await props.api('/categories/manage') } catch (e) { error.value = e.message } })
async function change(kind, category) {
  if (!category.removed && !window.confirm(t('Remove {name} from category choices? Past transactions and reports stay unchanged.', { name: categoryLabel(category.name, kind) }))) return
  busy.value = true; error.value = ''
  try { categories.value = await props.api('/categories/change', { kind, name: category.name, removed: !category.removed }); emit('changed') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <section class="report-settings category-manager">
    <div class="section-top"><h2>{{ t('Manage categories') }}</h2><button class="secondary" @click="$emit('close')">{{ t('Close') }}</button></div>
    <p class="muted">{{ t('Remove categories you no longer use. Past transactions stay unchanged. Default categories can be restored; custom categories can be saved again when adding a transaction.') }}</p>
    <p v-if="error" class="error" role="alert">{{ t(error) }}</p>
    <div class="planning-grid"><div v-for="kind in ['expense', 'income']" :key="kind"><h3>{{ t(kind === 'expense' ? 'Expenses' : 'Income') }}</h3><div v-for="category in categories[kind]" :key="category.name" class="category-row"><span :class="{ muted: category.removed }">{{ categoryLabel(category.name, kind) }}</span><button class="secondary" :disabled="busy" @click="change(kind, category)">{{ t(category.removed ? 'Restore' : 'Remove') }}</button></div></div></div>
  </section>
</template>
<style scoped>
.category-manager { margin-bottom: 24px; }
.category-row { gap: 12px; }
.category-row > span { overflow-wrap: anywhere; }
.category-row button { flex-shrink: 0; }
</style>
