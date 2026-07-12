import type { Diagnostic } from '../types/doc'

export interface Health {
  status: string
  library: string
  studio: string
}

export interface ApiErrorExtras {
  diagnostics?: Diagnostic[] | null
  activeRunId?: string | null
  recordId?: string | null
}

/** Structured backend error: the {detail, code} envelope from webapp design §6. */
export class ApiError extends Error {
  status: number
  code: string | null
  diagnostics: Diagnostic[] | null
  activeRunId: string | null
  recordId: string | null

  constructor(status: number, message: string, code: string | null = null, extras: ApiErrorExtras = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.diagnostics = extras.diagnostics ?? null
    this.activeRunId = extras.activeRunId ?? null
    this.recordId = extras.recordId ?? null
  }
}

const isDiagnostic = (d: unknown): d is Diagnostic =>
  d !== null && typeof d === 'object' &&
  typeof (d as Diagnostic).category === 'string' &&
  typeof (d as Diagnostic).path === 'string' &&
  typeof (d as Diagnostic).message === 'string'

/** App-absolute '/api/...' → base-relative 'api/...': resolved by fetch/href against the
 * document base URL, so the SPA works both at '/' and behind a prefix-stripping proxy
 * (deployed at /studio/ — companion lab-bridge integration spec). */
export const apiPath = (path: string): string => path.replace(/^\//, '')

export async function toApiError(path: string, resp: Response): Promise<ApiError> {
  let message = `${path}: HTTP ${resp.status}`
  let code: string | null = null
  const extras: ApiErrorExtras = {}
  try {
    const body: unknown = await resp.json()
    if (body !== null && typeof body === 'object') {
      const rec = body as Record<string, unknown>
      if (typeof rec.detail === 'string' && rec.detail.length > 0) message = rec.detail
      if (typeof rec.code === 'string') code = rec.code
      if (Array.isArray(rec.diagnostics) && rec.diagnostics.every(isDiagnostic)) {
        extras.diagnostics = rec.diagnostics
      }
      if (typeof rec.active_run_id === 'string') extras.activeRunId = rec.active_run_id
      if (typeof rec.record_id === 'string') extras.recordId = rec.record_id
    }
  } catch {
    // non-JSON body (proxy error page, empty body) — keep the generic message
  }
  return new ApiError(resp.status, message, code, extras)
}

const DEFAULT_TIMEOUT_MS = 30_000 // generous: guards hangs, not slow agents

async function request<T>(
  path: string, init?: RequestInit, timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  let text: string
  try {
    const resp = await fetch(apiPath(path), { signal: AbortSignal.timeout(timeoutMs), ...init })
    if (!resp.ok) throw await toApiError(path, resp)
    if (resp.status === 204) return undefined as T
    text = await resp.text()
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      throw new ApiError(0, `${path}: request timed out`)
    }
    throw e
  }
  if (text === '') return undefined as T // W3 carry-forward: empty 2xx body is legal
  return JSON.parse(text) as T
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getJson = <T>(path: string, timeoutMs?: number) => request<T>(path, undefined, timeoutMs)
export const postJson = <T>(path: string, body: unknown, timeoutMs?: number) =>
  request<T>(path, jsonInit('POST', body), timeoutMs)
export const putJson = <T>(path: string, body: unknown) => request<T>(path, jsonInit('PUT', body))
export const patchJson = <T>(path: string, body: unknown) => request<T>(path, jsonInit('PATCH', body))
export const deleteJson = (path: string) => request<void>(path, { method: 'DELETE' })

export const getHealth = () => getJson<Health>('/api/health')
