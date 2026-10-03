<script setup>
import AppIcon from './AppIcon.vue'
</script>
<template>
  <a class="repository-link" href="https://github.com/kborysovsky/budgenta" target="_blank" rel="noopener noreferrer" :aria-label="$t(&quot;Budgenta source code on GitHub (opens in a new tab)&quot;)">{{ $t("Open source on GitHub") }} <AppIcon name="arrow-up-right" /></a>
</template>

<style scoped>
.repository-link { color: inherit; text-underline-offset: 3px; white-space: nowrap; }
.repository-link:hover { text-decoration-thickness: 2px; }
</style>
