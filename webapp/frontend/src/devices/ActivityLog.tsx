import { inlineButtonClass } from '../ui/controls'
import { useDeviceControlStore, type ActivityState } from '../stores/deviceControlStore'

const CHIP: Record<ActivityState, string> = {
  started: 'bg-slate-100 text-slate-600',
  running: 'bg-blue-100 text-blue-700',
  ok: 'bg-emerald-100 text-emerald-700',
  error: 'bg-red-100 text-red-700',
}

const clock = (iso: string): string => {
  const t = iso.slice(11, 19)
  return t === '' ? iso : t
}

/** Ephemeral session log of command → result/error, newest first (design §8). Cleared on
 * refresh; not persisted. */
export function ActivityLog() {
  const activity = useDeviceControlStore((s) => s.activity)
  const clearActivity = useDeviceControlStore((s) => s.clearActivity)

  return (
    <section className="mt-4">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="text-xs font-semibold uppercase text-caption">Activity</h3>
        {activity.length > 0 && (
          <button onClick={clearActivity} className={inlineButtonClass() + ' ml-auto'}>
            Clear
          </button>
        )}
      </div>
      <div className="rounded border border-slate-200 bg-white p-2">
        {activity.length === 0 ? (
          <p className="text-xs text-hint">No commands run yet.</p>
        ) : (
          <ul className="space-y-0.5">
            {activity.map((e) => (
              <li key={e.key} className="flex items-center gap-2 text-xs">
                <span className="shrink-0 font-mono text-hint">{clock(e.at)}</span>
                <span className="shrink-0 font-mono text-caption">{e.device}</span>
                <span className="shrink-0">{e.cmd}</span>
                <span className={'shrink-0 rounded px-1.5 py-0.5 ' + CHIP[e.state]}>
                  {e.state}
                  {e.progress !== null && ` ${Math.round(e.progress * 100)}%`}
                </span>
                <span className="min-w-0 truncate text-caption" title={e.detail}>
                  {e.detail}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
