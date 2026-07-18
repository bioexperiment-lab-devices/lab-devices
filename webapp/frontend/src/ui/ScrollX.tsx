import { useEffect, useState, type RefObject } from 'react'
import { scrollEdges, type ScrollEdges } from './scrollEdges'

/** Track which edges of a horizontal scroller still have content beyond them. */
export function useScrollEdges(ref: RefObject<HTMLElement | null>): ScrollEdges {
  const [edges, setEdges] = useState<ScrollEdges>({
    overflowing: false,
    atStart: true,
    atEnd: true,
  })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => setEdges(scrollEdges(el))
    measure()
    el.addEventListener('scroll', measure, { passive: true })
    // The scroller's own size AND its content's size both change the answer: collapsing a
    // block or adding a lane changes scrollWidth without any scroll event firing.
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    for (const child of Array.from(el.children)) ro.observe(child)
    return () => {
      el.removeEventListener('scroll', measure)
      ro.disconnect()
    }
  }, [ref])

  return edges
}

/** The fade overlays themselves (spec §4.1).
 *
 * These are ABSOLUTE OVERLAYS, not a background — that is the entire fix for finding #1.
 * The old `scroll-x-shadow` utility painted the fade via `background:` on the scroll
 * container, so it rendered behind the white block cards and survived only in the gutters
 * between them, reading as a rendering artifact rather than a feature.
 *
 * Render inside a `relative` parent that also holds the scroller. `from` must match the
 * scroller's own background (e.g. `from-slate-100` on the canvas) or the fade shows a seam.
 */
export function ScrollFades(props: { edges: ScrollEdges; from: string }) {
  const { edges, from } = props
  if (!edges.overflowing) return null
  return (
    <>
      {!edges.atStart && (
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-y-0 left-0 z-10 w-10 bg-gradient-to-r ${from} to-transparent`}
        />
      )}
      {!edges.atEnd && (
        <div
          aria-hidden
          className={`pointer-events-none absolute inset-y-0 right-0 z-10 w-10 bg-gradient-to-l ${from} to-transparent`}
        />
      )}
    </>
  )
}
