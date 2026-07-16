import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { BlockJson, ExperimentDocJson } from '../types/doc'
import { DocConvertError, docToTree, nodeToBlock, treeToDoc } from './convert'
import type { LoopNode, MeasureNode, SerialNode, WaitNode } from './tree'

const fixture = (name: string): ExperimentDocJson =>
  JSON.parse(
    readFileSync(new URL(`../../../fixtures/${name}.json`, import.meta.url), 'utf8'),
  ) as ExperimentDocJson

describe('docToTree', () => {
  it('parses the golden fixture into an editor tree', () => {
    const content = docToTree(fixture('valid-od-growth'))
    expect(content.name).toBe('OD growth curve')
    expect(content.roles).toEqual({
      feed_pump: { type: 'pump' },
      od_meter: { type: 'densitometer' },
    })
    expect(content.streams).toEqual({ od: { units: 'AU' } })
    expect(content.tree).toHaveLength(1)
    const root = content.tree[0] as SerialNode
    expect(root.kind).toBe('serial')
    expect(root.children.map((c) => c.kind)).toEqual(['command', 'loop'])
    const loop = root.children[1] as LoopNode
    expect(loop).toMatchObject({
      mode: 'until',
      until: 'mean(od, last=3) > 0.6',
      check: 'after',
      pace: '30s',
    })
    const measure = loop.body[0] as MeasureNode
    expect(measure).toMatchObject({ device: 'od_meter', verb: 'measure', into: 'od' })
  })

  it('parses both invalid fixtures without throwing (they are diagnostics cases, not parse cases)', () => {
    expect(() => docToTree(fixture('invalid-roles'))).not.toThrow()
    expect(() => docToTree(fixture('invalid-workflow'))).not.toThrow()
  })

  it('assigns unique uids to every node', () => {
    const { tree } = docToTree(fixture('valid-od-growth'))
    const uids: string[] = []
    const visit = (nodes: typeof tree): void => {
      for (const n of nodes) {
        uids.push(n.uid)
        if (n.kind === 'serial' || n.kind === 'parallel') visit(n.children)
        if (n.kind === 'loop') visit(n.body)
        if (n.kind === 'branch') {
          visit(n.then)
          if (n.else) visit(n.else)
        }
      }
    }
    visit(tree)
    expect(new Set(uids).size).toBe(uids.length)
    expect(uids.length).toBe(5)
  })

  it('refuses docs that use groups or group_ref blocks', () => {
    const doc = fixture('valid-od-growth')
    doc.workflow.groups = { prep: { body: [] } }
    expect(() => docToTree(doc)).toThrow(DocConvertError)
    const doc2 = fixture('valid-od-growth')
    doc2.workflow.blocks = [{ group_ref: { name: 'prep' } }]
    expect(() => docToTree(doc2)).toThrow(/group_ref/)
  })

  it('reports for_each as a specific unsupported-in-builder message, not the generic one', () => {
    const doc = fixture('valid-od-growth')
    doc.workflow.blocks = [
      { for_each: { var: 't', in: [1, 2], body: [{ wait: { duration: '1s' } }] } },
    ] as unknown as BlockJson[]
    expect(() => docToTree(doc)).toThrow(DocConvertError)
    expect(() => docToTree(doc)).toThrow(/for_each is not yet supported in the builder/)
  })

  it('reports abort as a specific unsupported-in-builder message', () => {
    const doc = fixture('valid-od-growth')
    doc.workflow.blocks = [
      { abort: { if: 'true', message: 'safety stop' } },
    ] as unknown as BlockJson[]
    expect(() => docToTree(doc)).toThrow(DocConvertError)
    expect(() => docToTree(doc)).toThrow(/abort is not yet supported in the builder/)
  })

  it('reports alarm as a specific unsupported-in-builder message', () => {
    const doc = fixture('valid-od-growth')
    doc.workflow.blocks = [
      { alarm: { if: 'true', message: 'flagged condition' } },
    ] as unknown as BlockJson[]
    expect(() => docToTree(doc)).toThrow(DocConvertError)
    expect(() => docToTree(doc)).toThrow(/alarm is not yet supported in the builder/)
  })
})

