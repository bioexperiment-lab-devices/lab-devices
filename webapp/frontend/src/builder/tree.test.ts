import { describe, expect, it } from 'vitest'
import {
  canDrop,
  childSlots,
  containsUid,
  duplicateNode,
  findLocation,
  findNode,
  insertNode,
  moveNode,
  newGroupRefNode,
  newPaletteNode,
  newVerbNode,
  removeNode,
  replaceSlot,
  retryAfterVerbChange,
  updateNode,
  withFreshUids,
  wrapAsLane,
  type BlockNode,
  type SerialNode,
  type ParallelNode,
  type LoopNode,
  type ForEachNode,
  type GroupRefNode,
} from './tree'
import type { VerbSpec } from '../types/catalog'

const wait = (uid: string): BlockNode => ({
  uid, kind: 'wait', duration: '1s', label: null, gapAfter: null, startOffset: null,
})
const serial = (uid: string, children: BlockNode[]): SerialNode => ({
  uid, kind: 'serial', children, label: null, gapAfter: null, startOffset: null,
})
const loop = (uid: string, body: BlockNode[]): LoopNode => ({
  uid, kind: 'loop', mode: 'count', count: 2, until: '', check: 'after', pace: null,
  body, label: null, gapAfter: null, startOffset: null,
})

