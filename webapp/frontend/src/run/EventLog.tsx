/** Scrolling event log (§9.4): last 500 events, auto-scroll pinned to the bottom unless
 * the pointer is over the log (pause-on-hover). Reused by the record viewer with a
 * static list (rev stays constant there). */
import { useEffect, useRef, useState } from 'react'
import { formatElapsed } from '../records/format'
import { describeEvent } from './describeEvent'

export interface LogEvent {
  timestamp: number
  kind: string
  block_id: string | null
  data: Record<string, unknown>
}

const KIND_COLOR: Record<string, string> = {
  block_failed: 'text-red-700',
  invariant_violation: 'text-red-700',
  finalize_step_failed: 'text-red-700',
  measure_recorded: 'text-blue-700',
  input_requested: 'text-amber-700',
  input_bound: 'text-amber-700',
}

export function EventLog(props: { events: ReadonlyArray<LogEvent>; origin: number | null; rev: number }) {
  const box = useRef<HTMLDivElement | null>(null)
  const [hovered, setHovered] = useState(false)

  useEffect(() => {
    if (!hovered && box.current !== null) box.current.scrollTop = box.current.scrollHeight
  }, [props.rev, hovered])

  const shown = props.events.slice(-500)
  return (
    <div
      ref={box}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white p-2 font-mono text-xs"
    >
      {props.events.length > shown.length && (
        <p className="text-slate-400">
          … showing last {shown.length} of {props.events.length} events (download the zip for the full log)
        </p>
      )}
      {shown.length === 0 && <p className="text-slate-400">no events yet</p>}
      {shown.map((e, i) => (
        <div key={`${props.events.length - shown.length + i}`} className="flex gap-2 py-px">
          <span className="w-20 shrink-0 text-right text-slate-400">
            {props.origin !== null ? `+${formatElapsed(e.timestamp - props.origin)}` : ''}
          </span>
          <span className={`min-w-0 flex-1 ${KIND_COLOR[e.kind] ?? 'text-slate-700'}`}>
            {describeEvent(e)}
            {e.block_id !== null && <span className="ml-1 text-slate-400">[{e.block_id}]</span>}
          </span>
        </div>
      ))}
    </div>
  )
}
