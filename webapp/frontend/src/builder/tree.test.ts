import { describe, expect, it } from 'vitest'
import {
  canDrop,
  containsUid,
  duplicateNode,
  findLocation,
  findNode,
  insertNode,
  moveNode,
  newStructureNode,
  newVerbNode,
  removeNode,
  replaceSlot,
  updateNode,
  withFreshUids,
  type BlockNode,
  type SerialNode,
  type ParallelNode,
  type LoopNode,
} from './tree'

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
    const parallel = newStructureNode('parallel') as ParallelNode
    expect(parallel.children).toHaveLength(2)
    expect(parallel.children.every((lane) => lane.kind === 'serial')).toBe(true)
    const branch = newStructureNode('branch')
    expect(branch).toMatchObject({ condition: '', else: [] })
    expect(newStructureNode('wait')).toMatchObject({ duration: '1s' })
    const l = newStructureNode('loop')
    expect(l).toMatchObject({ mode: 'count', count: 2, check: 'after' })
  })

  it('builds command vs measure nodes from the verb spec kind', () => {
    const cmd = newVerbNode('feed_pump', 'dispense', { kind: 'command', params: [], result_field: null })
    expect(cmd).toMatchObject({ kind: 'command', device: 'feed_pump', verb: 'dispense', params: {} })
    const meas = newVerbNode('od_meter', 'measure', { kind: 'measure', params: [], result_field: 'absorbance' })
    expect(meas).toMatchObject({ kind: 'measure', device: 'od_meter', into: '' })
  })

  it('replaceSlot swaps the named slot and throws for leaf kinds', () => {
    const serial = newStructureNode('serial')
    const wait = newStructureNode('wait')
    const out = replaceSlot(serial, 'children', [wait]) as SerialNode
    expect(out.children).toHaveLength(1)
    expect(out.uid).toBe(serial.uid)
    expect(() => replaceSlot(wait, 'children', [])).toThrow(/no child slot/)
  })
})
