import { describe, expect, it } from 'vitest'
import { ApiError, toApiError } from './client'

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
