const fields = [
  ['income', 'Income'], ['expenses', 'Expenses'],
  ['transfers_out', 'Transferred out'], ['transfers_in', 'Received from transfers'],
]
export const activityRows = total => fields.filter(([key]) => Number(total[key] || 0) !== 0).map(([key, label]) => ({ key, label, amount: total[key] }))
export const activeTotals = totals => totals.filter(total => activityRows(total).length)
export function activityAmount(amount, locale) {
  const value = Number(amount)
  return value > 0 && value < 0.005 ? '<0.01' : value.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
