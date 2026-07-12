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
