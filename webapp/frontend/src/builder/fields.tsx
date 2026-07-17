import { useEffect, useState, type ReactNode } from 'react'
import { useCatalogStore } from '../stores/catalogStore'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { collectBindings } from './refs'
import { buildExpressionHelp } from './exprHelp'
import { DURATION_RE } from './params'

const inputClass =
  'w-full rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs focus:border-blue-400 focus:outline-none'

export function FieldRow(props: { label: string; required?: boolean; children: ReactNode }) {
  return (
    <label className="block py-1 text-xs">
      <span className="mb-0.5 block text-slate-500">
        {props.label}
        {props.required && <span className="text-red-500"> *</span>}
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
      className={inputClass + (props.mono ? ' font-mono' : '')}
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
      className={
        'w-full rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs focus:border-blue-400 focus:outline-none' +
        (props.mono ? ' font-mono' : '')
      }
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
      {invalid && <p className="mt-0.5 text-[10px] text-amber-600">expected &lt;number&gt;ms|s|min|h</p>}
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
  return (
    <div className="relative">
      <div className="flex items-center gap-1">
        <TextField
          mono
          value={props.value}
          onCommit={props.onCommit}
          placeholder={props.placeholder ?? 'expression'}
        />
        <button
          type="button"
          title="Expression help"
          onClick={() => setOpen(!open)}
          className="shrink-0 rounded border border-slate-300 px-1 text-xs text-slate-500 hover:bg-slate-200"
        >
          ƒ
        </button>
      </div>
      {open && help && (
        <div className="absolute right-0 z-10 mt-1 w-72 rounded border border-slate-300 bg-white p-2 text-xs shadow-lg">
          <p className="font-semibold text-slate-600">Streams</p>
          <p className="mb-1 font-mono text-slate-500">
            {help.streams.length > 0 ? help.streams.join(', ') : '— none declared —'}
          </p>
          <p className="font-semibold text-slate-600">Bindings</p>
          <p className="mb-1 font-mono text-slate-500">
            {help.bindings.length > 0 ? help.bindings.join(', ') : '— none —'}
          </p>
          <p className="font-semibold text-slate-600">Functions</p>
          <ul className="mb-1">
            {help.functions.map((f) => (
              <li key={f.name} className="flex justify-between gap-2">
                <span className="font-mono">{f.name}</span>
                <span className="font-mono text-slate-400">{f.example}</span>
              </li>
            ))}
          </ul>
          <p className="font-semibold text-slate-600">Windows</p>
          <ul>
            {help.windowForms.map((w) => (
              <li key={w.label} className="flex justify-between gap-2">
                <span>{w.label}</span>
                <span className="font-mono text-slate-400">{w.example}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
