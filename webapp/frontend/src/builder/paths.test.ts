import { describe, expect, it } from 'vitest'
import { diagnosticsByUid, mapDiagnostics, resolveDiagnosticPath } from './paths'
import type { BlockNode, BranchNode, LoopNode, SerialNode } from './tree'

const base = { label: null, gapAfter: null, startOffset: null }
const wait = (uid: string): BlockNode => ({ uid, kind: 'wait', duration: '1s', ...base })
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
    expect(resolveDiagnosticPath(tree, 'blocks[0]')).toEqual({ uid: 's1', role: null, param: null })
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[1]').uid).toBe('l1')
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[1].body[0]').uid).toBe('w2')
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[2].then[0]').uid).toBe('w3')
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[2].else[0]').uid).toBe('w4')
  })

  it('extracts the param suffix the engine appends to param diagnostics', () => {
    const r = resolveDiagnosticPath(tree, "blocks[0].children[0] param 'volume_ml'")
    expect(r.uid).toBe('w1')
    expect(r.param).toBe('volume_ml')
  })

  it('resolves role paths from the studio doc-level checks', () => {
    expect(resolveDiagnosticPath(tree, "roles['Feed_Pump']")).toEqual({
      uid: null, role: 'Feed_Pump', param: null,
    })
  })

  it('returns nulls for workflow-level and out-of-range paths', () => {
    expect(resolveDiagnosticPath(tree, 'workflow').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, 'blocks[9]').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, 'blocks[0].children[1].then[0]').uid).toBeNull()
    expect(resolveDiagnosticPath(tree, "groups['prep'].body[0]").uid).toBeNull()
  })
})

describe('mapDiagnostics', () => {
  it('attaches uids and groups by block', () => {
    const mapped = mapDiagnostics(tree, [
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
})
