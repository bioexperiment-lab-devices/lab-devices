# Expression Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Syntax highlighting, autocomplete, clickable expression help, and instant (client-side) validation on every expression surface in the Studio, plus expression-capable duration/count slots.

**Architecture:** A TS port of the engine's expression tokenizer+parser (`src/builder/expr/`), drift-pinned by a golden parity corpus generated from the engine; one shared `ExpressionEditor` component (native textarea + highlight overlay + autocomplete popup + clickable help popover) replacing `ExpressionInput`'s guts; server whole-doc diagnostics attributed to fields via the diagnostic path suffix.

**Tech Stack:** React 19 + Tailwind 4 + zustand (frontend), vitest node-env (pure functions only), pytest (golden generator/regen test). No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-21-expression-editor-design.md`

## Global Constraints

- vitest runs in node env: pure functions only — NO component rendering, no jsdom (frontend/CLAUDE.md).
- Every class baked into a helper is un-overridable by concatenation — never append a same-property utility to a helper's output; extend the helper with a *selecting* option instead (frontend/CLAUDE.md "Colour"/"Control height").
- Tailwind class names must be complete literals in source.
- Hue (blue/red/amber/emerald) is reserved for state. Highlight palette: violet/teal/fuchsia/slate only; draft-problem underlines `decoration-amber-600`; server diagnostics `text-red-600`.
- Interactive icons: lucide via `IconButton` only; no raw glyph buttons.
- Text inputs render at 24px via `controlClass()`; textareas share `textAreaClass()`.
- Meaning-carrying secondary text ≥ `text-caption` (slate-600); `text-hint` (slate-500) only for incidental text.
- Conventional-commit PR titles (release-please); squash merges.
- Engine grammar (`src/lab_devices/experiment/expr.py`) must NOT change.
- Backend ruff line-length 100; backend mypy checks `experiment_studio` only (tests exempt from mypy, not from ruff).
- Worktree: `/Users/khamit/lab-devices/.claude/worktrees/expression-editor` (branch `worktree-expression-editor`). Frontend commands run from `webapp/frontend` in the worktree.
- Local Python: engine tests `PYTHONPATH=<worktree>/src /Users/khamit/lab-devices/.venv/bin/python -m pytest tests -q` from worktree root; backend tests `PYTHONPATH=<worktree>/src /Users/khamit/lab-devices/webapp/backend/.venv/bin/python -m pytest tests -q` from `<worktree>/webapp/backend`.

---

## PR 1 — expr module, editor, clickable help, instant validation

### Task 1: TS tokenizer `expr/tokenize.ts`

**Files:**
- Create: `webapp/frontend/src/builder/expr/tokenize.ts`
- Test: `webapp/frontend/src/builder/expr/tokenize.test.ts`

**Interfaces (Produces):**
```ts
export type TokenKind = 'DURATION' | 'NUMBER' | 'STRING' | 'NAME' | 'OP' | 'END'
export interface Token { kind: TokenKind; text: string; pos: number }
export interface LexError { pos: number; char: string }
export interface LexResult { tokens: Token[]; error: LexError | null } // tokens always END-terminated
export const STAT_FNS: readonly string[]  // ['last','mean','min','max','count']
export const KEYWORDS: readonly string[]  // ['and','or','not','true','false']
export function tokenize(text: string): LexResult
```

- [ ] **Step 1: Write the failing test** (`tokenize.test.ts`):

```ts
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
      'mode', '==', "'chemo stat'", '',
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
```

- [ ] **Step 2: Run to verify failure**: `npm test -- tokenize` → FAIL (module not found).
- [ ] **Step 3: Implement** `tokenize.ts`:

```ts
/** TS port of the engine expression tokenizer (src/lab_devices/experiment/expr.py
 * `_TOKEN_RE`/`tokenize` + durations.py DURATION_PATTERN). Drift-pinned by the golden
 * parity corpus (__goldens__/expr-parity.json, regenerated by
 * webapp/backend/tests/test_expr_golden.py) — change only in lockstep with the engine. */

export type TokenKind = 'DURATION' | 'NUMBER' | 'STRING' | 'NAME' | 'OP' | 'END'

export interface Token {
  kind: TokenKind
  text: string
  pos: number
}

export interface LexError {
  pos: number
  char: string
}

export interface LexResult {
  /** Always END-terminated, even after an error (everything before the bad char). */
  tokens: Token[]
  error: LexError | null
}

export const STAT_FNS = ['last', 'mean', 'min', 'max', 'count'] as const
export const KEYWORDS = ['and', 'or', 'not', 'true', 'false'] as const

const TOKEN_KINDS = ['DURATION', 'NUMBER', 'STRING', 'NAME', 'OP'] as const

// DURATION before NUMBER so `30s` is one token; unit alternation longest-first
// (`min|ms|s|h`) and \b so `5min_x` lexes as NUMBER + NAME — all as in the engine.
const TOKEN_RE =
  /\s+|(?<DURATION>\d+(?:\.\d+)?(?:min|ms|s|h)\b)|(?<NUMBER>\d+(?:\.\d+)?)|(?<STRING>'[^']*')|(?<NAME>[A-Za-z_][A-Za-z0-9_]*)|(?<OP><=|>=|==|!=|[-+*/(),<>=])/y

export function tokenize(text: string): LexResult {
  const tokens: Token[] = []
  let pos = 0
  while (pos < text.length) {
    TOKEN_RE.lastIndex = pos
    const m = TOKEN_RE.exec(text)
    if (m === null) {
      // The engine raises here; the editor keeps what it has so highlighting can
      // still paint everything before the bad character.
      tokens.push({ kind: 'END', text: '', pos })
      return { tokens, error: { pos, char: text[pos] } }
    }
    const groups = m.groups ?? {}
    for (const kind of TOKEN_KINDS) {
      const t = groups[kind]
      if (t !== undefined) {
        tokens.push({ kind, text: t, pos })
        break
      }
    }
    pos = TOKEN_RE.lastIndex
  }
  tokens.push({ kind: 'END', text: '', pos: text.length })
  return { tokens, error: null }
}
```

- [ ] **Step 4: Run**: `npm test -- tokenize` → PASS.
- [ ] **Step 5: Commit**: `git add -A && git commit -m "feat(studio): TS port of the expression tokenizer"`

### Task 2: TS parser `expr/parse.ts`

**Files:**
- Create: `webapp/frontend/src/builder/expr/parse.ts`
- Test: `webapp/frontend/src/builder/expr/parse.test.ts`

**Interfaces (Produces):**
```ts
export type Window = { t: 'all' } | { t: 'samples'; n: number } | { t: 'dur'; seconds: number }
export type Expr =
  | { t: 'const'; value: number | boolean | string }
  | { t: 'durationConst'; seconds: number }
  | { t: 'binding'; name: string; pos: number }
  | { t: 'stat'; fn: string; stream: string; streamPos: number; window: Window }
  | { t: 'unary'; op: '-' | 'not'; operand: Expr }
  | { t: 'binary'; op: string; left: Expr; right: Expr }
export interface ParseError { message: string; pos: number; atEnd: boolean }
export type ParseResult = { ok: true; ast: Expr } | { ok: false; error: ParseError }
export function parseExpression(text: string): ParseResult
export function parseDurationLiteral(text: string): number
```

- [ ] **Step 1: Failing test** (`parse.test.ts`):

```ts
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
```

- [ ] **Step 2: Run** `npm test -- expr/parse` → FAIL.
- [ ] **Step 3: Implement** `parse.ts` — a line-for-line port of `_Parser` (expr.py:111-290). Same productions, same error positions; messages mirror the engine's leading clause (parity asserts positions/outcomes, not text):

```ts
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

