import { getJson, postJson, putJson } from './client'
import type { LabDevice, LabSummary } from '../types/labs'

export const listLabs = () => getJson<LabSummary[]>('/api/labs')

export const labDevices = (lab: string) =>
  getJson<LabDevice[]>(`/api/labs/${encodeURIComponent(lab)}/devices`)

export const labDiscover = (lab: string) =>
  postJson<LabDevice[]>(`/api/labs/${encodeURIComponent(lab)}/discover`, {}, 120_000)

export const setDeviceName = (lab: string, id: string, name: string) =>
  putJson<{ name: string | null }>(
    `/api/labs/${encodeURIComponent(lab)}/devices/${encodeURIComponent(id)}/name`,
    { name },
  )
