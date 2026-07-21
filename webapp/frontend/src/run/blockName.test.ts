/** blockName resolves a run-log event's authored source_path against the doc tree, preferring
 * the user's label, then the derived blockSummary, then the raw path — never blank (task-5
 * brief). The doc literal mirrors the shape pinned in builder/convert.test.ts /
 * builder/summary.test.ts: doc_version 1, workflow.schema_version 3, one type-key per block. */
import { describe, expect, it } from 'vitest'
import { blockName } from './blockName'
import { docToTree } from '../builder/convert'
import type { GroupsMap } from '../builder/paths'
import type { BlockNode } from '../builder/tree'
import type { ExperimentDocJson } from '../types/doc'

// blocks[0]: a command WITH a label (label must win over its summary).
// blocks[1]: a wait with no label (must fall back to its derived summary).
// blocks[2]: a for_each whose body[0] is an authored command block (proves the resolver
// descends into a child slot, not just top-level blocks[i]).
const doc: ExperimentDocJson = {
  doc_version: 1,
  name: 'block name test',
  description: null,
  workflow: {
    schema_version: 3,
    metadata: { name: 'block name test' },
    persistence: { default: 'in_memory', format: 'jsonl' },
    roles: { pump1: { type: 'pump' } },
    streams: {},
    blocks: [
      { command: { device: 'pump1', verb: 'dispense', params: { volume: 5 } }, label: 'drug pulse' },
      { wait: { duration: '30s' } },
      {
        for_each: {
          vars: [{ name: 'tube', kind: 'int' }],
          in: [{ tube: 1 }, { tube: 2 }],
          body: [{ command: { device: 'pump1', verb: 'dispense', params: { volume: 1 } } }],
        },
      },
    ],
  },
}

/** docToTree types `groups` as optional (DocContent callers may predate the field), even
 * though it always populates it in practice — coerce to the non-optional GroupsMap blockName
 * expects, the same way docStore.ts's normalizer does (`content.groups ?? {}`). */
function resolve(d: ExperimentDocJson): { tree: BlockNode[]; groups: GroupsMap } {
  const content = docToTree(d)
  return { tree: content.tree, groups: content.groups ?? {} }
}

const ev = (source_path: string | null, block_id: string | null = source_path) => ({
  block_id,
  source_path,
})

describe('blockName', () => {
  it('prefers the user label when set', () => {
    const { tree, groups } = resolve(doc)
    expect(blockName(ev('blocks[0]'), tree, groups)).toEqual({ text: 'drug pulse', path: 'blocks[0]' })
  })

  it('falls back to the derived summary when there is no label', () => {
    const { tree, groups } = resolve(doc)
    expect(blockName(ev('blocks[1]'), tree, groups)).toEqual({ text: 'wait 30s', path: 'blocks[1]' })
  })

  it('resolves a for_each body block to its own summary', () => {
    const { tree, groups } = resolve(doc)
    expect(blockName(ev('blocks[2].body[0]'), tree, groups)).toEqual({
      text: 'pump1 · dispense (volume=1)',
      path: 'blocks[2].body[0]',
    })
  })

  it('returns the raw path when the path is unresolvable', () => {
    const { tree, groups } = resolve(doc)
    expect(blockName(ev('blocks[9]'), tree, groups)).toEqual({ text: 'blocks[9]', path: 'blocks[9]' })
  })

  it('uses block_id when source_path is absent', () => {
    const { tree, groups } = resolve(doc)
    expect(blockName(ev(null, 'blocks[0]'), tree, groups)).toEqual({ text: 'drug pulse', path: 'blocks[0]' })
  })

  it('returns null when there is no path at all', () => {
    const { tree, groups } = resolve(doc)
    expect(blockName(ev(null, null), tree, groups)).toBeNull()
  })

  it('returns the raw path when no tree is available', () => {
    expect(blockName(ev('blocks[0]'), null, null)).toEqual({ text: 'blocks[0]', path: 'blocks[0]' })
  })
})
