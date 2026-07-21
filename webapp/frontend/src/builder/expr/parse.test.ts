import { describe, expect, it } from 'vitest'
import { parseExpression } from './parse'

function err(text: string) {
  const r = parseExpression(text)
  if (r.ok) throw new Error(`expected failure for ${text}`)
  return r.error
}

describe('parseExpression', () => {
  it('parses precedence: or < and < not < cmp < add < mul < unary', () => {
    const r = parseExpression('not a and b + 2 * c < 5 or true')
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.ast.t).toBe('binary')
    if (r.ast.t !== 'binary') return
    expect(r.ast.op).toBe('or')
  })
  it('parses stat calls with all three window forms', () => {
    for (const [text, window] of [
      ['mean(od)', { t: 'all' }],
      ['mean(od, last=5)', { t: 'samples', n: 5 }],
      ['mean(od, last=30s)', { t: 'dur', seconds: 30 }],
    ] as const) {
      const r = parseExpression(text)
      expect(r.ok).toBe(true)
      if (r.ok && r.ast.t === 'stat') expect(r.ast.window).toEqual(window)
    }
  })
  it('duration literal is a value with seconds', () => {
    const r = parseExpression('5min')
    expect(r).toEqual({ ok: true, ast: { t: 'durationConst', seconds: 300 } })
  })
  it('rejects chained comparisons at the trailing operator', () => {
    expect(err('1 < x < 2')).toMatchObject({ pos: 6, atEnd: false })
  })
  it('rejects unknown functions at the name', () => {
    expect(err('median(od)').pos).toBe(0)
    expect(err('median(od)').message).toContain('unknown function')
  })
  it('rejects keyword stream names', () => {
    expect(err('mean(and)').message).toContain('expected a stream name')
  })
  it('window errors', () => {
    expect(err('mean(od, last=0)').message).toContain('positive')
    expect(err('mean(od, last=2.5)').message).toContain('integer')
    expect(err('mean(od, first=3)').message).toContain('last=')
  })
  it('reports at end of input', () => {
    const e = err('1 +')
    expect(e.atEnd).toBe(true)
    expect(e.pos).toBe(3)
  })
  it('empty expression', () => {
    expect(err('  ').message).toBe('empty expression')
  })
  it('caps nesting at 64', () => {
    const deep = '('.repeat(65) + '1' + ')'.repeat(65)
    expect(err(deep).message).toContain('too deeply nested')
  })
  it('lex errors surface as parse errors', () => {
    expect(err('od > §3')).toMatchObject({ pos: 5, atEnd: false })
  })
})
