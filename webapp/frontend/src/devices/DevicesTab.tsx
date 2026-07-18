import { useEffect } from 'react'
import { RefreshCw } from 'lucide-react'
import { useLabsStore } from '../stores/labsStore'

/** Devices tab (spec §9.2): lab picker with online badges, read-only device table, and
 * a confirmed Rediscover that re-enumerates the lab's bus. Device control belongs to
 * experiments, not this tab. Per-device ping is deferred (no §6 endpoint). */
export function DevicesTab() {
  const s = useLabsStore()

  useEffect(() => {
    void useLabsStore.getState().refreshLabs()
    if (useLabsStore.getState().selected !== null) {
      void useLabsStore.getState().refreshDevices()
    }
  }, [])

  const rediscover = () => {
    if (
      window.confirm(
        'Rediscover re-enumerates the serial bus on the lab agent. It takes a few seconds ' +
          'and must not run during an active experiment. Continue?',
      )
    ) {
      void s.rediscover()
    }
  }

  return (
    <div className="flex gap-4">
      <aside className="w-64 shrink-0">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Labs</h2>
          <button
            onClick={() => void s.refreshLabs()}
            disabled={s.loadingLabs}
            className="flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40"
          >
            <RefreshCw size={12} aria-hidden />
            {s.loadingLabs ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        {s.labsError && (
          <p className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
            roster unreachable: {s.labsError}{' '}
            <button onClick={() => void s.refreshLabs()} className="underline">
              retry
            </button>
          </p>
        )}
        {s.labs !== null && s.labs.length === 0 && (
          <p className="text-xs text-hint">no labs in the roster</p>
        )}
        <ul className="space-y-1">
          {(s.labs ?? []).map((lab) => (
            <li key={lab.name}>
              <button
                onClick={() => s.selectLab(lab.name)}
                className={
                  'flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-sm ' +
                  (s.selected === lab.name
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-slate-200 bg-white hover:border-slate-300')
                }
              >
                <span
                  title={lab.online ? 'online' : 'offline'}
                  className={
                    'h-2 w-2 shrink-0 rounded-full ' + (lab.online ? 'bg-emerald-500' : 'bg-slate-500')
                  }
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1">
                    <span className="min-w-0 truncate">{lab.name}</span>
                    {!lab.online && (
                      <span className="shrink-0 rounded bg-slate-200 px-1 text-[10px] uppercase text-slate-600">
                        offline
                      </span>
                    )}
                  </span>
                  <span className="block truncate text-xs text-caption">
                    {lab.host}:{lab.port}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="min-w-0 flex-1">
        {s.selected === null ? (
          s.labsError !== null ? (
            <p className="rounded border border-red-200 bg-red-50 p-8 text-center text-sm text-red-700">
              The lab roster is unreachable, so there are no labs to pick. Use the sidebar’s
              Refresh to retry once the connection is back.
            </p>
          ) : (
            <p className="rounded border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-hint">
              Pick a lab to see its devices.
            </p>
          )
        ) : (
          <>
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-sm font-semibold text-slate-700">Devices — {s.selected}</h2>
              <span className="ml-auto flex gap-1">
                <button
                  onClick={() => void s.refreshDevices()}
                  disabled={s.loadingDevices || s.discovering}
                  className="flex items-center gap-1 rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40"
                >
                  <RefreshCw size={12} aria-hidden />
                  Refresh
                </button>
                <button
                  onClick={rediscover}
                  disabled={s.loadingDevices || s.discovering}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40"
                >
                  {s.discovering ? 'Rediscovering…' : 'Rediscover'}
                </button>
              </span>
            </div>
            {s.devicesError && (
              <p className="mb-2 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-700">
                {s.devicesError}{' '}
                <button onClick={() => void s.refreshDevices()} className="underline">
                  retry
                </button>
              </p>
            )}
            {s.loadingDevices && <p className="text-xs text-hint">loading devices…</p>}
            {s.discovering && (
              <p className="mb-2 rounded border border-blue-200 bg-blue-50 p-2 text-xs text-blue-700">
                Rediscovering devices — this takes a few seconds; the table below is the previous
                enumeration.
              </p>
            )}
            {s.devices !== null && (
              <div className={s.discovering ? 'pointer-events-none opacity-50' : ''}>
                <table className="w-full border-collapse rounded bg-white text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-xs uppercase text-caption">
                      <th className="px-2 py-1.5">id</th>
                      <th className="px-2 py-1.5">type</th>
                      <th className="px-2 py-1.5">port</th>
                      <th className="px-2 py-1.5">connected</th>
                      <th className="px-2 py-1.5">model</th>
                      <th className="px-2 py-1.5">firmware</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.devices.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-2 py-4 text-center text-xs text-hint">
                          no devices attached
                        </td>
                      </tr>
                    )}
                    {s.devices.map((d) => (
                      <tr key={d.id} className="border-b border-slate-100">
                        <td className="px-2 py-1.5 font-mono text-xs">{d.id}</td>
                        <td className="px-2 py-1.5">{d.type}</td>
                        <td className="px-2 py-1.5 font-mono text-xs">{d.port ?? '—'}</td>
                        <td className="px-2 py-1.5">
                          {d.connected === null ? (
                            <span className="text-xs text-caption">—</span>
                          ) : (
                            <span
                              className={
                                'rounded-full px-2 py-0.5 text-xs ' +
                                (d.connected
                                  ? 'bg-emerald-100 text-emerald-700'
                                  : 'bg-slate-100 text-slate-500')
                              }
                            >
                              {d.connected ? 'connected' : 'disconnected'}
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-xs">{d.model ?? '—'}</td>
                        <td className="px-2 py-1.5 text-xs">{d.firmware ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
