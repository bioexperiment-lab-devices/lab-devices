import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { setSocketFactoryForTests, useRunStore } from './runStore'
import type { RunSocketHandlers } from '../api/runSocket'
import type { RunWsMsg } from '../types/runs'

const ACTIVE = {
  run_id: 'r1', record_id: 'r1', experiment: { id: 'e1', name: 'OD growth' },
  lab: 'lab_a', status: 'running', seq: 1, pending_input: null,
}
const RECORD = {
  id: 'r1', name: 'OD growth — now', experiment_id: 'e1', experiment_name: 'OD growth',
  lab: 'lab_a', role_mapping: {}, status: 'completed', started_at: '', ended_at: '',
  dir: 'runs/r1', report: { status: 'completed', error: null, finalize_errors: [],
    persistence_errors: [], diagnostics: [], clock_origin: 0, started_at: '', ended_at: '',
    experiment_name: 'OD growth', lab: 'lab_a', role_mapping: {} },
  doc: { doc_version: 1, name: 'OD growth', description: null, roles: {},
    workflow: { schema_version: 1, blocks: [], streams: { od: { units: 'AU' } } } },
}

let sockets: { runId: string; handlers: RunSocketHandlers; connected: boolean }[]
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 })

beforeEach(() => {
  sockets = []
  setSocketFactoryForTests((runId, _lastSeq, handlers) => {
    const record = { runId, handlers, connected: false }
    sockets.push(record)
    return { connect: () => { record.connected = true }, close: () => {} }
  })
  useRunStore.getState().dismiss() // reset to idle baseline between tests
})
afterEach(() => {
  setSocketFactoryForTests(null)
  vi.unstubAllGlobals()
})

const push = (msg: RunWsMsg) => sockets[0].handlers.onMessage(msg)

describe('runStore', () => {
  it('attach adopts an active run and opens a socket', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      url.includes('api/records/') ? json(RECORD) : json(ACTIVE)))
    await useRunStore.getState().attach()
    const s = useRunStore.getState()
    expect(s.phase).toBe('active')
    expect(s.runId).toBe('r1')
    expect(s.streamUnits).toEqual({ od: 'AU' })
    expect(sockets).toHaveLength(1)
    expect(sockets[0].connected).toBe(true)
  })
  it('attach with no active run lands in idle', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(null)))
    await useRunStore.getState().attach()
    expect(useRunStore.getState().phase).toBe('idle')
  })
  it('events fold into the feed; terminal close fetches the report', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) =>
      url.includes('api/records/') ? json(RECORD) : json(ACTIVE)))
    await useRunStore.getState().attach()
    push({ type: 'event', seq: 0, timestamp: 1, kind: 'run_started', block_id: null, data: {} })
    push({ type: 'status', seq: 1, status: 'completed' })
    sockets[0].handlers.onTerminal()
    await vi.waitFor(() => expect(useRunStore.getState().phase).toBe('terminal'))
    expect(useRunStore.getState().report?.status).toBe('completed')
  })
  it('input_requested refetches the pending input from /runs/active', async () => {
    const pending = { ...ACTIVE, pending_input: { name: 'target', type: 'int', prompt: 'n?',
      min: 1, max: 10, choices: null, block_id: 'b1' } }
    let calls = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('api/records/')) return json(RECORD)
      calls += 1
      return json(calls === 1 ? ACTIVE : pending)
    }))
    await useRunStore.getState().attach()
    push({ type: 'event', seq: 0, timestamp: 1, kind: 'input_requested', block_id: 'b1',
      data: { name: 'target' } })
    await vi.waitFor(() =>
      expect(useRunStore.getState().pendingInput?.name).toBe('target'))
    push({ type: 'event', seq: 1, timestamp: 2, kind: 'input_bound', block_id: 'b1',
      data: { name: 'target', value: 5 } })
    expect(useRunStore.getState().pendingInput).toBeNull()
  })
  it('start surfaces 422 diagnostics without leaving idle', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        return new Response(JSON.stringify({ detail: 'preflight failed',
          code: 'preflight_failed',
          diagnostics: [{ category: 'mapping', path: "roles['feed']", message: 'unmapped' }],
        }), { status: 422 })
      }
      return json(null)
    }))
    await useRunStore.getState().attach()
    await useRunStore.getState().start({ experiment_id: 'e1', lab: 'lab_a', role_mapping: {} })
    const s = useRunStore.getState()
    expect(s.phase).toBe('idle')
    expect(s.startDiagnostics).toHaveLength(1)
  })
})
