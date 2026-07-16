import { deleteJson, getJson, postJson, putJson } from './client'
import type { Catalog } from '../types/catalog'
import type {
  ExperimentDocJson,
  ExperimentResource,
  ExperimentSummary,
  ValidateResponse,
} from '../types/doc'

export const getCatalog = () => getJson<Catalog>('/api/catalog')

export const listExperiments = () => getJson<ExperimentSummary[]>('/api/experiments')

export const getExperiment = (id: string) =>
  getJson<ExperimentResource>(`/api/experiments/${id}`)

export const createExperiment = (doc: ExperimentDocJson) =>
  postJson<ExperimentResource>('/api/experiments', doc)

export const importExperiment = (doc: ExperimentDocJson) =>
  postJson<ExperimentResource>('/api/experiments/import', doc)

export const replaceExperiment = (id: string, doc: ExperimentDocJson) =>
  putJson<ExperimentResource>(`/api/experiments/${id}`, doc)

export const deleteExperiment = (id: string) => deleteJson(`/api/experiments/${id}`)

export const duplicateExperiment = (id: string) =>
  postJson<ExperimentResource>(`/api/experiments/${id}/duplicate`, {})

export const validateDoc = (doc: ExperimentDocJson) =>
  postJson<ValidateResponse>('/api/validate', doc)
