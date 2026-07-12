/** Wire types for the run pipeline (§6, §7.4, §7.5). Mirrors the W4 backend exactly. */

export type RunStatus =
  | 'running' | 'paused'
  | 'completed' | 'failed' | 'aborted' | 'cancelled' | 'interrupted'

export const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  'completed', 'failed', 'aborted', 'cancelled', 'interrupted',
])

export interface PendingInput {
  name: string
  type: 'bool' | 'int' | 'float' | 'enum'
  prompt: string | null
  min: number | null
  max: number | null
  choices: string[] | null
  block_id: string
}

export interface ActiveRunPayload {
  run_id: string
  record_id: string
  experiment: { id: string; name: string }
  lab: string
  status: 'running' | 'paused'
  seq: number
  pending_input: PendingInput | null
}

export interface RunEventMsg {
  type: 'event'
  seq: number
  timestamp: number
  kind: string
  block_id: string | null
  data: Record<string, unknown>
}

export interface RunStatusMsg {
  type: 'status'
  seq: number
  status: string
}

export type RunWsMsg = RunEventMsg | RunStatusMsg

/** A run_log.jsonl line (GET /api/records/{id}/events) — an event without the WS envelope. */
export interface RecordEvent {
  timestamp: number
  kind: string
  block_id: string | null
  data: Record<string, unknown>
}
