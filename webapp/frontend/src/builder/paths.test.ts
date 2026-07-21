import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  diagnosticsByUid,
  fieldDiagnostics,
  mapDiagnostics,
  pathForUid,
  resolveDiagnosticNode,
  resolveDiagnosticPath,
  unclaimedDiagnostics,
  type GroupsMap,
  type MappedDiagnostic,
} from './paths'
import type { BlockNode, BranchNode, ForEachNode, LoopNode, SerialNode } from './tree'
import { visitNodes } from './tree'
import { docToTree } from './convert'
import type { ExperimentDocJson } from '../types/doc'

const base = { label: null, gapAfter: null, startOffset: null }
const wait = (uid: string): BlockNode => ({ uid, kind: 'wait', duration: '1s', ...base })
const waitNode = wait('w0')
const tree: BlockNode[] = [
  {
    uid: 's1', kind: 'serial', ...base,
    children: [
      wait('w1'),
      {
        uid: 'l1', kind: 'loop', mode: 'count', count: 2, until: '', check: 'after',
        pace: null, body: [wait('w2')], ...base,
      } satisfies LoopNode,
      {
        uid: 'b1', kind: 'branch', condition: 'last(od) > 1', then: [wait('w3')],
        else: [wait('w4')], ...base,
      } satisfies BranchNode,
    ],
  } satisfies SerialNode,
]

