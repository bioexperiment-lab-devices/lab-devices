import { useEffect, useRef, type RefObject } from 'react'

export type DismissTarget = Node
export type DismissContainer = { contains: (n: DismissTarget) => boolean }

/** Should this event close the open transient layer? (spec §4.2, finding #6.)
 *
 * Pure so the node-env vitest setup can test it; the hook below is only wiring.
 * Escape wins regardless of focus position — a user pressing Escape means "close it"
 * even while the caret sits inside the layer.
 */
export function shouldDismiss(
  e: { type: string; key?: string; target: DismissTarget | null },
  container: DismissContainer | null,
): boolean {
  if (e.type === 'keydown') return e.key === 'Escape'
  if (!container || !e.target) return false
  return !container.contains(e.target)
}

/** Close `open` layers on outside pointerdown or Escape. Attach the returned ref to the
 * element that counts as "inside" — for a popover, the wrapper holding BOTH the trigger
 * and the panel, or clicking the trigger to close would immediately reopen it.
 *
 * `pointerdown` rather than `click`: a click that starts inside and ends outside (a drag
 * or a text selection) must not dismiss.
 *
 * `extra`, when given, names a second "inside" container — for a popover panel rendered
 * through a portal (so it can escape a scroll-clipping ancestor), the panel lives outside
 * the DOM subtree the primary ref covers, so a click on it would otherwise read as
 * "outside" and immediately dismiss the very panel it landed on.
 */
export function useDismissable(
  open: boolean,
  onClose: () => void,
  extra?: RefObject<HTMLElement | null>,
): RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement>(null)
  // Held in a ref so a caller passing an inline arrow does not re-register listeners
  // on every render.
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    const handle = (e: Event) => {
      const key = e instanceof KeyboardEvent ? e.key : undefined
      // `extra` is read inside the listener (not captured by the effect's deps) — it's a
      // ref, stable across renders, so it needs no dependency-array entry.
      const container: DismissContainer | null = ref.current && {
        contains: (n: DismissTarget) =>
          Boolean(ref.current?.contains(n) || extra?.current?.contains(n)),
      }
      if (shouldDismiss({ type: e.type, key, target: e.target as Node | null }, container)) {
        onCloseRef.current()
      }
    }
    document.addEventListener('pointerdown', handle)
    document.addEventListener('keydown', handle)
    return () => {
      document.removeEventListener('pointerdown', handle)
      document.removeEventListener('keydown', handle)
    }
  }, [open])

  return ref
}