const COMPARE_OPS = new Set(['<', '<=', '>', '>=', '==', '!='])
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
  constructor(readonly error: ParseError) {}
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
    while (this.matchName('and')) expr = { t: 'binary', op: 'and', left: expr, right: this.notExpr() }
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
    if (trailing.kind === 'OP' && COMPARE_OPS.has(trailing.text)) {
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
      if (!Number.isFinite(value) && tok.text.includes('.')) {
        throw this.fail(tok, 'numeric literal is not finite')
      }
      return { t: 'const', value }
    }
    if (tok.kind === 'DURATION') return { t: 'durationConst', seconds: parseDurationLiteral(tok.text) }
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
      throw this.fail(fnTok, `unknown function '${fnTok.text}'; expected one of ${[...STAT_FNS].sort().join(', ')}`)
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
```

Note the deliberate engine mirror in `atom()`: the engine's int branch (`"." not in text`) cannot raise on huge integers and its float branch raises on non-finite — JS `Number` returns `Infinity` for both, so the finite check applies **only when the text contains a dot**, keeping outcomes aligned.

- [ ] **Step 4: Run** `npm test -- expr/parse` → PASS. Also `npm run typecheck`.
- [ ] **Step 5: Commit**: `feat(studio): TS port of the expression parser`

### Task 3: Golden parity corpus (engine generator + backend regen test + vitest parity)

**Files:**
- Create: `webapp/backend/tests/test_expr_golden.py`
- Create (generated): `webapp/frontend/src/builder/expr/__goldens__/expr-parity.json`
- Test: `webapp/frontend/src/builder/expr/parity.test.ts`

**Interfaces:** Golden JSON shape (consumed by parity.test.ts):
```json
{ "note": "...", "cases": [ { "expr": "...", "tokens": [{"kind","text","pos"}] | null,
  "lex_error_pos": int | null, "parse_ok": bool, "parse_error_pos": int | null,
  "parse_error": "full engine message (human reference only)" | null } ] }
