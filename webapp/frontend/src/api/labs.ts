import { getJson, postJson } from './client'
import type { LabDevice, LabSummary } from '../types/labs'

export const listLabs = () => getJson<LabSummary[]>('/api/labs')

export const labDevices = (lab: string) =>
  getJson<LabDevice[]>(`/api/labs/${encodeURIComponent(lab)}/devices`)

export const labDiscover = (lab: string) =>
  postJson<LabDevice[]>(`/api/labs/${encodeURIComponent(lab)}/discover`, {})
