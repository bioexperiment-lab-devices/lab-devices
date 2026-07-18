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
 */
export function useDismissable(open: boolean, onClose: () => void): RefObject<HTMLDivElement | null> {
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
      if (shouldDismiss({ type: e.type, key, target: e.target as Node | null }, ref.current)) {
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
