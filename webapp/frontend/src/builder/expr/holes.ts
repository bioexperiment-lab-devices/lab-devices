/** Group-body {name} holes (engine expand.py `_HOLE_RE`) are not lexable by the parity-pinned
 * expr tokenizer. This masks each `{ident}` to an equal-length bare identifier `_ident_` so the
 * client-side validator/highlighter can tokenize the rest, while recording each hole's span so
 * callers map results back to the original `{name}` form. Equal length keeps every downstream
 * position (underlines, highlight spans) exact. Does NOT touch tokenize.ts/parse.ts — the golden
 * parity corpus and engine port stay in lockstep. */
export interface Hole {
  start: number
  end: number
  name: string
}

const HOLE_RE = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g

export function maskHoles(text: string): { masked: string; holes: Hole[] } {
  const holes: Hole[] = []
  const masked = text.replace(HOLE_RE, (m, name: string, offset: number) => {
    holes.push({ start: offset, end: offset + m.length, name })
    return `_${name}_`
  })
  return { masked, holes }
}
