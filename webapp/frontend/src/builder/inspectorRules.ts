import type { BlockNode } from './tree'

/** Where the "Gap after" row shows (audit F5). The engine honors gap_after through the
 * one shared runner (execute.py:451) for serial, loop body, branch arms, group bodies —
 * and for for_each BODY children, whose keys survive splicing (expand.py:195; the
 * engine's own error for gap_after on the for_each block says "put it on the body
 * blocks"). It is meaningless only on a parallel child (no next-in-list), and rejected
 * on the for_each block itself (validate.py:117-120). */
export function gapAfterEligible(
  kind: BlockNode['kind'],
  parentKind: BlockNode['kind'] | null,
): boolean {
  return kind !== 'for_each' && parentKind !== 'parallel'
}
