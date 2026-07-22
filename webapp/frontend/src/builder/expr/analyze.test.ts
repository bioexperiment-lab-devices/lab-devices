import { describe, expect, it } from 'vitest'
import { analyzeExpression } from './analyze'

const scope = { streams: ['od', 'temp'], bindings: ['feed_ml'] }

describe('analyzeExpression', () => {
  it('empty text has no problems', () => {
    expect(analyzeExpression('  ', 'any', scope)).toEqual([])
  })
  it('reports a parse error with its position', () => {
    const p = analyzeExpression('mean(od', 'any', scope)
    expect(p).toHaveLength(1)
    expect(p[0].pos).toBe(7)
    expect(p[0].len).toBe(0)
  })
  it('flags unknown streams and bindings with spans', () => {
    const p = analyzeExpression('mean(ph) > lvl', 'any', scope)
    expect(p).toEqual([
      { message: "unknown stream 'ph'", pos: 5, len: 2 },
      { message: "unknown binding 'lvl'", pos: 11, len: 3 },
    ])
  })
  it('accepts known names anywhere in the tree', () => {
    expect(analyzeExpression('not (mean(od, last=5) > feed_ml)', 'any', scope)).toEqual([])
  })
  it('duration slots flag bare unitless numbers', () => {
    expect(analyzeExpression('30', 'duration', scope)[0].message).toContain('30s')
    expect(analyzeExpression('30s', 'duration', scope)).toEqual([])
    expect(analyzeExpression('cycle * 1min', 'duration', scope)).toEqual([
      { message: "unknown binding 'cycle'", pos: 0, len: 5 },
    ])
  })
  it('int slots flag bare float literals', () => {
    expect(analyzeExpression('2.5', 'int', scope)).toHaveLength(1)
    expect(analyzeExpression('2', 'int', scope)).toEqual([])
  })
  it('does not flag a constant in scope as an unknown binding', () => {
    const res = analyzeExpression('FEED_RATE * 2', 'any', { streams: [], bindings: ['FEED_RATE'] })
    expect(res.some((d) => /unknown binding/.test(d.message))).toBe(false)
  })
})

describe('analyzeExpression with {holes}', () => {
  const holeScope = { streams: ['{od}'], bindings: ['{tube}', 'warm'] }

  it('accepts a known stream hole inside a stat call', () => {
    expect(analyzeExpression('mean({od}, last=5)', 'any', holeScope)).toEqual([])
  })

  it('accepts a known binding hole', () => {
    expect(analyzeExpression('{tube}', 'any', holeScope)).toEqual([])
  })

  it('does not report "unexpected character" for a brace', () => {
    const out = analyzeExpression('{tube} + warm', 'any', holeScope)
    expect(out.some((p) => /unexpected character/.test(p.message))).toBe(false)
  })

  it('reports an unknown hole using its {name} form', () => {
    const out = analyzeExpression('{bogus}', 'any', holeScope)
    expect(out).toHaveLength(1)
    expect(out[0].message).toBe("unknown binding '{bogus}'")
    expect(out[0].pos).toBe(0)
    expect(out[0].len).toBe('{bogus}'.length)
  })
})