```
`parse_error_pos` is `null` for at-end/unpositioned errors; TS maps `atEnd → null`.

- [ ] **Step 1: Write the generator + regen test** `webapp/backend/tests/test_expr_golden.py`:

```python
"""Golden parity corpus pinning the TS expression-grammar port to the engine.

Regenerate (from webapp/backend): `python tests/test_expr_golden.py`
The committed JSON is asserted byte-identical below, so ANY engine grammar change
fails CI here until the corpus is regenerated AND the TS port
(webapp/frontend/src/builder/expr/) is re-synced against parity.test.ts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from lab_devices.experiment.errors import ExpressionError
from lab_devices.experiment.expr import parse_expression, tokenize

GOLDEN_PATH = (
    Path(__file__).resolve().parents[3]
    / "webapp/frontend/src/builder/expr/__goldens__/expr-parity.json"
)

CORPUS: list[str] = [
    # literals and bindings
    "1", "0.5", "42", "true", "false", "od", "feed_ml", "_x1",
    "'chemostat'", "''", "'a b c'", "5min", "30s", "250ms", "1.5h", "0.5s",
    "9" * 400,          # huge int: fine in both (JS precision loss is irrelevant client-side)
    "9" * 400 + ".0",   # huge float: non-finite in both
    # stat calls and windows
    "mean(od)", "last(od)", "min(od)", "max(od)", "count(od)",
    "mean(od, last=5)", "mean(od, last=30s)", "mean (od , last=5)",
    "count(od,last=90s) > 0 and mean(od,last=90s) > 2.0",
    # operators, precedence, unary
    "not a and b + 2 * c < 5 or true", "-x + 2", "not not true", "-(-1)",
    "a / b * c - d", "(a or b) and c", "mode == 'chemostat'", "x != 'a'",
    "last(od) > 0.5", "5min + 30s", "cycle_min * 1min",
    # errors: lexing
    "od > §3", "x == 'oops", "a & b", "#tag", "!x",
    # errors: parsing
    "", "   ", "1 +", "mean(", "mean(od", "mean(od,", "mean(od, last=",
    "median(od)", "mean(and)", "mean(5)", "mean(od, first=3)",
    "mean(od, last=0)", "mean(od, last=2.5)", "mean(od, last=-1)",
    "1 < x < 2", "x and", "()", "not", "true false", "1 1", ") od",
    "and od", "5min(od)", "x == == 2",
    "(" * 65 + "1" + ")" * 65,   # depth cap
    "-" * 65 + "1",
    "5min_x",                    # \b guard: NUMBER + NAME → binding 'min_x'? no: 5 then min_x → trailing input
]

_POS_RE = re.compile(r"at position (\d+)")
# NB: positions are extracted from engine messages; the corpus must never include a
# FAILING expression whose own text contains "at position N" (the message embeds the text).


def _case(expr: str) -> dict[str, object]:
    case: dict[str, object] = {"expr": expr}
    try:
        toks = tokenize(expr)
        case["tokens"] = [
            {"kind": t.kind, "text": t.text, "pos": t.pos} for t in toks if t.kind != "END"
        ]
        case["lex_error_pos"] = None
    except ExpressionError as e:
        m = _POS_RE.search(str(e))
        case["tokens"] = None
        case["lex_error_pos"] = int(m.group(1)) if m else None
    try:
        parse_expression(expr)
        case["parse_ok"] = True
        case["parse_error_pos"] = None
        case["parse_error"] = None
    except ExpressionError as e:
        m = _POS_RE.search(str(e))
        case["parse_ok"] = False
        case["parse_error_pos"] = int(m.group(1)) if m else None
        case["parse_error"] = str(e)
    return case


def build_golden() -> dict[str, object]:
    return {
        "note": "generated by webapp/backend/tests/test_expr_golden.py -- do not edit by hand",
        "cases": [_case(e) for e in CORPUS],
    }


def _dump(data: dict[str, object]) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def test_committed_golden_matches_engine() -> None:
    assert GOLDEN_PATH.read_text() == _dump(build_golden()), (
        "expr parity golden drifted from the engine grammar; regenerate with "
        "`python tests/test_expr_golden.py` (from webapp/backend) and re-sync the TS port"
    )


if __name__ == "__main__":
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(_dump(build_golden()))
    print(f"wrote {GOLDEN_PATH}")
```

- [ ] **Step 2: Generate the golden**: from `<worktree>/webapp/backend`: `PYTHONPATH=<worktree>/src /Users/khamit/lab-devices/webapp/backend/.venv/bin/python tests/test_expr_golden.py` → writes the JSON. Inspect a few cases by eye (e.g. `mean(od, last=30s)` tokens; `1 < x < 2` parse_error_pos 6).
- [ ] **Step 3: Run the regen test**: same env, `python -m pytest tests/test_expr_golden.py -q` → PASS.
- [ ] **Step 4: Write parity.test.ts**:

```ts
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
```

- [ ] **Step 5: Run** `npm test -- parity` → PASS (fix any port divergence NOW — this is the point of the corpus).
- [ ] **Step 6: Backend suite + ruff**: backend pytest -q → all pass; `/Users/khamit/lab-devices/webapp/backend/.venv/bin/python -m ruff check tests/test_expr_golden.py` (from webapp/backend) → clean.
- [ ] **Step 7: Commit**: `feat(studio): golden parity corpus pinning the TS grammar port to the engine`

### Task 4: `expr/analyze.ts` (instant validation core)

**Files:**
- Create: `webapp/frontend/src/builder/expr/analyze.ts`
- Test: `webapp/frontend/src/builder/expr/analyze.test.ts`

**Interfaces (Produces):**
```ts
export type ExpectedType = 'bool' | 'number' | 'int' | 'duration' | 'any'
export interface ExprProblem { message: string; pos: number; len: number } // len 0 = no span
export interface ExprScope { streams: string[]; bindings: string[] }
export function analyzeExpression(text: string, expected: ExpectedType, scope: ExprScope): ExprProblem[]
```

- [ ] **Step 1: Failing test**:

```ts
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
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**:

```ts
/** Client-side draft analysis (spec §3.4): syntax via the parity-pinned parser, plus
 * known-name checks against the ACTIVE scope and two slot heuristics. Types and units
 * deliberately stay server-side — this file must never grow a copy of the lattice. */
import { parseExpression, type Expr } from './parse'

export type ExpectedType = 'bool' | 'number' | 'int' | 'duration' | 'any'

export interface ExprProblem {
  message: string
  pos: number
  /** 0 = no usable span (at-end parse errors). */
  len: number
}

export interface ExprScope {
  streams: string[]
  bindings: string[]
}

function walk(ast: Expr, scope: ExprScope, out: ExprProblem[]): void {
  switch (ast.t) {
    case 'stat':
      if (!scope.streams.includes(ast.stream)) {
        out.push({ message: `unknown stream '${ast.stream}'`, pos: ast.streamPos, len: ast.stream.length })
      }
      return
    case 'binding':
      if (!scope.bindings.includes(ast.name)) {
        out.push({ message: `unknown binding '${ast.name}'`, pos: ast.pos, len: ast.name.length })
      }
      return
    case 'unary':
      walk(ast.operand, scope, out)
      return
    case 'binary':
      walk(ast.left, scope, out)
      walk(ast.right, scope, out)
      return
    default:
      return
  }
}

export function analyzeExpression(
  text: string,
  expected: ExpectedType,
  scope: ExprScope,
): ExprProblem[] {
  if (text.trim() === '') return []
  const result = parseExpression(text)
  if (!result.ok) {
    const { message, pos, atEnd } = result.error
    return [{ message, pos, len: atEnd ? 0 : 1 }]
  }
  const problems: ExprProblem[] = []
  walk(result.ast, scope, problems)
  const ast = result.ast
  if (expected === 'duration' && ast.t === 'const' && typeof ast.value === 'number') {
    problems.push({ message: 'durations need a unit — 30s, not 30', pos: 0, len: text.length })
  }
  if (
    expected === 'int' && ast.t === 'const' && typeof ast.value === 'number' &&
    !Number.isInteger(ast.value)
  ) {
    problems.push({ message: 'expected a whole number', pos: 0, len: text.length })
  }
  return problems
}
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit**: `feat(studio): client-side expression analysis (syntax + scope names + slot heuristics)`

### Task 5: `expr/highlight.ts`

**Files:**
- Create: `webapp/frontend/src/builder/expr/highlight.ts`
- Test: `webapp/frontend/src/builder/expr/highlight.test.ts`

**Interfaces (Produces):**
```ts
export type SpanClass = 'fn' | 'name' | 'number' | 'duration' | 'string' | 'keyword' | 'op' | 'plain' | 'error'
export interface Span { start: number; end: number; cls: SpanClass; underline: boolean }
export function highlightSpans(text: string, underlines: Array<{ pos: number; len: number }>): Span[]
export const SPAN_CLASSES: Record<SpanClass, string>
export const UNDERLINE_CLASS: string
```
Invariant: spans tile `[0, text.length)` exactly, in order, no overlaps.

- [ ] **Step 1: Failing test**:

```ts
import { describe, expect, it } from 'vitest'
import { highlightSpans } from './highlight'

const flat = (text: string, spans = highlightSpans(text, [])) =>
  spans.map((s) => `${s.cls}:${text.slice(s.start, s.end)}${s.underline ? '~' : ''}`)

describe('highlightSpans', () => {
  it('classifies a full expression and tiles the text exactly', () => {
    const text = "mean(od, last=30s) > 0.6 and mode == 'x'"
    const spans = highlightSpans(text, [])
    expect(spans[0]).toMatchObject({ start: 0, end: 4, cls: 'fn' })
    expect(flat(text, spans)).toEqual([
      'fn:mean', 'op:(', 'name:od', 'op:,', 'plain: ', 'name:last', 'op:=',
      'duration:30s', 'op:)', 'plain: ', 'op:>', 'plain: ', 'number:0.6',
      'plain: ', 'keyword:and', 'plain: ', 'name:mode', 'plain: ', 'op:==',
      "plain: ", "string:'x'",
    ])
    expect(spans[0].start).toBe(0)
    expect(spans[spans.length - 1].end).toBe(text.length)
  })
  it('a stat name NOT followed by ( is a plain name; unknown fn is a name too', () => {
    expect(flat('count > 2')[0]).toBe('name:count')
    expect(flat('median(od)')[0]).toBe('name:median')
  })
  it('marks the un-lexable tail as an underlined error span', () => {
    const text = 'od > §3'
    const spans = highlightSpans(text, [])
    const last = spans[spans.length - 1]
    expect(last).toMatchObject({ start: 5, end: 7, cls: 'error', underline: true })
  })
  it('splits spans at underline boundaries', () => {
    const text = 'mean(ph)'
    const spans = highlightSpans(text, [{ pos: 5, len: 2 }])
    expect(flat(text, spans)).toEqual(['fn:mean', 'op:(', 'name:ph~', 'op:)'])
  })
  it('partial underline splits a token', () => {
    const spans = highlightSpans('abcd', [{ pos: 1, len: 2 }])
    expect(spans.map((s) => [s.start, s.end, s.underline])).toEqual([
      [0, 1, false], [1, 3, true], [3, 4, false],
    ])
  })
})
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**:

```ts
/** Token-stream → colored spans for the highlight overlay (spec §3.8). The palette is a
 * NEW color language: state hues (blue/red/amber/emerald) are reserved, so token colors
 * come from violet/teal/fuchsia/slate only; draft-problem underlines are the amber draft
 * language. Contrast verified via `npm run capture` (probe R5). */
import { KEYWORDS, STAT_FNS, tokenize, type Token } from './tokenize'

export type SpanClass =
  | 'fn' | 'name' | 'number' | 'duration' | 'string' | 'keyword' | 'op' | 'plain' | 'error'

export interface Span {
  start: number
  end: number
  cls: SpanClass
  underline: boolean
}

const KEYWORD_SET = new Set<string>(KEYWORDS)
const STAT_FN_SET = new Set<string>(STAT_FNS)

export const SPAN_CLASSES: Record<SpanClass, string> = {
  fn: 'text-violet-700',
  name: 'text-teal-700',
  number: 'text-slate-800',
  duration: 'text-slate-800',
  string: 'text-fuchsia-700',
  keyword: 'text-slate-500',
  op: 'text-slate-500',
  plain: 'text-slate-800',
  error: 'text-slate-800',
}

export const UNDERLINE_CLASS = 'underline decoration-wavy decoration-amber-600'

function clsFor(tok: Token, next: Token | undefined): SpanClass {
  switch (tok.kind) {
    case 'NUMBER':
      return 'number'
    case 'DURATION':
      return 'duration'
    case 'STRING':
      return 'string'
    case 'OP':
      return 'op'
    case 'NAME':
      if (KEYWORD_SET.has(tok.text)) return 'keyword'
      if (STAT_FN_SET.has(tok.text) && next?.kind === 'OP' && next.text === '(') return 'fn'
      return 'name'
    default:
      return 'plain'
  }
}

function classify(text: string): Array<{ start: number; end: number; cls: SpanClass }> {
  const { tokens, error } = tokenize(text)
  const out: Array<{ start: number; end: number; cls: SpanClass }> = []
  let cursor = 0
  const significant = tokens.filter((t) => t.kind !== 'END')
  significant.forEach((tok, i) => {
    if (tok.pos > cursor) out.push({ start: cursor, end: tok.pos, cls: 'plain' })
    const end = tok.pos + tok.text.length
    out.push({ start: tok.pos, end, cls: clsFor(tok, significant[i + 1]) })
    cursor = end
  })
  if (error) {
    if (error.pos > cursor) out.push({ start: cursor, end: error.pos, cls: 'plain' })
    // The bad char AND the un-lexed rest: the engine sees none of it, so paint it as error.
    out.push({ start: error.pos, end: text.length, cls: 'error' })
    cursor = text.length
  }
  if (cursor < text.length) out.push({ start: cursor, end: text.length, cls: 'plain' })
  return out
}

export function highlightSpans(
  text: string,
  underlines: Array<{ pos: number; len: number }>,
): Span[] {
  const cuts = new Set<number>([0, text.length])
  const marks = underlines.filter((u) => u.len > 0)
  for (const u of marks) {
    cuts.add(Math.min(u.pos, text.length))
    cuts.add(Math.min(u.pos + u.len, text.length))
  }
  const base = classify(text)
  for (const s of base) {
    cuts.add(s.start)
    cuts.add(s.end)
  }
  const points = [...cuts].sort((a, b) => a - b)
  const spans: Span[] = []
  for (let i = 0; i < points.length - 1; i++) {
    const [start, end] = [points[i], points[i + 1]]
    if (start === end) continue
    const cls = base.find((s) => s.start <= start && end <= s.end)?.cls ?? 'plain'
    const underlined =
      cls === 'error' || marks.some((u) => u.pos <= start && end <= u.pos + u.len)
    spans.push({ start, end, cls, underline: underlined })
  }
  return spans
}
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit**: `feat(studio): expression token highlighting spans + palette`

### Task 6: `expr/insert.ts` (shared caret insertion)

**Files:**
- Create: `webapp/frontend/src/builder/expr/insert.ts`
- Test: `webapp/frontend/src/builder/expr/insert.test.ts`

**Interfaces (Produces):**
```ts
export interface InsertOptions { replace?: { start: number; end: number }; caretBack?: number }
export function insertFragment(text: string, caret: number, fragment: string, opts?: InsertOptions): { text: string; caret: number }
```

- [ ] **Step 1: Failing test**:

```ts
import { describe, expect, it } from 'vitest'
import { insertFragment } from './insert'

describe('insertFragment', () => {
  it('inserts at the caret', () => {
    expect(insertFragment('a > ', 4, 'od')).toEqual({ text: 'a > od', caret: 6 })
  })
  it('pads with a space against an adjacent identifier', () => {
    expect(insertFragment('not', 3, 'od')).toEqual({ text: 'not od', caret: 6 })
    expect(insertFragment('od', 0, 'not')).toEqual({ text: 'not od', caret: 3 })
  })
  it('does not pad against operators or parens', () => {
    expect(insertFragment('mean(', 5, 'od')).toEqual({ text: 'mean(od', caret: 7 })
  })
  it('replaces a range and honours caretBack', () => {
    expect(insertFragment('me > 2', 2, 'mean()', { replace: { start: 0, end: 2 }, caretBack: 1 }))
      .toEqual({ text: 'mean() > 2', caret: 5 })
  })
})
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**:

```ts
/** Insert-at-caret shared by autocomplete acceptance and the clickable help popover
 * (spec §3.6). Pads a space only where the insert would otherwise glue two identifier
 * tokens together. */
const IDENT_CHAR = /[A-Za-z0-9_]/

export interface InsertOptions {
  replace?: { start: number; end: number }
  /** Move the caret back N chars from the end of the inserted fragment (before any
   * trailing pad space) — e.g. 1 places it inside `name()`. */
  caretBack?: number
}

export function insertFragment(
  text: string,
  caret: number,
  fragment: string,
  opts: InsertOptions = {},
): { text: string; caret: number } {
  const start = opts.replace?.start ?? caret
  const end = opts.replace?.end ?? caret
  let lead = ''
  let tail = ''
  if (start > 0 && IDENT_CHAR.test(text[start - 1]) && IDENT_CHAR.test(fragment[0])) lead = ' '
  if (end < text.length && IDENT_CHAR.test(text[end]) && IDENT_CHAR.test(fragment[fragment.length - 1])) {
    tail = ' '
  }
  const newText = text.slice(0, start) + lead + fragment + tail + text.slice(end)
  return { text: newText, caret: start + lead.length + fragment.length - (opts.caretBack ?? 0) }
}
```

- [ ] **Step 4: Run** → PASS. **Step 5: Commit**: `feat(studio): shared insert-at-caret for completions and help`

### Task 7: `expr/complete.ts` (autocomplete candidates)

**Files:**
- Create: `webapp/frontend/src/builder/expr/complete.ts`
- Test: `webapp/frontend/src/builder/expr/complete.test.ts`

**Interfaces (Produces):**
```ts
export interface Completion { label: string; kind: 'fn' | 'stream' | 'binding' | 'keyword' | 'window'; insert: string; caretBack: number }
export interface CompletionSet { items: Completion[]; replace: { start: number; end: number } }
export function completionsAt(text: string, caret: number, scope: ExprScope, force?: boolean): CompletionSet | null
export function insideStatCallArgs(text: string, caret: number): boolean
```

- [ ] **Step 1: Failing test**:

```ts
import { describe, expect, it } from 'vitest'
import { completionsAt, insideStatCallArgs } from './complete'

const scope = { streams: ['od', 'temp'], bindings: ['feed_ml'] }
const labels = (s: ReturnType<typeof completionsAt>) => s?.items.map((i) => i.label)

describe('completionsAt', () => {
  it('offers functions, streams, bindings, and not at an atom position', () => {
    const s = completionsAt('', 0, scope, true)
    expect(labels(s)).toEqual(['last', 'mean', 'min', 'max', 'count', 'od', 'temp', 'feed_ml', 'not'])
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
    const s = completionsAt('mean > 2', 2, scope)  // caret inside 'mean'
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
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**:

```ts
/** Caret-context autocomplete (spec §3.6): three contexts only — atom position, stat-call
 * first argument, window slot after the comma. Pure so vitest can cover it; the popup DOM
 * is probe territory. */
import type { ExprScope } from './analyze'
import { KEYWORDS, STAT_FNS, tokenize, type Token } from './tokenize'

export interface Completion {
  label: string
  kind: 'fn' | 'stream' | 'binding' | 'keyword' | 'window'
  insert: string
  caretBack: number
}

export interface CompletionSet {
  items: Completion[]
  replace: { start: number; end: number }
}

const STAT_FN_SET = new Set<string>(STAT_FNS)
const ATOM_LEAD_OPS = new Set(['(', '+', '-', '*', '/', '<', '<=', '>', '>=', '==', '!=', '='])
const ATOM_LEAD_NAMES = new Set(['and', 'or', 'not'])

/** Tokens strictly before the caret, and the NAME token the caret touches (pos < caret
 * <= end), if any. Returns null when a lex error precedes the caret. */
function context(text: string, caret: number): { prev: Token[]; partial: Token | null } | null {
  const { tokens, error } = tokenize(text)
  if (error && error.pos < caret) return null
  const before = tokens.filter((t) => t.kind !== 'END' && t.pos < caret)
  const last = before[before.length - 1]
  if (last && last.kind === 'NAME' && caret <= last.pos + last.text.length) {
    return { prev: before.slice(0, -1), partial: last }
  }
  // A caret inside a non-NAME token (number, string, op) is not completable.
  if (last && caret < last.pos + last.text.length) return null
  return { prev: before, partial: null }
}

/** Is the caret inside the argument parens of a stat call? Scans for an unmatched '('
 * whose preceding token is a stat-function name. */
export function insideStatCallArgs(text: string, caret: number): boolean {
  const ctx = context(text, caret)
  if (!ctx) return false
  const prev = ctx.prev
  let depth = 0
  for (let i = prev.length - 1; i >= 0; i--) {
    const t = prev[i]
    if (t.kind !== 'OP') continue
    if (t.text === ')') depth += 1
    else if (t.text === '(') {
      if (depth === 0) {
        const before = prev[i - 1]
        return before?.kind === 'NAME' && STAT_FN_SET.has(before.text)
      }
      depth -= 1
    }
  }
  return false
}

export function completionsAt(
  text: string,
  caret: number,
  scope: ExprScope,
  force = false,
): CompletionSet | null {
  const ctx = context(text, caret)
  if (!ctx) return null
  const { prev, partial } = ctx
  const prefix = partial ? text.slice(partial.pos, caret) : ''
  if (!force && prefix === '') return null
  const last = prev[prev.length - 1]
  const beforeLast = prev[prev.length - 2]

  let pool: Completion[]
  if (last?.kind === 'OP' && last.text === '(' && beforeLast?.kind === 'NAME' && STAT_FN_SET.has(beforeLast.text)) {
    pool = scope.streams.map((s) => ({ label: s, kind: 'stream' as const, insert: s, caretBack: 0 }))
  } else if (last?.kind === 'OP' && last.text === ',' && insideStatCallArgs(text, last.pos)) {
    pool = [{ label: 'last=', kind: 'window', insert: 'last=', caretBack: 0 }]
  } else if (
    last === undefined ||
    (last.kind === 'OP' && ATOM_LEAD_OPS.has(last.text)) ||
    (last.kind === 'NAME' && ATOM_LEAD_NAMES.has(last.text))
  ) {
    pool = [
      ...STAT_FNS.map((f) => ({ label: f, kind: 'fn' as const, insert: `${f}()`, caretBack: 1 })),
      ...scope.streams.map((s) => ({ label: s, kind: 'stream' as const, insert: s, caretBack: 0 })),
      ...scope.bindings.map((b) => ({ label: b, kind: 'binding' as const, insert: b, caretBack: 0 })),
      { label: 'not', kind: 'keyword' as const, insert: 'not', caretBack: 0 },
    ]
  } else {
    return null
  }

  const items = pool.filter((i) => i.label.startsWith(prefix))
  if (items.length === 0) return null
  const replace = partial
    ? { start: partial.pos, end: partial.pos + partial.text.length }
    : { start: caret, end: caret }
  return { items, replace }
}
```

Note `insideStatCallArgs(text, last.pos)` for the window context: the comma itself must be inside the call. `KEYWORDS` import is used by `context` indirectly? — it is NOT; do not import it (oxlint flags unused imports).

- [ ] **Step 4: Run** → PASS; `npm run lint` clean. **Step 5: Commit**: `feat(studio): caret-context autocomplete candidates`

### Task 8: `ExpressionEditor` component + swap into all `ExpressionInput` sites

**Files:**
- Create: `webapp/frontend/src/builder/ExpressionEditor.tsx`
- Modify: `webapp/frontend/src/ui/controls.ts` (ghost textarea variant — a *selecting* option, per the cascade rule)
- Modify: `webapp/frontend/src/builder/exprHelp.ts` (+ `fragment` on window forms), `webapp/frontend/src/builder/exprHelp.test.ts`
- Modify: `webapp/frontend/src/builder/fields.tsx` (ExpressionInput delegates; remove its popover/imports)

**Interfaces:**
- Consumes: everything from Tasks 4-7, `autoGrowHeight`/`collapseNewlines`, `textAreaClass`, `useDismissable`, `IconButton`, scope hooks (`useScopeRefs`, `scopeStreamNames`, `scopeBindingNames`, `collectBindings`, `useActiveTree`), `buildExpressionHelp`.
- Produces: `ExpressionEditor(props: { value: string; onCommit: (v: string) => void; placeholder?: string; expected?: ExpectedType })`. `ExpressionInput` keeps its exact current signature and becomes `return <ExpressionEditor {...props} />`.

- [ ] **Step 1: controls.ts ghost variant.** Change `controlSurfaceClass` and `textAreaClass`:

```ts
function controlSurfaceClass(opts: { mono?: boolean; invalid?: boolean; ghost?: boolean } = {}): string {
  // ghost: the transparent INPUT half of the expression editor's overlay pair — the
  // visual surface (bg, border color) is painted by the overlay div BEHIND it, so the
  // input keeps identical metrics (border width, padding) but transparent paint, a
  // visible caret, and the focus ring on top. Selected here, never appended (CLAUDE.md).
  const border = opts.ghost
    ? 'border-transparent '
    : opts.invalid
      ? 'border-red-400 '
      : 'border-slate-300 '
  const paint = opts.ghost ? 'bg-transparent text-transparent caret-slate-800 ' : 'bg-white '
  return (
    'rounded border px-1.5 text-xs focus:border-blue-400 focus:outline-none ' +
    border + paint + (opts.mono ? 'font-mono' : '')
  ).trim()
}

export function textAreaClass(
  opts: { mono?: boolean; fillParent?: boolean; ghost?: boolean } = {},
): string {
  return (
    `w-full py-0.5 ${controlSurfaceClass(opts)} ` + (opts.fillParent ? 'max-h-full' : '')
  ).trim()
}
```

- [ ] **Step 2: exprHelp fragments.** In `exprHelp.ts`, extend `windowForms` to `Array<{ label: string; example: string; fragment: string | null }>`; `windowExamples` gains `fragment`: `all → null`, `last_n → ', last=5'`, `duration → ', last=30s'`; the unknown-window fallback keeps `fragment: null`. Update `exprHelp.test.ts` expectations accordingly (run `npm test -- exprHelp` after).
- [ ] **Step 3: Write `ExpressionEditor.tsx`** (the scope/help wiring moves here from `ExpressionInput` verbatim, including its two comments; memoized against the unstable-dep trap):

```tsx
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { SquareFunction } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { autoGrowHeight, collapseNewlines } from '../ui/autoGrow'
import { textAreaClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import { useDismissable } from '../ui/useDismissable'
import { analyzeExpression, type ExpectedType, type ExprProblem, type ExprScope } from './expr/analyze'
import { completionsAt, insideStatCallArgs, type Completion, type CompletionSet } from './expr/complete'
import { highlightSpans, SPAN_CLASSES, UNDERLINE_CLASS } from './expr/highlight'
import { insertFragment } from './expr/insert'
import { buildExpressionHelp, type ExpressionHelp } from './exprHelp'
import { DURATION_RE } from './params'
import { collectBindings } from './refs'
import { scopeBindingNames, scopeStreamNames, useScopeRefs } from './scopeRefs'

const MAX_LINES = 6
const VALIDATE_DEBOUNCE_MS = 300
```

Component skeleton (implement exactly; each piece annotated with its spec section):

```tsx
export function ExpressionEditor(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  expected?: ExpectedType
}) {
  const { expected = 'any' } = props
  const streams = useDocStore((s) => s.streams)
  const activeTree = useActiveTree()
  const { group } = useScopeRefs()
  const expression = useCatalogStore((s) => s.catalog?.expression ?? null)
  const scope = useMemo<ExprScope>(
    () => ({
      streams: scopeStreamNames(streams, group),
      bindings: Array.from(new Set([...collectBindings(activeTree), ...scopeBindingNames(group)])),
    }),
    [streams, group, activeTree],
  )
  const help = useMemo<ExpressionHelp | null>(
    () => (expression ? buildExpressionHelp(expression, scope.streams, scope.bindings) : null),
    [expression, scope],
  )

  const taRef = useRef<HTMLTextAreaElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const caretRef = useRef(0)
  const pendingCaretRef = useRef<number | null>(null)
  const [draft, setDraft] = useState(props.value)
  const [problems, setProblems] = useState<ExprProblem[]>([])
  const [popup, setPopup] = useState<{ set: CompletionSet; index: number } | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  useEffect(() => setDraft(props.value), [props.value])
  ...
}
```

Behaviors to implement inside (all from spec §3.1/3.4/3.6):
1. **Auto-grow + scroll sync** — the `useLayoutEffect` from `AutoGrowTextArea` verbatim (height from `autoGrowHeight`, `maxLines: MAX_LINES`), plus `overlayRef.current.style.height = el.style.height` is NOT needed (overlay is `inset-0`); after height set, `overlayRef.current.scrollTop = el.scrollTop`. Textarea `onScroll={() => { if (overlayRef.current && taRef.current) overlayRef.current.scrollTop = taRef.current.scrollTop }}`.
2. **Caret restore** — `useLayoutEffect` on `[draft]`: if `pendingCaretRef.current !== null` → `taRef.current?.focus()`, `taRef.current?.setSelectionRange(p, p)`, clear.
3. **Instant validation** — `useEffect` on `[draft, expected, scope]`: empty trim OR (`expected === 'duration'` && `DURATION_RE.test(draft.trim())`) → `setProblems([])` immediately (the spec §3.7 literal fast-path); else `setTimeout(() => setProblems(analyzeExpression(draft, expected, scope)), VALIDATE_DEBOUNCE_MS)` with cleanup.
4. **applyInsert** helper:
```tsx
const applyInsert = (fragment: string, opts?: { replace?: { start: number; end: number }; caretBack?: number }) => {
  const r = insertFragment(draft, caretRef.current, fragment, opts)
  setDraft(r.text)
  caretRef.current = r.caret
  pendingCaretRef.current = r.caret
  setPopup(null)
}
```
5. **onChange** — `const next = collapseNewlines(e.target.value)`; `setDraft(next)`; `caretRef.current = e.target.selectionStart ?? next.length`; `const set = completionsAt(next, caretRef.current, scope)`; `setPopup(set ? { set, index: 0 } : null)`; if a set opened, `setHelpOpen(false)` (mutual exclusion).
6. **onSelect** — update `caretRef`; if popup open, recompute `completionsAt` at the new caret and update/close.
7. **onKeyDown** (this exact order):
```tsx
if (popup) {
  const n = popup.set.items.length
  if (e.key === 'ArrowDown') { e.preventDefault(); setPopup({ ...popup, index: (popup.index + 1) % n }); return }
  if (e.key === 'ArrowUp') { e.preventDefault(); setPopup({ ...popup, index: (popup.index - 1 + n) % n }); return }
  if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); accept(popup.set.items[popup.index], popup.set.replace); return }
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setPopup(null); return }
}
if (e.key === 'Escape') { setDraft(props.value); return }
if (e.key === 'Enter') { e.preventDefault(); commit(); return }
if (e.key === ' ' && e.ctrlKey) {
  e.preventDefault()
  const set = completionsAt(draft, caretRef.current, scope, true)
  if (set) { setPopup({ set, index: 0 }); setHelpOpen(false) }
}
```
with `const accept = (item: Completion, replace: { start: number; end: number }) => applyInsert(item.insert, { replace, caretBack: item.caretBack })` and `const commit = () => { if (draft !== props.value) props.onCommit(draft) }`.
8. **onBlur** — `commit(); setPopup(null)`.
9. **Render** — wrapper `useDismissable(helpOpen, () => setHelpOpen(false))` ref around everything (same trigger-plus-panel reasoning comment as today):
```tsx
<div ref={wrapRef} className="relative">
  <div className="flex items-start gap-1">
    <div className="relative min-w-0 flex-1">
      <div
        ref={overlayRef}
        aria-hidden
        className={`${textAreaClass({ mono: true })} pointer-events-none absolute inset-0 select-none overflow-hidden whitespace-pre-wrap break-words`}
      >
        {spans.map((s, i) => (
          <span key={i} className={SPAN_CLASSES[s.cls] + (s.underline ? ' ' + UNDERLINE_CLASS : '')}>
            {draft.slice(s.start, s.end)}
          </span>
        ))}
      </div>
      <textarea
        ref={taRef}
        value={draft}
        rows={1}
        placeholder={props.placeholder ?? 'expression'}
        className={`${textAreaClass({ mono: true, ghost: true })} placeholder:text-slate-400 relative resize-none`}
        ... (onChange/onSelect/onKeyDown/onBlur/onScroll above)
      />
    </div>
    <IconButton icon={SquareFunction} label="Expression help"
      onClick={() => { setHelpOpen(!helpOpen); setPopup(null) }}
      className="border border-slate-300" />
  </div>
  {problems.length > 0 && (
    <div className="mt-0.5">
      {problems.map((p, i) => (
        <p key={i} className="text-[10px] text-amber-700">{p.message}</p>
      ))}
    </div>
  )}
  {popup && <CompletionPopup popup={popup} onPick={accept} />}
  {helpOpen && help && <HelpPopover help={help} onName={...} onFn={...} onWindow={...} />}
</div>
```
`const spans = useMemo(() => highlightSpans(draft, problems), [draft, problems])` — `ExprProblem.pos/len` is structurally the underline input. The positioning wrapper around the textarea gets `relative min-w-0 flex-1`; the overlay renders FIRST (behind), textarea after with `relative` (on top). Placeholder: ghost text is transparent, so an explicit `placeholder:text-slate-400` keeps it visible (incidental text — hint-level is acceptable; it sits on white).
   - NOTE the underline-spans subtlety: `problems` are recomputed 300 ms AFTER `draft` changes; `highlightSpans` clamps stale out-of-range underline offsets (Task 5 implementation clamps via `Math.min(..., text.length)`), so a fast delete cannot crash the renderer.
10. **CompletionPopup** (same file, below):
```tsx
function CompletionPopup(props: {
  popup: { set: CompletionSet; index: number }
  onPick: (item: Completion, replace: { start: number; end: number }) => void
}) {
  return (
    <ul role="listbox" aria-label="Completions"
      className="absolute left-0 z-20 mt-1 max-h-48 w-56 overflow-auto rounded border border-slate-300 bg-white py-0.5 text-xs shadow-lg">
      {props.popup.set.items.map((it, i) => (
        <li key={it.kind + it.label} role="option" aria-selected={i === props.popup.index}>
          <button type="button"
            className={'flex w-full items-center justify-between gap-2 px-2 py-0.5 text-left ' +
              (i === props.popup.index ? 'bg-blue-100 text-blue-700' : 'hover:bg-slate-100')}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => props.onPick(it, props.popup.set.replace)}>
            <span className="font-mono">{it.label}</span>
            <span className="text-hint">{it.kind}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}
```
(`onMouseDown preventDefault` keeps textarea focus so blur-commit doesn't fire before the click.)
11. **HelpPopover** (same file) — today's popover JSX with every row a `<button type="button" onMouseDown={(e) => e.preventDefault()} ...>`: streams/bindings render as a wrapped row of per-name buttons calling `onName(name)`; function rows keep the name+example layout, whole row a button calling `onFn(f.name)`; window rows a button calling `onWindow(w)`. Handlers in the editor:
```tsx
const onName = (name: string) => applyInsert(name)
const onFn = (name: string) => applyInsert(`${name}()`, { caretBack: 1 })
const onWindow = (w: { example: string; fragment: string | null }) => {
  if (w.fragment !== null && insideStatCallArgs(draft, caretRef.current)) applyInsert(w.fragment)
  else applyInsert(w.example)
}
```
The popover does NOT close on insert (spec: composition), and `useDismissable` already keeps it open while clicks stay inside the wrapper.
12. **fields.tsx** — `ExpressionInput` becomes:
```tsx
export function ExpressionInput(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
}) {
  return <ExpressionEditor {...props} />
}
```
Delete its old body + now-unused imports (`SquareFunction`, stores, refs/scopeRefs, exprHelp, `AutoGrowTextArea`, `IconButton`, `useDismissable`); keep `DURATION_RE` import (DurationField still uses it in PR 1).

- [ ] **Step 4: Gates**: `npm test` (all suites incl. exprHelp), `npm run typecheck`, `npm run lint` → clean. Fix fallout (e.g. unused imports) now.
- [ ] **Step 5: Commit**: `feat(studio): ExpressionEditor — highlight overlay, autocomplete, clickable help, instant validation`

### Task 9: Field-attributed server diagnostics

**Files:**
- Modify: `webapp/frontend/src/builder/paths.ts` (capture the suffix as `field`), `webapp/frontend/src/builder/paths.test.ts`
- Modify: `webapp/frontend/src/builder/inspectorRules.ts` (+ `claimedFieldSuffixes`), `webapp/frontend/src/builder/inspectorRules.test.ts`
- Modify: `webapp/frontend/src/builder/Inspector.tsx` (FieldDiags + node strip + wiring)

**Interfaces (Produces):**
```ts
// paths.ts
export interface ResolvedPath { uid; role; param; scope; field: string | null }   // + field
export interface MappedDiagnostic extends Diagnostic { uid; role; param; scope; field: string | null }
export function fieldDiagnostics(diags: MappedDiagnostic[], uid: string, fields: string[]): MappedDiagnostic[]
export function unclaimedDiagnostics(diags: MappedDiagnostic[], uid: string, claimed: string[]): MappedDiagnostic[]
// inspectorRules.ts
export function claimedFieldSuffixes(kind: BlockNode['kind']): string[]
```

- [ ] **Step 1: Failing tests.** In `paths.test.ts` add:

```ts
it('captures the context suffix as field', () => {
  const d = resolveOne('blocks[0] branch if')       // use this file's existing resolve fixture helper
  expect(d.field).toBe('branch if')
})
it('param suffixes populate both param and field', () => {
  const d = resolveOne("blocks[0] param 'x'")
  expect(d.param).toBe('x')
  expect(d.field).toBe("param 'x'")
})
it('fieldDiagnostics and unclaimedDiagnostics partition by suffix', () => {
  const diags = [
    { uid: 'u1', field: 'branch if', ... },
    { uid: 'u1', field: null, ... },
    { uid: 'u2', field: 'branch if', ... },
  ] as MappedDiagnostic[]
  expect(fieldDiagnostics(diags, 'u1', ['branch if'])).toHaveLength(1)
  expect(unclaimedDiagnostics(diags, 'u1', ['branch if'])).toHaveLength(1)
})
```
(Adapt to the file's existing test fixtures/helpers — read `paths.test.ts` first and follow its established builders.) In `inspectorRules.test.ts`:
```ts
it('claims the condition/value suffixes per kind', () => {
  expect(claimedFieldSuffixes('branch')).toEqual(['branch if'])
  expect(claimedFieldSuffixes('loop')).toEqual(['loop until'])
  expect(claimedFieldSuffixes('compute')).toEqual(['compute value'])
  expect(claimedFieldSuffixes('record')).toEqual(['record value'])
  expect(claimedFieldSuffixes('abort')).toEqual(['abort if'])
  expect(claimedFieldSuffixes('alarm')).toEqual(['alarm if'])
  expect(claimedFieldSuffixes('wait')).toEqual([])
})
```
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.**
  - `paths.ts`: `NONE` gains `field: null`; where the suffix is split (`const suffix = ...`), thread `field: suffix === '' ? null : suffix` through every `ResolvedPath` return (including the `{ ...NONE, param }` early-outs, which become `{ ...NONE, param, field }`); append the two pure filters:
```ts
/** Diagnostics for one field of one block (Inspector, spec §3.5). */
export function fieldDiagnostics(
  diags: MappedDiagnostic[], uid: string, fields: string[],
): MappedDiagnostic[] {
  return diags.filter((d) => d.uid === uid && d.field !== null && fields.includes(d.field))
}

/** Diagnostics for a block that no rendered field claims — the Inspector-level strip. */
export function unclaimedDiagnostics(
  diags: MappedDiagnostic[], uid: string, claimed: string[],
): MappedDiagnostic[] {
  return diags.filter((d) => d.uid === uid && (d.field === null || !claimed.includes(d.field)))
}
```
  - `inspectorRules.ts`:
```ts
/** Diagnostic suffixes (validate.py context strings) CLAIMED by a field rendered in this
 * kind's Inspector form — everything else for the node falls to the header strip.
 * PR 2 adds the duration/count slots ('wait duration', 'loop count', 'loop pace',
 * 'retry backoff', 'gap_after', 'start_offset'). */
export function claimedFieldSuffixes(kind: BlockNode['kind']): string[] {
  switch (kind) {
    case 'branch': return ['branch if']
    case 'loop': return ['loop until']
    case 'compute': return ['compute value']
    case 'record': return ['record value']
    case 'abort': return ['abort if']
    case 'alarm': return ['alarm if']
    default: return []
  }
}
```
(import `BlockNode` type from `./tree` if not already imported there; if the import would be new, type the param as `string` keyed by the same union to avoid a cycle — check what inspectorRules.ts already imports.)
  - `Inspector.tsx`: add
```tsx
function FieldDiags({ uid, fields }: { uid: string; fields: string[] }) {
  const diagnostics = useDocStore((s) => s.diagnostics)
  const matches = fieldDiagnostics(diagnostics, uid, fields)
  return (
    <>
      {matches.map((d, i) => (
        <p key={i} className="mt-0.5 text-[10px] text-red-600">{d.message}</p>
      ))}
    </>
  )
}

function NodeDiagStrip({ node }: { node: BlockNode }) {
  const diagnostics = useDocStore((s) => s.diagnostics)
  const rest = unclaimedDiagnostics(diagnostics, node.uid, claimedFieldSuffixes(node.kind))
  if (rest.length === 0) return null
  return (
    <div className="mb-1">
      {rest.map((d, i) => (
        <p key={i} className="text-[10px] text-red-600">{d.message}</p>
      ))}
    </div>
  )
}
```
Render `<NodeDiagStrip node={node} />` directly under the block-form title (locate the single place the selected block's form header renders — the component that consults `KIND_TITLES`). Then under each expression FieldRow add the matching `<FieldDiags uid={node.uid} fields={['branch if']} />` (branch), `['loop until']` (loop until row only), `['compute value']`/`['record value']` (ValueForm — pick by `node.kind`), `['abort if']`/`['alarm if']` (ConditionForm by `node.kind`), and in the param editor (`ParamInput` call site at Inspector.tsx:881 area) `fields={[`param '${spec.name}'`, `param "${spec.name}"`]}` (both quote spellings — `!r` flips on embedded quotes).
- [ ] **Step 4: Gates**: `npm test`, `npm run typecheck`, `npm run lint` → clean.
- [ ] **Step 5: Commit**: `feat(studio): server diagnostics attributed to Inspector fields`

### Task 10: PR 1 finalize — full gates, probe, PR, CI, merge

- [ ] **Step 1: Full local gates** (worktree): frontend `npm test && npm run typecheck && npm run lint && npm run build`; engine pytest; backend pytest (commands in Global Constraints). All green.
- [ ] **Step 2: Probe/capture** — `npm run capture` per frontend/CLAUDE.md (R4 sibling heights, R5 contrast on the new palette). If the harness needs a live lab/doc and cannot run here, record that explicitly in the PR body (the Manual-device-control increment shipped with capture unrun for the same reason — precedent, not preference). Address any R4/R5 findings (palette bumps per spec §3.8).
- [ ] **Step 3: Push + PR**: `git push -u origin worktree-expression-editor`; `gh pr create` titled `feat(studio): expression editor — highlighting, autocomplete, clickable help, instant validation` with a body summarizing spec §2 decisions + gates run.
- [ ] **Step 4: CI**: `gh pr checks <n> --watch` → all green (else fix, push, repeat).
- [ ] **Step 5: Merge**: `gh pr merge <n> --squash --delete-branch`. Verify `gh pr view <n> --json state` → MERGED.

---

## PR 2 — expression-capable duration/count slots

### Task 11: Branch + doc model + convert round-trip

**Files:**
- Branch: from updated main — `git fetch origin && git checkout -B expr-slots origin/main` (in the same worktree).
- Modify: `webapp/frontend/src/types/doc.ts` (`LoopBody.count?: number | string`)
- Modify: `webapp/frontend/src/builder/tree.ts` (`LoopNode.count: number | string`)
- Modify: `webapp/frontend/src/builder/convert.ts`, Test: `convert.test.ts`

- [ ] **Step 1: Failing tests** (`convert.test.ts`, following its existing round-trip fixtures):

```ts
it('round-trips an expression loop count as a string', () => {
  // build a doc whose loop has count: 'n_cycles + 1', convert to tree and back
  // assert the emitted BlockJson still has count: 'n_cycles + 1'
})
it('canonicalizes a numeric-string count to a JSON number', () => {
  // tree node count '3' (typed as an expression) must serialize as count: 3
})
it('keeps numeric counts as numbers end-to-end', () => { ... })
```
Write them concretely against convert.ts's actual fixture helpers (read the file's existing loop tests first and mirror them).
- [ ] **Step 2: Run** → FAIL (type errors first — that's the point). **Step 3: Implement**: widen the two types; in convert.ts serialization (line ~321):
```ts
if (node.mode === 'count') {
  const c = node.count
  body.count = typeof c === 'string' && /^\d+$/.test(c.trim()) ? Number(c.trim()) : c
}
```
Parsing (line ~174-175) needs no change (`b.count ?? 2` accepts both). Chase compile errors through any other `count` consumers (`summary.ts` renders `×N` markers — coerce with `String(node.count)` where needed; grep `\.count` under `src/builder` and `src/run`).
- [ ] **Step 4: Run** `npm test && npm run typecheck` → PASS. **Step 5: Commit**: `feat(studio): loop count doc model accepts expressions`

### Task 12: Slot editors + diagnostics claims

**Files:**
- Modify: `webapp/frontend/src/builder/fields.tsx` (DurationField), `webapp/frontend/src/builder/Inspector.tsx` (count field, FieldDiags for slots), `webapp/frontend/src/builder/inspectorRules.ts` (+ suffixes), `inspectorRules.test.ts`

- [ ] **Step 1: Failing test** — extend `claimedFieldSuffixes` expectations:
```ts
expect(claimedFieldSuffixes('wait')).toEqual(['wait duration'])
expect(claimedFieldSuffixes('loop')).toEqual(['loop until', 'loop count', 'loop pace'])
```
- [ ] **Step 2: Implement.**
  - `inspectorRules.ts`: `wait → ['wait duration']`, `loop → ['loop until', 'loop count', 'loop pace']`.
  - `fields.tsx` DurationField:
```tsx
export function DurationField(props: {
  value: string | null
  onCommit: (v: string | null) => void
  allowEmpty?: boolean
  placeholder?: string
}) {
  return (
    <ExpressionEditor
      value={props.value ?? ''}
      expected="duration"
      placeholder={props.placeholder ?? 'e.g. 30s, 5min, or an expression'}
      onCommit={(t) => {
        const trimmed = t.trim()
        if (trimmed === '' && props.allowEmpty) props.onCommit(null)
        else props.onCommit(trimmed)
      }}
    />
  )
}
```
(the amber `DURATION_RE` message row disappears — `expected='duration'` analysis replaces it; drop the now-unused `DURATION_RE` import if nothing else in fields.tsx uses it).
  - Inspector count field (LoopForm):
```tsx
<FieldRow label="Count" required>
  <ExpressionEditor
    value={typeof node.count === 'number' ? String(node.count) : node.count}
    expected="int"
    onCommit={(t) => {
      const trimmed = t.trim()
      patchBlock(node.uid, {
        count: trimmed === '' ? 1 : /^\d+$/.test(trimmed) ? Number(trimmed) : trimmed,
      })
    }}
  />
  <FieldDiags uid={node.uid} fields={['loop count']} />
</FieldRow>
```
  - FieldDiags additions: WaitForm duration → `['wait duration']`; LoopForm pace → `['loop pace']`; the retry backoff DurationField (Inspector.tsx:674 area) → `['retry backoff']`; the timing section's gap_after/start_offset DurationFields (Inspector.tsx:527/536 area) → `['gap_after']` / `['start_offset']`. Retry/timing sections render for many kinds whose `claimedFieldSuffixes` doesn't list those suffixes — extend the function: append `['retry backoff', 'gap_after', 'start_offset']` for every kind that renders the failure/timing sections (consult `failureFields`/`timingFields` in inspectorRules.ts and claim accordingly; update the Step-1 test to match what those rules say).
- [ ] **Step 3: Gates**: `npm test && npm run typecheck && npm run lint` → clean.
- [ ] **Step 4: Commit**: `feat(studio): duration/count slots accept expressions`

### Task 13: PR 2 finalize + cleanup

- [ ] **Step 1: Full gates** (frontend four + engine + backend pytest) → green. `npm run capture` best-effort as in Task 10.
- [ ] **Step 2: Push + PR**: branch `expr-slots`, title `feat(studio): expressions in duration and count slots`. Body: engine already accepts these (#58); this is the Studio catch-up. CI watch → green → squash-merge, delete branch.
- [ ] **Step 3: Cleanup**: back on main (`git checkout main && git pull`), remove the worktree (ExitWorktree/`git worktree remove`), prune local branches. Update auto-memory (increment status note).

## Self-review checklist (run after writing, fixed inline)

- Spec coverage: §3.1→T8, §3.2→T1/T2/T4, §3.3→T3, §3.4→T4/T8, §3.5→T9, §3.6→T6/T7/T8, §3.7→T11/T12, §3.8→T5/T10, §4→per-task, §5→T10/T13. No gaps.
- Placeholders: Task 9 Step 1 and Task 11 Step 1 direct the implementer to mirror existing fixture helpers rather than pasting speculative fixture code that may not match those files — deliberate, bounded, and resolved at execution time by reading the named files first.
- Type consistency: `ExprProblem {message,pos,len}` doubles as the underline input (`{pos,len}` structural subset) — checked; `Completion`/`CompletionSet` names match between T7 and T8; `claimedFieldSuffixes` evolves T9→T12 with tests updated in both.
