/** Human-readable name for a run-log event's block: the user's label if set, else the derived
 * blockSummary, resolved from the event's authored source_path (engine source map) against the
 * authored doc tree. Falls back to the raw structural path so a line never loses its block id. */
import { resolveDiagnosticNode, type GroupsMap } from '../builder/paths'
import { blockSummary } from '../builder/summary'
import type { BlockNode } from '../builder/tree'

export interface NamedBlock {
  text: string
  path: string | null
}

export function blockName(
  event: { block_id: string | null; source_path?: string | null },
  tree: BlockNode[] | null,
  groups: GroupsMap | null,
): NamedBlock | null {
  const path = event.source_path ?? event.block_id
  if (path === null || path === undefined) return null
  if (tree !== null && groups !== null) {
    const node = resolveDiagnosticNode(tree, groups, path)
    if (node !== null) return { text: node.label?.trim() ? node.label : blockSummary(node), path }
  }
  return { text: path, path }
}
