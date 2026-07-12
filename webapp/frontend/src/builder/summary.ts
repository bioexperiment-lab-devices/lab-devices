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

export function blockSummary(node: BlockNode): string {
  switch (node.kind) {
    case 'command': {
      const params = formatParams(node.params)
      return `▸ ${node.device} · ${node.verb}${params ? ` (${params})` : ''}`
    }
    case 'measure':
      return `◉ ${node.device} · ${node.verb} → ${node.into || '?'}`
    case 'wait':
      return `⏱ wait ${node.duration}`
    case 'operator_input':
      return `⌨ input ${node.name} (${node.inputType})`
    case 'serial':
      return `≡ Serial · ${node.children.length}`
    case 'parallel':
      return `∥ Parallel · ${node.children.length} lanes`
    case 'loop':
      return node.mode === 'count' ? `↻ Loop ×${node.count}` : `↻ Loop until ${node.until || '…'}`
    case 'branch':
      return `⑂ If ${node.condition || '…'}`
  }
}
