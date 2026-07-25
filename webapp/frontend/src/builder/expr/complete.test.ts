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

describe('constants in scope', () => {
  it('completes a constant name from scope.bindings', () => {
    const s = completionsAt('FEED', 4, { streams: [], bindings: ['FEED_RATE'] })
    expect(labels(s)).toContain('FEED_RATE')
    expect(s?.items.find((i) => i.label === 'FEED_RATE')).toMatchObject({ kind: 'binding' })
  })
})

describe('insideStatCallArgs', () => {
  it('detects the inside of an open stat call', () => {
    expect(insideStatCallArgs('mean(od', 7)).toBe(true)
    expect(insideStatCallArgs('mean(od)', 8)).toBe(false)
    expect(insideStatCallArgs('(od', 3)).toBe(false)
  })
})

// A group body references its own params and locals as {holes} (engine expand.py _HOLE_RE), and
// scopeRefs.ts already puts them in scope in that form. Only the completion path could not see
// them: it lexes with the parity-pinned tokenizer, which has no '{'.
const groupScope = { streams: ['od', '{feed}'], bindings: ['feed_ml', '{target_od}', '{tube}'] }

describe('completionsAt with {holes}', () => {
  it('offers every hole the moment { is typed', () => {
    const s = completionsAt('{', 1, groupScope)
    expect(labels(s)).toEqual(['{feed}', '{target_od}', '{tube}'])
    expect(s?.replace).toEqual({ start: 0, end: 1 })
    expect(s?.items[0]).toMatchObject({ insert: '{feed}', caretBack: 0, kind: 'stream' })
  })

  it('filters holes on the inner name and keeps the braces in the replacement', () => {
    const s = completionsAt('{t', 2, groupScope)
    expect(labels(s)).toEqual(['{target_od}', '{tube}'])
    expect(s?.replace).toEqual({ start: 0, end: 2 })
  })

  it('replaces a whole complete hole when the caret sits inside one', () => {
    // `{tu|be}` — accepting must not nest a second brace pair inside the first.
    const s = completionsAt('{tube} > 1', 3, groupScope)
    expect(labels(s)).toEqual(['{tube}'])
    expect(s?.replace).toEqual({ start: 0, end: 6 })
  })

  it('says nothing right after a finished hole', () => {
    expect(completionsAt('{tube}', 6, groupScope)).toBeNull()
  })

  it('still completes AFTER a hole earlier in the line', () => {
    // The regression that made the whole surface feel dead: an unmasked '{' lexes as an error,
    // and context() bails for every caret position after it.
    const s = completionsAt('{target_od} - me', 16, groupScope)
    expect(labels(s)).toEqual(['mean'])
    expect(s?.replace).toEqual({ start: 14, end: 16 })
  })

  it('reaches a hole from a bare prefix, braces and all', () => {
    const s = completionsAt('tu', 2, groupScope)
    expect(labels(s)).toEqual(['{tube}'])
    expect(s?.items[0]).toMatchObject({ insert: '{tube}' })
    expect(s?.replace).toEqual({ start: 0, end: 2 })
  })

  it('offers hole streams as a stat-call argument', () => {
    expect(labels(completionsAt('mean(f', 6, groupScope))).toEqual(['{feed}'])
  })

  it('offers nothing for { at the workflow scope, where holes are not syntax', () => {
    expect(completionsAt('{', 1, scope)).toBeNull()
  })
})
