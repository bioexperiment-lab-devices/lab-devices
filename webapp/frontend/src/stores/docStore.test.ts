import { beforeEach, describe, expect, it } from 'vitest'
import { docToTree } from '../builder/convert'
import { newStructureNode } from '../builder/tree'
import {
  loadDoc,
  newDoc,
  redo,
  selectDirty,
  selectDoc,
  undo,
  useDocStore,
} from './docStore'

const store = () => useDocStore.getState()

beforeEach(() => {
  newDoc()
})

describe('docStore', () => {
  it('starts as a clean untitled doc that serializes to a valid empty doc', () => {
    expect(selectDirty(store())).toBe(false)
    const doc = selectDoc(store())
    expect(doc.doc_version).toBe(1)
    expect(doc.workflow.blocks).toEqual([])
  })

  it('tracks dirty through edits and back through undo', () => {
    store().setName('Growth curve')
    expect(selectDirty(store())).toBe(true)
    undo()
    expect(store().name).toBe('Untitled experiment')
    expect(selectDirty(store())).toBe(false)
    redo()
    expect(store().name).toBe('Growth curve')
  })

  it('selection changes do not create undo steps', () => {
    store().insertBlock(newStructureNode('wait'), { parentUid: null, slot: 'blocks', index: 0 })
    const uid = store().tree[0].uid
    store().select(null)
    store().select(uid)
    undo()
    expect(store().tree).toEqual([])
  })

  it('insertBlock selects the inserted block', () => {
    const node = newStructureNode('wait')
    store().insertBlock(node, { parentUid: null, slot: 'blocks', index: 0 })
    expect(store().selectedUid).toBe(node.uid)
  })

  it('removeBlock clears selection when the selected node goes away', () => {
    const node = newStructureNode('serial')
    store().insertBlock(node, { parentUid: null, slot: 'blocks', index: 0 })
    store().removeBlock(node.uid)
    expect(store().selectedUid).toBeNull()
    expect(store().tree).toEqual([])
  })

  it('role lifecycle: add, rename cascades in one undo step, delete refused while referenced', () => {
    expect(store().addRole('feed_pump', 'pump')).toBeNull()
    expect(store().addRole('feed_pump', 'pump')).toMatch(/exists/)
    expect(store().addRole('Feed', 'pump')).toMatch(/must match/)
    store().insertBlock(
      { uid: 'c1', kind: 'command', device: 'feed_pump', verb: 'stop', params: {},
        label: null, gapAfter: null, startOffset: null },
      { parentUid: null, slot: 'blocks', index: 0 },
    )
    expect(store().removeRole('feed_pump')).toMatch(/1 block/)
    expect(store().renameRole('feed_pump', 'acid_pump')).toBeNull()
    expect(store().roles).toHaveProperty('acid_pump')
    expect(store().roles).not.toHaveProperty('feed_pump')
    expect(selectDoc(store()).workflow.blocks[0].command?.device).toBe('acid_pump')
    undo() // single step: role map + block rewrite together
    expect(store().roles).toHaveProperty('feed_pump')
    expect(selectDoc(store()).workflow.blocks[0].command?.device).toBe('feed_pump')
    store().removeBlock('c1')
    expect(store().removeRole('feed_pump')).toBeNull()
  })

  it('stream lifecycle mirrors roles: rename cascades measure.into, delete refused while referenced', () => {
    expect(store().addStream('od', 'AU')).toBeNull()
    expect(store().addStream('od', null)).toMatch(/exists/)
    store().insertBlock(
      { uid: 'm1', kind: 'measure', device: 'od_meter', verb: 'measure', into: 'od',
        params: {}, label: null, gapAfter: null, startOffset: null },
      { parentUid: null, slot: 'blocks', index: 0 },
    )
    expect(store().removeStream('od')).toMatch(/1 block/)
    expect(store().renameStream('od', 'od600')).toBeNull()
    expect(selectDoc(store()).workflow.blocks[0].measure?.into).toBe('od600')
    expect(selectDoc(store()).workflow.streams).toHaveProperty('od600')
    store().setStreamUnits('od600', 'mAU')
    expect(store().streams.od600.units).toBe('mAU')
    store().removeBlock('m1')
    expect(store().removeStream('od600')).toBeNull()
  })

  it('loadDoc replaces state, clears history, and reads clean; markSaved clears dirty', () => {
    store().setName('scratch')
    loadDoc(
      docToTree({
        doc_version: 1, name: 'Loaded', description: null,
        roles: { p: { type: 'pump' } },
        workflow: { schema_version: 1, blocks: [] },
      }),
      'id-123',
    )
    expect(store().name).toBe('Loaded')
    expect(store().serverId).toBe('id-123')
    expect(selectDirty(store())).toBe(false)
    undo() // history cleared — nothing to undo
    expect(store().name).toBe('Loaded')
    store().setName('Loaded v2')
    expect(selectDirty(store())).toBe(true)
    store().markSaved('id-123')
    expect(selectDirty(store())).toBe(false)
  })
})
