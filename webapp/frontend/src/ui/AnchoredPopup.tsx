import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'

/** A popup that escapes ancestor `overflow` clipping (#7): portalled to document.body,
 * position:fixed, measured from `anchorRef`. Flips above when it would overflow the viewport
 * bottom; clamps horizontally so both edges stay ≥ 8px inside. Generalised from RolesSection's
 * colour picker. The caller supplies the panel chrome (border/bg/shadow/width) as `children`.
 *
 * Pass `panelRef` when a `useDismissable(open, close, panelRef)` must treat this portalled panel
 * as "inside" — the panel lives outside the trigger's DOM subtree, so without it a click on the
 * panel reads as "outside" and dismisses the very panel it landed on. */
export function AnchoredPopup(props: {
  anchorRef: RefObject<HTMLElement | null>
  align: 'left' | 'right'
  children: ReactNode
  panelRef?: RefObject<HTMLDivElement | null>
}) {
  const localRef = useRef<HTMLDivElement>(null)
  const panelRef = props.panelRef ?? localRef
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    const trigger = props.anchorRef.current?.getBoundingClientRect()
    const panel = panelRef.current?.getBoundingClientRect()
    if (!trigger || !panel) return
    const below = trigger.bottom + 4 + panel.height <= window.innerHeight
    const top = below ? trigger.bottom + 4 : Math.max(8, trigger.top - 4 - panel.height)
    const rawLeft = props.align === 'right' ? trigger.right - panel.width : trigger.left
    const left = Math.max(8, Math.min(rawLeft, window.innerWidth - 8 - panel.width))
    setPos({ top, left })
  }, [props.anchorRef, props.align, panelRef])

  return createPortal(
    <div
      ref={panelRef}
      style={{
        position: 'fixed',
        top: pos?.top ?? 0,
        left: pos?.left ?? 0,
        visibility: pos ? 'visible' : 'hidden',
        maxWidth: 'calc(100vw - 16px)',
      }}
      className="z-30"
    >
      {props.children}
    </div>,
    document.body,
  )
}
