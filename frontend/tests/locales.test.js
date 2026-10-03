import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parse as parseVue } from '@vue/compiler-sfc'
import { parse as parseTemplate } from '@vue/compiler-dom'
import { parse, parseExpression } from '@babel/parser'
const root = fileURLToPath(new URL('../src/', import.meta.url))
const catalogs = Object.fromEntries(['ru', 'uk', 'es'].map(code => [code, JSON.parse(readFileSync(new URL(`../../locales/${code}.json`, import.meta.url)))]))

function visit(node, fn) {
  if (!node || typeof node !== 'object') return
  fn(node)
  for (const [key, value] of Object.entries(node)) {
    if (key === 'loc' || key === 'ast') continue
    if (Array.isArray(value)) value.forEach(child => visit(child, fn))
    else if (value && typeof value === 'object') visit(value, fn)
  }
}

test('every explicit UI message has all three translations and matching placeholders', () => {
  const keys = new Set()
  const collect = node => {
    if (node.type === 'CallExpression' && ['$t', 't'].includes(node.callee.name) && node.arguments[0]?.type === 'StringLiteral') keys.add(node.arguments[0].value)
  }
  for (const name of readdirSync(root, { recursive: true }).filter(name => /\.(vue|js)$/.test(name))) {
    const source = readFileSync(root + name, 'utf8')
    if (name.endsWith('.js')) { visit(parse(source, { sourceType: 'module' }), collect); continue }
    const { descriptor } = parseVue(source)
    if (descriptor.scriptSetup) visit(parse(descriptor.scriptSetup.content, { sourceType: 'module' }), collect)
    if (descriptor.template) visit(parseTemplate(descriptor.template.content), node => {
      if (node.type === 5) visit(parseExpression(node.content.content), collect)
      // Directive expressions can also contain multiple statements and v-for syntax.
      if (node.type === 7 && node.exp && !['for', 'on', 'slot'].includes(node.name)) visit(parseExpression(node.exp.content), collect)
    })
  }
  assert.ok(keys.size > 300)
  for (const [language, catalog] of Object.entries(catalogs)) {
    for (const key of keys) assert.ok(catalog[key], `${language}: missing ${key}`)
    assert.deepEqual(Object.keys(catalog), Object.keys(catalogs.ru))
    const parameters = value => [...new Set(value.match(/\{\w+\}/g) || [])].sort()
    for (const [key, value] of Object.entries(catalog)) assert.deepEqual(parameters(value), parameters(key), `${language}: ${key}`)
  }
})