describe('treeToDoc', () => {
  it('round-trips the golden fixture exactly', () => {
    const raw = fixture('valid-od-growth')
    expect(treeToDoc(docToTree(raw))).toEqual(raw)
  })

  it('emits check only alongside until, and omits count in until mode', () => {
    const { tree } = docToTree(fixture('valid-od-growth'))
    const root = tree[0] as SerialNode
    const loop = root.children[1] as LoopNode
    const untilJson = nodeToBlock(loop)
    expect(untilJson.loop).toMatchObject({ until: 'mean(od, last=3) > 0.6', check: 'after' })
    expect(untilJson.loop).not.toHaveProperty('count')
    const countJson = nodeToBlock({ ...loop, mode: 'count', count: 3 })
    expect(countJson.loop).toMatchObject({ count: 3 })
    expect(countJson.loop).not.toHaveProperty('until')
    expect(countJson.loop).not.toHaveProperty('check')
  })

  it('omits on_error entirely for a default-fail block — engine parity: block_to_dict emits ' +
    'on_error only via `!= "fail"`, so a default block must round-trip with no on_error key', () => {
    const base: WaitNode = {
      uid: 'x', kind: 'wait', duration: '1s', label: null, gapAfter: null, startOffset: null,
    }
    expect(nodeToBlock(base)).not.toHaveProperty('on_error')
    expect(nodeToBlock({ ...base, onError: 'fail' })).not.toHaveProperty('on_error')
    expect(nodeToBlock({ ...base, onError: 'continue' })).toHaveProperty('on_error', 'continue')
  })

  it('omits empty params, null timing keys, and null else', () => {
    const { tree } = docToTree(fixture('valid-od-growth'))
    const root = tree[0] as SerialNode
    const measureJson = nodeToBlock((root.children[1] as LoopNode).body[0])
    expect(measureJson.measure).not.toHaveProperty('params')
    expect(measureJson).not.toHaveProperty('label')
    expect(measureJson).not.toHaveProperty('gap_after')
    const branchJson = nodeToBlock({
      uid: 'b', kind: 'branch', condition: 'last(od) > 1', then: [], else: null,
      label: null, gapAfter: null, startOffset: null,
    })
    expect(branchJson.branch).not.toHaveProperty('else')
    const withElse = nodeToBlock({
      uid: 'b', kind: 'branch', condition: 'last(od) > 1', then: [], else: [],
      label: null, gapAfter: null, startOffset: null,
    })
    expect(withElse.branch).toHaveProperty('else', [])
  })

  it('always stamps builder-owned metadata and persistence sections', () => {
    const doc = treeToDoc({ name: 'X', description: null, roles: {}, streams: {}, tree: [] })
    expect(doc.workflow.metadata).toEqual({ name: 'X' })
    expect(doc.workflow.persistence).toEqual({ default: 'in_memory', format: 'jsonl' })
    expect(doc.workflow.blocks).toEqual([])
    expect(doc.doc_version).toBe(1)
  })

  it('round-trips retry and on_error through the builder tree', () => {
    // docToTree/treeToDoc operate on a full ExperimentDocJson, not a bare BlockJson[] —
    // the brief's snippet was written before the engine landed and guessed wrong here.
    const blocks: BlockJson[] = [
      {
        measure: { device: 'od_meter', verb: 'measure', into: 'od_1' },
        label: 'read OD',
        retry: { attempts: 3, backoff: '2s' },
        on_error: 'continue',
      },
    ]
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Retry test',
      description: null,
      roles: { od_meter: { type: 'densitometer' } },
      workflow: {
        schema_version: 1,
        metadata: { name: 'Retry test' },
        persistence: { default: 'in_memory', format: 'jsonl' },
        streams: {},
        blocks,
      },
    }
    expect(treeToDoc(docToTree(doc)).workflow.blocks).toEqual(blocks)
  })

  it('round-trips workflow.defaults.retry, which the builder has no UI for but must not destroy', () => {
    // Reproduces the reviewer's proof: a hand-authored doc with a workflow-wide retry
    // policy must survive Save unmodified, or the run loses its only fault-tolerance
    // safety net (2026-07-14 review, Fix 1).
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Defaults test',
      description: null,
      roles: {},
      workflow: {
        schema_version: 1,
        metadata: { name: 'Defaults test' },
        persistence: { default: 'in_memory', format: 'jsonl' },
        streams: {},
        defaults: { retry: { attempts: 3, backoff: '2s' } },
        blocks: [],
      },
    }
    expect(treeToDoc(docToTree(doc)).workflow.defaults).toEqual({
      retry: { attempts: 3, backoff: '2s' },
    })
  })

  it('preserves a custom persistence setting instead of clobbering it with the hardcoded default', () => {
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Persistence test',
      description: null,
      roles: {},
      workflow: {
        schema_version: 1,
        metadata: { name: 'Persistence test' },
        persistence: { default: 'disk' },
        streams: {},
        blocks: [],
      },
    }
    expect(treeToDoc(docToTree(doc)).workflow.persistence).toEqual({ default: 'disk' })
  })

  it('still stamps the historical default persistence when the doc carries none', () => {
    const doc = treeToDoc({ name: 'X', description: null, roles: {}, streams: {}, tree: [] })
    expect(doc.workflow.persistence).toEqual({ default: 'in_memory', format: 'jsonl' })
    expect(doc.workflow).not.toHaveProperty('defaults')
  })

  it('round-trips a per-stream persistence override, which the builder has no UI for but ' +
    'must not destroy (2026-07-14 review, I2) — a stream declared persistence: "disk" under ' +
    'an in_memory workflow default must not be silently downgraded to in-memory on save, or ' +
    'its samples are never written to disk at all', () => {
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Stream persistence test',
      description: null,
      roles: {},
      workflow: {
        schema_version: 1,
        metadata: { name: 'Stream persistence test' },
        persistence: { default: 'in_memory', format: 'jsonl' },
        streams: { od: { units: 'AU', persistence: 'disk' } },
        blocks: [],
      },
    }
    expect(treeToDoc(docToTree(doc)).workflow.streams).toEqual({
      od: { units: 'AU', persistence: 'disk' },
    })
  })

  it('omits the per-stream persistence key entirely for a stream that never had an override', () => {
    const content = docToTree(fixture('valid-od-growth'))
    expect(treeToDoc(content).workflow.streams?.od?.persistence).toBeUndefined()
  })
})
