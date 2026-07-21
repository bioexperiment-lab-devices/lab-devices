/** TS port of the engine expression parser (expr.py `_Parser`). Grammar and error
 * POSITIONS are parity-pinned (__goldens__/expr-parity.json); message text mirrors the
 * engine's leading clause but is not asserted. Change only in lockstep with the engine. */
import { KEYWORDS, STAT_FNS, tokenize, type Token } from './tokenize'

export type Window = { t: 'all' } | { t: 'samples'; n: number } | { t: 'dur'; seconds: number }

export type Expr =
  | { t: 'const'; value: number | boolean | string }
  | { t: 'durationConst'; seconds: number }
  | { t: 'binding'; name: string; pos: number }
  | { t: 'stat'; fn: string; stream: string; streamPos: number; window: Window }
  | { t: 'unary'; op: '-' | 'not'; operand: Expr }
  | { t: 'binary'; op: string; left: Expr; right: Expr }

export interface ParseError {
  message: string
  pos: number // for atEnd errors this is text.length
  atEnd: boolean
}

export type ParseResult = { ok: true; ast: Expr } | { ok: false; error: ParseError }

const COMPARE_OPS = ['<', '<=', '>', '>=', '==', '!=']
const COMPARE_OP_SET = new Set(COMPARE_OPS)
const KEYWORD_SET = new Set<string>(KEYWORDS)
const STAT_FN_SET = new Set<string>(STAT_FNS)
const MAX_NESTING = 64
const UNIT_SECONDS: Record<string, number> = { ms: 0.001, s: 1, min: 60, h: 3600 }
const DURATION_LIT_RE = /^(\d+(?:\.\d+)?)(min|ms|s|h)$/

export function parseDurationLiteral(text: string): number {
  const m = DURATION_LIT_RE.exec(text)
  if (!m) throw new Error(`not a duration literal: ${text}`)
  return Number(m[1]) * UNIT_SECONDS[m[2]]
}

class Failure {
  readonly error: ParseError
  constructor(error: ParseError) {
    this.error = error
  }
}

class Parser {
  private readonly tokens: Token[]
  private pos = 0
  private depth = 0

  constructor(text: string) {
    const { tokens, error } = tokenize(text)
    this.tokens = tokens
    if (error) {
      throw new Failure({
        message: `unexpected character '${error.char}'`,
        pos: error.pos,
        atEnd: false,
      })
    }
  }

  parse(): Expr {
    const expr = this.orExpr()
    const tok = this.peek()
    if (tok.kind !== 'END') throw this.fail(tok, 'unexpected trailing input')
    return expr
  }

  private peek(): Token {
    return this.tokens[this.pos]
  }

  private advance(): Token {
    return this.tokens[this.pos++]
  }

  private fail(tok: Token, msg: string): Failure {
    const shown = tok.text ? ` (got '${tok.text}')` : ''
    return new Failure({ message: `${msg}${shown}`, pos: tok.pos, atEnd: tok.kind === 'END' })
  }

  private matchOp(...ops: string[]): Token | null {
    const tok = this.peek()
    if (tok.kind === 'OP' && ops.includes(tok.text)) return this.advance()
    return null
  }

  private expectOp(op: string): void {
    if (this.matchOp(op) === null) throw this.fail(this.peek(), `expected '${op}'`)
  }

  private matchName(name: string): boolean {
    const tok = this.peek()
    if (tok.kind === 'NAME' && tok.text === name) {
      this.advance()
      return true
    }
    return false
  }

  private bumpDepth(tok: Token): void {
    this.depth += 1
    if (this.depth > MAX_NESTING) {
      throw this.fail(tok, `expression too deeply nested (max ${MAX_NESTING})`)
    }
  }

  private orExpr(): Expr {
    let expr = this.andExpr()
    while (this.matchName('or')) expr = { t: 'binary', op: 'or', left: expr, right: this.andExpr() }
    return expr
  }

  private andExpr(): Expr {
    let expr = this.notExpr()
    while (this.matchName('and')) {
      expr = { t: 'binary', op: 'and', left: expr, right: this.notExpr() }
    }
    return expr
  }

  private notExpr(): Expr {
    const tok = this.peek()
    if (this.matchName('not')) {
      this.bumpDepth(tok)
      try {
        return { t: 'unary', op: 'not', operand: this.notExpr() }
      } finally {
        this.depth -= 1
      }
    }
    return this.comparison()
  }

