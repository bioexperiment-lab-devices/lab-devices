/** Construct identity, nesting depth, and how they stay out of the state palette's way
 * (design 2026-07-18-canvas-visual-language §3.1, §3.2).
 *
 * Every colour reaching the canvas before this module meant STATE, never identity: blue is
 * selection and legal drop target, red is error and illegal drop, amber is warning, emerald
 * is valid. A Scratch-style hue-per-family scheme would therefore put category colour in
 * direct competition with error colour — a red-tinted Safety block beside a red-bordered
 * broken block is a canvas that can no longer say *something is wrong here*. So hue stays
 * reserved for state, and construct identity rides on the container card's ALREADY EXISTING
 * border and header row. Nothing new is drawn; an existing stroke is recoloured.
 *
 * Every class below is written out in full. Tailwind 4 scans source text, so an interpolated
 * `bg-${family}-50` would compile to no CSS at all.
 */
import type { BlockNode, FlowKind } from './tree'

/** Keyed by FlowKind, so adding a sixth container kind to tree.ts fails to compile here
 * rather than rendering it as an untinted lookalike of `serial`. */
export const CONSTRUCT_CHROME: Record<FlowKind, { border: string; header: string }> = {
  // Sequential is the baseline construct and gets the quietest treatment — a tint on the
  // most common container would be noise, not signal.
  serial: { border: 'border-slate-300', header: 'bg-slate-50' },
  parallel: { border: 'border-teal-200', header: 'bg-teal-50' },
  branch: { border: 'border-violet-200', header: 'bg-violet-50' },
  // loop and for_each carried BYTE-IDENTICAL container classes before this increment
  // ('ml-2 border-l-2 border-slate-200 px-2 pb-2' for both), so they are the pair a reader
  // most often confuses. Their hues are deliberately the furthest apart in this map.
  loop: { border: 'border-fuchsia-200', header: 'bg-fuchsia-50' },
  for_each: { border: 'border-lime-200', header: 'bg-lime-50' },
}

const NEUTRAL_BORDER = 'border-slate-300'
const SELECTED_BORDER = 'border-blue-500'

export function isFlowKind(kind: BlockNode['kind']): kind is FlowKind {
  return kind in CONSTRUCT_CHROME
}

/** The card's single border class.
 *
 * Selection SELECTS rather than appends. `border-blue-500` and `border-fuchsia-200` are
 * equal-specificity utilities in the same `@layer utilities` block, so appending would let
 * the compiled stylesheet's declaration order decide which wins — the exact defect that
 * shipped in W12, where an appended `text-blue-700` lost to a baked-in `text-slate-500` and
 * the active-scope highlight never rendered while looking perfect in source. Returning one
 * class means there is no cascade fight to lose, which is strictly stronger than winning it.
 */
export function cardBorderClass(opts: {
  kind: BlockNode['kind']
  selected: boolean
}): string {
  if (opts.selected) return SELECTED_BORDER
  return isFlowKind(opts.kind) ? CONSTRUCT_CHROME[opts.kind].border : NEUTRAL_BORDER
}

/** Header-row fill for containers; empty string for leaves, which stay `bg-white`. */
export function headerFillClass(kind: BlockNode['kind']): string {
  return isFlowKind(kind) ? CONSTRUCT_CHROME[kind].header : ''
}

/** Container interior fill, alternating by depth parity. The outermost container's
 * interior is depth 1.
 *
 * Parity, not a monotone ramp: a ramp runs out of usable range in four levels, and nesting
 * here routinely goes deeper. `bg-white` is deliberately NOT in the rotation — leaf cards
 * are white, so a white interior would leave a card distinguishable only by its 1px border
 * at every other level. `bg-slate-100` matching the canvas backdrop is harmless: the canvas
 * is depth 0 and can never be adjacent to a depth-2 interior.
 */
export function interiorFillClass(depth: number): string {
  return depth % 2 === 1 ? 'bg-slate-50' : 'bg-slate-100'
}
