import { ref, computed } from 'vue'
import ru from '../../locales/ru.json'
import uk from '../../locales/uk.json'
import es from '../../locales/es.json'

export const languages = { en: 'English', ru: 'Русский', uk: 'Українська', es: 'Español' }
const catalogs = { ru, uk, es }
let stored = 'en'
try { stored = localStorage.getItem('budgenta.language') || 'en' } catch { /* Storage may be disabled. */ }
export const locale = ref(Object.hasOwn(languages, stored) ? stored : 'en')
export const numberLocale = computed(() => ({ en: 'en-US', ru: 'ru-RU', uk: 'uk-UA', es: 'es-AR' })[locale.value])
export function setLanguage(value) {
  if (!Object.hasOwn(languages, value)) return
  locale.value = value
  document.documentElement.lang = value
  try { localStorage.setItem('budgenta.language', value) } catch { /* Keep this session's choice. */ }
}
export function t(message, values = {}) {
  const text = catalogs[locale.value]?.[message] ?? message
  return typeof text === 'string' ? text.replace(/\{(\w+)\}/g, (match, key) => Object.hasOwn(values, key) ? String(values[key]) : match) : text
}
const categoryDefaults = {
  expense: new Set(['Grocery', 'Outside Food', 'Self Care', 'Rent', 'Health', 'Clothes', 'Emergency', 'Debts', 'Leisure', 'Delivery', 'Home', 'Transport', 'Subscriptions']),
  income: new Set(['Salary', 'Freelance', 'Other']),
}
export const categoryLabel = (name, kind) => (kind ? categoryDefaults[kind]?.has(name) : Object.values(categoryDefaults).some(values => values.has(name))) ? t(name) : name
setLanguage(locale.value)

export function quoteLabel(quote) {
  for (const suffix of [' (official)', ' (blue venta)']) {
    if (quote.display_rate.endsWith(suffix)) return quote.display_rate.slice(0, -suffix.length) + t(suffix)
  }
  return quote.display_rate
}
export function errorMessage(message) {
  const precision = typeof message === 'string' && message.match(/^(USD|EUR|ARS|UAH|USDT|TRX|BTC|ETH) allows at most (\d+) decimal places\.$/)
  if (precision) return t('{currency} allows at most {places} decimal places.', { currency: precision[1], places: precision[2] })
  return t(message)
}
