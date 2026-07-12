export interface Health {
  status: string
  library: string
  studio: string
}

/** Structured backend error: the {detail, code} envelope from webapp design §6. */
export class ApiError extends Error {
  status: number
  code: string | null

  constructor(status: number, message: string, code: string | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function toApiError(path: string, resp: Response): Promise<ApiError> {
  let message = `${path}: HTTP ${resp.status}`
  let code: string | null = null
  try {
    const body: unknown = await resp.json()
    if (body !== null && typeof body === 'object') {
      const rec = body as Record<string, unknown>
      if (typeof rec.detail === 'string' && rec.detail.length > 0) message = rec.detail
      if (typeof rec.code === 'string') code = rec.code
    }
  } catch {
    // non-JSON body (proxy error page, empty body) — keep the generic message
  }
  return new ApiError(resp.status, message, code)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) throw await toApiError(path, resp)
  if (resp.status === 204) return undefined as T
  return (await resp.json()) as T
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getJson = <T>(path: string) => request<T>(path)
export const postJson = <T>(path: string, body: unknown) => request<T>(path, jsonInit('POST', body))
export const putJson = <T>(path: string, body: unknown) => request<T>(path, jsonInit('PUT', body))
export const deleteJson = (path: string) => request<void>(path, { method: 'DELETE' })

export const getHealth = () => getJson<Health>('/api/health')
