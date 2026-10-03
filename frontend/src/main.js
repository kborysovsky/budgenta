import { createApp } from 'vue'
import App from './App.vue'
import './styles/style.css'
import { t, categoryLabel, quoteLabel, errorMessage } from './i18n.js'
const app = createApp(App)
app.config.globalProperties.$t = t
app.config.globalProperties.$category = categoryLabel
app.config.globalProperties.$quote = quoteLabel
app.config.globalProperties.$error = errorMessage
app.mount('#app')
