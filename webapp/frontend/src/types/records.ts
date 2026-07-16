import type { Diagnostic, ExperimentDocJson } from './doc'

export interface RecordRow {
  id: string
  name: string
  experiment_id: string | null
  experiment_name: string
  lab: string
  role_mapping: Record<string, string>
  status: string
  started_at: string
  ended_at: string | null
  dir: string
}

export interface ToleratedErrorJson {
  block_id: string
  error: string
}

export interface AlarmJson {
  block_id: string
  message: string
}

export interface RecordReport {
  status: string
  error: string | null
  finalize_errors: string[]
  persistence_errors: string[]
  diagnostics: Diagnostic[]
  clock_origin: number | null
  started_at: string
  ended_at: string
  experiment_name: string
  lab: string
  role_mapping: Record<string, string>
  // Failures absorbed by on_error: 'continue' (design 2026-07-14 §3.4). A run that dropped 40
  // samples still reports status 'completed' — this is what stops it looking like a clean one.
  tolerated_errors?: ToleratedErrorJson[]
  // alarm blocks that fired (design 2026-07-16 §4.4); a completed run with alarms is not silent.
  alarms?: AlarmJson[]
}

export interface RecordDetail extends RecordRow {
  report: RecordReport | null
  doc: ExperimentDocJson | null
}

export interface StreamSeries {
  t: number[]
  v: number[]
  units: string | null
}

export type RecordStreams = Record<string, StreamSeries>
