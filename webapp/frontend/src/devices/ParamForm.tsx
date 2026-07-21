import { useMemo, useState } from 'react'
import { Play } from 'lucide-react'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { useDeviceControlStore } from '../stores/deviceControlStore'
import { buildPayload } from './buildPayload'
import type { CommandDef, ParamDef } from './catalog'

const seedValues = (params: ParamDef[]): Record<string, string> => {
  const out: Record<string, string> = {}
  for (const p of params) out[p.name] = p.default === undefined ? '' : String(p.default)
  return out
}

/** Param entry for one command. Number/int stay text inputs so buildPayload owns coercion;
 * enum/bool are selects. Run is disabled until buildPayload yields a payload (all required
 * fields present and numbers parseable). */
export function ParamForm(props: { lab: string; deviceId: string; command: CommandDef }) {
  const { lab, deviceId, command } = props
  const [values, setValues] = useState<Record<string, string>>(() => seedValues(command.params))
  const busy = useDeviceControlStore((s) => s.busy)
  const run = useDeviceControlStore((s) => s.run)

  const payload = useMemo(() => buildPayload(command.params, values), [command.params, values])
  const set = (name: string, v: string) => setValues((prev) => ({ ...prev, [name]: v }))

  return (
    <div className="mt-2 rounded border border-slate-200 bg-white p-2">
      <div className="flex flex-wrap items-end gap-3">
        {command.params.map((p) => (
          <label key={p.name} className="flex flex-col gap-0.5 text-xs">
            <span className="text-caption">
              {p.label}
              {p.unit !== undefined && <span className="text-hint"> ({p.unit})</span>}
              {p.required && <span className="text-hint"> *</span>}
            </span>
            {p.kind === 'enum' ? (
              <select
                value={values[p.name] ?? ''}
                onChange={(e) => set(p.name, e.target.value)}
                className={controlClass({ width: 'w-36' })}
              >
                {!p.required && <option value="">—</option>}
                {(p.options ?? []).map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : p.kind === 'bool' ? (
              <select
                value={values[p.name] ?? ''}
                onChange={(e) => set(p.name, e.target.value)}
                className={controlClass({ width: 'w-24' })}
              >
                {!p.required && <option value="">—</option>}
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                type="text"
                inputMode="decimal"
                value={values[p.name] ?? ''}
                onChange={(e) => set(p.name, e.target.value)}
                className={controlClass({ width: 'w-28' })}
              />
            )}
          </label>
        ))}
        <button
          type="button"
          disabled={busy || payload === null}
          onClick={() => {
            if (payload !== null) void run(lab, deviceId, command.cmd, payload, command.isJob)
          }}
          className={inlineButtonClass() + ' gap-1'}
        >
          <Play size={12} aria-hidden />
          Run
        </button>
      </div>
      {payload === null && (
        <p className="mt-1 text-xs text-hint">Fill the required fields (*) to run.</p>
      )}
    </div>
  )
}
