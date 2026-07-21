import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parseExpression } from './parse'
import { tokenize } from './tokenize'

interface GoldenCase {
  expr: string
  tokens: Array<{ kind: string; text: string; pos: number }> | null
  lex_error_pos: number | null
  parse_ok: boolean
  parse_error_pos: number | null
  parse_error: string | null
}

const golden = JSON.parse(
  readFileSync(new URL('./__goldens__/expr-parity.json', import.meta.url), 'utf8'),
) as { cases: GoldenCase[] }

describe('parity with the engine grammar (see test_expr_golden.py)', () => {
  it('has a real corpus', () => {
    expect(golden.cases.length).toBeGreaterThan(50)
  })
  for (const c of golden.cases) {
    it(`tokens: ${JSON.stringify(c.expr).slice(0, 60)}`, () => {
      const { tokens, error } = tokenize(c.expr)
      if (c.tokens === null) {
        expect(error?.pos).toBe(c.lex_error_pos)
      } else {
        expect(error).toBeNull()
        expect(tokens.filter((t) => t.kind !== 'END')).toEqual(c.tokens)
      }
    })
    it(`parse: ${JSON.stringify(c.expr).slice(0, 60)}`, () => {
      const r = parseExpression(c.expr)
      expect(r.ok).toBe(c.parse_ok)
      if (!r.ok) {
        expect(r.error.atEnd ? null : r.error.pos).toBe(c.parse_error_pos)
      }
    })
  }
})
