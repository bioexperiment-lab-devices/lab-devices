export type ScrollEdges = { overflowing: boolean; atStart: boolean; atEnd: boolean }

/** Which horizontal edges have more content beyond them (spec §3, finding #1).
 *
 * The settled behaviour is that a fade appears at an edge ONLY while content continues
 * that way. The old CSS got this from `background-attachment: local`, but an overlay does
 * not scroll with its content, so the condition has to be computed from scroll position —
 * this function is that computation, and the only reason ScrollX holds state.
 */
export function scrollEdges(
  m: { scrollLeft: number; scrollWidth: number; clientWidth: number },
  tolerance = 1,
): ScrollEdges {
  const overflowing = m.scrollWidth - m.clientWidth > tolerance
  if (!overflowing) return { overflowing: false, atStart: true, atEnd: true }
  return {
    overflowing: true,
    atStart: m.scrollLeft <= tolerance,
    atEnd: m.scrollLeft >= m.scrollWidth - m.clientWidth - tolerance,
  }
}
