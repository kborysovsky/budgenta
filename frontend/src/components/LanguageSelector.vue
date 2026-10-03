<script setup>
import { languages, locale, t } from '../i18n.js'
defineProps({ disabled: Boolean })
defineEmits(['change'])
</script>
<template>
  <label class="language-selector"><span>{{ t('Language') }}</span><select :aria-label="t('Language')" :value="locale" :disabled="disabled" @change="$emit('change', $event.target.value)"><option v-for="(name, code) in languages" :key="code" :value="code" :lang="code">{{ name }}</option></select></label>
</template>
<style scoped>
.language-selector { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 13px; }
.language-selector select { margin: 0; width: auto; min-height: 40px; max-width: 160px; padding: 8px 10px; }
@media (max-width: 600px) { .language-selector > span { display: none; } }
</style>
