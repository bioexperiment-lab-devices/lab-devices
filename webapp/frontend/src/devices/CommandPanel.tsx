import { useEffect, useState } from 'react'
import { Square } from 'lucide-react'
import { inlineButtonClass } from '../ui/controls'
import { useDeviceControlStore } from '../stores/deviceControlStore'
import type { LabDevice } from '../types/labs'
import { commandsFor, type CommandDef } from './catalog'
import { deviceLabel } from './deviceLabel'
import { ParamForm } from './ParamForm'

const CATEGORY_ORDER: { key: CommandDef['category']; label: string }[] = [
  { key: 'info', label: 'Info' },
  { key: 'measure', label: 'Measure' },
  { key: 'actuate', label: 'Actuate' },
  { key: 'cal-config', label: 'Cal / Config' },
]

/** The shared per-type command panel: pick a command for the selected device. No-param
 * commands run on click; commands with params reveal a form (design §4). Stop is always
 * available and interrupts any command in flight (design §6.3). */
export function CommandPanel(props: { lab: string; devices: LabDevice[] }) {
  const selectedId = useDeviceControlStore((s) => s.selectedId)
  const busy = useDeviceControlStore((s) => s.busy)
  const run = useDeviceControlStore((s) => s.run)
  const stop = useDeviceControlStore((s) => s.stop)
  const [picked, setPicked] = useState<string | null>(null)

  const device = props.devices.find((d) => d.id === selectedId) ?? null

  // Reset the picked command whenever the target device changes.
  useEffect(() => {
    setPicked(null)
  }, [selectedId])

  if (device === null) {
    return (
      <p className="mt-3 rounded border border-dashed border-slate-300 bg-white p-4 text-center text-xs text-hint">
        Select a device above to send it a command.
      </p>
    )
  }

  const commands = commandsFor(device.type)
  const pickedDef = commands.find((c) => c.cmd === picked) ?? null

  const onCommand = (cmd: CommandDef) => {
    if (cmd.params.length === 0) {
      setPicked(null)
      void run(props.lab, device.id, cmd.cmd, null, cmd.isJob)
    } else {
      setPicked((cur) => (cur === cmd.cmd ? null : cmd.cmd))
    }
  }

  return (
    <div className="mt-3">
      <div className="mb-2 flex items-center gap-2">
        <h3 className="text-xs font-semibold text-slate-700">
          Commands — <span className="font-mono">{deviceLabel(device)}</span>
        </h3>
        <button
          type="button"
          onClick={() => void stop(props.lab, device.id)}
          className={inlineButtonClass({ danger: true }) + ' ml-auto gap-1'}
        >
          <Square size={12} aria-hidden />
          Stop
        </button>
      </div>

      <div className="space-y-1.5">
        {CATEGORY_ORDER.map(({ key, label }) => {
          const group = commands.filter((c) => c.category === key)
          if (group.length === 0) return null
          return (
            <div key={key} className="flex flex-wrap items-center gap-1.5">
              <span className="w-24 shrink-0 text-xs text-caption">{label}</span>
              {group.map((cmd) => (
                <button
                  key={cmd.cmd}
                  type="button"
                  disabled={busy}
                  onClick={() => onCommand(cmd)}
                  className={inlineButtonClass({ active: picked === cmd.cmd })}
                >
                  {cmd.label}
                </button>
              ))}
            </div>
          )
        })}
      </div>

      {pickedDef !== null && (
        <ParamForm key={pickedDef.cmd} lab={props.lab} deviceId={device.id} command={pickedDef} />
      )}
    </div>
  )
}
