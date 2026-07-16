import { describe, expect, it } from 'vitest'
import { diagnosticsByUid, mapDiagnostics, resolveDiagnosticPath, type GroupsMap } from './paths'
import type { BlockNode, BranchNode, ForEachNode, LoopNode, SerialNode } from './tree'

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
      uid: 's1', role: null, param: null, scope: null,
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
      uid: null, role: 'Feed_Pump', param: null, scope: null,
    })
  })

  it('resolves a double-quoted role path — repr flips quote style for an apostrophe (Finding 4)', () => {
    // Pre-existing gap, unchanged from main: the role regex was single-quote only, so the
    // one diagnostic whose whole job is flagging a bad role name died silently the moment
    // that name contained an apostrophe.
    expect(resolveDiagnosticPath(tree, {}, `roles["o'brien"]`)).toEqual({
      uid: null, role: "o'brien", param: null, scope: null,
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
    const groups: GroupsMap = { service: { params: ['tube'], body: [waitNode] } }
    expect(resolveDiagnosticPath([], groups, "groups['service'].body[0]")).toMatchObject({
      uid: waitNode.uid,
      scope: 'service',
    })
  })

  it('resolves a nested slot inside a group body (groups[...] head + trailer)', () => {
    const inner = wait('inner')
    const groups: GroupsMap = {
      service: {
        params: [],
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
    const groups: GroupsMap = { service: { params: [], body: [waitNode] } }
    expect(resolveDiagnosticPath([], groups, "groups['service'].body[5]").uid).toBeNull()
  })

  it('accepts a double-quoted group name — Python repr flips quote style for an apostrophe', () => {
    const groups: GroupsMap = { "o'brien": { params: [], body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, `groups["o'brien"].body[0]`)
    expect(r).toMatchObject({ uid: waitNode.uid, scope: "o'brien" })
  })

  it('resolves a group name containing a space, with no suffix present (Finding 1)', () => {
    // Pre-fix, `path.indexOf(' ')` found the space INSIDE the quoted name and mistook it
    // for a suffix boundary that does not exist, leaving `structural` as the truncated
    // `groups['a` — uid null even though there is no compound/suffix anywhere in this path.
    const groups: GroupsMap = { 'a b': { params: [], body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, "groups['a b'].body[0]")
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'a b' })
  })

  it('resolves a group name containing "->", not misread as a compound path (Finding 1)', () => {
    // Pre-fix, `structural.lastIndexOf('->')` found the arrow INSIDE the quoted name and
    // took the direct group-scope path for a compound one, whose GROUP_SEGMENT_RE then
    // failed on the mangled remainder — uid null for a fully direct, non-compound path.
    const groups: GroupsMap = { 'a->b': { params: [], body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, "groups['a->b'].body[0]")
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'a->b' })
  })

  it('resolves a group name containing a space AND carries a context suffix (Finding 1)', () => {
    const groups: GroupsMap = { 'a b': { params: [], body: [waitNode] } }
    const r = resolveDiagnosticPath([], groups, "groups['a b'].body[0] compute value")
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'a b' })
  })

  it('resolves a compound call-site->group path to the group DEFINITION, not the call site', () => {
    // validate.py:894/:940 f"{path}->{b.name}.body" — a plain group's body is expanded in
    // place (expand.py:270-274), so the call-site prefix before `->` is context only; the
    // authored, editable location is inside the group, which is where scope must switch to.
    const groups: GroupsMap = { mygroup: { params: [], body: [waitNode] } }
    const r = resolveDiagnosticPath(tree, groups, 'blocks[0].children[1]->mygroup.body[0] compute value')
    expect(r).toMatchObject({ uid: waitNode.uid, scope: 'mygroup' })
  })

  it('resolves a doubly-compound path to the INNERMOST group, not the first', () => {
    const inner = wait('g2w0')
    const groups: GroupsMap = {
      g1: { params: [], body: [wait('g1w0')] },
      g2: { params: [], body: [inner] },
    }
    const r = resolveDiagnosticPath(tree, groups, 'blocks[0]->g1.body[0]->g2.body[0]')
    expect(r).toMatchObject({ uid: inner.uid, scope: 'g2' })
  })

  it('returns uid null (not the wrong block) for an out-of-range index in a compound path', () => {
    const groups: GroupsMap = { mygroup: { params: [], body: [waitNode] } }
    expect(
      resolveDiagnosticPath(tree, groups, 'blocks[0]->mygroup.body[5]').uid,
    ).toBeNull()
  })

  it('resolves a for_each body path through the body slot', () => {
    // childSlots now returns for_each's body (Task 3), so no path logic changes here —
    // this pins that behavior against a regression.
    const innerNode = wait('inner')
    const forEachNode: ForEachNode = {
      uid: 'fe', kind: 'for_each', var: 'tube', items: [1, 2, 3], body: [innerNode], ...base,
    }
    expect(resolveDiagnosticPath([forEachNode], {}, 'blocks[0].body[0]').uid).toBe(innerNode.uid)
  })

  it('returns uid null for an out-of-range index rather than the wrong block', () => {
    expect(resolveDiagnosticPath(tree, {}, 'blocks[99]').uid).toBeNull()
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
    const groups: GroupsMap = { service: { params: [], body: [waitNode] } }
    const mapped = mapDiagnostics(tree, groups, [
      { category: 'roles', path: "groups['service'].body[0]", message: 'unknown role' },
    ])
    expect(mapped[0]).toMatchObject({ uid: waitNode.uid, scope: 'service' })
  })
})
