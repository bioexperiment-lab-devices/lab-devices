import { describe, expect, it } from 'vitest'
import { applyMessage, emptyFeed, type FeedState } from './reducer'
import type { RunWsMsg } from '../types/runs'

const ev = (seq: number, kind: string, data: Record<string, unknown> = {}, ts = seq): RunWsMsg =>
  ({ type: 'event', seq, timestamp: ts, kind, block_id: null, data })
const st = (seq: number, status: string): RunWsMsg => ({ type: 'status', seq, status })

const feedAll = (msgs: RunWsMsg[], s: FeedState = emptyFeed()): FeedState =>
  msgs.reduce(applyMessage, s)

describe('applyMessage', () => {
  it('accumulates events, origin from the first event, rev per message', () => {
    const s = feedAll([ev(0, 'run_started', {}, 10.5), ev(1, 'block_started', {}, 11)])
    expect(s.origin).toBe(10.5)
    expect(s.lastSeq).toBe(1)
    expect(s.events.map((e) => e.kind)).toEqual(['run_started', 'block_started'])
    expect(s.rev).toBe(2)
  })
  it('drops replay duplicates (seq <= lastSeq) without touching state', () => {
    const s1 = feedAll([ev(0, 'run_started'), ev(1, 'block_started')])
    const s2 = applyMessage(s1, ev(1, 'block_started'))
    expect(s2).toBe(s1)
  })
  it('folds measure_recorded into per-stream samples', () => {
    const s = feedAll([
      ev(0, 'run_started', {}, 0),
      ev(1, 'measure_recorded', { stream: 'od', value: 0.5 }, 5),
      ev(2, 'measure_recorded', { stream: 'od', value: 0.7 }, 10),
      ev(3, 'measure_recorded', { stream: 'temp', value: 37 }, 10),
    ])
    expect(s.samples.od).toEqual({ t: [5, 10], v: [0.5, 0.7] })
    expect(s.samples.temp).toEqual({ t: [10], v: [37] })
  })
  it('folds sample_recorded (record blocks) into samples like measure_recorded', () => {
    const s = feedAll([
      ev(0, 'run_started', {}, 0),
      ev(1, 'measure_recorded', { stream: 'od_1', value: 0.4 }, 5),
      ev(2, 'sample_recorded', { stream: 'c_series_1', value: 1.25 }, 6),
      ev(3, 'sample_recorded', { stream: 'c_series_1', value: 1.4 }, 12),
    ])
    expect(s.samples.od_1).toEqual({ t: [5], v: [0.4] })
    expect(s.samples.c_series_1).toEqual({ t: [6, 12], v: [1.25, 1.4] })
  })
  it('status messages update status and flag terminal', () => {
    let s = feedAll([ev(0, 'run_started'), st(1, 'paused')])
    expect(s.status).toBe('paused')
    expect(s.terminal).toBe(false)
    s = applyMessage(s, st(2, 'completed'))
    expect(s.status).toBe('completed')
    expect(s.terminal).toBe(true)
  })
  it('replay then live merge is seamless across a reconnect overlap', () => {
    const msgs = [ev(0, 'run_started'), ev(1, 'measure_recorded', { stream: 'od', value: 1 }),
      st(2, 'paused'), st(3, 'running'), ev(4, 'block_finished')]
    const once = feedAll(msgs)
    const twice = feedAll([...msgs.slice(2)], feedAll(msgs.slice(0, 4))) // overlap 2..3
    expect(twice.lastSeq).toBe(once.lastSeq)
    expect(twice.events.length).toBe(once.events.length)
    expect(twice.samples).toEqual(once.samples)
  })
})
