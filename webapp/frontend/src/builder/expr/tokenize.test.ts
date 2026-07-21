import { describe, expect, it } from 'vitest'
import { tokenize } from './tokenize'

describe('tokenize', () => {
  it('lexes a stat call with a duration window', () => {
    const { tokens, error } = tokenize('mean(od, last=30s) > 0.6')
    expect(error).toBeNull()
    expect(tokens).toEqual([
      { kind: 'NAME', text: 'mean', pos: 0 },
      { kind: 'OP', text: '(', pos: 4 },
      { kind: 'NAME', text: 'od', pos: 5 },
      { kind: 'OP', text: ',', pos: 7 },
      { kind: 'NAME', text: 'last', pos: 9 },
      { kind: 'OP', text: '=', pos: 13 },
      { kind: 'DURATION', text: '30s', pos: 14 },
      { kind: 'OP', text: ')', pos: 17 },
      { kind: 'OP', text: '>', pos: 19 },
      { kind: 'NUMBER', text: '0.6', pos: 21 },
      { kind: 'END', text: '', pos: 24 },
    ])
  })
  it('prefers DURATION over NUMBER+NAME, with the \\b guard', () => {
    expect(tokenize('1.5h').tokens[0]).toEqual({ kind: 'DURATION', text: '1.5h', pos: 0 })
    // 5min_x: \b fails inside the identifier, so NUMBER + NAME
    expect(tokenize('5min_x').tokens.map((t) => t.kind)).toEqual(['NUMBER', 'NAME', 'END'])
  })
  it('lexes strings, two-char ops before one-char', () => {
    expect(tokenize("mode == 'chemo stat'").tokens.map((t) => t.text)).toEqual([
      'mode',
      '==',
      "'chemo stat'",
      '',
    ])
    expect(tokenize('a<=b').tokens[1]).toEqual({ kind: 'OP', text: '<=', pos: 1 })
  })
  it('reports an unexpected character and stops', () => {
    const { tokens, error } = tokenize('od > §3')
    expect(error).toEqual({ pos: 5, char: '§' })
    expect(tokens.map((t) => t.kind)).toEqual(['NAME', 'OP', 'END'])
  })
  it('unterminated string is a lex error at the quote', () => {
    expect(tokenize("x == 'oops").error).toEqual({ pos: 5, char: "'" })
  })
})
