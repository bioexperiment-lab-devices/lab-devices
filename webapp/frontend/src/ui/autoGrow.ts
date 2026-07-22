/** Decide the rendered height of an auto-growing textarea (spec §4.2, finding #4).
 *
 * Split out as a pure function because vitest here runs in node with no jsdom, so this
 * is the only part of the auto-grow behaviour that can be tested at all. The component
 * does nothing but measure `scrollHeight` and apply what this returns.
 */
export function autoGrowHeight(m: {
  scrollHeight: number
  lineHeight: number
  maxLines: number
  /** Floor for the returned height (defaults to one line). The expression editor passes the
   * 24px control height so a single-line expression matches sibling inputs (#12). */
  minHeight?: number
}): { height: number; overflow: 'hidden' | 'auto' } {
  const cap = m.lineHeight * m.maxLines
  const wanted = Math.max(m.scrollHeight, m.minHeight ?? m.lineHeight)
  if (wanted > cap) return { height: cap, overflow: 'auto' }
  return { height: wanted, overflow: 'hidden' }
}

/** Collapse newlines so a pasted multi-line value stays single-line (spec §4.2, finding #4).
 *
 * Lives here rather than in `builder/` so that `ui/` never imports from a feature module —
 * `AutoGrowTextArea` is the only consumer, via its `singleLine` prop. The expression fields
 * render as textareas purely to get soft wrapping; the VALUE must stay single-line because
 * the expression grammar has no newline token.
 */
export function collapseNewlines(s: string): string {
  return s.replace(/[\r\n]+/g, ' ')
}
