import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { docToTree } from '../convert'
import { childSlots } from '../tree'
import type { BlockKind, BlockNode } from '../tree'
import type { ExperimentDocJson } from '../../types/doc'

const FIXTURE = fileURLToPath(
  new URL('../../../../fixtures/ui-audit-torture.json', import.meta.url),
)

/** Every BlockNode kind in tree.ts:26-117. The audit's Inspector matrix is one state per
 * entry (design §7), so a fixture missing a kind silently shrinks the audit.
 *
 * Type-level exhaustiveness, not a hand-maintained count: `Record<BlockKind, true>` forces
 * this object literal to have exactly one key per member of BlockKind. Omitting a kind here
 * (or letting tree.ts add one nobody added here) is a compile error, not a silent gap — the
 * same failure mode the ALL_KINDS list itself would otherwise be. */
const ALL_KINDS_MAP: Record<BlockKind, true> = {
  command: true,
  measure: true,
  operator_input: true,
  wait: true,
  serial: true,
  parallel: true,
  loop: true,
  branch: true,
  for_each: true,
  group_ref: true,
  compute: true,
  record: true,
  abort: true,
  alarm: true,
}
const ALL_KINDS = Object.keys(ALL_KINDS_MAP) as BlockKind[]

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
    // `n.device` on a CommandNode/MeasureNode holds a ROLE name (e.g. `pump_01`), not a
    // device type — keying the set by role.verb double-counts every role that shares a
    // type (six pumps, five valves, three densitometers) and lets six deleted catalog
    // verbs hide behind six unrelated role.verb pairs from wide_parallel/deep_nest.
    // Resolving role -> content.roles[role].type collapses that padding, so the set is
    // exactly the catalog's type.verb pairs with zero slack.
    const verbs = new Set<string>()
    const walk = (nodes: BlockNode[]) => {
      for (const n of nodes) {
        if (n.kind === 'command' || n.kind === 'measure') {
          const type = content.roles[n.device]?.type
          verbs.add(`${type}.${n.verb}`)
        }
        for (const [, slot] of childSlots(n)) walk(slot)
      }
    }
    walk(content.tree)
    for (const g of Object.values(content.groups ?? {})) walk(g.body)
    // Exact set, not just a count: when this fails, the diff names which catalog verb
    // went missing instead of just reporting a number that no longer means 16.
    expect([...verbs].sort()).toEqual(
      [
        'pump.dispense', 'pump.rotate', 'pump.stop', 'pump.set_calibration',
        'valve.set_position', 'valve.home', 'valve.configure', 'valve.stop',
        'densitometer.measure', 'densitometer.measure_blank', 'densitometer.set_led',
        'densitometer.set_thermostat', 'densitometer.set_tube_correction',
        'densitometer.calibrate_tube', 'densitometer.stop', 'densitometer.stop_monitoring',
      ].sort(),
    )
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

  it('carries block labels as siblings of the type key, per convert.ts:65/109', () => {
    // The engine grammar is one type key per block PLUS sibling block-level keys (label,
    // gap_after, start_offset, retry, on_error) — never nested inside the body
    // (`BLOCK_KEYS`, convert.ts:65; the type-key filter, convert.ts:102). If the fixture
    // writes `label` inside the body instead, blockToNode's `label: block.label ?? null`
    // (convert.ts:109) reads it off the OUTER object and silently gets `null`: every label
    // in the fixture disappears with no error, no throw, nothing. That's exactly the
    // failure mode this test exists to catch — the other tests above (kinds, verbs, counts)
    // would all still pass on a fixture where every label was dropped.
    //
    // Walks via the app's own `childSlots` (tree.ts:157), same as `collectKinds` above — a
    // hand-listed slot set would silently stop descending the day a new container kind lands.
    const content = docToTree(doc)
    const labels = new Set<string>()
    const walk = (nodes: BlockNode[]) => {
      for (const n of nodes) {
        if (n.label !== null) labels.add(n.label)
        for (const [, slot] of childSlots(n)) walk(slot)
      }
    }
    walk(content.tree)
    for (const g of Object.values(content.groups ?? {})) walk(g.body)

    // LONG_LABEL_WAIT / LONG_LABEL_GROUP_WAIT (~130 chars each): the W7 truncate-without-title
    // class Canvas.tsx:199 renders (`<span className="truncate ...">` with no `title`
    // attribute) — the probe boundary this fixture exists to plant. If labels are dropped, no
    // label survives at all, let alone one this long. This check is deliberately generic (any
    // label >=120 chars) and is NOT a substitute for the named checks below — see why.
    expect([...labels].some((l) => l.length >= 120)).toBe(true)

    // The specific sites gen_torture.py plants a label at, named so each site is pinned
    // independently. Every one of these lives inside a body key in a naively-nested fixture
    // and would be absent from `labels` if so.
    //
    // The two long-label entries used to be a single shared LONG_LABEL string reused at both
    // gen_torture.py's top-level wait and long_label_group's wait. A reviewer
    // showed that made this test blind to re-nesting either site alone: with identical text at
    // both sites, the generic `length >= 120` check above is satisfied by whichever site
    // survives, and a named-list check can't pin LONG_LABEL by value because the two sites are
    // textually indistinguishable in the emitted JSON. gen_torture.py now emits two distinct
    // strings (LONG_LABEL_WAIT, LONG_LABEL_GROUP_WAIT) so each is named here and re-nesting
    // either site alone fails this exact assertion, naming that string.
    for (const expected of [
      'Every catalog verb',
      '8 lanes — S1 says parallelism is spatially visible',
      'lane 1',
      'lane 8',
      'Nested 8 deep',
      'Nested 4 deep',
      'Empty serial (bare drop slot)',
      'Empty loop body',
      // LONG_LABEL_WAIT — gen_torture.py's top-level wait, pushed as a bare block.
      'Label that keeps going Label that keeps going Label that keeps going Label that keeps ' +
        'going Label that keeps going Label that keeps going ',
      // LONG_LABEL_GROUP_WAIT — gen_torture.py's long_label_group, inside `groups`.
      "long_label_group's wait: a differently-worded label that is also long enough to " +
        "overflow Canvas.tsx's truncated span, on purpose",
    ]) {
      // Custom message so a failure names the missing label instead of just "false !== true" —
      // that's the whole point of pinning each site by name.
      expect(labels.has(expected), `missing expected label: ${JSON.stringify(expected)}`).toBe(
        true,
      )
    }
  })
})