describe('tree ops', () => {
  it('finds nodes and locations in nested slots', () => {
    const tree = [serial('s1', [wait('w1'), loop('l1', [wait('w2')])])]
    expect(findNode(tree, 'w2')?.kind).toBe('wait')
    expect(findLocation(tree, 'w2')).toMatchObject({ slot: 'body', index: 0 })
    expect(findLocation(tree, 'w2')?.parent?.uid).toBe('l1')
    expect(findLocation(tree, 's1')).toMatchObject({ parent: null, slot: 'blocks', index: 0 })
    expect(containsUid(tree[0], 'w2')).toBe(true)
    expect(containsUid(tree[0], 'nope')).toBe(false)
  })

  it('inserts at root and into container slots without mutating the input', () => {
    const tree = [serial('s1', [])]
    const atRoot = insertNode(tree, wait('w1'), { parentUid: null, slot: 'blocks', index: 0 })
    expect(atRoot.map((n) => n.uid)).toEqual(['w1', 's1'])
    const nested = insertNode(atRoot, wait('w2'), { parentUid: 's1', slot: 'children', index: 0 })
    expect((findNode(nested, 's1') as SerialNode).children.map((n) => n.uid)).toEqual(['w2'])
    expect((findNode(atRoot, 's1') as SerialNode).children).toEqual([])
  })

  it('returns the same tree when the insert target does not exist', () => {
    const tree = [serial('s1', [])]
    expect(insertNode(tree, wait('w1'), { parentUid: 'ghost', slot: 'children', index: 0 })).toBe(tree)
  })

  it('removes nested nodes and reports the removed subtree', () => {
    const tree = [serial('s1', [wait('w1'), wait('w2')])]
    const [next, removed] = removeNode(tree, 'w1')
    expect(removed?.uid).toBe('w1')
    expect((findNode(next, 's1') as SerialNode).children.map((n) => n.uid)).toEqual(['w2'])
    const [same, none] = removeNode(tree, 'ghost')
    expect(same).toBe(tree)
    expect(none).toBeNull()
  })

  it('refuses to drop a container into its own subtree', () => {
    const inner = serial('inner', [])
    const tree = [serial('outer', [inner]), wait('w1')]
    expect(canDrop(tree, 'outer', { parentUid: 'inner', slot: 'children', index: 0 })).toBe(false)
    expect(canDrop(tree, 'outer', { parentUid: 'outer', slot: 'children', index: 0 })).toBe(false)
    expect(canDrop(tree, 'w1', { parentUid: 'inner', slot: 'children', index: 0 })).toBe(true)
    const illegal = moveNode(tree, 'outer', { parentUid: 'inner', slot: 'children', index: 0 })
    expect(illegal).toBe(tree)
  })

  it('refuses to drop into a slot the target does not expose', () => {
    const tree = [wait('w1'), serial('s1', []), { uid: 'b1', kind: 'branch' as const, condition: '', then: [], else: null, label: null, gapAfter: null, startOffset: null }]
    // leaf target: wait has no child slots
    expect(canDrop(tree, 's1', { parentUid: 'w1', slot: 'children', index: 0 })).toBe(false)
    // wrong slot name on a real container
    expect(canDrop(tree, 'w1', { parentUid: 's1', slot: 'body', index: 0 })).toBe(false)
    // branch else slot while else is null
    expect(canDrop(tree, 'w1', { parentUid: 'b1', slot: 'else', index: 0 })).toBe(false)
    // moveNode must never lose the node in any of these cases
    for (const at of [
      { parentUid: 'w1', slot: 'children', index: 0 },
      { parentUid: 's1', slot: 'body', index: 0 },
      { parentUid: 'b1', slot: 'else', index: 0 },
    ]) {
      expect(moveNode(tree, 'w1', at)).toBe(tree)
    }
  })

  it('adjusts the index when moving forward within the same list', () => {
    const tree = [wait('a'), wait('b'), wait('c')]
    const next = moveNode(tree, 'a', { parentUid: null, slot: 'blocks', index: 2 })
    expect(next.map((n) => n.uid)).toEqual(['b', 'a', 'c'])
    const back = moveNode(next, 'a', { parentUid: null, slot: 'blocks', index: 0 })
    expect(back.map((n) => n.uid)).toEqual(['a', 'b', 'c'])
  })

  it('moves nodes across parents', () => {
    const tree = [serial('s1', [wait('w1')]), serial('s2', [])]
    const next = moveNode(tree, 'w1', { parentUid: 's2', slot: 'children', index: 0 })
    expect((findNode(next, 's1') as SerialNode).children).toEqual([])
    expect((findNode(next, 's2') as SerialNode).children.map((n) => n.uid)).toEqual(['w1'])
  })

  it('duplicates a subtree with fresh uids right after the original', () => {
    const tree = [serial('s1', [wait('w1')])]
    const [next, cloneUid] = duplicateNode(tree, 's1')
    expect(next).toHaveLength(2)
    expect(cloneUid).not.toBeNull()
    expect(next[1].uid).toBe(cloneUid)
    const clone = next[1] as SerialNode
    expect(clone.children).toHaveLength(1)
    expect(clone.children[0].uid).not.toBe('w1')
    const fresh = withFreshUids(tree[0])
    expect(fresh.uid).not.toBe('s1')
  })

  it('patches node fields immutably', () => {
    const tree = [wait('w1')]
    const next = updateNode(tree, 'w1', { duration: '5min' })
    expect(next[0]).toMatchObject({ duration: '5min' })
    expect(tree[0]).toMatchObject({ duration: '1s' })
  })

  it('builds structure nodes with builder defaults', () => {
    const parallel = newPaletteNode('parallel') as ParallelNode
    expect(parallel.children).toHaveLength(2)
    expect(parallel.children.every((lane) => lane.kind === 'serial')).toBe(true)
    const branch = newPaletteNode('branch')
    expect(branch).toMatchObject({ condition: '', else: [] })
    expect(newPaletteNode('wait')).toMatchObject({ duration: '1s' })
    const l = newPaletteNode('loop')
    expect(l).toMatchObject({ mode: 'count', count: 2, check: 'after' })
  })

  it('builds command vs measure nodes from the verb spec kind', () => {
    const cmd = newVerbNode('feed_pump', 'dispense', {
      kind: 'command', params: [], result_field: null, retry_safe: false,
    })
    expect(cmd).toMatchObject({ kind: 'command', device: 'feed_pump', verb: 'dispense', params: {} })
    const meas = newVerbNode('od_meter', 'measure', {
      kind: 'measure', params: [], result_field: 'absorbance', retry_safe: true,
    })
    expect(meas).toMatchObject({ kind: 'measure', device: 'od_meter', into: '' })
  })

  it('replaceSlot swaps the named slot and throws for leaf kinds', () => {
    const serial = newPaletteNode('serial')
    const wait = newPaletteNode('wait')
    const out = replaceSlot(serial, 'children', [wait]) as SerialNode
    expect(out.children).toHaveLength(1)
    expect(out.uid).toBe(serial.uid)
    expect(() => replaceSlot(wait, 'children', [])).toThrow(/no child slot/)
  })

  it('creates control-block nodes with no child slots', () => {
    for (const kind of ['compute', 'record', 'abort', 'alarm'] as const) {
      const node = newPaletteNode(kind)
      expect(node.kind).toBe(kind)
      expect(childSlots(node)).toEqual([])
      expect(node.label).toBeNull()
    }
  })

  it('seeds control blocks with empty, author-fillable fields', () => {
    expect(newPaletteNode('compute')).toMatchObject({ into: '', value: '' })
    expect(newPaletteNode('record')).toMatchObject({ into: '', value: '' })
    expect(newPaletteNode('abort')).toMatchObject({ condition: '', message: '' })
    expect(newPaletteNode('alarm')).toMatchObject({ condition: '', message: '' })
  })

  describe('retryAfterVerbChange', () => {
    it('leaves an unset retry alone', () => {
      expect(retryAfterVerbChange(undefined)).toBeUndefined()
    })

    it('strips allow_repeat but keeps attempts/backoff, when switching verb', () => {
      // Reproduces the reviewer's proof (2026-07-14 review, I3): a block on a non-
      // retry_safe verb with allow_repeat ticked, switched to a different non-retry_safe
      // verb, must not carry the old verb's hazard acknowledgement onto the new one.
      const result = retryAfterVerbChange({ attempts: 3, backoff: '2s', allow_repeat: true })
      expect(result?.allow_repeat).toBeUndefined()
      expect(result).toMatchObject({ attempts: 3, backoff: '2s' })
    })

    it('is a no-op on a retry that never had allow_repeat set', () => {
      const result = retryAfterVerbChange({ attempts: 2 })
      expect(result?.allow_repeat).toBeUndefined()
      expect(result).toMatchObject({ attempts: 2 })
    })
  })

  it('gives for_each a body child slot so the tree ops reach into it', () => {
    const node = newPaletteNode('for_each') as ForEachNode
    expect(node.kind).toBe('for_each')
    expect(node.vars).toEqual([{ name: 'tube', kind: 'int' }])
    expect(node.rows).toEqual([{ tube: 1 }, { tube: 2 }, { tube: 3 }])
    expect(childSlots(node).map(([slot]) => slot)).toEqual(['body'])
    const wait = newPaletteNode('wait')
    const withChild = replaceSlot(node, 'body', [wait]) as ForEachNode
    expect(withChild.body).toEqual([wait])
    expect(findNode([withChild], wait.uid)).toBe(wait)
  })

  it('creates a group_ref with no child slots', () => {
    const node = newPaletteNode('group_ref')
    expect(node.kind).toBe('group_ref')
    expect(node).toMatchObject({ name: '', as: null, args: {} })
    expect(childSlots(node)).toEqual([])
  })
})

