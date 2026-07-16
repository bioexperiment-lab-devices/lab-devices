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

/** A stream is written by `measure` XOR `record` (engine Increment 6). Both must count, or
 * deleting a record-only stream reports 0 refs and silently orphans the record block. */
export function countStreamRefs(tree: BlockNode[], stream: string): number {
  let count = 0
  visitNodes(tree, (node) => {
    if ((node.kind === 'measure' || node.kind === 'record') && node.into === stream) count++
  })
  return count
}

export function renameStreamRefs(tree: BlockNode[], from: string, to: string): BlockNode[] {
  return mapNodes(tree, (node) =>
    (node.kind === 'measure' || node.kind === 'record') && node.into === from
      ? { ...node, into: to }
      : node,
  )
}

/** Bindings are written by `operator_input` and by `compute` (engine blocks.py:96) — both
 * land in the same RunState.bindings namespace, so expression help must offer both. The
 * seed-then-accumulate idiom writes one name from several computes, hence the de-dup. */
export function collectBindings(tree: BlockNode[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  visitNodes(tree, (node) => {
    const name =
      node.kind === 'operator_input' ? node.name : node.kind === 'compute' ? node.into : null
    if (name && !seen.has(name)) {
      seen.add(name)
      out.push(name)
    }
  })
  return out
}