describe('resolveDiagnosticPath', () => {
  it('resolves root and nested structural paths', () => {
    expect(resolveDiagnosticPath(tree, {}, 'blocks[0]')).toEqual({
      uid: 's1', role: null, param: null, scope: null, field: null,
    })
    expect(resolveDiagnosticPath(tree, {}, 'blocks[0].children[1]').uid).toBe('l1')
    expect(resolveDiagnosticPath(tree, {}, 'blocks[0].children[1].body[0]').uid).toBe('w2')
    expect(resolveDiagnosticPath(tree, {}, 'blocks[0].children[2].then[0]').uid).toBe('w3')
    expect(resolveDiagnosticPath(tree, {}, 'blocks[0].children[2].else[0]').uid).toBe('w4')
  })

  it('still extracts the param name from a param path', () => {
    const r = resolveDiagnosticPath(tree, {}, "blocks[0].children[0] param 'volume_ml'")
    expect(r.uid).toBe('w1')
    expect(r.param).toBe('volume_ml')
  })

  it('resolves role paths from the studio doc-level checks', () => {
    expect(resolveDiagnosticPath(tree, {}, "roles['Feed_Pump']")).toEqual({
      uid: null, role: 'Feed_Pump', param: null, scope: null, field: null,
    })
  })

  it('resolves a double-quoted role path — repr flips quote style for an apostrophe (Finding 4)', () => {
    // Pre-existing gap, unchanged from main: the role regex was single-quote only, so the
    // one diagnostic whose whole job is flagging a bad role name died silently the moment
    // that name contained an apostrophe.
    expect(resolveDiagnosticPath(tree, {}, `roles["o'brien"]`)).toEqual({
      uid: null, role: "o'brien", param: null, scope: null, field: null,
    })
  })

  it('returns nulls for workflow-level and out-of-range paths', () => {
    expect(resolveDiagnosticPath(tree, {}, 'workflow').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, {}, 'blocks[9]').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, {}, 'blocks[0].children[1].then[0]').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, {}, "groups['prep'].body[0]").uid).toBeNull()
  })

  it('resolves a context-suffixed expression path onto the block', () => {
    // Pre-existing gap (W8 final review): only " param 'x'" was stripped, so these all
    // returned uid null (validate.py's `_expr_reads`/serialize.py append these after the
    // structural path; docs_store.py:186 partitions on the FIRST space only).
    for (const suffix of ['compute value', 'branch if', 'alarm if', 'record value', 'loop until']) {
      expect(resolveDiagnosticPath(tree, {}, `blocks[0] ${suffix}`).uid).toBe(tree[0].uid)
    }
  })

  it('still extracts the param name from a param path (context-suffix rewrite)', () => {
    const r = resolveDiagnosticPath(tree, {}, "blocks[0] param 'volume_ml'")
    expect(r).toMatchObject({ uid: tree[0].uid, param: 'volume_ml' })
  })

  it('extracts a double-quoted param name — repr flips quote style for an apostrophe (Finding 3)', () => {
    const r = resolveDiagnosticPath(tree, {}, `blocks[0] param "o'brien"`)
    expect(r).toMatchObject({ uid: tree[0].uid, param: "o'brien" })
  })

  it('resolves a group body path to the group scope', () => {
    const groups: GroupsMap = { service: { body: [waitNode] } }
    expect(resolveDiagnosticPath([], groups, "groups['service'].body[0]")).toMatchObject({
      uid: waitNode.uid,
      scope: 'service',
    })
  })

  it('resolves a nested slot inside a group body (groups[...] head + trailer)', () => {
    const inner = wait('inner')
    const groups: GroupsMap = {
      service: {
        body: [
          {
            uid: 'l2', kind: 'loop', mode: 'count', count: 1, until: '', check: 'after',
            pace: null, body: [inner], ...base,
          } satisfies LoopNode,
        ],
      },
    }
    expect(resolveDiagnosticPath([], groups, "groups['service'].body[0].body[0]")).toMatchObject({
      uid: inner.uid,
      scope: 'service',
    })
  })

  it('returns uid null (not the wrong block) for an out-of-range group-body index', () => {
    const groups: GroupsMap = { service: { body: [waitNode] } }
    // scope is null too when the node does not resolve: an unresolved group path carries no
    // editable location, so it must not report a scope (pre-refactor resolveDiagnosticPath
    // parity — the shared resolveStructuralNode only tags scope when resolveTail found a node).
    expect(resolveDiagnosticPath([], groups, "groups['service'].body[5]"))
      .toMatchObject({ uid: null, scope: null })
  })

  it('accepts a double-quoted group name — Python repr flips quote style for an apostrophe', () => {
    const groups: GroupsMap = { "o'brien": { body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, `groups["o'brien"].body[0]`)
    expect(r).toMatchObject({ uid: waitNode.uid, scope: "o'brien" })
  })

  it('resolves a group name containing a space, with no suffix present (Finding 1)', () => {
    // Pre-fix, `path.indexOf(' ')` found the space INSIDE the quoted name and mistook it
    // for a suffix boundary that does not exist, leaving `structural` as the truncated
    // `groups['a` — uid null even though there is no compound/suffix anywhere in this path.
    const groups: GroupsMap = { 'a b': { body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, "groups['a b'].body[0]")
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'a b' })
  })

  it('resolves a group name containing "->", not misread as a compound path (Finding 1)', () => {
    // Pre-fix, `structural.lastIndexOf('->')` found the arrow INSIDE the quoted name and
    // took the direct group-scope path for a compound one, whose GROUP_SEGMENT_RE then
    // failed on the mangled remainder — uid null for a fully direct, non-compound path.
    const groups: GroupsMap = { 'a->b': { body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, "groups['a->b'].body[0]")
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'a->b' })
  })

  it('resolves a group name containing a space AND carries a context suffix (Finding 1)', () => {
    const groups: GroupsMap = { 'a b': { body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, "groups['a b'].body[0] compute value")
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'a b' })
  })

  it('resolves a compound call-site->group path to the group DEFINITION, not the call site', () => {
    // validate.py:894/:940 f"{path}->{b.name}.body" — a plain group's body is expanded in
    // place (expand.py:270-274), so the call-site prefix before `->` is context only; the
    // authored, editable location is inside the group, which is where scope must switch to.
    const groups: GroupsMap = { mygroup: { body: [waitNode] } }
    const r = resolveDiagnosticPath(tree, groups, 'blocks[0].children[1]->mygroup.body[0] compute value')
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'mygroup' })
  })

  it('resolves a compound path whose call-site HEAD is itself a quoted group (Finding 1 + 3)', () => {
    // The file header used to claim a quoted `groups[...]` head and a compound path are
    // "mutually exclusive grammars" -- false: docs_store.py's `_remap_group_segment`
    // preserves exactly this shape when a plain group_ref's call site sits inside a
    // PARAMETRIZED group (test_docs_store.py:254, `groups['paramgroup'].body[0]->plaingroup
    // .body[0] compute value`). The group name here also carries a space, so this doubles
    // as the cross-language seam for Finding 1: the head's embedded space must not be
    // mistaken for the suffix boundary, nor should it hide the real compound arrow.
    const groups: GroupsMap = {
      'param group': { body: [] },
      plaingroup: { body: [waitNode] },
    }
    const r = resolveDiagnosticPath(
      [],
      groups,
      "groups['param group'].body[0]->plaingroup.body[0] compute value",
    )
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'plaingroup' })
  })

  it('resolves a doubly-compound path to the INNERMOST group, not the first', () => {
    const inner = wait('g2w0')
    const groups: GroupsMap = {
      g1: { body: [wait('g1w0')] },
      g2: { body: [inner] },
    }
    const r = resolveDiagnosticPath(tree, groups, 'blocks[0]->g1.body[0]->g2.body[0]')
    expect(r).toMatchObject({ uid: inner.uid, scope: 'g2' })
  })

  it('returns uid null (not the wrong block) for an out-of-range index in a compound path', () => {
    const groups: GroupsMap = { mygroup: { body: [waitNode] } }
    expect(
      resolveDiagnosticPath(tree, groups, 'blocks[0]->mygroup.body[5]').uid,
    ).toBeNull()
  })

  it('resolves a for_each body path through the body slot', () => {
    // childSlots now returns for_each's body (Task 3), so no path logic changes here —
    // this pins that behavior against a regression.
    const innerNode = wait('inner')
    const forEachNode: ForEachNode = {
      uid: 'fe', kind: 'for_each', vars: [{ name: 'tube', kind: 'int' }],
      rows: [{ tube: 1 }, { tube: 2 }, { tube: 3 }], body: [innerNode], ...base,
    }
    expect(resolveDiagnosticPath([forEachNode], {}, 'blocks[0].body[0]').uid).toBe(innerNode.uid)
  })

  it('returns uid null for an out-of-range index rather than the wrong block', () => {
    expect(resolveDiagnosticPath(tree, {}, 'blocks[99]').uid).toBeNull()
  })
})

