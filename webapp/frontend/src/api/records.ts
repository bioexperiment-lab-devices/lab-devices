import { apiPath, deleteJson, getJson, patchJson } from './client'
import type { RecordEvent } from '../types/runs'
import type { RecordDetail, RecordRow, RecordStreams } from '../types/records'

export const listRecords = () => getJson<RecordRow[]>('/api/records')
export const getRecord = (id: string) => getJson<RecordDetail>(`/api/records/${id}`)
export const renameRecord = (id: string, name: string) =>
  patchJson<RecordRow>(`/api/records/${id}`, { name })
export const deleteRecord = (id: string) => deleteJson(`/api/records/${id}`)
export const recordEvents = (id: string) => getJson<RecordEvent[]>(`/api/records/${id}/events`)
export const recordStreams = (id: string) => getJson<RecordStreams>(`/api/records/${id}/streams`)
export const recordDownloadUrl = (id: string) => apiPath(`/api/records/${id}/download`)
