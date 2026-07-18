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

export function blockSummary(node: BlockNode): string {
  const marker = faultMarker(node)
  switch (node.kind) {
    case 'command': {
      const params = formatParams(node.params)
      return `${node.device} · ${node.verb}${params ? ` (${params})` : ''}${marker}`
    }
    case 'measure':
      return `${node.device} · ${node.verb} → ${node.into || '?'}${marker}`
    case 'wait':
      return `wait ${node.duration}${marker}`
    case 'operator_input':
      return `input ${node.name} (${node.inputType})${marker}`
    case 'serial':
      return `Serial · ${node.children.length}${marker}`
    case 'parallel':
      return `Parallel · ${node.children.length} lanes${marker}`
    case 'loop':
      return (
        (node.mode === 'count' ? `Loop ×${node.count}` : `Loop until ${node.until || '…'}`) + marker
      )
    case 'branch':
      return `If ${node.condition || '…'}${marker}`
    case 'compute':
      return `${node.into || '?'} = ${String(node.value) || '…'}${marker}`
    case 'record':
      return `${node.into || '?'} ← ${String(node.value) || '…'}${marker}`
    case 'abort':
      return `Abort if ${node.condition || '…'}${marker}`
    case 'alarm':
      return `Alarm if ${node.condition || '…'}${marker}`
    case 'for_each':
      return (
        (node.var !== null
          ? `For each ${node.var} in [${node.items.join(', ')}]`
          : `For each of ${node.items.length} items`) + marker
      )
    case 'group_ref': {
      const args = formatParams(node.args)
      return `${node.name || '?'}${args ? `(${args})` : ''}${marker}`
    }
  }
}
