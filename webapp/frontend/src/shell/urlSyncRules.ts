/** The decisions the URL <-> store binding makes, lifted out of `useUrlSync` so they can be
 * tested (design §3.1, §4).
 *
 * `useUrlSync` itself is unavoidably untestable here — vitest runs in the node environment
 * (webapp/frontend/CLAUDE.md), so there is no `window`, no `history`, and no way to mount a
 * hook. That is an argument for the hook holding *only* listener wiring and the feedback-loop
 * ref, and for every judgement it would otherwise make living here instead: the projection of
 * three stores onto a `UrlState`, which changes deserve a history entry, and what a URL that
 * names things the document no longer contains should resolve to. Each of those has a wrong
 * answer that looks right (a `sel` param reading `null`, a Back button that behaves like a
 * second undo stack, a selection silently pointing at a deleted block), and none of them
 * needs a browser to demonstrate.
 */
import { pathForUid, resolveDiagnosticPath, type GroupsMap } from '../builder/paths'
import type { BlockNode } from '../builder/tree'
import type { UrlState } from './bootstrap'
import type { Tab } from './tabs'

/** The slice of navStore + docStore + recordsStore that the URL is a projection of. A plain
 * value rather than the stores themselves, so the projection below is a pure function. */
export interface SyncView {
  tab: Tab
  serverId: string | null
  openRecordId: string | null
  scope: string | null
  selectedUid: string | null
  tree: BlockNode[]
  groups: GroupsMap
}

/** Store state -> URL state.
 *
 * `sel` is a STRUCTURAL path, never a uid: `newUid()` re-mints uids on every `docToTree`
 * (convert.ts), so a uid in a shared link means nothing to the recipient. `pathForUid` returns
 * null for a uid it cannot spell — a block that is no longer in the tree, or one inside a group
 * whose name contains both quote characters (paths.ts's `quoteGroupName`) — and that null must
 * stay a null all the way to `formatHash`, which then omits the param entirely. Interpolating
 * it into a string first would put a `sel=null` in the URL that `resolveDiagnosticPath` would
 * later fail to resolve, i.e. a param that is indistinguishable from a genuinely stale link.
 *
 * `rec` is suppressed off the Records tab because `formatHash` only emits it under `/records`
 * and `parseHash` only reads it there. Carrying a live `openRecordId` in the `UrlState` under
 * another tab would make two `UrlState`s that format to the same hash compare as different,
 * which `isNavigation` below would then read as a navigation that produced no URL change.
 */
export function urlStateOf(v: SyncView): UrlState {
  return {
    tab: v.tab,
    exp: v.serverId,
    rec: v.tab === 'Records' ? v.openRecordId : null,
    scope: v.scope,
    sel: v.selectedUid === null ? null : pathForUid(v.tree, v.groups, v.selectedUid),
  }
}

/** Which changes earn a history entry (`pushState`) rather than replacing the current one.
 *
 * Everything except `sel`. Tab, document, record and scope are places you can be, and going
 * back to one is what a Back button is for. A selection is not a place — it is a cursor, and
 * it moves on every click on the canvas. Pushing it would build a second, far denser undo
 * stack on the Back button, sitting alongside the real undo/redo (zundo, docStore.ts) and
 * disagreeing with it: Back would sometimes move the cursor and sometimes leave the tab.
 */
export const isNavigation = (a: UrlState, b: UrlState): boolean =>
  a.tab !== b.tab || a.exp !== b.exp || a.rec !== b.rec || a.scope !== b.scope

export interface UrlView {
  scope: string | null
  selectedUid: string | null
}

/** URL state -> the view fields, resolved against the document that is loaded NOW.
 *
 * A link can outlive what it names: the block was deleted, the group was renamed, someone else
 * saved over the document. Both fields therefore clear rather than guess — resolving onto the
 * *wrong* block is worse than resolving onto none, which is the same rule `resolveTail`
 * (paths.ts) already follows for an out-of-range index. `useUrlSync` then re-writes the hash
 * from the resulting state, so the dead param is dropped from the URL instead of rotting there
 * and being re-shared.
 *
 * The `scope` check uses `Object.hasOwn`, not `in`: `in` walks the prototype chain, so a URL
 * carrying `scope=toString` or `scope=constructor` would pass and leave `docStore.scope` naming
 * a group that does not exist — a state nothing else in the app can produce (`removeGroup`
 * resets scope to null, `renameGroup` follows it) and which renders as a silently empty canvas,
 * since `activeList` falls back to `[]`.
 *
 * `scope` and `sel` are resolved INDEPENDENTLY, and a `sel` inside a group is not taken as
 * evidence about `scope`. `formatHash`/`urlStateOf` always emit the two consistently, so a
 * disagreement is only reachable by hand-editing the URL, and there the least surprising
 * behaviour is to do what the URL literally says rather than to infer one field from the other.
 */
export function viewFromUrl(url: UrlState, tree: BlockNode[], groups: GroupsMap): UrlView {
  return {
    scope: url.scope !== null && Object.hasOwn(groups, url.scope) ? url.scope : null,
    selectedUid: url.sel === null ? null : resolveDiagnosticPath(tree, groups, url.sel).uid,
  }
}
