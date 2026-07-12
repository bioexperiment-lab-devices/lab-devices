import { describe, expect, it } from 'vitest'
import { collectBindings, countRoleRefs, countStreamRefs, renameRoleRefs, renameStreamRefs } from './refs'
import type { BlockNode, CommandNode, LoopNode, MeasureNode, SerialNode } from './tree'

const base = { label: null, gapAfter: null, startOffset: null }
const cmd = (uid: string, device: string): CommandNode => ({
  uid, kind: 'command', device, verb: 'stop', params: {}, ...base,
})
const meas = (uid: string, device: string, into: string): MeasureNode => ({
  uid, kind: 'measure', device, verb: 'measure', into, params: {}, ...base,
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
})

describe('collectBindings', () => {
  it('collects operator_input names in DFS order, deduped', () => {
    expect(collectBindings(tree)).toEqual(['feed_ml'])
    const twice = [...tree, { uid: 'oi2', kind: 'operator_input' as const, name: 'feed_ml',
      inputType: 'float' as const, prompt: null, min: null, max: null, choices: null, ...base }]
    expect(collectBindings(twice)).toEqual(['feed_ml'])
  })
})
