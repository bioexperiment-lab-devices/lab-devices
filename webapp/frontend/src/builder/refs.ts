/** Role/stream reference bookkeeping for the cascades in webapp design §4.2:
 * renaming rewrites referencing blocks; deleting is refused while references exist. */
import { childSlots, replaceSlot, visitNodes, type BlockNode } from './tree'

/** Preserves array identity when `fn` touches nothing in `tree` (recursively): a no-op rename
 * must return the SAME array reference it was given, not a structurally-equal new one.
 * `Array.prototype.map` always allocates, so a naive rewrite makes every rename "change" `tree`
 * even when it has zero matching refs — and `followUndoScope` (docStore.ts) relies on `tree`'s
 * reference staying stable across a no-op to find which scope an undo/redo actually touched. */
function mapNodes(tree: BlockNode[], fn: (node: BlockNode) => BlockNode): BlockNode[] {
  let changed = false
  const next = tree.map((node) => {
    let out = fn(node)
    if (out !== node) changed = true
    for (const [slot, children] of childSlots(out)) {
      const mapped = mapNodes(children, fn)
      if (mapped !== children) {
        out = replaceSlot(out, slot, mapped)
        changed = true
      }
    }
    return out
  })
  return changed ? next : tree
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

/** Counts `group_ref` blocks citing `name` within ONE tree — a group can `group_ref` another
 * group (design §5.2), so a caller checking whether a group is safe to delete must sum this
 * across the main tree AND every group body, not just the main tree. */
export function countGroupRefs(tree: BlockNode[], name: string): number {
  let count = 0
  visitNodes(tree, (node) => {
    if (node.kind === 'group_ref' && node.name === name) count++
  })
  return count
}

/** Renaming a group must cascade to every `group_ref` that cites it — left un-cascaded, a
 * rename produces the exact class of dangling reference this design closes elsewhere
 * (expand.py:231 `group_ref 'x': unknown group`), just triggered by a rename instead of a
 * dropped save. The caller applies this to the main tree and to every group body. */
export function renameGroupRefs(tree: BlockNode[], from: string, to: string): BlockNode[] {
  return mapNodes(tree, (node) =>
    node.kind === 'group_ref' && node.name === from ? { ...node, name: to } : node,
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

/** Which block kind writes each stream. The engine enforces measure XOR record per stream
 * (Increment 6), so a stream has at most one writer kind; on a doc that violates it, first
 * writer seen wins and the backend validator reports the real error. */
export function streamSources(tree: BlockNode[]): Record<string, 'measure' | 'record'> {
  const out: Record<string, 'measure' | 'record'> = {}
  visitNodes(tree, (node) => {
    if ((node.kind === 'measure' || node.kind === 'record') && node.into && !(node.into in out)) {
      out[node.into] = node.kind
    }
  })
  return out
}
