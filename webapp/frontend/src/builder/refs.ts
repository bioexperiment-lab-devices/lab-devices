/** Role/stream reference bookkeeping for the cascades in webapp design §4.2:
 * renaming rewrites referencing blocks; deleting is refused while references exist. */
import { childSlots, replaceSlot, visitNodes, type BlockNode } from './tree'

function mapNodes(tree: BlockNode[], fn: (node: BlockNode) => BlockNode): BlockNode[] {
  return tree.map((node) => {
    let out = fn(node)
    for (const [slot, children] of childSlots(out)) {
      out = replaceSlot(out, slot, mapNodes(children, fn))
    }
    return out
  })
}

export function countRoleRefs(tree: BlockNode[], role: string): number {
  let count = 0
  visitNodes(tree, (node) => {
    if ((node.kind === 'command' || node.kind === 'measure') && node.device === role) count++
  })
  return count
}

export function renameRoleRefs(tree: BlockNode[], from: string, to: string): BlockNode[] {
  return mapNodes(tree, (node) =>
    (node.kind === 'command' || node.kind === 'measure') && node.device === from
      ? { ...node, device: to }
      : node,
  )
}

export function countStreamRefs(tree: BlockNode[], stream: string): number {
  let count = 0
  visitNodes(tree, (node) => {
    if (node.kind === 'measure' && node.into === stream) count++
  })
  return count
}

export function renameStreamRefs(tree: BlockNode[], from: string, to: string): BlockNode[] {
  return mapNodes(tree, (node) =>
    node.kind === 'measure' && node.into === from ? { ...node, into: to } : node,
  )
}

export function collectBindings(tree: BlockNode[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  visitNodes(tree, (node) => {
    if (node.kind === 'operator_input' && node.name && !seen.has(node.name)) {
      seen.add(node.name)
      out.push(node.name)
    }
  })
  return out
}
