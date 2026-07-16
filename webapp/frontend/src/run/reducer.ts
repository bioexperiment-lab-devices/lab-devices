/** Pure fold over the run WS feed (§7.5). Returns a new top-level object per accepted
 * message but appends to events/sample arrays IN PLACE (rev signals appends) so long
 * runs don't pay O(n) copies per message. `seq <= lastSeq` drops replay duplicates. */
import { TERMINAL_STATUSES, type RunWsMsg, type RunEventMsg } from '../types/runs'

export interface StreamSamples {
  t: number[]
  v: number[]
}

export interface FeedState {
  lastSeq: number
  rev: number
  origin: number | null
  lastTimestamp: number | null
  status: string
  terminal: boolean
  events: RunEventMsg[]
  samples: Record<string, StreamSamples>
}

export const emptyFeed = (status = 'running'): FeedState => ({
  lastSeq: -1,
  rev: 0,
  origin: null,
  lastTimestamp: null,
  status,
  terminal: false,
  events: [],
  samples: {},
})

export function applyMessage(s: FeedState, msg: RunWsMsg): FeedState {
  if (msg.seq <= s.lastSeq) return s
  if (msg.type === 'status') {
    return {
      ...s,
      lastSeq: msg.seq,
      rev: s.rev + 1,
      status: msg.status,
      terminal: s.terminal || TERMINAL_STATUSES.has(msg.status),
    }
  }
  s.events.push(msg)
  let samples = s.samples
  // Both carry {stream, value}: `measure_recorded` from a device read (execute.py:647),
  // `sample_recorded` from a `record` block's computed sample (execute.py:691). A stream is
  // measure XOR record in the engine, so the two can never collide on one series.
  if (msg.kind === 'measure_recorded' || msg.kind === 'sample_recorded') {
    const stream = String(msg.data.stream)
    const series = samples[stream] ?? { t: [], v: [] }
    series.t.push(msg.timestamp)
    series.v.push(Number(msg.data.value))
    if (!(stream in samples)) samples = { ...samples, [stream]: series }
  }
  return {
    ...s,
    lastSeq: msg.seq,
    rev: s.rev + 1,
    origin: s.origin ?? msg.timestamp,
    lastTimestamp: msg.timestamp,
    samples,
  }
}
