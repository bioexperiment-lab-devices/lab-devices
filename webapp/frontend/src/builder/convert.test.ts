import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { BlockJson, ExperimentDocJson, WorkflowJson } from '../types/doc'
import { docToTree, nodeToBlock, treeToDoc, type DocContent } from './convert'
import type { ComputeNode, ForEachNode, LoopNode, MeasureNode, SerialNode, WaitNode } from './tree'

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
      workflow: {
        schema_version: 3,
        metadata: { name: 'Retry test' },
        persistence: { default: 'in_memory', format: 'jsonl' },
        roles: { od_meter: { type: 'densitometer' } },
        streams: {},
        blocks,
      },
    }
    expect(treeToDoc(docToTree(doc)).workflow.blocks).toEqual(blocks)
  })

  it('round-trips the compute/record `as` unit cast through the builder tree', () => {
    const blocks: BlockJson[] = [
      { compute: { into: 'r', value: '24 * mean(od) / last(od)', as: 'per_hour' } },
      { record: { into: 'r_series', value: 'r', as: 'per_hour' } },
      { compute: { into: 'flag', value: 'last(od) > 1' } }, // no cast -> `as` omitted
    ]
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Cast test',
      description: null,
      workflow: {
        schema_version: 3,
        metadata: { name: 'Cast test' },
        persistence: { default: 'in_memory', format: 'jsonl' },
        roles: {},
        streams: { od: { units: 'AU' }, r_series: { units: 'per_hour' } },
        blocks,
      },
    }
    const tree = docToTree(doc)
    expect(tree.tree[0]).toMatchObject({ kind: 'compute', as: 'per_hour' })
    expect(tree.tree[2]).toMatchObject({ kind: 'compute', as: null })
    expect(treeToDoc(tree).workflow.blocks).toEqual(blocks)
  })

  it('round-trips workflow.defaults.retry, which the builder has no UI for but must not destroy', () => {
    // Reproduces the reviewer's proof: a hand-authored doc with a workflow-wide retry
    // policy must survive Save unmodified, or the run loses its only fault-tolerance
    // safety net (2026-07-14 review, Fix 1).
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Defaults test',
      description: null,
      workflow: {
        schema_version: 3,
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

  it('round-trips workflow.metadata.author/description, which the builder has no UI for but ' +
    'must not destroy — opening and saving a doc with hand-authored metadata must not erase ' +
    'its authorship or its scientific description', () => {
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Metadata test',
      description: null,
      workflow: {
        schema_version: 3,
        metadata: {
          name: 'Metadata test',
          author: 'lab-devices examples',
          description: 'a multi-paragraph scientific description',
        },
        persistence: { default: 'in_memory', format: 'jsonl' },
        streams: {},
        blocks: [],
      },
    }
    expect(treeToDoc(docToTree(doc)).workflow.metadata).toEqual({
      name: 'Metadata test',
      author: 'lab-devices examples',
      description: 'a multi-paragraph scientific description',
    })
  })

  it('renaming the doc updates metadata.name while preserving author/description, and keeps ' +
    'name first in key order', () => {
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Original name',
      description: null,
      workflow: {
        schema_version: 3,
        metadata: { name: 'Original name', author: 'someone', description: 'about this doc' },
        persistence: { default: 'in_memory', format: 'jsonl' },
        streams: {},
        blocks: [],
      },
    }
    const renamed = { ...docToTree(doc), name: 'New name' }
    const metadata = treeToDoc(renamed).workflow.metadata
    expect(metadata).toEqual({
      name: 'New name',
      author: 'someone',
      description: 'about this doc',
    })
    // Key order matters for the byte-exact round trip (spread semantics keep a re-assigned
    // key's original position) — JSON.stringify is sensitive to it where toEqual is not.
    expect(JSON.stringify(metadata)).toBe(
      JSON.stringify({ name: 'New name', author: 'someone', description: 'about this doc' }),
    )
  })

  it('preserves a custom persistence setting instead of clobbering it with the hardcoded default', () => {
    const doc: ExperimentDocJson = {
      doc_version: 1,
      name: 'Persistence test',
      description: null,
      workflow: {
        schema_version: 3,
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
      workflow: {
        schema_version: 3,
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

describe('treeToDoc rejects a corrupt-but-shaped DocContent', () => {
  // App.tsx's boot executor calls treeToDoc(action.draft.content) as a pre-flight, purely for
  // its throw, before a restored draft ever reaches loadDoc/the store: draftStorage.ts's
  // parseDraft only checks that `content` is an object and then casts, so a damaged
  // sessionStorage/localStorage entry can hand the executor a `DocContent` that is shaped but
  // not valid. That pre-flight is only as good as treeToDoc's willingness to throw on the
  // shapes storage damage actually produces — this is the property it depends on, proven here
  // because it is pure and cheap to check without a browser (Task 8 review, Finding 1).
  const base: Omit<DocContent, 'tree'> = {
    name: 'x',
    description: null,
    roles: {},
    streams: {},
    groups: {},
  }

  it('throws when tree is null', () => {
    expect(() => treeToDoc({ ...base, tree: null as unknown as DocContent['tree'] })).toThrow()
  })

  it('throws when tree is a bare object instead of an array', () => {
    expect(() => treeToDoc({ ...base, tree: {} as unknown as DocContent['tree'] })).toThrow()
  })

  it('throws when tree contains a block with no recognizable type key', () => {
    expect(() =>
      treeToDoc({ ...base, tree: [{ zap: 1 }] as unknown as DocContent['tree'] }),
    ).toThrow()
  })

  it('throws when streams is missing entirely', () => {
    const { streams: _streams, ...withoutStreams } = base
    expect(() => treeToDoc({ ...withoutStreams, tree: [] } as unknown as DocContent)).toThrow()
  })
})

describe('control blocks', () => {
  const doc = (blocks: BlockJson[]): ExperimentDocJson => ({
    doc_version: 1,
    name: 'control',
    description: null,
    workflow: {
      schema_version: 3,
      metadata: { name: 'control' },
      persistence: { default: 'in_memory', format: 'jsonl' },
      streams: { c_series: { units: null } },
      blocks,
    },
  })

  const BLOCKS: BlockJson[] = [
    { compute: { into: 'c', value: 'c * 0.9' } },
    { record: { into: 'c_series', value: 'c' } },
    { abort: { if: 'emergency_stop', message: 'operator emergency stop' } },
    { alarm: { if: 'od > 2.0', message: 'tube 1 contaminated' }, on_error: 'continue' },
  ]

  it('round-trips every control block', () => {
    const input = doc(BLOCKS)
    expect(treeToDoc(docToTree(input))).toEqual(input)
  })

  it('parses control blocks into their node shapes', () => {
    const tree = docToTree(doc(BLOCKS)).tree
    expect(tree[0]).toMatchObject({ kind: 'compute', into: 'c', value: 'c * 0.9' })
    expect(tree[1]).toMatchObject({ kind: 'record', into: 'c_series', value: 'c' })
    expect(tree[2]).toMatchObject({
      kind: 'abort',
      condition: 'emergency_stop',
      message: 'operator emergency stop',
    })
    expect(tree[3]).toMatchObject({ kind: 'alarm', condition: 'od > 2.0', onError: 'continue' })
  })

  it('keeps a literal compute value a number, not a string', () => {
    const tree = docToTree(doc([{ compute: { into: 'V', value: 12 } }])).tree
    expect((tree[0] as ComputeNode).value).toBe(12)
    expect(nodeToBlock(tree[0])).toEqual({ compute: { into: 'V', value: 12 } })
  })

  it('round-trips the control-blocks fixture with identical bytes', () => {
    const input = fixture('valid-control-blocks')
    // Deep-equal is blind to 6.0 vs 6 and to key order (W7 review); compare serialised bytes,
    // which is what actually reaches the backend.
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })
})

describe('repetition blocks', () => {
  // Key order mirrors the engine's canonical order (workflow_to_dict): schema_version,
  // metadata, persistence, defaults, roles, streams, groups, blocks. `defaults`/`roles`/`groups`
  // are spread in at their canonical position (conditionally, so an absent one is omitted)
  // rather than via a trailing `...workflow` spread — a trailing spread only overwrites a key's
  // value in place when the key already exists in the base literal, but `groups`/`roles` don't,
  // so one would land wherever the spread appears (after `blocks`) instead of before it.
  const doc = (workflow: Partial<WorkflowJson>): ExperimentDocJson => ({
    doc_version: 1,
    name: 'macro',
    description: null,
    workflow: {
      schema_version: workflow.schema_version ?? 3,
      metadata: workflow.metadata ?? { name: 'macro' },
      persistence: workflow.persistence ?? { default: 'in_memory', format: 'jsonl' },
      ...(workflow.defaults !== undefined ? { defaults: workflow.defaults } : {}),
      ...(workflow.roles !== undefined ? { roles: workflow.roles } : {}),
      streams: workflow.streams ?? {},
      ...(workflow.groups !== undefined ? { groups: workflow.groups } : {}),
      blocks: workflow.blocks ?? [],
    },
  })

  it('round-trips a for_each with typed vars and rows', () => {
    const input = doc({ blocks: [{ for_each: {
      vars: [{ name: 'tube', kind: 'int' }],
      in: [{ tube: 1 }, { tube: 2 }, { tube: 3 }],
      body: [{ wait: { duration: '{tube}s' } }],
    } }] })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('round-trips typed group params, locals, and a group_ref with as + args', () => {
    const input = doc({
      groups: { service: {
        params: [{ name: 'tube', kind: 'int' }, { name: 'od', kind: 'stream' }],
        locals: { c: { kind: 'binding', init: '0' }, c_series: { kind: 'stream', units: 'x_MIC' } },
        body: [{ compute: { into: '{c}', value: 'c * 0.9' } }],
      } },
      blocks: [{ group_ref: { name: 'service', as: 'tube_{tube}', args: { tube: 1, od: 'od_1' } } }],
    })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('round-trips a plain param-less, as-less group_ref unchanged', () => {
    const input = doc({ groups: { wash: { body: [{ wait: { duration: '1s' } }] } },
      blocks: [{ group_ref: { name: 'wash' } }] })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('parses a for_each into a node with typed vars/rows and a body slot', () => {
    const tree = docToTree(doc({ blocks: [{ for_each: {
      vars: [{ name: 't', kind: 'int' }], in: [{ t: 1 }], body: [{ wait: { duration: '1s' } }],
    } }] })).tree
    expect(tree[0]).toMatchObject({ kind: 'for_each', vars: [{ name: 't', kind: 'int' }], rows: [{ t: 1 }] })
    expect((tree[0] as ForEachNode).body).toHaveLength(1)
  })

  it('emits roles inside the workflow, not the envelope', () => {
    const out = treeToDoc(docToTree(doc({ blocks: [] })))
    expect('roles' in out).toBe(false)
    const withRole = treeToDoc({ name: 'x', description: null, roles: { p: { type: 'pump' } }, streams: {}, tree: [] })
    expect(withRole.workflow.roles).toEqual({ p: { type: 'pump' } })
    expect(Object.keys(withRole.workflow)).toEqual(['schema_version', 'metadata', 'persistence', 'roles', 'streams', 'blocks'])
  })

  it('round-trips a role carrying an optional direct device binding', () => {
    const input = doc({ roles: { medium_pump: { type: 'pump', device: 'pump_2' } }, blocks: [] })
    expect(JSON.stringify(treeToDoc(docToTree(input)))).toBe(JSON.stringify(input))
  })

  it('omits groups entirely when the doc has none', () => {
    const out = treeToDoc(docToTree(doc({ blocks: [{ wait: { duration: '1s' } }] })))
    expect('groups' in out.workflow).toBe(false)
  })

  it('opens examples/morbidostat.json and round-trips it byte-for-byte', () => {
    // The W9 acceptance (spec §8): the flagship uses groups + for_each and has never been
    // openable in the builder. Byte comparison, not toEqual — deep-equal is blind to key order
    // and to 6.0 vs 6 (the W7 trap).
    const input = JSON.parse(
      readFileSync(new URL('../../../../examples/morbidostat.json', import.meta.url), 'utf8'),
    ) as ExperimentDocJson
    const content = docToTree(input)
    // DocContent.groups is typed optional for callers that predate the field, but docToTree
    // always populates it (convert.ts:53) — `?? {}` satisfies the type without a `!` assertion.
    expect(Object.keys(content.groups ?? {})).toContain('service')
    expect(JSON.stringify(treeToDoc(content))).toBe(JSON.stringify(input))
  })
})
