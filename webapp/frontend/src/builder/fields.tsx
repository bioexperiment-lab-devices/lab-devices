import { useEffect, useState, type ReactNode } from 'react'
import { controlClass, textAreaClass } from '../ui/controls'
import { ExpressionEditor } from './ExpressionEditor'

export function FieldRow(props: {
  label: string
  required?: boolean
  /** Lets this row's field grow to fill the remaining space in a flex-column parent and
   * scroll internally once it runs out, instead of the row just sizing to its content
   * (Inspector's "Experiment"/"Group" panels — the description/params field grows while
   * the trailing summary lines stay pinned to the bottom). `min-h-0` is load-bearing: without
   * it a flex child refuses to shrink below its content, so the field pushes the pinned
   * lines off the panel instead of scrolling. */
  grow?: boolean
  children: ReactNode
}) {
  return (
    <label className={'text-xs ' + (props.grow ? 'flex min-h-0 flex-1 flex-col py-1' : 'block py-1')}>
      <span className="mb-0.5 block text-caption">
        {props.label}
        {/* red-600 is this app's standard error red (Toolbar, ProblemsPanel, diagnostics);
            red-500 measured 3.64:1 (probe R5) and is below AA on meaning-carrying text. */}
        {props.required && <span className="text-red-600"> *</span>}
      </span>
      {props.children}
    </label>
  )
}

export function TextField(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  mono?: boolean
}) {
  const [draft, setDraft] = useState(props.value)
  useEffect(() => setDraft(props.value), [props.value])
  const commit = () => {
    if (draft !== props.value) props.onCommit(draft)
  }
  return (
    <input
      value={draft}
      placeholder={props.placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit()
        if (e.key === 'Escape') setDraft(props.value)
      }}
      className={controlClass({ mono: props.mono })}
    />
  )
}

export function TextAreaField(props: {
  value: string
  onCommit: (v: string) => void
  rows?: number
  mono?: boolean
  placeholder?: string
}) {
  const [draft, setDraft] = useState(props.value)
  useEffect(() => setDraft(props.value), [props.value])
  const commit = () => {
    if (draft !== props.value) props.onCommit(draft)
  }
  return (
    <textarea
      value={draft}
      rows={props.rows ?? 3}
      placeholder={props.placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Escape') setDraft(props.value)
      }}
      className={textAreaClass({ mono: props.mono })}
    />
  )
}

export function NumberField(props: {
  value: number | null
  onCommit: (v: number | null) => void
  integer?: boolean
  min?: number
  placeholder?: string
}) {
  const text = props.value === null ? '' : String(props.value)
  return (
    <TextField
      mono
      value={text}
      placeholder={props.placeholder}
      onCommit={(t) => {
        const trimmed = t.trim()
        if (trimmed === '') {
          props.onCommit(null)
          return
        }
        const n = Number(trimmed)
        if (Number.isNaN(n)) return
        if (props.integer && !Number.isInteger(n)) return
        if (props.min !== undefined && n < props.min) return
        props.onCommit(n)
      }}
    />
  )
}

export function DurationField(props: {
  value: string | null
  onCommit: (v: string | null) => void
  allowEmpty?: boolean
  placeholder?: string
}) {
  // A duration slot is a number<s> expression since schema v3 (engine #58): a literal
  // (`30s`) or an expression (`cycle_min * 1min`). The editor's `expected='duration'`
  // analysis replaces the old DURATION_RE-only amber message.
  return (
    <ExpressionEditor
      value={props.value ?? ''}
      expected="duration"
      placeholder={props.placeholder ?? 'e.g. 30s, 5min, or an expression'}
      onCommit={(t) => {
        const trimmed = t.trim()
        if (trimmed === '' && props.allowEmpty) props.onCommit(null)
        else props.onCommit(trimmed)
      }}
    />
  )
}

export function ExpressionInput(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
}) {
  return <ExpressionEditor {...props} />
}
