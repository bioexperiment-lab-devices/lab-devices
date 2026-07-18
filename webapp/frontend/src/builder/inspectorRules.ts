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

/** The tail sections' membership (design 2026-07-18 §3.3). An EMPTY array means the section
 * is not rendered at all — that is how `for_each` ends up with no tail and `abort` with no
 * "On failure", which states each engine rule better than a disabled control would. */
export type TimingField = 'gapAfter' | 'startOffset'
export type FailureField = 'onError' | 'retry'

export function timingFields(
  kind: BlockNode['kind'],
  parentKind: BlockNode['kind'] | null,
): TimingField[] {
  const fields: TimingField[] = []
  if (gapAfterEligible(kind, parentKind)) fields.push('gapAfter')
  // start_offset positions a lane against the parallel's own start, so it is meaningful
  // only for a direct child of a parallel — and never for a for_each, which is spliced
  // away before there is a runtime block to offset (expand.py:26).
  if (kind !== 'for_each' && parentKind === 'parallel') fields.push('startOffset')
  return fields
}

/** A Record, not a set membership check: a fifteenth kind is then a COMPILE error until it
 * declares its failure policy. W12 proved the difference — a hand-maintained array of kinds
 * silently defaults a new kind to the wrong bucket and the test still passes. */
const FAILURE_POLICY: Record<BlockNode['kind'], FailureField[]> = {
  command: ['onError', 'retry'],
  measure: ['onError', 'retry'],
  operator_input: ['onError'],
  wait: ['onError'],
  serial: ['onError'],
  parallel: ['onError'],
  loop: ['onError'],
  branch: ['onError'],
  compute: ['onError'],
  record: ['onError'],
  alarm: ['onError'],
  group_ref: ['onError'],
  abort: [],
  for_each: [],
}

export function failureFields(kind: BlockNode['kind']): FailureField[] {
  return FAILURE_POLICY[kind]
}

/** Collapsed-header summary (design §4). Returning `null` for "all defaults" means the
 * caller's open-by-default test is exactly `summary !== null`, so the disclosure state and
 * the text describing it are derived from one expression and cannot drift apart.
 *
 * Each summary filters through its own membership function, so it can only ever mention a
 * control the section actually renders. */
export function timingSummary(
  node: BlockNode,
  parentKind: BlockNode['kind'] | null,
): string | null {
  const fields = timingFields(node.kind, parentKind)
  const parts: string[] = []
  if (fields.includes('gapAfter') && node.gapAfter !== null) parts.push(`gap after ${node.gapAfter}`)
  if (fields.includes('startOffset') && node.startOffset !== null) {
    parts.push(`start +${node.startOffset}`)
  }
  return parts.length > 0 ? parts.join(', ') : null
}

export function failureSummary(node: BlockNode): string | null {
  const fields = failureFields(node.kind)
  const parts: string[] = []
  // 'fail' is the engine default, so only 'continue' is worth surfacing.
  if (fields.includes('onError') && node.onError === 'continue') parts.push('continue')
  if (fields.includes('retry') && node.retry !== undefined) {
    parts.push(`retry ×${node.retry.attempts}`)
  }
  return parts.length > 0 ? parts.join(', ') : null
}