describe('resolveDiagnosticNode', () => {
  it('returns the node for a main-tree path', () => {
    expect(resolveDiagnosticNode(tree, {}, 'blocks[0].children[1].body[0]')?.uid).toBe('w2')
  })
  it('returns the node for a group-scope path', () => {
    // uses the same `groups` fixture the resolveDiagnosticPath group tests use
    const groups: GroupsMap = { service: { body: [waitNode] } }
    expect(resolveDiagnosticNode([], groups, "groups['service'].body[0]")?.uid)
      .toBe(resolveDiagnosticPath([], groups, "groups['service'].body[0]").uid)
  })
  it('returns null for an unresolvable or role path', () => {
    expect(resolveDiagnosticNode(tree, {}, 'blocks[9]')).toBeNull()
    expect(resolveDiagnosticNode(tree, {}, "roles['Feed_Pump']")).toBeNull()
  })
})

// paths.test.ts sits at src/builder/, so the repo's webapp/fixtures/ dir is three levels up
// (src/builder -> src -> frontend -> webapp). __tests__/torture.test.ts needs four, being one
// directory deeper.
const FIXTURE = fileURLToPath(new URL('../../../fixtures/ui-audit-torture.json', import.meta.url))

const singleWaitDoc = () =>
  ({
    doc_version: 1,
    name: 't',
    description: null,
    workflow: { schema_version: 3, blocks: [{ wait: { duration: '1s' } }] },
  }) as unknown as ExperimentDocJson

describe('pathForUid', () => {
  it('emits blocks[i] for a top-level node', () => {
    const { tree: t } = docToTree(singleWaitDoc())
    expect(pathForUid(t, {}, t[0].uid)).toBe('blocks[0]')
  })

  it('emits a slot trailer for a nested node, descending via childSlots', () => {
    expect(pathForUid(tree, {}, 'w2')).toBe('blocks[0].children[1].body[0]')
    expect(pathForUid(tree, {}, 'w3')).toBe('blocks[0].children[2].then[0]')
    expect(pathForUid(tree, {}, 'w4')).toBe('blocks[0].children[2].else[0]')
  })

  it('returns null for a uid that is not in the tree', () => {
    expect(pathForUid([], {}, 'nope')).toBeNull()
    expect(pathForUid(tree, {}, 'nope')).toBeNull()
  })

  it('never emits the compound blocks[i]->name.body[i] form', () => {
    // That form describes a group RENDERED at a call site, not an authored location, so it
    // has no writer (design §4.1). Every path this file emits addresses where the node was
    // AUTHORED: the main tree, or the group's own body.
    const groups: GroupsMap = { mygroup: { body: [waitNode] } }
    const path = pathForUid(tree, groups, waitNode.uid)
    expect(path).toBe("groups['mygroup'].body[0]")
    expect(path).not.toContain('->')
  })

  // The property that matters: whatever pathForUid writes, resolveDiagnosticPath must read
  // back to the same node. The torture fixture is type-forced to contain every BlockKind
  // (__tests__/torture.test.ts), so this covers every container shape childSlots knows.
  it('round-trips every node in the torture fixture', () => {
    const doc = JSON.parse(readFileSync(FIXTURE, 'utf8')) as ExperimentDocJson
    // DocContent types `groups` as optional (convert.ts stays permissive for the docStore's
    // required-field authoring API); docToTree always populates it, so `{}` never applies.
    const { tree: fixtureTree, groups = {} } = docToTree(doc)
    const uids: string[] = []
    visitNodes(fixtureTree, (n) => uids.push(n.uid))
    let groupUidCount = 0
    for (const group of Object.values(groups)) {
      visitNodes(group.body, (n) => {
        uids.push(n.uid)
        groupUidCount++
      })
    }
    // Guard against the property vacuously passing over an empty or main-tree-only list.
    expect(uids.length).toBeGreaterThan(30)
    expect(groupUidCount).toBeGreaterThan(4)
    expect(new Set(uids).size).toBe(uids.length)
    for (const uid of uids) {
      const path = pathForUid(fixtureTree, groups, uid)
      expect(path, `no path for ${uid}`).not.toBeNull()
      expect(
        resolveDiagnosticPath(fixtureTree, groups, path!).uid,
        `round-trip failed for ${path}`,
      ).toBe(uid)
    }
  })

  // Non-identifier group names are reachable via Import: GROUP_NAME_RE (docStore.ts) is
  // enforced only on add/rename, and convert.ts loads keys verbatim (paths.ts header).
  it.each(['a b', "a'b", 'a->b', 'a"b', "o'brien"])(
    'round-trips inside a group named %j',
    (name) => {
      const groups: GroupsMap = {
        [name]: { body: docToTree(singleWaitDoc()).tree },
      }
      const uid = groups[name].body[0].uid
      const path = pathForUid([], groups, uid)
      expect(path).not.toBeNull()
      const r = resolveDiagnosticPath([], groups, path!)
      expect(r.uid).toBe(uid)
      expect(r.scope).toBe(name)
    },
  )

  it('returns null for a group name the path grammar cannot represent', () => {
    // A name carrying BOTH quote characters has no unescaped spelling: the reader's
    // GROUP_HEAD_RE accepts `'[^']*'` or `"[^"]*"` and has no escape handling, so either
    // spelling would be misparsed. Emitting nothing beats emitting a path that resolves to
    // the wrong node (or to null) downstream.
    const name = `a'b"c`
    const groups: GroupsMap = { [name]: { body: [waitNode] } }
    expect(pathForUid([], groups, waitNode.uid)).toBeNull()
  })
})

