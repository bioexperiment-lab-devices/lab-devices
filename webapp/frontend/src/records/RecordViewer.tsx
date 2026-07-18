/** Record viewer (§9.5): chart from /streams, log from /events, report summary, and the
 * workflow snapshot rendered read-only. Every fetch failure renders inline with retry. */
import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { getRecord, recordDownloadUrl, recordEvents, recordStreams } from '../api/records'
import { useRecordsStore } from '../stores/recordsStore'
import type { RecordEvent } from '../types/runs'
import type { RecordDetail, RecordStreams } from '../types/records'
import { EventLog } from '../run/EventLog'
import { StreamChart } from '../charts/StreamChart'
import { StatusChip } from './RecordsTable'
import { formatDuration, formatWhen } from './format'
import { WorkflowSnapshot } from './WorkflowSnapshot'

export function RecordViewer(props: { id: string }) {
  const [detail, setDetail] = useState<RecordDetail | null>(null)
  const [events, setEvents] = useState<RecordEvent[] | null>(null)
  const [streams, setStreams] = useState<RecordStreams | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setError(null)
    Promise.all([getRecord(props.id), recordEvents(props.id), recordStreams(props.id)])
      .then(([d, e, s]) => {
        setDetail(d)
        setEvents(e)
        setStreams(s)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [props.id])
  useEffect(load, [load])

  if (error !== null) {
    return (
      <div className="rounded-lg border border-red-200 bg-white p-6 text-center text-sm">
        <p className="mb-2 text-red-700">{error}</p>
        <button onClick={load} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100">Retry</button>
      </div>
    )
  }
  if (detail === null || events === null || streams === null) {
    return <p className="p-6 text-sm text-hint">loading record…</p>
  }

  const firstTs = Object.values(streams)
    .map((s) => s.t[0])
    .filter((t): t is number => t !== undefined)
  const origin =
    detail.report?.clock_origin ??
    (events.length > 0 ? events[0].timestamp : firstTs.length > 0 ? Math.min(...firstTs) : 0)
  const series = Object.entries(streams).map(([label, s]) => ({
    label,
    units: s.units,
    t: s.t.map((t) => t - origin),
    v: s.v,
  }))

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 py-2">
        <button
          onClick={() => useRecordsStore.getState().open(null)}
          className="inline-flex items-center gap-1 text-xs text-slate-600 hover:underline"
        >
          <ArrowLeft size={12} aria-hidden /> records
        </button>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold" title={detail.name}>{detail.name}</p>
          <p className="text-xs text-caption">
            {detail.experiment_name} · {detail.lab} · {formatWhen(detail.started_at)} ·{' '}
            {formatDuration(detail.started_at, detail.ended_at)}
          </p>
        </div>
        <StatusChip status={detail.status} />
        <a
          href={recordDownloadUrl(detail.id)}
          className="ml-auto rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100"
        >
          Download zip
        </a>
      </div>

      {detail.report !== null && detail.report.error !== null && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">
          <p>error: {detail.report.error}</p>
        </div>
      )}
      {detail.report !== null &&
        (detail.report.finalize_errors.length > 0 ||
          detail.report.persistence_errors.length > 0 ||
          detail.report.diagnostics.length > 0) && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
          {detail.report.finalize_errors.map((e, i) => (
            <p key={`f${i}`}>finalize: {e}</p>
          ))}
          {detail.report.persistence_errors.map((e, i) => (
            <p key={`p${i}`}>persistence: {e}</p>
          ))}
          {detail.report.diagnostics.map((d, i) => (
            <p key={`d${i}`}>
              <span className="font-mono">{d.category} {d.path}</span> {d.message}
            </p>
          ))}
        </div>
      )}

      {/* A run that dropped 40 samples via on_error: 'continue' must not look identical to a
          clean one — this panel is the point of RunReport.tolerated_errors. */}
      {detail.report !== null && (detail.report.tolerated_errors?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="mb-1 font-semibold">
            {detail.report.tolerated_errors?.length} block failure(s) tolerated
          </p>
          {detail.report.tolerated_errors?.map((t, i) => (
            <p key={`t${i}`}>
              <span className="font-mono">{t.block_id}</span>: {t.error}
            </p>
          ))}
        </div>
      )}

      {/* An alarm block firing must not look identical to a silent run — this panel is the
          point of RunReport.alarms (design 2026-07-16 §4.4). */}
      {detail.report !== null && (detail.report.alarms?.length ?? 0) > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="mb-1 font-semibold">
            {detail.report.alarms?.length} alarm(s)
          </p>
          {detail.report.alarms?.map((a, i) => (
            <p key={`a${i}`}>
              <span className="font-mono">{a.block_id}</span>: {a.message}
            </p>
          ))}
        </div>
      )}

      <StreamChart series={series} />
      <EventLog events={events} origin={events.length > 0 ? events[0].timestamp : null} rev={0} />

      <div className="rounded-lg border border-slate-200 bg-white p-3">
        <p className="mb-2 text-xs font-semibold text-caption">Workflow snapshot</p>
        <WorkflowSnapshot doc={detail.doc} />
        <p className="mt-2 text-[10px] text-caption">
          roles: {Object.entries(detail.role_mapping).map(([r, d]) => `${r} → ${d}`).join(', ') || '—'}
        </p>
      </div>
    </div>
  )
}
