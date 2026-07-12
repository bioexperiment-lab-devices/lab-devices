/** Active-run screen (§9.4): status header + controls, event log, terminal report,
 * operator-input dialog. The live chart slot is filled by Task 9. */
import { useEffect, useState } from 'react'
import { useNavStore } from '../stores/navStore'
import { useRecordsStore } from '../stores/recordsStore'
import { useRunStore } from '../stores/runStore'
import { StatusChip } from '../records/RecordsTable'
import { formatElapsed } from '../records/format'
import { StreamChart } from '../charts/StreamChart'
import { EventLog } from './EventLog'
import { InputDialog } from './InputDialog'

function Elapsed() {
  const feed = useRunStore((s) => s.feed)
  const lastWallMs = useRunStore((s) => s.lastWallMs)
  const [, tick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])
  if (feed.origin === null || feed.lastTimestamp === null) return null
  const base = feed.lastTimestamp - feed.origin
  const drift =
    !feed.terminal && lastWallMs !== null ? (Date.now() - lastWallMs) / 1000 : 0
  return <span className="font-mono text-sm text-slate-500">{formatElapsed(base + drift)}</span>
}

function LiveChart() {
  // feed is a fresh top-level object per accepted message (rev bump) — subscribing to it
  // re-renders on every in-place sample append without copying the arrays
  const feed = useRunStore((s) => s.feed)
  const streamUnits = useRunStore((s) => s.streamUnits)
  const origin = feed.origin ?? 0
  const series = Object.entries(feed.samples).map(([label, s]) => ({
    label,
    units: streamUnits[label] ?? null,
    t: s.t.map((t) => t - origin),
    v: s.v,
  }))
  return <StreamChart series={series} />
}

export function RunView() {
  const experiment = useRunStore((s) => s.experiment)
  const lab = useRunStore((s) => s.lab)
  const feed = useRunStore((s) => s.feed)
  const phase = useRunStore((s) => s.phase)
  const controlBusy = useRunStore((s) => s.controlBusy)
  const report = useRunStore((s) => s.report)
  const recordId = useRunStore((s) => s.recordId)

  const buttonClass =
    'rounded border border-slate-300 bg-white px-3 py-1 text-xs hover:bg-slate-100 disabled:opacity-40'

  return (
    <div className="space-y-3">
      <InputDialog />
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{experiment?.name ?? 'experiment'}</p>
          <p className="text-xs text-slate-400">lab: {lab}</p>
        </div>
        <StatusChip status={feed.status} />
        <Elapsed />
        <span className="ml-auto flex gap-1">
          {phase === 'active' && feed.status === 'running' && (
            <button className={buttonClass} disabled={controlBusy}
              onClick={() => void useRunStore.getState().pause()}>Pause</button>
          )}
          {phase === 'active' && feed.status === 'paused' && (
            <button className={buttonClass} disabled={controlBusy}
              onClick={() => void useRunStore.getState().resume()}>Resume</button>
          )}
          {phase === 'active' && (
            <button
              className={`${buttonClass} text-red-700`}
              disabled={controlBusy}
              onClick={() => {
                if (window.confirm('Abort this run? The finalizer will tear devices down.')) {
                  void useRunStore.getState().abort()
                }
              }}
            >
              Abort
            </button>
          )}
          {phase === 'terminal' && (
            <button className={buttonClass} onClick={() => useRunStore.getState().dismiss()}>
              New run
            </button>
          )}
        </span>
      </div>

      {phase === 'terminal' && (
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
          <p className="mb-1 font-semibold">
            Run finished: <StatusChip status={report?.status ?? feed.status} />
          </p>
          {report?.error && <p className="text-xs text-red-700">error: {report.error}</p>}
          {report !== null && report.finalize_errors.length > 0 && (
            <p className="text-xs text-amber-700">
              finalize errors: {report.finalize_errors.join('; ')}
            </p>
          )}
          {report !== null && report.persistence_errors.length > 0 && (
            <p className="text-xs text-amber-700">
              persistence errors: {report.persistence_errors.join('; ')}
            </p>
          )}
          {recordId !== null && (
            <button
              onClick={() => {
                useRecordsStore.getState().open(recordId)
                useNavStore.getState().setTab('Records')
              }}
              className="mt-2 rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100"
            >
              Open record
            </button>
          )}
        </div>
      )}

      <LiveChart />
      <EventLog events={feed.events} origin={feed.origin} rev={feed.rev} />
    </div>
  )
}