  private comparison(): Expr {
    const expr = this.additive()
    const opTok = this.matchOp(...COMPARE_OPS)
    if (opTok === null) return expr
    const right = this.additive()
    const trailing = this.peek()
    if (trailing.kind === 'OP' && COMPARE_OP_SET.has(trailing.text)) {
      throw this.fail(trailing, 'comparisons cannot be chained')
    }
    return { t: 'binary', op: opTok.text, left: expr, right }
  }

  private additive(): Expr {
    let expr = this.multiplicative()
    for (let tok = this.matchOp('+', '-'); tok !== null; tok = this.matchOp('+', '-')) {
      expr = { t: 'binary', op: tok.text, left: expr, right: this.multiplicative() }
    }
    return expr
  }

  private multiplicative(): Expr {
    let expr = this.unary()
    for (let tok = this.matchOp('*', '/'); tok !== null; tok = this.matchOp('*', '/')) {
      expr = { t: 'binary', op: tok.text, left: expr, right: this.unary() }
    }
    return expr
  }

  private unary(): Expr {
    const tok = this.peek()
    if (this.matchOp('-') !== null) {
      this.bumpDepth(tok)
      try {
        return { t: 'unary', op: '-', operand: this.unary() }
      } finally {
        this.depth -= 1
      }
    }
    return this.atom()
  }

  private atom(): Expr {
    const tok = this.advance()
    if (tok.kind === 'NUMBER') {
      const value = Number(tok.text)
      // Engine mirror: the int branch ("." not in text) cannot raise — Python ints are
      // arbitrary-precision — while the float branch rejects non-finite values. JS Number
      // overflows to Infinity for both, so the finite check applies only with a dot.
      if (!Number.isFinite(value) && tok.text.includes('.')) {
        throw this.fail(tok, 'numeric literal is not finite')
      }
      return { t: 'const', value }
    }
    if (tok.kind === 'DURATION') {
      return { t: 'durationConst', seconds: parseDurationLiteral(tok.text) }
    }
    if (tok.kind === 'STRING') return { t: 'const', value: tok.text.slice(1, -1) }
    if (tok.kind === 'NAME') {
      if (tok.text === 'true') return { t: 'const', value: true }
      if (tok.text === 'false') return { t: 'const', value: false }
      if (KEYWORD_SET.has(tok.text)) throw this.fail(tok, `unexpected keyword '${tok.text}'`)
      const nxt = this.peek()
      if (nxt.kind === 'OP' && nxt.text === '(') return this.statCall(tok)
      return { t: 'binding', name: tok.text, pos: tok.pos }
    }
    if (tok.kind === 'OP' && tok.text === '(') {
      this.bumpDepth(tok)
      let expr: Expr
      try {
        expr = this.orExpr()
      } finally {
        this.depth -= 1
      }
      this.expectOp(')')
      return expr
    }
    throw this.fail(tok, "expected a literal, name, stat call, or '('")
  }

  private statCall(fnTok: Token): Expr {
    if (!STAT_FN_SET.has(fnTok.text)) {
      throw this.fail(
        fnTok,
        `unknown function '${fnTok.text}'; expected one of ${[...STAT_FNS].sort().join(', ')}`,
      )
    }
    this.expectOp('(')
    const streamTok = this.advance()
    if (streamTok.kind !== 'NAME' || KEYWORD_SET.has(streamTok.text)) {
      throw this.fail(streamTok, 'expected a stream name')
    }
    let window: Window = { t: 'all' }
    if (this.matchOp(',') !== null) window = this.window()
    this.expectOp(')')
    return { t: 'stat', fn: fnTok.text, stream: streamTok.text, streamPos: streamTok.pos, window }
  }

  private window(): Window {
    const key = this.advance()
    if (key.kind !== 'NAME' || key.text !== 'last') {
      throw this.fail(key, 'window must be last=<N> or last=<duration>')
    }
    this.expectOp('=')
    const val = this.advance()
    if (val.kind === 'NUMBER') {
      if (val.text.includes('.')) throw this.fail(val, 'window sample count must be an integer')
      const n = Number(val.text)
      if (n <= 0) throw this.fail(val, 'window sample count must be positive')
      return { t: 'samples', n }
    }
    if (val.kind === 'DURATION') return { t: 'dur', seconds: parseDurationLiteral(val.text) }
    throw this.fail(val, 'window must be last=<N> or last=<duration>')
  }
}

export function parseExpression(text: string): ParseResult {
  if (text.trim() === '') {
    return { ok: false, error: { message: 'empty expression', pos: 0, atEnd: true } }
  }
  try {
    return { ok: true, ast: new Parser(text).parse() }
  } catch (e) {
    if (e instanceof Failure) return { ok: false, error: e.error }
    throw e
  }
}
