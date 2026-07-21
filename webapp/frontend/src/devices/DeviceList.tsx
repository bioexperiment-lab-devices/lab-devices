import { MapPin } from 'lucide-react'
import { inlineButtonClass } from '../ui/controls'
import { useDeviceControlStore } from '../stores/deviceControlStore'
import type { LabDevice } from '../types/labs'
import { NameEditor } from './NameEditor'

function ConnectedBadge(props: { connected: boolean | null }) {
  if (props.connected === null) return <span className="text-xs text-caption">—</span>
  return (
    <span
      className={
        'rounded-full px-2 py-0.5 text-xs ' +
        (props.connected ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500')
      }
    >
      {props.connected ? 'connected' : 'disconnected'}
    </span>
  )
}

/** Devices of the selected type: radio-select the command target, edit the name, and Locate
 * (a bounded visible actuation) to identify which physical unit this is (design §4). */
export function DeviceList(props: { lab: string; devices: LabDevice[] }) {
  const selectedId = useDeviceControlStore((s) => s.selectedId)
  const select = useDeviceControlStore((s) => s.select)
  const locate = useDeviceControlStore((s) => s.locate)
  const busy = useDeviceControlStore((s) => s.busy)

  return (
    <ul className="space-y-1">
      {props.devices.map((d) => (
        <li
          key={d.id}
          className={
            'flex items-center gap-3 rounded border px-2 py-1.5 ' +
            (selectedId === d.id ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white')
          }
        >
          <button
            type="button"
            aria-pressed={selectedId === d.id}
            onClick={() => select(d.id)}
            className={inlineButtonClass({ active: selectedId === d.id }) + ' font-mono'}
            title="Make this device the command target"
          >
            {d.id}
          </button>
          <NameEditor lab={props.lab} device={d} />
          <span className="ml-auto flex shrink-0 items-center gap-2">
            <ConnectedBadge connected={d.connected} />
            <button
              type="button"
              disabled={busy}
              onClick={() => void locate(props.lab, { id: d.id, type: d.type })}
              className={inlineButtonClass() + ' gap-1'}
              title="Briefly actuate this device so you can see which physical unit it is"
            >
              <MapPin size={12} aria-hidden />
              Locate
            </button>
          </span>
        </li>
      ))}
    </ul>
  )
}
