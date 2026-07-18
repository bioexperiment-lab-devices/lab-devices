import { useEffect, useState, type ReactNode } from 'react'
import { SquareFunction } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { collectBindings } from './refs'
import { buildExpressionHelp } from './exprHelp'
import { DURATION_RE } from './params'
import { controlClass, textAreaClass } from '../ui/controls'
import { AutoGrowTextArea } from '../ui/AutoGrowTextArea'
import { IconButton } from '../ui/IconButton'
import { useDismissable } from '../ui/useDismissable'

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
  const value = props.value ?? ''
  const invalid = value !== '' && !DURATION_RE.test(value)
  return (
    <div>
      <TextField
        mono
        value={value}
        placeholder={props.placeholder ?? 'e.g. 30s, 5min, 250ms, 1.5h'}
        onCommit={(t) => {
          const trimmed = t.trim()
          if (trimmed === '' && props.allowEmpty) props.onCommit(null)
          else props.onCommit(trimmed)
        }}
      />
      {invalid && <p className="mt-0.5 text-[10px] text-amber-700">expected &lt;number&gt;ms|s|min|h</p>}
    </div>
  )
}

export function ExpressionInput(props: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
}) {
  const [open, setOpen] = useState(false)
  const streams = useDocStore((s) => s.streams)
  // Bindings must be collected from the ACTIVE scope, not always the main tree (2026-07-16
  // review, Finding 1): a group body is unreachable from `tree` (a `group_ref` node has no
  // `childSlots`), so an expression inside a group — e.g. morbidostat.json's `groups.service`,
  // whose own `compute` blocks feed later expressions in that same body — needs its own
  // group's bindings, not the main workflow's.
  const activeTree = useActiveTree()
  const expression = useCatalogStore((s) => s.catalog?.expression ?? null)
  const help = expression
    ? buildExpressionHelp(expression, Object.keys(streams), collectBindings(activeTree))
    : null
  // The ref wraps BOTH the trigger and the panel: if the trigger sat outside it, clicking
  // it while open would dismiss and immediately re-open (spec §4.2, finding #6).
  const wrapRef = useDismissable(open, () => setOpen(false))
  return (
    <div ref={wrapRef} className="relative">
      <div className="flex items-start gap-1">
        <AutoGrowTextArea
          mono
          singleLine
          maxLines={6}
          value={props.value}
          onCommit={props.onCommit}
          placeholder={props.placeholder ?? 'expression'}
        />
        <IconButton
          icon={SquareFunction}
          label="Expression help"
          onClick={() => setOpen(!open)}
          className="border border-slate-300"
        />
      </div>
      {open && help && (
        <div className="absolute right-0 z-20 mt-1 w-72 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg">
          <p className="font-semibold text-slate-600">Streams</p>
          <p className="mb-1 font-mono text-caption">
            {help.streams.length > 0 ? help.streams.join(', ') : '— none declared —'}
          </p>
          <p className="font-semibold text-slate-600">Bindings</p>
          <p className="mb-1 font-mono text-caption">
            {help.bindings.length > 0 ? help.bindings.join(', ') : '— none —'}
          </p>
          <p className="font-semibold text-slate-600">Functions</p>
          <ul className="mb-1">
            {help.functions.map((f) => (
              <li key={f.name} className="flex justify-between gap-2">
                <span className="font-mono">{f.name}</span>
                <span className="font-mono text-hint">{f.example}</span>
              </li>
            ))}
          </ul>
          <p className="font-semibold text-slate-600">Windows</p>
          <ul>
            {help.windowForms.map((w) => (
              <li key={w.label} className="flex justify-between gap-2">
                <span>{w.label}</span>
                <span className="font-mono text-hint">{w.example}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
