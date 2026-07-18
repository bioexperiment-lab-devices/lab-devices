import { useRef, useState } from 'react'
import { X } from 'lucide-react'
import { useDocStore } from '../stores/docStore'
import { streamSources } from './refs'
import { filterStreamNames } from './streamFilter'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'

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
  const [query, setQuery] = useState('')

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

  const matches = filterStreamNames(Object.keys(streams), query)

  return (
    <div className="space-y-1">
      <input
        value={query}
        placeholder="filter streams…"
        onChange={(e) => setQuery(e.target.value)}
        className={controlClass()}
      />
      <ul className="space-y-1">
        {query.trim() !== '' && matches.length === 0 && (
          <li className="text-xs text-hint">no streams match</li>
        )}
        {matches.map((name) => {
          const s = streams[name]
          return (
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
                className={controlClass({ mono: true }) + ' w-24'}
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
                className={inlineButtonClass()}
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
              className={
                'flex h-6 shrink-0 items-center rounded px-1 text-xs ' +
                (sources[name] === undefined ? 'bg-amber-100 text-amber-700' : 'bg-slate-200 text-slate-600')
              }
            >
              {sources[name] ?? 'unused'}
            </span>
            <input
              value={s.units ?? ''}
              placeholder="units"
              onChange={(e) => setStreamUnits(name, e.target.value || null)}
              className={controlClass() + ' w-14'}
            />
            <IconButton
              icon={X}
              label="Delete stream"
              destructive
              className="ml-auto"
              onClick={() => setError(removeStream(name))}
            />
          </li>
          )
        })}
      </ul>
      <div className="flex items-center gap-1">
        <input
          value={newName}
          placeholder="stream name"
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass({ mono: true }) + ' w-24'}
        />
        <input
          value={newUnits}
          placeholder="units"
          onChange={(e) => setNewUnits(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass() + ' w-14'}
        />
        <button onClick={add} className={inlineButtonClass()}>
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
