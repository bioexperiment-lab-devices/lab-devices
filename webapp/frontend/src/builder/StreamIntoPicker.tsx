import { useState } from 'react'
import { useDocStore } from '../stores/docStore'

/** Picker over declared streams + inline "+ new stream…" creation (audit F15: one
 * affordance for Measure AND Record — record.into stays a picker, never free text,
 * per the W8-settled decision). */
export function StreamIntoPicker(props: { value: string; onPick: (name: string) => void }) {
  const { value, onPick } = props
  const streams = useDocStore((s) => s.streams)
  const addStream = useDocStore((s) => s.addStream)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [units, setUnits] = useState('')
  const [error, setError] = useState<string | null>(null)
  const names = Object.keys(streams)
  const create = () => {
    const err = addStream(name, units || null)
    setError(err)
    if (!err) {
      onPick(name)
      setAdding(false)
      setName('')
      setUnits('')
    }
  }
  return (
    <>
      <select
        value={adding ? '__new__' : value}
        onChange={(e) => {
          if (e.target.value === '__new__') setAdding(true)
          else {
            setAdding(false)
            onPick(e.target.value)
          }
        }}
        className="w-full rounded border border-slate-300 px-1 py-0.5 text-xs"
      >
        {value === '' && !adding && <option value="">— pick a stream —</option>}
        {names.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
        <option value="__new__">+ new stream…</option>
      </select>
      {adding && (
        <div className="mt-1 flex items-center gap-1">
          <input
            value={name}
            placeholder="name"
            onChange={(e) => setName(e.target.value)}
            className="w-20 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
          />
          <input
            value={units}
            placeholder="units"
            onChange={(e) => setUnits(e.target.value)}
            className="w-14 rounded border border-slate-300 px-1 py-0.5 text-xs"
          />
          <button onClick={create} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
            Add
          </button>
        </div>
      )}
      {error && <p className="text-[10px] text-red-600">{error}</p>}
    </>
  )
}
