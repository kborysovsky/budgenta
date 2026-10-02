import test from 'node:test'
import assert from 'node:assert/strict'
import { allAmount } from '../src/utils/amounts.js'

test('All preserves fiat and crypto precision without Number rounding', () => {
  assert.equal(allAmount('123.450000'), '123.45')
  assert.equal(allAmount('0.00000001'), '0.00000001')
  assert.equal(allAmount('123456789012345678.12345678'), '123456789012345678.12345678')
  assert.equal(allAmount('0.00000100'), '0.000001')
})
test('All caps debt payments exactly, including scientific-notation amounts', () => {
  assert.equal(allAmount('100.000000', '25.55'), '25.55')
  assert.equal(allAmount('10.000000', '25.55'), '10')
  assert.equal(allAmount('0.00000003', '1E-8'), '0.00000001')
  assert.equal(allAmount('999999999999999999.99', '999999999999999999.98'), '999999999999999999.98')
})
test('All is unavailable for missing, empty, negative, or invalid balances/limits', () => {
  for (const value of [undefined, null, '', '0', '-1', 'NaN', 'Infinity', '0.000000001']) assert.equal(allAmount(value), '')
  assert.equal(allAmount('10', '0'), '')
  assert.equal(allAmount('10', '-1'), '')
})
