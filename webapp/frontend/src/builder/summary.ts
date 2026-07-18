/** One-line captions for canvas cards and the drag overlay. Pure so it is testable and
 * reusable by the record viewer's read-only canvas in W5. The block-kind glyph is no longer
 * baked into the string — `KindIcon` (../ui/icons) renders it beside this text on cards, chips
 * and snapshots, so the same kind always wears the same mark (W10 de-glyph). */
import type { ParamValue } from '../types/doc'
import type { BlockNode } from './tree'

export function formatParams(params: Record<string, ParamValue>, max = 2): string {
  const entries = Object.entries(params)
  const shown = entries.slice(0, max).map(([k, v]) => `${k}=${String(v)}`)
  if (entries.length > max) shown.push('…')
  return shown.join(', ')
}

/** Compact fault-tolerance marker so retry/on_error are not invisible in the tree:
 * `R×<attempts>` when a retry policy is set, `⤳` when on_error is 'continue'. Empty
 * (no leading space) when neither is set.
 *
 * `R×N` (not a circular-arrow glyph) is deliberate: the Loop card already renders a Repeat
 * icon (see KindIcon, ../ui/icons), so a looping block with retry previously rendered as
 * `↻ Loop ×3 ↻2` — two near-identical arrows next to each other, unreadable at a glance
 * (2026-07-14 review, Fix 5). `R×N` cannot collide with the Repeat icon. */
export function faultMarker(node: BlockNode): string {
  const parts: string[] = []
  if (node.retry) parts.push(`R×${node.retry.attempts}`)
  if (node.onError === 'continue') parts.push('⤳')
  return parts.length > 0 ? ` ${parts.join(' ')}` : ''
}

/** A run of summary text tagged by what it is, so the canvas can give the three facts on a
 * card different weights instead of rendering `pump1 · dispense (volume=5)` as one
 * undifferentiated slate run (design §3.4).
 *
 * `subject` is the actor (a device role, or the target of a compute/record); `verb` is what
 * happens; `detail` is everything else including separators; `marker` is the fault-tolerance
 * suffix. Separators live in `detail` segments so the join reproduces the legacy string
 * byte-for-byte — `blockSummary` is that join, so there is exactly one source of truth. */
export type SummarySegment = {
  text: string
  role: 'subject' | 'verb' | 'detail' | 'marker'
}

const seg = (text: string, role: SummarySegment['role']): SummarySegment => ({ text, role })

/** Segments whose concatenation IS `blockSummary(node)`. Pinned by test. */
export function blockSummaryParts(node: BlockNode): SummarySegment[] {
  const marker = faultMarker(node)
  const tail: SummarySegment[] = marker ? [seg(marker, 'marker')] : []
  const parts = (): SummarySegment[] => {
    switch (node.kind) {
      case 'command': {
        const params = formatParams(node.params)
        return [
          seg(node.device, 'subject'),
          seg(' · ', 'detail'),
          seg(node.verb, 'verb'),
          ...(params ? [seg(` (${params})`, 'detail')] : []),
        ]
      }
      case 'measure':
        return [
          seg(node.device, 'subject'),
          seg(' · ', 'detail'),
          seg(node.verb, 'verb'),
          seg(` → ${node.into || '?'}`, 'detail'),
        ]
      case 'wait':
        return [seg('wait', 'verb'), seg(` ${node.duration}`, 'detail')]
      case 'operator_input':
        return [
          seg('input', 'verb'),
          seg(' ', 'detail'),
          seg(node.name, 'subject'),
          seg(` (${node.inputType})`, 'detail'),
        ]
      case 'serial':
        return [seg('Serial', 'verb'), seg(` · ${node.children.length}`, 'detail')]
      case 'parallel':
        return [seg('Parallel', 'verb'), seg(` · ${node.children.length} lanes`, 'detail')]
      case 'loop':
        return node.mode === 'count'
          ? [seg('Loop', 'verb'), seg(` ×${node.count}`, 'detail')]
          : [seg('Loop until', 'verb'), seg(` ${node.until || '…'}`, 'detail')]
      case 'branch':
        return [seg('If', 'verb'), seg(` ${node.condition || '…'}`, 'detail')]
      case 'compute':
        return [
          seg(node.into || '?', 'subject'),
          seg(` = ${String(node.value) || '…'}`, 'detail'),
        ]
      case 'record':
        return [
          seg(node.into || '?', 'subject'),
          seg(` ← ${String(node.value) || '…'}`, 'detail'),
        ]
      case 'abort':
        return [seg('Abort if', 'verb'), seg(` ${node.condition || '…'}`, 'detail')]
      case 'alarm':
        return [seg('Alarm if', 'verb'), seg(` ${node.condition || '…'}`, 'detail')]
      case 'for_each':
        return node.var !== null
          ? [
              seg('For each', 'verb'),
              seg(' ', 'detail'),
              seg(node.var, 'subject'),
              seg(` in [${node.items.join(', ')}]`, 'detail'),
            ]
          : [seg('For each', 'verb'), seg(` of ${node.items.length} items`, 'detail')]
      case 'group_ref': {
        const args = formatParams(node.args)
        return [
          seg(node.name || '?', 'subject'),
          ...(args ? [seg(`(${args})`, 'detail')] : []),
        ]
      }
    }
  }
  return [...parts(), ...tail]
}

export function blockSummary(node: BlockNode): string {
  return blockSummaryParts(node)
    .map((s) => s.text)
    .join('')
}
