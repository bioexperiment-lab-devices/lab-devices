import { useRef, useState } from 'react'
import { useDocStore } from '../stores/docStore'
import { streamSources } from './refs'

/** Streams are name + units only (settled decision S5) — per-stream persistence is carried
 * opaquely through convert.ts but has no UI, and the backend forces disk persistence on
 * every run. The source tag shows the stream's writer: measure XOR record (Increment 6). */
export function StreamsPanel() {
  const streams = useDocStore((s) => s.streams)
  const tree = useDocStore((s) => s.tree)
  const addStream = useDocStore((s) => s.addStream)
  const renameStream = useDocStore((s) => s.renameStream)
  const removeStream = useDocStore((s) => s.removeStream)
  const setStreamUnits = useDocStore((s) => s.setStreamUnits)
  const sources = streamSources(tree)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const cancelled = useRef(false)
  const [newName, setNewName] = useState('')
  const [newUnits, setNewUnits] = useState('')

  const commitRename = (from: string) => {
    const err = draft && draft !== from ? renameStream(from, draft) : null
    setError(err)
    if (!err) setEditing(null)
  }

  const add = () => {
    if (!newName) return
    const err = addStream(newName, newUnits || null)
    setError(err)
    if (!err) {
      setNewName('')
      setNewUnits('')
    }
  }

  return (
    <div className="space-y-1">
      <ul className="space-y-1">
        {Object.entries(streams).map(([name, s]) => (
          <li key={name} className="flex items-center gap-1 text-sm">
            {editing === name ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => {
                  if (cancelled.current) {
                    cancelled.current = false
                    return
                  }
                  commitRename(name)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename(name)
                  if (e.key === 'Escape') {
                    cancelled.current = true
                    setEditing(null)
                  }
                }}
                className="w-24 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
              />
            ) : (
              <button
                title="Rename stream"
                onClick={() => {
                  setEditing(name)
                  setDraft(name)
                  setError(null)
                  cancelled.current = false
                }}
                className="rounded px-1 font-mono text-xs hover:bg-slate-200"
              >
                {name}
              </button>
            )}
            <span
              title={
                sources[name] === undefined
                  ? 'No block writes this stream'
                  : `Written by a ${sources[name]} block`
              }
              className="shrink-0 rounded bg-slate-200 px-1 text-xs text-slate-500"
            >
              {sources[name] ?? 'unused'}
            </span>
            <input
              value={s.units ?? ''}
              placeholder="units"
              onChange={(e) => setStreamUnits(name, e.target.value || null)}
              className="w-14 rounded border border-slate-200 px-1 py-0.5 text-xs"
            />
            <button
              title="Delete stream"
              onClick={() => setError(removeStream(name))}
              className="ml-auto rounded px-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600"
            >
              ✕
            </button>
          </li>
        ))}
      </ul>
      <div className="flex items-center gap-1">
        <input
          value={newName}
          placeholder="stream name"
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className="w-24 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
        />
        <input
          value={newUnits}
          placeholder="units"
          onChange={(e) => setNewUnits(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className="w-14 rounded border border-slate-300 px-1 py-0.5 text-xs"
        />
        <button onClick={add} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
