/** Caret-context autocomplete (spec §3.6): three contexts only — atom position, stat-call
 * first argument, window slot after the comma. Pure so vitest can cover it; the popup DOM
 * is probe territory. */
import type { ExprScope } from './analyze'
import { STAT_FNS, tokenize, type Token } from './tokenize'

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
 * <= end), if any. Returns null when a lex error precedes the caret or the caret sits
 * inside a non-NAME token. */
function context(text: string, caret: number): { prev: Token[]; partial: Token | null } | null {
  const { tokens, error } = tokenize(text)
  if (error && error.pos < caret) return null
  const before = tokens.filter((t) => t.kind !== 'END' && t.pos < caret)
  const last = before[before.length - 1]
  if (last && last.kind === 'NAME' && caret <= last.pos + last.text.length) {
    return { prev: before.slice(0, -1), partial: last }
  }
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
  if (
    last?.kind === 'OP' &&
    last.text === '(' &&
    beforeLast?.kind === 'NAME' &&
    STAT_FN_SET.has(beforeLast.text)
  ) {
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
      ...scope.bindings.map((b) => ({
        label: b,
        kind: 'binding' as const,
        insert: b,
        caretBack: 0,
      })),
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
