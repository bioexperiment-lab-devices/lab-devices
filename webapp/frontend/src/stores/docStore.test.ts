import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it } from 'vitest'
import { docToTree } from '../builder/convert'
import {
  newPaletteNode,
  type CommandNode,
  type GroupRefNode,
  type MeasureNode,
} from '../builder/tree'
import type { ExperimentDocJson } from '../types/doc'
import {
  loadDoc,
  newDoc,
  pauseHistory,
  redo,
  resumeHistory,
  selectContent,
  selectDirty,
  selectDoc,
  snapshotOf,
  undo,
  useDocStore,
} from './docStore'

const store = () => useDocStore.getState()

const groupRef = (uid: string, name: string): GroupRefNode => ({
  uid, kind: 'group_ref', name, as: null, args: {}, label: null, gapAfter: null, startOffset: null,
})

const cmd = (uid: string, device: string): CommandNode => ({
  uid, kind: 'command', device, verb: 'stop', params: {},
  label: null, gapAfter: null, startOffset: null,
})

const meas = (uid: string, device: string, into: string): MeasureNode => ({
  uid, kind: 'measure', device, verb: 'measure', into, params: {},
  label: null, gapAfter: null, startOffset: null,
})

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
    store().insertBlock(newPaletteNode('wait'), { parentUid: null, slot: 'blocks', index: 0 })
    const uid = store().tree[0].uid
    store().select(null)
    store().select(uid)
    undo()
    expect(store().tree).toEqual([])
  })

  it('insertBlock selects the inserted block', () => {
    const node = newPaletteNode('wait')
    store().insertBlock(node, { parentUid: null, slot: 'blocks', index: 0 })
    expect(store().selectedUid).toBe(node.uid)
  })

  it('removeBlock clears selection when the selected node goes away', () => {
    const node = newPaletteNode('serial')
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
        workflow: { schema_version: 2, roles: { p: { type: 'pump' } }, blocks: [] },
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

  it('loading a doc without defaults/persistence clears what the PREVIOUS doc left behind ' +
    '(I1 — cross-document contamination introduced by the Task 8 carry-through fix)', () => {
    loadDoc(
      docToTree({
        doc_version: 1, name: 'A', description: null,
        workflow: {
          schema_version: 2,
          persistence: { default: 'disk' },
          defaults: { retry: { attempts: 3, backoff: '2s' } },
          streams: {},
          blocks: [],
        },
      }),
      'a-id',
    )
    expect(store().defaults).toEqual({ retry: { attempts: 3, backoff: '2s' } })
    expect(store().persistence).toEqual({ default: 'disk' })

    loadDoc(
      docToTree({
        doc_version: 1, name: 'B', description: null,
        workflow: { schema_version: 2, streams: {}, blocks: [] },
      }),
      'b-id',
    )
    expect(store().defaults).toBeUndefined()
    expect(store().persistence).toBeUndefined()
    const savedB = selectDoc(store())
    expect(savedB.workflow.defaults).toBeUndefined()
    expect(savedB.workflow.persistence).toEqual({ default: 'in_memory', format: 'jsonl' })
  })

  it('the dirty-check covers defaults and persistence, not just the visible fields', () => {
    // No UI mutates either today, so this was inert — but a snapshot that omits them means a
    // change to either reads CLEAN and is silently lost on navigate-away.
    loadDoc(
      docToTree({
        doc_version: 1, name: 'A', description: null,
        workflow: {
          schema_version: 2,
          defaults: { retry: { attempts: 3, backoff: '2s' } },
          streams: {},
          blocks: [],
        },
      }),
      'a-id',
    )
    expect(selectDirty(store())).toBe(false)
    useDocStore.setState({ defaults: { retry: { attempts: 5, backoff: '2s' } } })
    expect(selectDirty(store())).toBe(true)
    store().markSaved('a-id', snapshotOf(selectContent(store())))
    expect(selectDirty(store())).toBe(false)
    useDocStore.setState({ persistence: { default: 'disk' } })
    expect(selectDirty(store())).toBe(true)
  })

  it('newDoc() also starts clean of whatever the previously open document carried', () => {
    loadDoc(
      docToTree({
        doc_version: 1, name: 'A', description: null,
        workflow: {
          schema_version: 2,
          persistence: { default: 'disk' },
          defaults: { retry: { attempts: 3 } },
          streams: {},
          blocks: [],
        },
      }),
      'a-id',
    )
    newDoc()
    expect(store().defaults).toBeUndefined()
    expect(store().persistence).toBeUndefined()
    expect(selectDoc(store()).workflow.persistence).toEqual({ default: 'in_memory', format: 'jsonl' })
  })

  it('loading a doc without metadata clears what the PREVIOUS doc left behind, same as ' +
    'defaults/persistence (I1) — otherwise doc B would inherit doc A\'s author/description', () => {
    loadDoc(
      docToTree({
        doc_version: 1, name: 'A', description: null,
        workflow: {
          schema_version: 2,
          metadata: { name: 'A', author: 'someone', description: 'about A' },
          streams: {},
          blocks: [],
        },
      }),
      'a-id',
    )
    expect(store().metadata).toEqual({ name: 'A', author: 'someone', description: 'about A' })

    loadDoc(
      docToTree({
        doc_version: 1, name: 'B', description: null,
        workflow: { schema_version: 2, streams: {}, blocks: [] },
      }),
      'b-id',
    )
    expect(store().metadata).toBeUndefined()
    expect(selectDoc(store()).workflow.metadata).toEqual({ name: 'B' })
  })

  it('the dirty-check covers metadata, not just the visible fields — a hand-authored ' +
    'author/description must not read clean after being edited underneath the store', () => {
    loadDoc(
      docToTree({
        doc_version: 1, name: 'A', description: null,
        workflow: {
          schema_version: 2,
          metadata: { name: 'A', author: 'someone' },
          streams: {},
          blocks: [],
        },
      }),
      'a-id',
    )
    expect(selectDirty(store())).toBe(false)
    useDocStore.setState({ metadata: { name: 'A', author: 'someone else' } })
    expect(selectDirty(store())).toBe(true)
  })

  it('pauseHistory suppresses undo tracking until resumeHistory', () => {
    newDoc()
    pauseHistory()
    useDocStore.getState().setName('renamed while paused')
    resumeHistory()
    undo()
    expect(useDocStore.getState().name).toBe('renamed while paused')
  })

  it('removeBlock clears selection when the removed container held it', () => {
    newDoc()
    const serial = newPaletteNode('serial')
    useDocStore.getState().insertBlock(serial, { parentUid: null, slot: 'blocks', index: 0 })
    const wait = newPaletteNode('wait')
    useDocStore.getState().insertBlock(wait, { parentUid: serial.uid, slot: 'children', index: 0 })
    useDocStore.getState().select(wait.uid)
    useDocStore.getState().removeBlock(serial.uid)
    expect(useDocStore.getState().selectedUid).toBeNull()
    expect(useDocStore.getState().tree).toHaveLength(0)
  })

  describe('groups and the scope switcher (design §5.2)', () => {
    it('round-trips a groups-using doc through the store, not just through convert', () => {
      // The Save button's real path: loadDoc(docToTree(raw)) -> selectDoc(state) -> treeToDoc.
      // Task 4's pure-function round-trip was byte-perfect while THIS path silently deleted
      // groups.service and left dangling group_refs — the active bug this task closes.
      const input: ExperimentDocJson = {
        doc_version: 1,
        name: 'macro',
        description: null,
        workflow: {
          schema_version: 2,
          metadata: { name: 'macro' },
          persistence: { default: 'in_memory', format: 'jsonl' },
          streams: {},
          groups: {
            service: { params: [{ name: 'tube', kind: 'int' }], body: [{ wait: { duration: '{tube}s' } }] },
          },
          blocks: [
            { group_ref: { name: 'service', args: { tube: 1 } } },
            { group_ref: { name: 'service', args: { tube: 2 } } },
          ],
        },
      }
      loadDoc(docToTree(input), 'id-1')
      expect(JSON.stringify(selectDoc(useDocStore.getState()))).toBe(JSON.stringify(input))
    })

    it('round-trips examples/morbidostat.json through the store (what Save actually calls) ' +
      '— the W9 acceptance (spec §8): the flagship uses groups + for_each and has never been ' +
      'openable in the builder. loadDoc is a module-level export, not a store method; a pure ' +
      'docToTree/treeToDoc round-trip (convert.test.ts) proves nothing about what Save does, ' +
      'because Save goes through this path and Task 4\'s pure-function check passed byte-' +
      'perfectly while this path silently deleted groups.service.', () => {
      const input = JSON.parse(
        readFileSync(new URL('../../../../examples/morbidostat.json', import.meta.url), 'utf8'),
      ) as ExperimentDocJson
      // loadDoc is a module-level export, not a store method — store().loadDoc(...) does not
      // exist and would not compile.
      loadDoc(docToTree(input), 'id-1')
      expect(JSON.stringify(selectDoc(useDocStore.getState()))).toBe(JSON.stringify(input))
    })

    it('inserts blocks into the active scope, not the main tree', () => {
      expect(store().addGroup('svc')).toBeNull()
      store().setScope('svc')
      const node = newPaletteNode('wait')
      store().insertBlock(node, { parentUid: null, slot: 'blocks', index: 0 })
      expect(store().groups.svc.body).toEqual([node])
      expect(store().tree).toEqual([])
    })

    it('refuses to delete a group a group_ref still cites', () => {
      store().addGroup('svc')
      store().insertBlock(groupRef('r1', 'svc'), { parentUid: null, slot: 'blocks', index: 0 })
      expect(store().removeGroup('svc')).toMatch(/1 block/)
      expect(store().groups).toHaveProperty('svc')
    })

    it('allows deleting a group once its last group_ref is gone', () => {
      store().addGroup('svc')
      store().insertBlock(groupRef('r1', 'svc'), { parentUid: null, slot: 'blocks', index: 0 })
      store().removeBlock('r1')
      expect(store().removeGroup('svc')).toBeNull()
      expect(store().groups).not.toHaveProperty('svc')
    })

    it('counts group_refs inside OTHER group bodies, not just the main tree', () => {
      store().addGroup('inner')
      store().addGroup('outer')
      store().setScope('outer')
      store().insertBlock(groupRef('r1', 'inner'), { parentUid: null, slot: 'blocks', index: 0 })
      store().setScope(null)
      expect(store().tree).toEqual([]) // the ref landed in 'outer', not the main tree
      expect(store().removeGroup('inner')).toMatch(/1 block/)

      store().setScope('outer')
      store().removeBlock('r1')
      store().setScope(null)
      expect(store().removeGroup('inner')).toBeNull()
    })

    it('refuses a duplicate or non-identifier group name', () => {
      expect(store().addGroup('svc')).toBeNull()
      expect(store().addGroup('svc')).toMatch(/exists/)
      expect(store().addGroup('1bad')).toMatch(/identifier/)
    })

    it('keeps scope out of the undo snapshot, and undo switches scope to follow the ' +
      'reverted edit rather than applying it invisibly (design §5.2)', () => {
      store().addGroup('svc')
      store().setScope('svc')
      const node = newPaletteNode('wait')
      store().insertBlock(node, { parentUid: null, slot: 'blocks', index: 0 })
      store().setScope(null) // view a different scope than the one just edited
      undo()
      expect(store().groups.svc.body).toEqual([]) // the group edit reverted
      expect(store().scope).toBe('svc') // and the store followed the undo there to show it
    })

    it('renaming a group cascades to every group_ref by that name, across the main tree ' +
      'and other group bodies', () => {
      store().addGroup('svc')
      store().addGroup('outer')
      store().insertBlock(groupRef('r1', 'svc'), { parentUid: null, slot: 'blocks', index: 0 })
      store().setScope('outer')
      store().insertBlock(groupRef('r2', 'svc'), { parentUid: null, slot: 'blocks', index: 0 })
      store().setScope(null)

      expect(store().renameGroup('svc', 'ctrl')).toBeNull()
      expect(store().groups).toHaveProperty('ctrl')
      expect(store().groups).not.toHaveProperty('svc')
      expect((store().tree[0] as GroupRefNode).name).toBe('ctrl')
      expect((store().groups.outer.body[0] as GroupRefNode).name).toBe('ctrl')
    })

    it('renaming the currently-active group scope keeps scope pointing at it under the new name', () => {
      store().addGroup('svc')
      store().setScope('svc')
      expect(store().renameGroup('svc', 'ctrl')).toBeNull()
      expect(store().scope).toBe('ctrl')
    })

    it('removing the active group scope falls back to the main workflow', () => {
      store().addGroup('svc')
      store().setScope('svc')
      expect(store().removeGroup('svc')).toBeNull()
      expect(store().scope).toBeNull()
    })

    // Task 9 review, Finding 1: removeRole/renameRole/removeStream/renameStream counted and
    // rewrote refs against `tree` only, never `groups` — the exact bug class Task 6 just
    // closed for `groups` itself, one namespace over. A role/stream used exclusively inside a
    // group body (e.g. morbidostat.json's `drug_pump`, cited only from `groups.service.body`)
    // could be deleted with zero warning, or renamed while the group body kept citing the old,
    // now-nonexistent name — and Save never gates on validation, so that silently persisted.
    describe('role/stream ops must span group bodies, not just the main tree (Finding 1)', () => {
      it('refuses to delete a role referenced only from a group body', () => {
        store().addRole('drug_pump', 'pump')
        store().addGroup('service')
        store().setScope('service')
        store().insertBlock(cmd('c1', 'drug_pump'), { parentUid: null, slot: 'blocks', index: 0 })
        store().setScope(null)
        expect(store().tree).toEqual([]) // the only reference lives inside the group body
        expect(store().removeRole('drug_pump')).toMatch(/1 block/)
        expect(store().roles).toHaveProperty('drug_pump')
      })

      it('renaming a role rewrites a reference that lives only inside a group body', () => {
        store().addRole('drug_pump', 'pump')
        store().addGroup('service')
        store().setScope('service')
        store().insertBlock(cmd('c1', 'drug_pump'), { parentUid: null, slot: 'blocks', index: 0 })
        store().setScope(null)
        expect(store().renameRole('drug_pump', 'drug_pump_v2')).toBeNull()
        expect(store().roles).toHaveProperty('drug_pump_v2')
        expect(store().roles).not.toHaveProperty('drug_pump')
        expect((store().groups.service.body[0] as CommandNode).device).toBe('drug_pump_v2')
      })

      it('refuses to delete a stream referenced only from a group body (synthetic — the reviewer ' +
        'had no live repro on morbidostat.json specifically, but the code path is identical)', () => {
        store().addStream('od', 'AU')
        store().addGroup('service')
        store().setScope('service')
        store().insertBlock(meas('m1', 'od_meter', 'od'), { parentUid: null, slot: 'blocks', index: 0 })
        store().setScope(null)
        expect(store().tree).toEqual([])
        expect(store().removeStream('od')).toMatch(/1 block/)
        expect(store().streams).toHaveProperty('od')
      })

      it('renaming a stream rewrites a reference that lives only inside a group body', () => {
        store().addStream('od', 'AU')
        store().addGroup('service')
        store().setScope('service')
        store().insertBlock(meas('m1', 'od_meter', 'od'), { parentUid: null, slot: 'blocks', index: 0 })
        store().setScope(null)
        expect(store().renameStream('od', 'od600')).toBeNull()
        expect((store().groups.service.body[0] as MeasureNode).into).toBe('od600')
      })
    })

    // Task 9 review, Finding 2: mapNodes (refs.ts) used Array.prototype.map unconditionally,
    // which always allocates — so `renameGroupRefs(s.tree, ...)` changed `tree`'s identity on
    // EVERY renameGroup call, even one with zero refs in the main tree. followUndoScope checks
    // `before.tree !== after.tree` FIRST, so that spurious identity change always won, forcing
    // scope to `null` and never reaching the per-group diff — even when the reverted edit lived
    // entirely inside a group body. Reproduced here with the main tree empty throughout.
    it('undo follows an edit that lives only inside a group body, not the empty main tree ' +
      'renameGroup also happens to touch (Finding 2)', () => {
      store().addGroup('outer')
      store().setScope('outer')
      store().insertBlock(groupRef('r1', 'svc'), { parentUid: null, slot: 'blocks', index: 0 })
      store().setScope(null) // main tree is empty and stays empty throughout
      expect(store().tree).toEqual([])

      expect(store().renameGroup('svc', 'ctrl')).toBeNull()
      expect((store().groups.outer.body[0] as GroupRefNode).name).toBe('ctrl')
      expect(store().scope).toBeNull() // 'svc' wasn't the active scope, so nothing to follow yet

      undo()
      expect((store().groups.outer.body[0] as GroupRefNode).name).toBe('svc') // reverted
      expect(store().scope).toBe('outer') // and the store followed the undo there to show it
    })

    // Task 9 review, Finding 3 (test hygiene): nothing pinned `groups` being part of the
    // dirty-check hash — mutation-tested by removing `groups: content.groups,` from
    // `snapshotOf` and confirming the full suite stayed green without this test.
    it('the dirty-check covers groups — editing inside a group scope must not read clean', () => {
      loadDoc(
        docToTree({
          doc_version: 1, name: 'macro', description: null,
          workflow: {
            schema_version: 2,
            streams: {},
            groups: { service: { params: [], body: [] } },
            blocks: [],
          },
        }),
        'id-1',
      )
      expect(selectDirty(store())).toBe(false)
      store().setScope('service')
      store().insertBlock(newPaletteNode('wait'), { parentUid: null, slot: 'blocks', index: 0 })
      expect(selectDirty(store())).toBe(true)
    })

    it('setGroupParams stores typed decls; setGroupLocals stores locals; both round-trip and dirty', () => {
      loadDoc(docToTree({ doc_version: 1, name: 'g', description: null,
        workflow: { schema_version: 2, groups: { svc: { body: [] } }, blocks: [] } }), 'id')
      expect(selectDirty(store())).toBe(false)
      store().setGroupParams('svc', [{ name: 'tube', kind: 'int' }, { name: 'm', kind: 'role', device_type: 'densitometer' }])
      store().setGroupLocals('svc', { c: { kind: 'binding', init: '0' } })
      expect(store().groups.svc.params).toEqual([{ name: 'tube', kind: 'int' }, { name: 'm', kind: 'role', device_type: 'densitometer' }])
      expect(store().groups.svc.locals).toEqual({ c: { kind: 'binding', init: '0' } })
      expect(selectDirty(store())).toBe(true)
      const out = selectDoc(store()).workflow.groups!.svc
      expect(out.params).toEqual([{ name: 'tube', kind: 'int' }, { name: 'm', kind: 'role', device_type: 'densitometer' }])
      expect(out.locals).toEqual({ c: { kind: 'binding', init: '0' } })
    })
  })
})

