import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { useLabsStore } from '../stores/labsStore'
import { useRunStore } from '../stores/runStore'
import { useDeviceControlStore } from '../stores/deviceControlStore'
import { TypeNav } from './TypeNav'
import { DeviceList } from './DeviceList'
import { CommandPanel } from './CommandPanel'
import { ActivityLog } from './ActivityLog'

/** Manual device-control tab (design §4): pick a lab, navigate by device type, name devices,
 * and send commands. Locked while a run is active on the lab (the backend 409 is the backstop,
 * design §6.3). */
export function DevicesTab() {
  const lab = useLabsStore((s) => s.selected)
  const labs = useLabsStore((s) => s.labs)
  const devices = useLabsStore((s) => s.devices)
  const loadingDevices = useLabsStore((s) => s.loadingDevices)
  const devicesError = useLabsStore((s) => s.devicesError)
  const locked = useRunStore((s) => s.phase === 'active' && s.lab === lab)
  const [type, setType] = useState<string | null>(null)

  useEffect(() => {
    void useLabsStore.getState().refreshLabs()
    if (useLabsStore.getState().selected !== null) void useLabsStore.getState().refreshDevices()
    // Learn the current run state so the lock is accurate even if Run was never opened.
    if (useRunStore.getState().phase === 'unknown') void useRunStore.getState().attach()
  }, [])

  // Default the type once devices arrive; keep it valid if the roster changes.
  useEffect(() => {
    if (devices === null || devices.length === 0) return
    const present = new Set(devices.map((d) => d.type))
    if (type === null || !present.has(type)) setType(devices[0].type)
  }, [devices, type])

  // Keep a valid command target for the selected type.
  useEffect(() => {
    if (type === null || devices === null) return
    const ofType = devices.filter((d) => d.type === type)
    const current = useDeviceControlStore.getState().selectedId
    if (!ofType.some((d) => d.id === current)) {
      useDeviceControlStore.getState().select(ofType[0]?.id ?? null)
    }
  }, [type, devices])

  const online = labs?.find((l) => l.name === lab)?.online ?? null
  const ofType = type !== null && devices !== null ? devices.filter((d) => d.type === type) : []

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-caption">Lab</span>
          <select
            value={lab ?? ''}
            onChange={(e) => useLabsStore.getState().selectLab(e.target.value || null)}
            className={controlClass({ width: 'w-48' })}
          >
            <option value="">select a lab…</option>
            {(labs ?? []).map((l) => (
              <option key={l.name} value={l.name}>
                {l.name}
              </option>
            ))}
          </select>
        </label>
        {lab !== null && online !== null && (
          <span
            title={online ? 'online' : 'offline'}
            className={'h-2 w-2 shrink-0 rounded-full ' + (online ? 'bg-emerald-500' : 'bg-slate-500')}
          />
        )}
        <button
          onClick={() => {
            void useLabsStore.getState().refreshLabs()
            void useLabsStore.getState().refreshDevices()
          }}
          disabled={loadingDevices}
          className={inlineButtonClass() + ' ml-auto gap-1'}
        >
          <RefreshCw size={12} aria-hidden />
          Refresh
        </button>
      </div>

      {lab === null ? (
        <p className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-hint">
          Pick a lab to control its devices.
        </p>
      ) : (
        <>
          {locked && (
            <p className="mb-3 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
              A run is active on {lab} — manual control is locked until it finishes.
            </p>
          )}
          {devicesError && (
            <p className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
              {devicesError}{' '}
              <button onClick={() => void useLabsStore.getState().refreshDevices()} className="underline">
                retry
              </button>
            </p>
          )}
          <div className={'flex gap-4 ' + (locked ? 'pointer-events-none opacity-50' : '')}>
            <aside className="w-56 shrink-0">
              <h2 className="mb-2 text-sm font-semibold text-slate-700">Device types</h2>
              {loadingDevices && devices === null ? (
                <p className="text-xs text-caption">loading devices…</p>
              ) : (
                <TypeNav devices={devices ?? []} selected={type} onSelect={setType} />
              )}
            </aside>
            <section className="min-w-0 flex-1">
              {type === null ? (
                <p className="text-xs text-caption">This lab has no devices to control.</p>
              ) : (
                <>
                  <DeviceList lab={lab} devices={ofType} />
                  <CommandPanel lab={lab} devices={ofType} />
                  <ActivityLog />
                </>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
