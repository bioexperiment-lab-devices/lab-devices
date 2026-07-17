import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { docToTree } from '../convert'
import { childSlots } from '../tree'
import type { BlockNode } from '../tree'
import type { ExperimentDocJson } from '../../types/doc'

const FIXTURE = fileURLToPath(
  new URL('../../../../fixtures/ui-audit-torture.json', import.meta.url),
)

/** Every BlockNode kind in tree.ts:26-117. The audit's Inspector matrix is one state per
 * entry (design §7), so a fixture missing a kind silently shrinks the audit. */
const ALL_KINDS = [
  'command', 'measure', 'operator_input', 'wait', 'serial', 'parallel', 'loop',
  'branch', 'for_each', 'group_ref', 'compute', 'record', 'abort', 'alarm',
] as const

/** Walks via the app's own `childSlots` (tree.ts:157) rather than a hand-listed slot set.
 * A local list of ['children','body','then','else'] would silently stop descending the day a
 * new container kind lands — and a walker that quietly visits less is exactly how a fixture
 * "covers all 14 kinds" while covering twelve. */
function collectKinds(nodes: BlockNode[], acc: Set<string>): Set<string> {
  for (const n of nodes) {
    acc.add(n.kind)
    for (const [, slot] of childSlots(n)) collectKinds(slot, acc)
  }
  return acc
}

describe('ui-audit torture fixture', () => {
  const doc = JSON.parse(readFileSync(FIXTURE, 'utf8')) as ExperimentDocJson

  it('converts without throwing — the audit is blind if it does not', () => {
    expect(() => docToTree(doc)).not.toThrow()
  })

  it('covers all 14 block kinds across main + groups', () => {
    const content = docToTree(doc)
    const seen = collectKinds(content.tree, new Set<string>())
    // `groups` is OPTIONAL on DocContent (convert.ts:55) even though docToTree always
    // populates it — the `?? {}` is required under strict mode, not defensive noise.
    for (const g of Object.values(content.groups ?? {})) collectKinds(g.body, seen)
    expect([...ALL_KINDS].filter((k) => !seen.has(k))).toEqual([])
  })

  it('carries every catalog verb so every generated param form is photographed', () => {
    const content = docToTree(doc)
    const verbs = new Set<string>()
    const walk = (nodes: BlockNode[]) => {
      for (const n of nodes) {
        if (n.kind === 'command' || n.kind === 'measure') verbs.add(`${n.device}.${n.verb}`)
        for (const [, slot] of childSlots(n)) walk(slot)
      }
    }
    walk(content.tree)
    for (const g of Object.values(content.groups ?? {})) walk(g.body)
    expect(verbs.size).toBeGreaterThanOrEqual(16)
  })

  it('plants the boundary cases the probe exists to catch', () => {
    const content = docToTree(doc)
    const groups = content.groups ?? {}
    expect(Object.keys(content.streams).length).toBeGreaterThanOrEqual(30)
    expect(Object.keys(content.roles).length).toBeGreaterThanOrEqual(15)
    expect(Object.keys(groups).length).toBeGreaterThanOrEqual(5)
    // The W9 compound-path trap: repr() puts no restriction on group names and import never
    // enforces one (GROUP_NAME_RE guards only addGroup/renameGroup).
    expect(Object.keys(groups).some((n) => n.includes(' '))).toBe(true)
  })
})