const emptyDocContent = () => ({
  name: '',
  description: null,
  roles: {},
  streams: {},
  tree: [],
  groups: {},
})

describe('loadDoc view rehydration', () => {
  it('leaves view state cleared when no view is supplied', () => {
    loadDoc({ ...emptyDocContent(), name: 'a' }, 'srv1')
    const s = useDocStore.getState()
    expect(s.scope).toBeNull()
    expect(s.selectedUid).toBeNull()
    expect(s.collapsed).toEqual({})
  })

  it('rehydrates scope, selection and the collapsed map from a draft view', () => {
    loadDoc({ ...emptyDocContent(), name: 'a', groups: { dose: { params: [], locals: {}, body: [] } } }, 'srv1', {
      scope: 'dose',
      selectedUid: 'u7',
      collapsed: { u7: true },
    })
    const s = useDocStore.getState()
    expect(s.scope).toBe('dose')
    expect(s.selectedUid).toBe('u7')
    expect(s.collapsed).toEqual({ u7: true })
  })

  // Rehydrating view state must not reintroduce the cross-document contamination that the
  // explicit undefined-writes in loadDoc exist to prevent (2026-07-14 review, I1).
  it('clears a previous document view state when the next load supplies none', () => {
    loadDoc({ ...emptyDocContent(), name: 'a' }, 'srv1', {
      scope: null,
      selectedUid: 'u7',
      collapsed: { u7: true },
    })
    loadDoc({ ...emptyDocContent(), name: 'b' }, 'srv2')
    const s = useDocStore.getState()
    expect(s.selectedUid).toBeNull()
    expect(s.collapsed).toEqual({})
  })

  it('still clears undo history when a view is supplied', () => {
    loadDoc({ ...emptyDocContent(), name: 'a' }, 'srv1', {
      scope: null,
      selectedUid: null,
      collapsed: {},
    })
    expect(useDocStore.temporal.getState().pastStates).toHaveLength(0)
  })
})
