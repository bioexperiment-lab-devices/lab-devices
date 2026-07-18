import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { autoGrowHeight, collapseNewlines } from './autoGrow'
import { textAreaClass } from './controls'

/** A textarea that grows with its content up to `maxLines`, then scrolls internally
 * (spec §4.2, finding #4).
 *
 * `singleLine` serves the expression fields: the expression grammar has no newlines, so
 * newlines are stripped on input and Enter commits instead of inserting one. The value is
 * therefore always single-line — what the textarea buys is SOFT WRAPPING, so a long
 * expression is fully visible instead of scrolling sideways inside a one-line box.
 *
 * `fillParent` is for the Inspector's description (finding #5a): `max-h-full` lets the
 * flex parent bound the growth, so the field fills the free space and no more.
 *
 * Commit semantics deliberately match TextField (fields.tsx): commit on blur, revert on
 * Escape, so no caller has to learn a second interaction model.
 */
export function AutoGrowTextArea(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  mono?: boolean
  maxLines?: number
  singleLine?: boolean
  fillParent?: boolean
}) {
  const { maxLines = 12, singleLine = false, fillParent = false } = props
  const ref = useRef<HTMLTextAreaElement>(null)
  const [draft, setDraft] = useState(props.value)
  useEffect(() => setDraft(props.value), [props.value])

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    // Collapse first: scrollHeight only shrinks if the element is not already tall.
    el.style.height = 'auto'
    const lineHeight = Number.parseFloat(getComputedStyle(el).lineHeight) || 16
    const { height, overflow } = autoGrowHeight({
      scrollHeight: el.scrollHeight,
      lineHeight,
      maxLines,
    })
    el.style.height = `${height}px`
    el.style.overflowY = fillParent ? 'auto' : overflow
  }, [draft, maxLines, fillParent])

  const commit = () => {
    if (draft !== props.value) props.onCommit(draft)
  }

  return (
    <textarea
      ref={ref}
      value={draft}
      rows={1}
      placeholder={props.placeholder}
      onChange={(e) => setDraft(singleLine ? collapseNewlines(e.target.value) : e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Escape') {
          setDraft(props.value)
          return
        }
        if (singleLine && e.key === 'Enter') {
          e.preventDefault()
          commit()
        }
      }}
      className={`resize-none ${textAreaClass({ mono: props.mono, fillParent })}`}
    />
  )
}
