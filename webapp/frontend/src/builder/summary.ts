/** One-line captions for canvas cards and the drag overlay. Pure so it is testable and
 * reusable by the record viewer's read-only canvas in W5. */
import type { ParamValue } from '../types/doc'
import type { BlockNode } from './tree'

export function formatParams(params: Record<string, ParamValue>, max = 2): string {
  const entries = Object.entries(params)
  const shown = entries.slice(0, max).map(([k, v]) => `${k}=${String(v)}`)
  if (entries.length > max) shown.push('…')
  return shown.join(', ')
}

/** Compact fault-tolerance marker so retry/on_error are not invisible in the tree:
 * `↻<attempts>` when a retry policy is set, `⤳` when on_error is 'continue'. Empty
 * (no leading space) when neither is set. */
export function faultMarker(node: BlockNode): string {
  const parts: string[] = []
  if (node.retry) parts.push(`↻${node.retry.attempts}`)
  if (node.onError === 'continue') parts.push('⤳')
  return parts.length > 0 ? ` ${parts.join(' ')}` : ''
}

export function blockSummary(node: BlockNode): string {
  const marker = faultMarker(node)
  switch (node.kind) {
    case 'command': {
      const params = formatParams(node.params)
      return `▸ ${node.device} · ${node.verb}${params ? ` (${params})` : ''}${marker}`
    }
    case 'measure':
      return `◉ ${node.device} · ${node.verb} → ${node.into || '?'}${marker}`
    case 'wait':
      return `⏱ wait ${node.duration}${marker}`
    case 'operator_input':
      return `⌨ input ${node.name} (${node.inputType})${marker}`
    case 'serial':
      return `≡ Serial · ${node.children.length}${marker}`
    case 'parallel':
      return `∥ Parallel · ${node.children.length} lanes${marker}`
    case 'loop':
      return (
        (node.mode === 'count' ? `↻ Loop ×${node.count}` : `↻ Loop until ${node.until || '…'}`) + marker
      )
    case 'branch':
      return `⑂ If ${node.condition || '…'}${marker}`
  }
}
