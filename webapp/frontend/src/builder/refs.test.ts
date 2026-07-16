import { describe, expect, it } from 'vitest'
import { collectBindings, countRoleRefs, countStreamRefs, renameRoleRefs, renameStreamRefs, streamSources } from './refs'
import type { BlockNode, CommandNode, ComputeNode, LoopNode, MeasureNode, RecordNode, SerialNode } from './tree'

const base = { label: null, gapAfter: null, startOffset: null }
const cmd = (uid: string, device: string): CommandNode => ({
  uid, kind: 'command', device, verb: 'stop', params: {}, ...base,
})
const meas = (uid: string, device: string, into: string): MeasureNode => ({
  uid, kind: 'measure', device, verb: 'measure', into, params: {}, ...base,
})
const rec = (uid: string, into: string): RecordNode => ({
  uid, kind: 'record', into, value: 'c', ...base,
})
const comp = (uid: string, into: string, value: string): ComputeNode => ({
  uid, kind: 'compute', into, value, ...base,
})
const tree: BlockNode[] = [
  {
    uid: 's1', kind: 'serial', ...base,
    children: [
      cmd('c1', 'feed_pump'),
      {
        uid: 'l1', kind: 'loop', mode: 'until', count: 2, until: 'mean(od, last=3) > 0.6',
        check: 'after', pace: null, ...base,
        body: [
          meas('m1', 'od_meter', 'od'),
          { uid: 'oi1', kind: 'operator_input', name: 'feed_ml', inputType: 'float',
            prompt: null, min: null, max: null, choices: null, ...base },
          cmd('c2', 'feed_pump'),
        ],
      } satisfies LoopNode,
    ],
  } satisfies SerialNode,
]

describe('role refs', () => {
  it('counts command/measure blocks bound to a role', () => {
    expect(countRoleRefs(tree, 'feed_pump')).toBe(2)
    expect(countRoleRefs(tree, 'od_meter')).toBe(1)
    expect(countRoleRefs(tree, 'ghost')).toBe(0)
  })

  it('renames every referencing block in one pass', () => {
    const next = renameRoleRefs(tree, 'feed_pump', 'acid_pump')
    expect(countRoleRefs(next, 'feed_pump')).toBe(0)
    expect(countRoleRefs(next, 'acid_pump')).toBe(2)
    expect(countRoleRefs(tree, 'feed_pump')).toBe(2) // input untouched
  })

  it('cascades renames through both branch lanes', () => {
    const branched: BlockNode[] = [
      {
        uid: 'b1', kind: 'branch', condition: 'last(od) > 1', ...base,
        then: [cmd('t1', 'feed_pump')],
        else: [meas('e1', 'feed_pump', 'od')],
      },
    ]
    const next = renameRoleRefs(branched, 'feed_pump', 'acid_pump')
    expect(countRoleRefs(next, 'acid_pump')).toBe(2)
    expect(countRoleRefs(next, 'feed_pump')).toBe(0)
    const renamed = renameStreamRefs(next, 'od', 'od600')
    expect(countStreamRefs(renamed, 'od600')).toBe(1)
  })
})

describe('stream refs', () => {
  it('counts measure blocks writing into a stream', () => {
    expect(countStreamRefs(tree, 'od')).toBe(1)
    expect(countStreamRefs(tree, 'ph')).toBe(0)
  })

  it('renames into fields but leaves expression text alone (validation catches those)', () => {
    const next = renameStreamRefs(tree, 'od', 'od600')
    expect(countStreamRefs(next, 'od600')).toBe(1)
    const loop = (next[0] as SerialNode).children[1] as LoopNode
    expect(loop.until).toBe('mean(od, last=3) > 0.6')
  })

  it('counts a record block as a stream reference', () => {
    const t: BlockNode[] = [rec('r1', 'c_series')]
    expect(countStreamRefs(t, 'c_series')).toBe(1)
    expect(countStreamRefs(t, 'other')).toBe(0)
  })

  it('renames record stream references', () => {
    const out = renameStreamRefs([rec('r1', 'c_series')], 'c_series', 'conc')
    expect((out[0] as RecordNode).into).toBe('conc')
  })
})

describe('collectBindings', () => {
  it('collects operator_input names in DFS order, deduped', () => {
    expect(collectBindings(tree)).toEqual(['feed_ml'])
    const twice = [...tree, { uid: 'oi2', kind: 'operator_input' as const, name: 'feed_ml',
      inputType: 'float' as const, prompt: null, min: null, max: null, choices: null, ...base }]
    expect(collectBindings(twice)).toEqual(['feed_ml'])
  })

  it('collects compute targets as bindings alongside operator inputs', () => {
    const t: BlockNode[] = [
      {
        uid: 'oi1', kind: 'operator_input', name: 'od_min', inputType: 'float',
        prompt: null, min: null, max: null, choices: null, ...base,
      },
      comp('k1', 'c', '0'),
      comp('k2', 'c', 'c * 0.9'),
    ]
    // 'c' is written by two computes (the seed-then-accumulate idiom) and must de-duplicate.
    expect(collectBindings(t)).toEqual(['od_min', 'c'])
  })
})

describe('streamSources', () => {
  it('reports which block kind writes each stream', () => {
    const t: BlockNode[] = [meas('m1', 'od_meter', 'od'), rec('r1', 'c_series')]
    expect(streamSources(t)).toEqual({ od: 'measure', c_series: 'record' })
  })

  it('omits streams nothing writes', () => {
    expect(streamSources([])).toEqual({})
  })

  it('first writer wins when a stream is transiently written by both kinds', () => {
    const t: BlockNode[] = [meas('m1', 'od_meter', 'dual'), rec('r1', 'dual')]
    expect(streamSources(t)).toEqual({ dual: 'measure' })
  })

  it('skips a freshly-dragged block with an empty into', () => {
    const t: BlockNode[] = [meas('m1', 'od_meter', ''), rec('r1', 'c_series')]
    expect(streamSources(t)).toEqual({ c_series: 'record' })
  })
})
