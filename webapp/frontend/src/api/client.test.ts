import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiPath, ApiError, getJson, postJson, toApiError } from './client'

describe('apiPath', () => {
  it('strips the leading slash so fetch resolves against the document base', () => {
    expect(apiPath('/api/labs')).toBe('api/labs')
    expect(apiPath('/api/runs/xyz/events?since=3')).toBe('api/runs/xyz/events?since=3')
  })
  it('leaves already-relative paths alone', () => {
    expect(apiPath('api/labs')).toBe('api/labs')
  })
})

describe('toApiError', () => {
  it('extracts the structured {detail, code} envelope', async () => {
    const resp = new Response(JSON.stringify({ detail: 'experiment name taken', code: 'name_conflict' }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    })
    const err = await toApiError('/api/experiments', resp)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(409)
    expect(err.code).toBe('name_conflict')
    expect(err.message).toBe('experiment name taken')
  })

  it('tolerates FastAPI 422 envelopes where detail is a list', async () => {
    const resp = new Response(JSON.stringify({ detail: [{ loc: ['body', 'name'], msg: 'required' }] }), {
      status: 422,
    })
    const err = await toApiError('/api/experiments', resp)
    expect(err.status).toBe(422)
    expect(err.code).toBeNull()
    expect(err.message).toBe('/api/experiments: HTTP 422')
  })

  it('tolerates non-JSON bodies', async () => {
    const resp = new Response('<html>boom</html>', { status: 502 })
    const err = await toApiError('/api/labs', resp)
    expect(err.status).toBe(502)
    expect(err.message).toBe('/api/labs: HTTP 502')
  })
})

const stubFetch = (resp: Response) => vi.stubGlobal('fetch', vi.fn().mockResolvedValue(resp))
afterEach(() => vi.unstubAllGlobals())

describe('request', () => {
  it('parses a JSON body', async () => {
    stubFetch(new Response('{"a":1}', { status: 200 }))
    expect(await getJson<{ a: number }>('/api/x')).toEqual({ a: 1 })
  })
  it('returns undefined for 204', async () => {
    stubFetch(new Response(null, { status: 204 }))
    expect(await postJson<void>('/api/x', {})).toBeUndefined()
  })
  it('returns undefined for an empty 200 body', async () => {
    stubFetch(new Response('', { status: 200 }))
    expect(await getJson<void>('/api/x')).toBeUndefined()
  })
  it('parses a JSON null body', async () => {
    stubFetch(new Response('null', { status: 200 }))
    expect(await getJson<unknown>('/api/x')).toBeNull()
  })
  it('throws ApiError with envelope extras on failure', async () => {
    const body = {
      detail: 'preflight failed', code: 'preflight_failed',
      diagnostics: [{ category: 'mapping', path: "roles['feed']", message: 'unmapped' }],
    }
    stubFetch(new Response(JSON.stringify(body), { status: 422 }))
    const err = await getJson('/api/runs').catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).code).toBe('preflight_failed')
    expect((err as ApiError).diagnostics).toEqual(body.diagnostics)
  })
})

describe('toApiError extras', () => {
  it('captures active_run_id and record_id', async () => {
    const resp = new Response(
      JSON.stringify({ detail: 'busy', code: 'run_active', active_run_id: 'r1', record_id: 'c1' }),
      { status: 409 },
    )
    const err = await toApiError('/api/runs', resp)
    expect(err.activeRunId).toBe('r1')
    expect(err.recordId).toBe('c1')
  })
  it('leaves extras null when absent or malformed', async () => {
    const resp = new Response(JSON.stringify({ detail: 'x', diagnostics: 'nope' }), { status: 422 })
    const err = await toApiError('/api/x', resp)
    expect(err.diagnostics).toBeNull()
    expect(err.activeRunId).toBeNull()
  })
})