describe('wrapAsLane', () => {
  it('passes a serial through unchanged (same object)', () => {
    const s = newPaletteNode('serial')
    expect(wrapAsLane(s)).toBe(s)
  })
  it('wraps a non-serial in a fresh plain serial', () => {
    const w = newPaletteNode('wait')
    const lane = wrapAsLane(w)
    expect(lane.kind).toBe('serial')
    if (lane.kind !== 'serial') return
    expect(lane.children).toEqual([w])
    expect(lane.label).toBeNull()
    expect(lane.uid).not.toBe(w.uid)
  })
})

describe('lane auto-wrap on insert/move/duplicate', () => {
  it('insertNode into parallel children wraps a non-serial block', () => {
    const p = newPaletteNode('parallel') // seeds two empty serial lanes
    const w = newPaletteNode('wait')
    const out = insertNode([p], w, { parentUid: p.uid, slot: 'children', index: 2 })
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children).toHaveLength(3)
    expect(par.children[2].kind).toBe('serial')
    const lane = par.children[2]
    if (lane.kind !== 'serial') return
    expect(lane.children.map((c) => c.uid)).toEqual([w.uid])
  })
  it('insertNode into parallel children passes a serial through as the lane', () => {
    const p = newPaletteNode('parallel')
    const s = newPaletteNode('serial')
    const out = insertNode([p], s, { parentUid: p.uid, slot: 'children', index: 0 })
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children[0].uid).toBe(s.uid)
  })
  it('insertNode into a serial slot does NOT wrap', () => {
    const s = newPaletteNode('serial')
    const w = newPaletteNode('wait')
    const out = insertNode([s], w, { parentUid: s.uid, slot: 'children', index: 0 })
    const ser = out[0]
    if (ser.kind !== 'serial') throw new Error('expected serial')
    expect(ser.children[0].uid).toBe(w.uid)
  })
  it('moveNode of a block from inside a lane to lane level wraps it and keeps the source lane', () => {
    const p = newPaletteNode('parallel')
    const w = newPaletteNode('wait')
    const seeded = insertNode(
      [p],
      w,
      { parentUid: (p as { children: BlockNode[] }).children[0].uid, slot: 'children', index: 0 },
    )
    const out = moveNode(seeded, w.uid, { parentUid: p.uid, slot: 'children', index: 2 })
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children).toHaveLength(3) // lane 1 (now empty) survives, new lane appended
    const first = par.children[0]
    if (first.kind !== 'serial') throw new Error('expected serial lane')
    expect(first.children).toHaveLength(0)
    const moved = par.children[2]
    if (moved.kind !== 'serial') throw new Error('expected wrapped lane')
    expect(moved.children.map((c) => c.uid)).toEqual([w.uid])
  })
  it('duplicateNode of a bare-block lane wraps the clone', () => {
    const p = newPaletteNode('parallel')
    const cmd = newVerbNode('pump', 'dispense', {
      kind: 'command', params: [], result_field: null, retry_safe: false,
    } as VerbSpec)
    if (p.kind !== 'parallel') throw new Error('expected parallel')
    const tree: BlockNode[] = [{ ...p, children: [cmd] }]
    const [out] = duplicateNode(tree, cmd.uid)
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    expect(par.children).toHaveLength(2)
    expect(par.children[0].uid).toBe(cmd.uid) // original untouched
    expect(par.children[1].kind).toBe('serial') // clone wrapped
  })
  it('insertNode into parallel children wraps a group_ref chip drop', () => {
    const p = newPaletteNode('parallel')
    const g = newGroupRefNode('wash')
    const out = insertNode([p], g, { parentUid: p.uid, slot: 'children', index: 2 })
    const par = out[0]
    if (par.kind !== 'parallel') throw new Error('expected parallel')
    const lane = par.children[2]
    if (lane.kind !== 'serial') throw new Error('expected wrapped lane')
    expect(lane.children.map((c) => c.uid)).toEqual([g.uid])
  })
})

describe('newGroupRefNode', () => {
  it('builds a group_ref carrying the given name and no args', () => {
    const node = newGroupRefNode('dilute') as GroupRefNode
    expect(node.kind).toBe('group_ref')
    expect(node.name).toBe('dilute')
    expect(node.args).toEqual({})
  })

  it('gives each call a distinct uid', () => {
    expect(newGroupRefNode('dilute').uid).not.toBe(newGroupRefNode('dilute').uid)
  })

  it('starts with the NodeBase defaults every block shares', () => {
    const node = newGroupRefNode('dilute')
    expect(node.label).toBeNull()
    expect(node.gapAfter).toBeNull()
    expect(node.startOffset).toBeNull()
  })
})
