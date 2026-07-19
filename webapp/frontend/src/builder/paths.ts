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
 *    splitting there is exact, not a heuristic — EXCEPT that a quoted `groups['name'].body`
 *    head (point 2) is not "no structural token", and Python's `!r` places no restriction on
 *    what `name` may contain: a group named with a literal space or `->` is real, reachable
 *    state via Import (docStore.ts's `GROUP_NAME_RE` is enforced only on add/rename, not on
 *    load). The first-space/last-arrow scans below must therefore treat a quoted head as
 *    opaque, or a name like `'a b'`/`'a->b'` gets misread as carrying a suffix/compound it
 *    does not have. Only `param 'x'`/`param "x"` is parsed further, since `MappedDiagnostic.
 *    param` is consumed by the Inspector; every other suffix is discarded once the structural
 *    prefix is recovered.
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
const ROLE_RE = /^roles\[(?:'([^']*)'|"([^"]*)")\]$/
const PARAM_RE = /^param (?:'([^']+)'|"([^"]+)")$/

/** If `path` opens with a quoted `groups['name']`/`groups["name"]` head, returns the index
 * just past the closing quote — the point after which the space/arrow scans below may safely
 * resume. A quoted group name carries no identifier restriction (Python's `repr`, like Studio's
 * import path, allows a space or `->` in it — Finding 1 review), so those scans must not
 * mistake a character INSIDE the quotes for the suffix/compound boundary they are looking for.
 * Returns 0 for every other path form, which then scans from the very start exactly as before. */
function quotedGroupHeadEnd(path: string): number {
  const open = /^groups\[(['"])/.exec(path)
  if (!open) return 0
  const close = path.indexOf(open[1], open[0].length)
  return close === -1 ? 0 : close + 1
}

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
  const roleMatch = ROLE_RE.exec(path)
  if (roleMatch) return { ...NONE, role: roleMatch[1] ?? roleMatch[2] }

  // A quoted `groups[...]` head, if present, is opaque up to `headEnd` — the space/arrow
  // scans below must not resume inside it (Finding 1: an unescaped space or `->` in the
  // group name would otherwise be mistaken for the suffix/compound boundary).
  const headEnd = quotedGroupHeadEnd(path)
  const spaceIndex = path.indexOf(' ', headEnd)
  const structural = spaceIndex === -1 ? path : path.slice(0, spaceIndex)
  const suffix = spaceIndex === -1 ? '' : path.slice(spaceIndex + 1)
  const paramMatch = PARAM_RE.exec(suffix)
  const param = paramMatch ? (paramMatch[1] ?? paramMatch[2]) : null

  // Compound: only the INNERMOST (last) `->` segment is the edit target — everything
  // before it is call-site context (see file header, point 3). Skip the same opaque
  // `headEnd` prefix here too, so an arrow inside a quoted group name is never mistaken
  // for one. A quoted `groups[...]` head and a compound path are NOT mutually exclusive:
  // docs_store.py's `_remap_group_segment` preserves a quoted head that is itself a
  // call site into a plain group (test_docs_store.py's parametrized-group regression
  // guard), so this file must resolve that combination too — see the test below.
  const arrowTail = structural.slice(headEnd).lastIndexOf('->')
  const arrowIndex = arrowTail === -1 ? -1 : arrowTail + headEnd
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

/** Spells a group name as a quoted `groups[...]` head the reader above can read back, the
 * way Python's `repr()` would: single quotes normally, flipping to double quotes when the
 * name contains an apostrophe (docs_store.py builds every direct head with `{name!r}`, and
 * GROUP_HEAD_RE is quote-tolerant for exactly that reason).
 *
 * Returns null when the name contains BOTH quote characters. `repr()` would fall back to
 * single quotes with a backslash-escaped apostrophe, but GROUP_HEAD_RE's character classes
 * (`'[^']*'` / `"[^"]*"`) have no escape handling, so neither spelling survives the round
 * trip — and quotedGroupHeadEnd would end the opaque head early, letting a later space or
 * `->` inside the name be misread as a suffix/compound boundary. Emitting nothing is the
 * honest answer: a caller that gets null falls back to no selection, whereas a caller that
 * gets an unparseable path would select the wrong node.
 */
function quoteGroupName(name: string): string | null {
  if (!name.includes("'")) return `'${name}'`
  if (!name.includes('"')) return `"${name}"`
  return null
}

/** Depth-first search for `uid`, building the structural path as it descends. */
function findPath(list: BlockNode[], uid: string, prefix: string): string | null {
  for (let i = 0; i < list.length; i++) {
    const node = list[i]
    const here = `${prefix}[${i}]`
    if (node.uid === uid) return here
    for (const [slot, children] of childSlots(node)) {
      const found = findPath(children, uid, `${here}.${slot}`)
      if (found !== null) return found
    }
  }
  return null
}

/** The inverse of resolveDiagnosticPath: the structural path addressing a node (design §4.1),
 * so a selected block can be named in a URL by a STABLE structural location rather than by a
 * uid, which `newUid()` re-mints on every `docToTree` (convert.ts) and which therefore means
 * nothing to anyone but the author who produced it.
 *
 * Emits only the two forms the BUILDER can originate — `blocks[i]` + trailer, and
 * `groups['name'].body[i]` + trailer. It never emits the compound `blocks[i]->name.body[i]`
 * form: that is produced by a validator walk crossing from a call site into a plain group's
 * body (validate.py:894,940) and describes a group RENDERED at a call site, not an authored
 * location. Selection always refers to an authored node, so the compound form has no writer;
 * resolveDiagnosticPath keeps READING it for diagnostics.
 *
 * Descends via childSlots (tree.ts) rather than a local slot list, for the same reason the
 * torture walker does: a hand-listed set silently stops descending the day a new container
 * kind lands.
 */
export function pathForUid(tree: BlockNode[], groups: GroupsMap, uid: string): string | null {
  const inMain = findPath(tree, uid, 'blocks')
  if (inMain !== null) return inMain
  for (const [name, group] of Object.entries(groups)) {
    const quoted = quoteGroupName(name)
    if (quoted === null) continue
    const inGroup = findPath(group.body, uid, `groups[${quoted}].body`)
    if (inGroup !== null) return inGroup
  }
  return null
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
