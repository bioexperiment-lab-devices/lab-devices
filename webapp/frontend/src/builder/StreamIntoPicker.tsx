import { useState } from 'react'
import { useDocStore } from '../stores/docStore'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { useDismissable } from '../ui/useDismissable'

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
  const cancelAdding = () => {
    setAdding(false)
    setName('')
    setUnits('')
    setError(null)
  }
  // The ref wraps the <select> too, not just the inline form below it: the select is the
  // trigger that opens adding mode (picking "__new__") and it stays mounted and visible
  // the whole time adding is open, so it counts as part of the "inside" region — the same
  // trigger-plus-panel shape as ExpressionInput (fields.tsx). If the select sat outside the
  // ref, clicking it — even just to reconsider, without actually changing the selection —
  // would register as an outside pointerdown and dismiss the form, silently discarding
  // whatever the user had typed (spec §4.2, finding #6 analog).
  const wrapRef = useDismissable(adding, cancelAdding)
  return (
    <div ref={wrapRef}>
      <select
        value={adding ? '__new__' : value}
        onChange={(e) => {
          if (e.target.value === '__new__') setAdding(true)
          else {
            setAdding(false)
            onPick(e.target.value)
          }
        }}
        className={controlClass()}
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
            className={controlClass({ mono: true, width: 'w-20' })}
          />
          <input
            value={units}
            placeholder="units"
            onChange={(e) => setUnits(e.target.value)}
            className={controlClass({ width: 'w-14' })}
          />
          <button onClick={create} className={inlineButtonClass()}>
            Add
          </button>
          <button type="button" onClick={cancelAdding} className={inlineButtonClass({ subtle: true })}>
            cancel
          </button>
        </div>
      )}
      {error && <p className="text-[10px] text-red-600">{error}</p>}
    </div>
  )
}
