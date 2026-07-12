import { getJson, postJson } from './client'
import type { ActiveRunPayload } from '../types/runs'

export interface StartRunBody {
  experiment_id: string
  lab: string
  role_mapping: Record<string, string>
}

export const startRun = (body: StartRunBody) => postJson<{ run_id: string }>('/api/runs', body)
export const getActiveRun = () => getJson<ActiveRunPayload | null>('/api/runs/active')
export const pauseRun = (id: string) => postJson<void>(`/api/runs/${id}/pause`, {})
export const resumeRun = (id: string) => postJson<void>(`/api/runs/${id}/resume`, {})
export const abortRun = (id: string) => postJson<void>(`/api/runs/${id}/abort`, {})
export const submitRunInput = (id: string, value: boolean | number | string) =>
  postJson<void>(`/api/runs/${id}/input`, { value })
export const savedMapping = (experimentId: string, lab: string) =>
  getJson<Record<string, string>>(
    `/api/experiments/${experimentId}/mappings/${encodeURIComponent(lab)}`,
  )
