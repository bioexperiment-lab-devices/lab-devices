import { useRef, useState } from 'react'
import { Download, Pencil, X } from 'lucide-react'
import { recordDownloadUrl } from '../api/records'
import { useRecordsStore } from '../stores/recordsStore'
import type { RecordRow } from '../types/records'
import { IconButton, iconButtonClass } from '../ui/IconButton'
import { STATUS_STYLES, formatDuration, formatWhen } from './format'

export function StatusChip(props: { status: string }) {
  const cls = STATUS_STYLES[props.status] ?? 'bg-slate-200 text-slate-600'
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ${cls}`}>{props.status}</span>
  )
}

function NameCell(props: { row: RecordRow }) {
  const rename = useRecordsStore((s) => s.rename)
  const open = useRecordsStore((s) => s.open)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(props.row.name)
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)

  const commit = async () => {
    if (cancelled.current) {
      cancelled.current = false
      setEditing(false)
      return
    }
    const err = draft && draft !== props.row.name ? await rename(props.row.id, draft) : null
    setError(err)
    if (err === null) setEditing(false)
  }

  if (editing) {
    return (
      <div>
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void commit()
            if (e.key === 'Escape') {
              cancelled.current = true
              setEditing(false)
            }
          }}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-sm"
        />
        {error && <p className="text-xs text-red-600">{error}</p>}
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1">
      <button
        onClick={() => open(props.row.id)}
        title={props.row.name}
        className="truncate text-left text-sm hover:underline"
      >
        {props.row.name}
      </button>
      <IconButton
        icon={Pencil}
        label="Rename record"
        onClick={() => {
          setDraft(props.row.name)
          setEditing(true)
          setError(null)
          cancelled.current = false
        }}
      />
    </div>
  )
}

export function RecordsTable() {
  const items = useRecordsStore((s) => s.items)
  const error = useRecordsStore((s) => s.error)
  const loading = useRecordsStore((s) => s.loading)
  const refresh = useRecordsStore((s) => s.refresh)
  const remove = useRecordsStore((s) => s.remove)
  const [rowError, setRowError] = useState<string | null>(null)

  if (error !== null) {
    return (
      <div className="rounded-lg border border-red-200 bg-white p-6 text-center text-sm">
        <p className="mb-2 text-red-700">{error}</p>
        <button onClick={() => void refresh()} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100">
          Retry
        </button>
      </div>
    )
  }
  if (items === null) return <p className="p-6 text-sm text-hint">loading records…</p>
  if (items.length === 0) {
    return <p className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">No records yet — run an experiment first.</p>
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      {rowError && <p className="px-3 pt-2 text-xs text-red-600">{rowError}</p>}
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-xs text-caption">
            <th className="px-3 py-2">Name</th>
            <th className="px-3 py-2">Experiment</th>
            <th className="px-3 py-2">Lab</th>
            <th className="px-3 py-2">Status</th>
            <th className="px-3 py-2">Started</th>
            <th className="px-3 py-2">Duration</th>
            <th className="px-3 py-2" />
          </tr>
        </thead>
        <tbody>
          {items.map((row) => (
            <tr key={row.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
              <td className="max-w-64 px-3 py-1.5"><NameCell row={row} /></td>
              <td className="px-3 py-1.5 text-slate-500">{row.experiment_name}</td>
              <td className="px-3 py-1.5 text-slate-500">{row.lab}</td>
              <td className="px-3 py-1.5"><StatusChip status={row.status} /></td>
              <td className="px-3 py-1.5 text-slate-500">{formatWhen(row.started_at)}</td>
              <td className="px-3 py-1.5 text-slate-500">{formatDuration(row.started_at, row.ended_at)}</td>
              <td className="px-3 py-1.5 text-right">
                <span className="inline-flex items-center justify-end gap-1">
                  <a
                    href={recordDownloadUrl(row.id)}
                    title="Download zip"
                    aria-label="Download zip"
                    className={iconButtonClass() + 'mr-1'}
                  >
                    <Download size={14} aria-hidden />
                  </a>
                  <IconButton
                    icon={X}
                    label="Delete record"
                    destructive
                    onClick={() => {
                      if (!window.confirm(`Delete record '${row.name}' and its artifacts?`)) return
                      void remove(row.id).then(setRowError)
                    }}
                  />
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {loading && <p className="px-3 py-1 text-xs text-hint">refreshing…</p>}
    </div>
  )
}
