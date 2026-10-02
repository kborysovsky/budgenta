// Compare and copy money as decimal strings; never round account balances to floats.
function units(value) {
  const match = /^\+?(\d+)(?:\.(\d*))?(?:e([+-]?\d+))?$/i.exec(String(value ?? '').trim())
  if (!match) return null
  const shift = 8 + Number(match[3] || 0) - (match[2] || '').length
  if (Math.abs(shift) > 100) return null
  const digits = BigInt(match[1] + (match[2] || ''))
  const scale = 10n ** BigInt(Math.abs(shift))
  if (shift < 0 && digits % scale !== 0n) return null
  return shift < 0 ? digits / scale : digits * scale
}

export function allAmount(balance, limit = null) {
  let amount = units(balance)
  if (amount === null || amount <= 0n) return ''
  if (limit !== null && limit !== undefined) {
    const cap = units(limit)
    if (cap === null || cap <= 0n) return ''
    if (cap < amount) amount = cap
  }
  const digits = amount.toString().padStart(9, '0')
  const fraction = digits.slice(-8).replace(/0+$/, '')
  return digits.slice(0, -8) + (fraction ? `.${fraction}` : '')
}
