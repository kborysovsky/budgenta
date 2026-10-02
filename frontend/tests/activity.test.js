import test from 'node:test'
import assert from 'node:assert/strict'
import { activityRows, activeTotals, activityAmount } from '../src/utils/activity.js'

test('statistics show nonzero movement fields without inventing income or expenses', () => {
  const total = { currency: 'USD', income: '0', expenses: '10', transfers_out: '0', transfers_in: '15.00' }
  assert.deepEqual(activityRows(total), [{ key: 'expenses', label: 'Expenses', amount: '10' }, { key: 'transfers_in', label: 'Received from transfers', amount: '15.00' }])
  assert.deepEqual(activeTotals([{ currency: 'EUR', income: '0', expenses: '0' }, total]), [total])
  assert.equal(activityAmount('0.00000001'), '<0.01')
})
