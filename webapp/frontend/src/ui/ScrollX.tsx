import { useEffect, useState, type RefObject } from 'react'
import { scrollEdges, type ScrollEdges } from './scrollEdges'

const INITIAL_EDGES: ScrollEdges = { overflowing: false, atStart: true, atEnd: true }

function edgesEqual(a: ScrollEdges, b: ScrollEdges): boolean {
  return a.overflowing === b.overflowing && a.atStart === b.atStart && a.atEnd === b.atEnd
}

/** Track which edges of a horizontal scroller still have content beyond them. */
export function useScrollEdges(ref: RefObject<HTMLElement | null>): ScrollEdges {
  const [edges, setEdges] = useState<ScrollEdges>(INITIAL_EDGES)

  // `ref` is a plain object the CALLER owns (`useRef`) — its identity never changes, so an
  // effect keyed on `[ref]` (the previous version of this hook) runs exactly once at mount and
  // can never notice `ref.current` swapping later: mounting behind a conditional, or unmounting
  // in place. Rules of Hooks guarantee this hook body runs on every render of its caller, so
  // mirroring `ref.current` into state — re-checked every render — is how that swap gets
  // noticed at all. The `!==` guard (and React's own bail-out on a same-value `setState`) makes
  // an unrelated re-render of the caller a true no-op here, not a resubscribe.
  const [el, setEl] = useState<HTMLElement | null>(ref.current)
  // No deps array is deliberate — see above; this must run after every render, not just once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (ref.current !== el) setEl(ref.current)
  })

  useEffect(() => {
    if (!el) {
      setEdges(INITIAL_EDGES)
      return
    }

    // Functional update that bails out by returning the SAME `prev` reference when nothing
    // actually changed: React skips the re-render entirely for a same-reference return, which
    // is what keeps this loop-free. Without it, a ResizeObserver/MutationObserver callback ->
    // setEdges -> re-render that (say) toggles a fade's presence near an observed element is
    // the textbook resize-triggers-state-triggers-resize feedback loop.
    const measure = () => {
      setEdges((prev) => {
        const next = scrollEdges(el)
        return edgesEqual(prev, next) ? prev : next
      })
    }
    measure()
    el.addEventListener('scroll', measure, { passive: true })

    // The scroller's own size AND its content's size both change the answer: collapsing a
    // block or adding a lane changes scrollWidth without any scroll event firing.
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    for (const child of Array.from(el.children)) ro.observe(child)

    // Children present at setup time are covered above, but the child SET also changes after
    // mount — ParallelLanes' "Add lane" button, a block collapsing/expanding in place — and
    // neither a `scroll` event nor a resize of the scroller's OWN box fires for that (the
    // scroller's box is unchanged; only its `scrollWidth` moved). Re-sync the observed set
    // whenever the child list itself mutates, and re-measure directly on every mutation:
    // removing a child can shrink `scrollWidth` with nothing left over to report a resize of
    // its own — the node that shrank the content is the one that's now gone.
    const mo = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of Array.from(record.addedNodes)) {
          if (node instanceof Element) ro.observe(node)
        }
        for (const node of Array.from(record.removedNodes)) {
          if (node instanceof Element) ro.unobserve(node)
        }
      }
      measure()
    })
    mo.observe(el, { childList: true })

    return () => {
      el.removeEventListener('scroll', measure)
      mo.disconnect()
      ro.disconnect()
    }
  }, [el])

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
