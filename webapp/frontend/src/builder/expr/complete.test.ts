import { describe, expect, it } from 'vitest'
import { completionsAt, insideStatCallArgs } from './complete'

const scope = { streams: ['od', 'temp'], bindings: ['feed_ml'] }
const labels = (s: ReturnType<typeof completionsAt>) => s?.items.map((i) => i.label)

describe('completionsAt', () => {
  it('offers functions, streams, bindings, and not at an atom position', () => {
    const s = completionsAt('', 0, scope, true)
    expect(labels(s)).toEqual([
      'last',
      'mean',
      'min',
      'max',
      'count',
      'od',
      'temp',
      'feed_ml',
      'not',
    ])
    expect(s?.replace).toEqual({ start: 0, end: 0 })
  })
  it('filters by the typed prefix and replaces the partial token', () => {
    const s = completionsAt('me > 2', 2, scope)
    expect(labels(s)).toEqual(['mean'])
    expect(s?.replace).toEqual({ start: 0, end: 2 })
    expect(s?.items[0]).toMatchObject({ insert: 'mean()', caretBack: 1 })
  })
  it('offers only streams as the first stat-call argument', () => {
    expect(labels(completionsAt('mean(', 5, scope, true))).toEqual(['od', 'temp'])
    expect(labels(completionsAt('mean(o', 6, scope))).toEqual(['od'])
  })
  it('offers last= after the comma inside a stat call', () => {
    const s = completionsAt('mean(od, ', 9, scope, true)
    expect(labels(s)).toEqual(['last='])
  })
  it('is silent without a prefix unless forced, and after an operand', () => {
    expect(completionsAt('', 0, scope)).toBeNull()
    expect(completionsAt('od ', 3, scope, true)).toBeNull()
  })
  it('completes mid-token replacing the whole token', () => {
    const s = completionsAt('mean > 2', 2, scope) // caret inside 'mean'
    expect(s?.replace).toEqual({ start: 0, end: 4 })
  })
  it('is null when a lex error precedes the caret', () => {
    expect(completionsAt('§ me', 4, scope)).toBeNull()
  })
})

describe('insideStatCallArgs', () => {
  it('detects the inside of an open stat call', () => {
    expect(insideStatCallArgs('mean(od', 7)).toBe(true)
    expect(insideStatCallArgs('mean(od)', 8)).toBe(false)
    expect(insideStatCallArgs('(od', 3)).toBe(false)
  })
})
