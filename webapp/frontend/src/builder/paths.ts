/** Resolve backend diagnostic paths (engine structural grammar + studio doc-level
 * grammar) onto editor tree uids. Unresolvable paths map to uid null and surface in the
 * problems panel only.
 *
 * Path grammar (validate.py, roles.py, docs_store.py):
 *  - `blocks[i]` + trailer                — the main tree, scope null.
 *  - `groups['name'].body[i]` + trailer   — a group's own body, DIRECT (validate.py:63-64
 *    `_iter_all_blocks`, roles.py:71). The quote can be `'name'` or `"name"`: both are built
 *    with `f"groups[{name!r}].body"`, and Python's `repr()` flips to double quotes when
 *    `name` contains an apostrophe.
 *  - `blocks[i]...->name.body[i]` + trailer, possibly repeated `->name2.body[i]...` — a
 *    COMPOUND path, produced when a validate-phase walk crosses from a group_ref call site
 *    into a PLAIN (non-parametrized) group's body (validate.py:894, :940, both
 *    `f"{path}->{b.name}.body"`). Here the group name is spelled BARE, never
 *    `groups[...]`-wrapped (docs_store.py's `_remap_group_segment` preserves that spelling
 *    while still remapping the trailing indices). The call-site prefix before the FIRST
 *    `->` is context, not the edit target — the authored, editable location is inside the
 *    INNERMOST (last) segment's group, so that is the segment this file resolves against.
 *  - trailer: zero or more `.children[i]` / `.body[i]` / `.then[i]` / `.else[i]` hops,
 *    walked via `childSlots` (Task 3 taught it about for_each's `body`).
 *  - any of the above may carry a trailing context suffix the validator appends after the
 *    path's first space (" branch if", " compute value", " param 'x'", ... — serialize.py,
 *    validate.py's `_expr_reads`/`_check_condition`/`_check_param_value`). docs_store.py's
 *    `_remap` splits on the FIRST space only ("no structural token contains a space"), so
 *    splitting there is exact, not a heuristic. Only `param 'x'` is parsed further, since
 *    `MappedDiagnostic.param` is consumed by the Inspector; every other suffix is discarded
 *    once the structural prefix is recovered.
 */
import type { Diagnostic } from '../types/doc'
import { childSlots, type BlockNode } from './tree'

export type GroupsMap = Record<string, { params: string[]; body: BlockNode[] }>

export interface ResolvedPath {
  uid: string | null
  role: string | null
  param: string | null
  scope: string | null
}

export interface MappedDiagnostic extends Diagnostic {
  uid: string | null
  role: string | null
  param: string | null
  scope: string | null
}

const NONE: ResolvedPath = { uid: null, role: null, param: null, scope: null }

// A trailer is zero or more `.slot[i]` hops below the head token.
const TRAILER = String.raw`(?:\.(?:children|body|then|else)\[\d+\])*`
const BLOCKS_RE = new RegExp(`^blocks(\\[\\d+\\]${TRAILER})$`)
// Direct group-scope head (point 1 above): quote-tolerant per the `!r` caveat.
const GROUP_HEAD_RE = new RegExp(`^groups\\[(?:'([^']*)'|"([^"]*)")\\]\\.body(\\[\\d+\\]${TRAILER})$`)
// One bare `->name.body[i]...` compound segment (point 3 above) — no quoting: the engine
// interpolates `b.name` directly (validate.py:894/:940), never through `repr`.
const GROUP_SEGMENT_RE = new RegExp(`^([A-Za-z_][A-Za-z0-9_]*)\\.body(\\[\\d+\\]${TRAILER})$`)
const TOKEN_RE = /\[\d+\]|\.(?:children|body|then|else)\[\d+\]/g

/** Walks a `[i](.slot[i])*` index chain against `root` via `childSlots` for every hop past
 * the first. `tail` is always pre-validated against one of the RE's above (each fully
 * anchored `^...$`), so tokenizing it here cannot leave a gap. Any out-of-range index
 * returns null rather than the wrong block — resolving onto the wrong block is worse than
 * not resolving; that is the whole reason the source map exists. */
function resolveTail(root: BlockNode[] | null, tail: string): BlockNode | null {
  let node: BlockNode | null = null
  let list = root
  for (const token of tail.match(TOKEN_RE) ?? []) {
    const bracket = token.indexOf('[')
    if (token.startsWith('.')) {
      const slot = token.slice(1, bracket)
      list = node ? (childSlots(node).find(([name]) => name === slot)?.[1] ?? null) : null
    }
    const index = Number(token.slice(bracket + 1, -1))
    if (!list || index < 0 || index >= list.length) return null
    node = list[index]
  }
  return node
}

export function resolveDiagnosticPath(tree: BlockNode[], groups: GroupsMap, path: string): ResolvedPath {
  const roleMatch = /^roles\['(.+)'\]$/.exec(path)
  if (roleMatch) return { ...NONE, role: roleMatch[1] }

  const spaceIndex = path.indexOf(' ')
  const structural = spaceIndex === -1 ? path : path.slice(0, spaceIndex)
  const suffix = spaceIndex === -1 ? '' : path.slice(spaceIndex + 1)
  const paramMatch = /^param '([^']+)'$/.exec(suffix)
  const param = paramMatch ? paramMatch[1] : null

  // Compound: only the INNERMOST (last) `->` segment is the edit target — everything
  // before it is call-site context (see file header, point 3).
  const arrowIndex = structural.lastIndexOf('->')
  if (arrowIndex !== -1) {
    const segMatch = GROUP_SEGMENT_RE.exec(structural.slice(arrowIndex + 2))
    if (!segMatch) return { ...NONE, param }
    const [, name, tail] = segMatch
    const node = resolveTail(groups[name]?.body ?? null, tail)
    return node ? { uid: node.uid, role: null, param, scope: name } : { ...NONE, param }
  }

  const groupHeadMatch = GROUP_HEAD_RE.exec(structural)
  if (groupHeadMatch) {
    const name = groupHeadMatch[1] ?? groupHeadMatch[2]
    const node = resolveTail(groups[name]?.body ?? null, groupHeadMatch[3])
    return node ? { uid: node.uid, role: null, param, scope: name } : { ...NONE, param }
  }

  const blocksMatch = BLOCKS_RE.exec(structural)
  if (!blocksMatch) return { ...NONE, param }
  const node = resolveTail(tree, blocksMatch[1])
  return { uid: node?.uid ?? null, role: null, param, scope: null }
}

export function mapDiagnostics(
  tree: BlockNode[],
  groups: GroupsMap,
  diags: Diagnostic[],
): MappedDiagnostic[] {
  return diags.map((d) => ({ ...d, ...resolveDiagnosticPath(tree, groups, d.path) }))
}

export function diagnosticsByUid(diags: MappedDiagnostic[]): Map<string, MappedDiagnostic[]> {
  const out = new Map<string, MappedDiagnostic[]>()
  for (const d of diags) {
    if (!d.uid) continue
    const list = out.get(d.uid) ?? []
    list.push(d)
    out.set(d.uid, list)
  }
  return out
}
