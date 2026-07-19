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
import type { DisplacedDraft, UrlState } from './bootstrap'
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

/** Does this URL name a document other than the one that is open — i.e. must `apply` reopen it?
 *
 * Returns the id to fetch, or null when the loaded document already satisfies the URL. This is
 * the one judgement on the `exp` path (design §3.1), and it is here rather than inline in
 * `useUrlSync` for the usual reason: the async plumbing around it needs a browser, the decision
 * does not. Two of its three branches are non-obvious.
 *
 * `exp === serverId` is null and not a reload. Re-fetching the open document on every popstate
 * would discard unsaved edits on a Back press that only moved the scope or the selection — the
 * common case (browser check (d)), and one no `confirm()` guard covers.
 *
 * **`exp === null` is also null — never a `newDoc()`.** A URL naming no document is not a
 * request for a BLANK one, and reading it as such would be data loss triggered by a Back press.
 * The entry is reachable without hand-editing: an unsaved document has no `exp`, so saving it
 * changes `exp` from null to X, which `isNavigation` (above) pushes. Back then lands on the
 * pre-save entry — the SAME document, before it had a server id. Blanking there would destroy
 * the document the user just saved. `useUrlSync`'s trailing `write` re-projects `exp` from the
 * unchanged `serverId`, so the address bar goes back to naming what is actually open.
 */
export const documentToLoad = (url: UrlState, serverId: string | null): string | null =>
  url.exp !== null && url.exp !== serverId ? url.exp : null

/** Does reopening a different document mid-session — `apply`'s exp-changed path in
 * useUrlSync.ts, reachable by a Back/Forward press across two documents or a hand-edited `exp`
 * — discard unsaved work in the document that is open right now?
 *
 * Design §5.1 already settled this exact question for the BOOT path (`displacedBy`,
 * bootstrap.ts): a dirty draft belonging to a document other than the one about to load is
 * warned about, not silently dropped, because storage holds a single draft slot (fork 3) and
 * autosave overwrites it moments later regardless of how it was lost. `apply`'s `loadDoc`
 * destroys the open document's edits the IDENTICAL way `loadDoc` does at boot, so the
 * mid-session path must answer the identical way — this is not a new decision, just the same
 * one asked again where the boot executor cannot reach.
 *
 * Takes the already-sampled `dirty`/`name` rather than a store snapshot: the (impure) act of
 * reading `selectDirty` off `useDocStore.getState()`, and choosing WHEN to read it — before
 * `loadDoc` overwrites the very document being asked about, and only once the generation check
 * confirms this `apply` is not a stale one — stays in the hook. This stays a total function of
 * two plain values, returning the same `DisplacedDraft` shape `displacedBy` does so both paths
 * hand App.tsx an identical notice payload.
 */
export function displacedByReopen(dirty: boolean, name: string): DisplacedDraft | null {
  return dirty ? { name } : null
}

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
 * disagreement is reachable by hand-editing the URL, and there the least surprising behaviour
 * is to do what the URL literally says rather than to infer one field from the other. It is
 * also reachable without hand-editing: `followUndoScope` (docStore.ts) writes `scope` via a
 * bare `useDocStore.setState({ scope })` on undo/redo, which — unlike `setScope` — does not
 * clear `selectedUid`, so an undo that switches scope can leave `selectedUid` pointing inside a
 * group while `scope` reads something else. The next `write` then legitimately emits a
 * scope-absent `sel` that names a path inside a group. The consequence is benign either way:
 * Inspector's `findNode` returns null (an empty inspector) and the Delete path no-ops, since
 * `removeNode` returns its input array by identity when the uid is not in the active list.
 */
export function viewFromUrl(url: UrlState, tree: BlockNode[], groups: GroupsMap): UrlView {
  return {
    scope: url.scope !== null && Object.hasOwn(groups, url.scope) ? url.scope : null,
    selectedUid: url.sel === null ? null : resolveDiagnosticPath(tree, groups, url.sel).uid,
  }
}
