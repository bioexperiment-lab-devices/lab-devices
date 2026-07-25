/** Caret-context autocomplete (spec §3.6): four contexts — a {hole} reference, atom position,
 * stat-call first argument, and the window slot after the comma. Pure so vitest can cover it;
 * the popup DOM is probe territory. */
import type { ExprScope } from './analyze'
import { maskHoles } from './holes'
import { STAT_FNS, tokenize, type Token } from './tokenize'

export interface Completion {
  label: string
  kind: 'fn' | 'stream' | 'binding' | 'keyword' | 'window'
  insert: string
  caretBack: number
  /** What a typed prefix is matched against — the label, except for a {hole}, where it is the
   * inner name so typing `tu` reaches `{tube}` without the user knowing the brace syntax. */
  match: string
}

export interface CompletionSet {
  items: Completion[]
  replace: { start: number; end: number }
}

const STAT_FN_SET = new Set<string>(STAT_FNS)
const ATOM_LEAD_OPS = new Set(['(', '+', '-', '*', '/', '<', '<=', '>', '>=', '==', '!=', '='])
const ATOM_LEAD_NAMES = new Set(['and', 'or', 'not'])
const IDENT_CHAR = /[A-Za-z0-9_]/

const isHole = (name: string): boolean => name.startsWith('{') && name.endsWith('}')
const inner = (name: string): string => (isHole(name) ? name.slice(1, -1) : name)

/** Tokens strictly before the caret, and the NAME token the caret touches (pos < caret
 * <= end), if any. Returns null when a lex error precedes the caret or the caret sits
 * inside a non-NAME token.
 *
 * {holes} are masked before lexing (holes.ts, PR #80): they are group-body syntax the
 * parity-pinned tokenizer cannot lex, and an unmasked one is a lex error that kills completions
 * for every caret position after it — type one valid `{od}` and the rest of the line went dead.
 * The mask is equal-length by construction, so every token `pos` here still indexes the ORIGINAL
 * text and the replace spans stay valid against it. */
function context(text: string, caret: number): { prev: Token[]; partial: Token | null } | null {
  const { tokens, error } = tokenize(maskHoles(text).masked)
  if (error && error.pos < caret) return null
  const before = tokens.filter((t) => t.kind !== 'END' && t.pos < caret)
  const last = before[before.length - 1]
  if (last && last.kind === 'NAME' && caret <= last.pos + last.text.length) {
    return { prev: before.slice(0, -1), partial: last }
  }
  if (last && caret < last.pos + last.text.length) return null
  return { prev: before, partial: null }
}

/** The caret sits in a `{name` reference: scanning back over identifier characters reaches a `{`.
 * `end` swallows the closing brace when the hole is already complete, so accepting a completion
 * replaces `{tube}` whole rather than nesting a second pair of braces inside it. */
export function holeContextAt(
  text: string,
  caret: number,
): { start: number; end: number; prefix: string } | null {
  let i = caret
  while (i > 0 && IDENT_CHAR.test(text[i - 1])) i -= 1
  if (i === 0 || text[i - 1] !== '{') return null
  const tail = /^[A-Za-z0-9_]*\}/.exec(text.slice(caret))
  return { start: i - 1, end: caret + (tail ? tail[0].length : 0), prefix: text.slice(i, caret) }
}

/** Every {hole} the active scope offers, streams before bindings — the same order as the help
 * popover's sections, so the two reference surfaces list a group's own names alike. */
function holePool(scope: ExprScope): Completion[] {
  const mk = (name: string, kind: 'stream' | 'binding'): Completion => ({
    label: name,
    kind,
    insert: name,
    caretBack: 0,
    match: inner(name),
  })
  return [
    ...scope.streams.filter(isHole).map((s) => mk(s, 'stream')),
    ...scope.bindings.filter(isHole).map((b) => mk(b, 'binding')),
  ]
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
  // A `{` is an explicit trigger: the hole list opens on the brace alone, with no prefix and no
  // Ctrl+Space, because nothing else in the grammar can start with one. At the workflow scope no
  // hole-form names exist, so this yields nothing and `{` stays inert — correct, since holes are
  // group-body syntax and mean nothing out there.
  const hc = holeContextAt(text, caret)
  if (hc) {
    const items = holePool(scope).filter((i) => i.match.startsWith(hc.prefix))
    return items.length === 0 ? null : { items, replace: { start: hc.start, end: hc.end } }
  }
  // Just past a finished `{tube}` there is nothing left to complete, and the masked NAME token
  // would otherwise offer back the very hole the user has just closed.
  if (caret > 0 && text[caret - 1] === '}') return null

  const ctx = context(text, caret)
  if (!ctx) return null
  const { prev, partial } = ctx
  const prefix = partial ? text.slice(partial.pos, caret) : ''
  if (!force && prefix === '') return null
  const last = prev[prev.length - 1]
  const beforeLast = prev[prev.length - 2]
  const streamItem = (s: string): Completion => ({
    label: s,
    kind: 'stream',
    insert: s,
    caretBack: 0,
    match: inner(s),
  })

  let pool: Completion[]
  if (
    last?.kind === 'OP' &&
    last.text === '(' &&
    beforeLast?.kind === 'NAME' &&
    STAT_FN_SET.has(beforeLast.text)
  ) {
    pool = scope.streams.map(streamItem)
  } else if (last?.kind === 'OP' && last.text === ',' && insideStatCallArgs(text, last.pos)) {
    pool = [{ label: 'last=', kind: 'window', insert: 'last=', caretBack: 0, match: 'last=' }]
  } else if (
    last === undefined ||
    (last.kind === 'OP' && ATOM_LEAD_OPS.has(last.text)) ||
    (last.kind === 'NAME' && ATOM_LEAD_NAMES.has(last.text))
  ) {
    pool = [
      ...STAT_FNS.map((f) => ({
        label: f,
        kind: 'fn' as const,
        insert: `${f}()`,
        caretBack: 1,
        match: f,
      })),
      ...scope.streams.map(streamItem),
      ...scope.bindings.map((b) => ({
        label: b,
        kind: 'binding' as const,
        insert: b,
        caretBack: 0,
        match: inner(b),
      })),
      { label: 'not', kind: 'keyword' as const, insert: 'not', caretBack: 0, match: 'not' },
    ]
  } else {
    return null
  }

  // Matched on `match`, not `label`: a bare `tu` must reach `{tube}` (comment #13), so a user
  // never has to know the brace syntax to find a group's own param.
  const items = pool.filter((i) => i.match.startsWith(prefix))
  if (items.length === 0) return null
  const replace = partial
    ? { start: partial.pos, end: partial.pos + partial.text.length }
    : { start: caret, end: caret }
  return { items, replace }
}
