/** Token-stream → colored spans for the highlight overlay (spec §3.8). The palette is a
 * NEW color language: state hues (blue/red/amber/emerald) are reserved, so token colors
 * come from violet/teal/fuchsia/slate only; draft-problem underlines are the amber draft
 * language (§3.4: amber = draft, red = server-confirmed). Contrast verified via
 * `npm run capture` (probe R5). */
import { KEYWORDS, STAT_FNS, tokenize, type Token } from './tokenize'

export type SpanClass =
  | 'fn'
  | 'name'
  | 'number'
  | 'duration'
  | 'string'
  | 'keyword'
  | 'op'
  | 'plain'
  | 'error'

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

/** Spans tile [0, text.length) exactly, in order, no overlaps. `underlines` offsets may
 * be stale relative to `text` (the 300 ms analysis debounce) — they are clamped, never
 * trusted. */
export function highlightSpans(
  text: string,
  underlines: Array<{ pos: number; len: number }>,
): Span[] {
  const marks = underlines
    .filter((u) => u.len > 0 && u.pos < text.length)
    .map((u) => ({ start: u.pos, end: Math.min(u.pos + u.len, text.length) }))
  const base = classify(text)
  const cuts = new Set<number>([0, text.length])
  for (const m of marks) {
    cuts.add(m.start)
    cuts.add(m.end)
  }
  for (const s of base) {
    cuts.add(s.start)
    cuts.add(s.end)
  }
  const points = [...cuts].sort((a, b) => a - b)
  const spans: Span[] = []
  for (let i = 0; i < points.length - 1; i++) {
    const start = points[i]
    const end = points[i + 1]
    if (start === end) continue
    const cls = base.find((s) => s.start <= start && end <= s.end)?.cls ?? 'plain'
    const underlined = cls === 'error' || marks.some((m) => m.start <= start && end <= m.end)
    spans.push({ start, end, cls, underline: underlined })
  }
  return spans
}
