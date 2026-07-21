import { useState } from 'react'
import { Check, Pencil, X } from 'lucide-react'
import { IconButton } from '../ui/IconButton'
import { controlClass } from '../ui/controls'
import { setDeviceName } from '../api/labs'
import { useLabsStore } from '../stores/labsStore'
import type { LabDevice } from '../types/labs'

/** Inline editable device name. Saves to the backend, then re-pulls the roster so the merged
 * name shows everywhere (Labs table, Run dropdown) from the one source (design §7). */
export function NameEditor(props: { lab: string; device: LabDevice }) {
  const { lab, device } = props
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const begin = () => {
    setValue(device.name ?? '')
    setError(null)
    setEditing(true)
  }

  const save = () => {
    setBusy(true)
    setError(null)
    setDeviceName(lab, device.id, value)
      .then(() => useLabsStore.getState().refreshDevices())
      .then(() => setEditing(false))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (!editing) {
    return (
      <span className="flex items-center gap-1">
        {device.name !== null ? (
          <span className="text-caption">{device.name}</span>
        ) : (
          <span className="text-hint">name…</span>
        )}
        <IconButton icon={Pencil} label="Rename device" onClick={begin} />
      </span>
    )
  }

  return (
    <span className="flex items-center gap-1">
      <input
        type="text"
        autoFocus
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') save()
          if (e.key === 'Escape') setEditing(false)
        }}
        className={controlClass({ width: 'w-40' })}
      />
      <IconButton icon={Check} label="Save name" onClick={save} disabled={busy} />
      <IconButton icon={X} label="Cancel" onClick={() => setEditing(false)} disabled={busy} />
      {error !== null && <span className="text-xs text-red-600">{error}</span>}
    </span>
  )
}
