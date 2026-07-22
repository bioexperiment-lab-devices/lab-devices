import { describe, expect, it } from 'vitest'
import type { BlockNode } from './tree'
import {
  bindingIndex,
  bindingReferences,
  collectBindingReaders,
  collectBindingWriters,
  countBindingRefs,
} from './bindings'

const base = (uid: string, label: string | null = null) => ({
  uid,
  label,
  gapAfter: null,
  startOffset: null,
})
const oi = (uid: string, name: string): BlockNode => ({
  ...base(uid),
  kind: 'operator_input',
  name,
  inputType: 'int',
  prompt: null,
  min: null,
  max: null,
  choices: null,
})
const cmp = (uid: string, into: string, value: string, label: string | null = null): BlockNode => ({
  ...base(uid, label),
  kind: 'compute',
  into,
  value,
})
const branch = (uid: string, condition: string): BlockNode => ({
  ...base(uid),
  kind: 'branch',
  condition,
  then: [],
  else: null,
})

describe('collectBindingWriters', () => {
  it('records operator_input and compute writers, keeping multiples', () => {
    const tree = [oi('u1', 'n'), cmp('u2', 'x', '1'), cmp('u3', 'x', '2')]
    const w = collectBindingWriters(tree)
    expect(w['n']).toEqual([{ kind: 'operator_input', uid: 'u1', label: null }])
    expect(w['x'].map((r) => r.uid)).toEqual(['u2', 'u3'])
  })
})

describe('bindingReferences', () => {
  it('returns only known bare names referenced by the expression', () => {
    const names = new Set(['x', 'y'])
    expect(bindingReferences('x + z', names).sort()).toEqual(['x'])
    expect(bindingReferences('x + y', names).sort()).toEqual(['x', 'y'])
  })
  it('matches {hole} names by delimited substring and ignores unknown holes', () => {
    const names = new Set(['{c}'])
    expect(bindingReferences('{c} * working_volume_ml', names)).toEqual(['{c}'])
    expect(bindingReferences('{contaminated}', names)).toEqual([])
  })
})

describe('collectBindingReaders', () => {
  it('finds reads across compute value and branch condition', () => {
    const tree = [cmp('u1', 'x', '1'), cmp('u2', 'y', 'x + 1'), branch('u3', 'x > 0')]
    const readers = collectBindingReaders(tree, new Set(['x', 'y']))
    expect(readers['x'].map((r) => `${r.uid}:${r.field}`).sort()).toEqual([
      'u2:value',
      'u3:condition',
    ])
    expect(readers['y']).toBeUndefined()
  })
})

describe('bindingIndex', () => {
  it('merges writers, readers and types in document order', () => {
    const tree = [oi('u1', 'n'), cmp('u2', 'x', 'n + 1')]
    const rows = bindingIndex(tree, null, { n: { base: 'int', unit: 'unitless' } })
    expect(rows.map((r) => r.name)).toEqual(['n', 'x'])
    const n = rows[0]
    expect(n.type).toEqual({ base: 'int', unit: 'unitless' })
    expect(n.writers.map((w) => w.uid)).toEqual(['u1'])
    expect(n.readers.map((r) => r.uid)).toEqual(['u2'])
    expect(rows[1].type).toBeNull()
  })

  it('tags a declared-but-unwritten group binding param/local', () => {
    const group = {
      params: [{ name: 'p', kind: 'binding' as const }],
      locals: { c: { kind: 'binding' as const, init: '0' } },
      body: [],
    }
    const rows = bindingIndex([], group, {})
    const byName = Object.fromEntries(rows.map((r) => [r.name, r]))
    expect(byName['{p}'].decl).toBe('param')
    expect(byName['{c}'].decl).toBe('local')
  })
})

describe('countBindingRefs', () => {
  it('counts expression fields that reference a name', () => {
    const tree = [
      { uid: '1', kind: 'compute', into: 'x', value: 'K + 1' },
      { uid: '2', kind: 'branch', condition: 'K > 0', then: [], else: [] },
      { uid: '3', kind: 'wait', duration: '5min' },
    ] as never
    expect(countBindingRefs(tree, 'K')).toBe(2)
    expect(countBindingRefs(tree, 'Z')).toBe(0)
  })
})
