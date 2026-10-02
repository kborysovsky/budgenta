<script setup>
defineProps({ name: { type: String, required: true } })

// Local SVG geometry avoids platform emoji fonts, colors, and background tiles.
const paths = {
  overview: 'M3 3h7v18H3z M14 3h7v7h-7z M14 14h7v7h-7z',
  card: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z M3 10h18 M6 15h4',
  cash: 'M3 5h18v14H3z M3 9a4 4 0 0 0 4-4 M17 5a4 4 0 0 0 4 4 M3 15a4 4 0 0 1 4 4 M17 19a4 4 0 0 1 4-4 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  wallet: 'M20 8V5H5a2 2 0 0 0 0 4h16v11H5a2 2 0 0 1-2-2V7 M21 12h-5v5h5 M18 14.5h.01',
  crypto: 'm12 2 9 10-9 10L3 12Z m0 5 4 5-4 5-4-5Z',
  savings: 'm12 3 9 9-9 9-9-9Z',
  transfer: 'M3 8h18m-4-4 4 4-4 4 M21 16H3m4-4-4 4 4 4',
  exchange: 'M4 9a8 8 0 0 1 13-5l3 3 M20 2v5h-5 M20 15a8 8 0 0 1-13 5l-3-3 M4 22v-5h5',
  debt: 'M19 5 5 19 M5 9v10h10',
  goal: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0 M12 12h.01',
  report: 'M4 3h16v18H4z M8 16v-4 M12 16V7 M16 16v-6',
  star: 'M12 2v20 M2 12h20 M5 5l14 14 M5 19 19 5',
  logout: 'M9 3H4v18h5 M9 12h12m-5-5 5 5-5 5',
  calendar: 'M4 5h16v16H4z M8 3v4 M16 3v4 M4 10h16 M8 14h2 M14 14h2 M8 17h2',
  telegram: 'm3 10 18-7-7 18-4-7Z M10 14 21 3',
  settings: 'm9.5 3-.7 2.4-2.4 1L4 5.8 1.5 10l1.8 1.8v.4L1.5 14 4 18.2l2.4-.6 2.4 1 .7 2.4h5l.7-2.4 2.4-1 2.4.6 2.5-4.2-1.8-1.8v-.4l1.8-1.8L20 5.8l-2.4.6-2.4-1L14.5 3z M15.2 12a3.2 3.2 0 1 1-6.4 0 3.2 3.2 0 0 1 6.4 0',
  plus: 'M12 5v14 M5 12h14',
  close: 'm6 6 12 12 M6 18 18 6',
  check: 'm5 12 4 4L19 6',
  'chevron-down': 'm6 9 6 6 6-6',
  'arrow-up': 'M12 20V4m-6 6 6-6 6 6',
  'arrow-down': 'M12 4v16m-6-6 6 6 6-6',
  'arrow-right': 'M4 12h16m-6-6 6 6-6 6',
  'arrow-left': 'M20 12H4m6-6-6 6 6 6',
  'arrow-up-right': 'M5 19 19 5 M5 5h14v14',
}
</script>

<template>
  <svg class="app-icon" :data-icon="name" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path :d="paths[name]" /></svg>
</template>

<style scoped>
.app-icon { display: inline-block; width: 1em; height: 1em; flex-shrink: 0; vertical-align: -.15em; pointer-events: none; }
</style>
