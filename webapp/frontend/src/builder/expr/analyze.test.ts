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
})
