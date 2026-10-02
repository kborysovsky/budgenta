<script setup>
defineProps({ compact: Boolean })
</script>
<template>
  <span class="brand-logo" :class="{ compact }"><img src="/budgenta-mark.svg" alt="" width="36" height="36"><span>Budgenta</span></span>
</template>
<style scoped>
.brand-logo { display: inline-flex; align-items: center; gap: 9px; white-space: nowrap; font-family: 'Manrope', sans-serif; font-weight: 800; letter-spacing: -.8px; }
.brand-logo img { display: block; flex-shrink: 0; }
.brand-logo.compact { font-size: 15px; gap: 6px; letter-spacing: -.4px; }
.brand-logo.compact img { width: 22px; height: 22px; }
</style>