describe('mapDiagnostics', () => {
  it('attaches uids and groups by block', () => {
    const mapped = mapDiagnostics(tree, {}, [
      { category: 'block', path: 'blocks[0].children[1]', message: 'loop is empty' },
      { category: 'schema', path: 'workflow', message: 'loop until: invalid expression' },
      { category: 'roles', path: "roles['x']", message: 'unknown device type' },
    ])
    expect(mapped[0].uid).toBe('l1')
    expect(mapped[1].uid).toBeNull()
    expect(mapped[2].role).toBe('x')
    const byUid = diagnosticsByUid(mapped)
    expect(byUid.get('l1')).toHaveLength(1)
    expect(byUid.has('')).toBe(false)
  })

  it('resolves a group-scope diagnostic and carries its scope through', () => {
    const groups: GroupsMap = { service: { body: [waitNode] } }
    const mapped = mapDiagnostics(tree, groups, [
      { category: 'roles', path: "groups['service'].body[0]", message: 'unknown role' },
    ])
    expect(mapped[0]).toMatchObject({ uid: waitNode.uid, scope: 'service' })
  })
})

describe('field capture (spec §3.5)', () => {
  it('captures the context suffix as field', () => {
    const r = resolveDiagnosticPath(tree, {}, 'blocks[0].children[2] branch if')
    expect(r.uid).toBe('b1')
    expect(r.field).toBe('branch if')
  })
  it('param suffixes populate both param and field', () => {
    const r = resolveDiagnosticPath(tree, {}, "blocks[0].children[0] param 'volume_ml'")
    expect(r.param).toBe('volume_ml')
    expect(r.field).toBe("param 'volume_ml'")
  })
  it('suffix-less paths have a null field', () => {
    expect(resolveDiagnosticPath(tree, {}, 'blocks[0]').field).toBeNull()
  })
})

describe('fieldDiagnostics / unclaimedDiagnostics', () => {
  const diag = (uid: string | null, field: string | null): MappedDiagnostic => ({
    category: 'type', path: 'x', message: 'm', uid, role: null, param: null, scope: null, field,
  })
  const diags = [diag('u1', 'branch if'), diag('u1', null), diag('u2', 'branch if')]

  it('partitions one block\'s diagnostics by claimed suffix', () => {
    expect(fieldDiagnostics(diags, 'u1', ['branch if'])).toHaveLength(1)
    expect(fieldDiagnostics(diags, 'u1', ['branch if'])[0].uid).toBe('u1')
    expect(unclaimedDiagnostics(diags, 'u1', ['branch if'])).toHaveLength(1)
    expect(unclaimedDiagnostics(diags, 'u1', ['branch if'])[0].field).toBeNull()
  })
  it('an unclaimed suffix falls to the strip', () => {
    expect(unclaimedDiagnostics(diags, 'u1', [])).toHaveLength(2)
    expect(fieldDiagnostics(diags, 'u1', [])).toHaveLength(0)
  })
})
