/** Put a URL's view focus — `scope` and `sel` — into docStore.
 *
 * Extracted because it had two identical copies: App.tsx's boot executor and `useUrlSync`'s
 * popstate `apply`, each carrying its own transcription of the ordering rule below. That
 * duplication is not a line count, it is a correctness hazard: the two orderings are subtle in
 * opposite directions (one half conditional, the other deliberately not), and a future edit that
 * "tidied" one copy would leave the two paths resolving the SAME link differently depending on
 * whether it was followed cold or arrived at by Back — the exact divergence App.tsx's comment
 * says must not exist. One definition makes that unrepresentable.
 *
 * Not in urlSyncRules.ts: everything there is a pure function of plain values, and this mutates
 * a store. It is nonetheless testable in the node environment (urlFocus.test.ts) — docStore is
 * plain zustand and touches no browser API, which is why `useUrlSync` keeps only the parts that
 * genuinely need `window`.
 *
 * Callers own the question of WHETHER to apply focus at all. The boot executor skips this
 * entirely for a URL that names neither field, so a restored draft's own focus stands
 * (App.tsx); `apply` always calls it, because on a Back press a URL naming neither field means
 * "no scope, no selection" and must actively clear both.
 */
import { useDocStore } from '../stores/docStore'
import type { UrlState } from './bootstrap'
import { viewFromUrl } from './urlSyncRules'

export function applyUrlFocus(url: UrlState): void {
  const doc = useDocStore.getState()
  const view = viewFromUrl(url, doc.tree, doc.groups)
  // Scope BEFORE selection, always: docStore's `setScope` clears `selectedUid` as a side
  // effect (docStore.ts), so selecting first would have the selection silently discarded by
  // the scope change that follows it.
  //
  // The two halves are asymmetric ON PURPOSE and neither may be flipped. `setScope` is guarded
  // because it is destructive — calling it when the scope already matches would wipe a
  // selection the URL is about to re-assert only because the assertion happens to come next.
  // `select` is unguarded because it is the thing that makes the guard above safe: whenever the
  // guard skips `setScope`, `select` still runs and writes the resolved selection (including
  // null). Guarding `select` too would let a Back press to a selection-less entry leave the
  // previous selection standing; dropping the `setScope` guard would make every selection-only
  // apply clobber the selection it just resolved.
  if (view.scope !== doc.scope) doc.setScope(view.scope)
  useDocStore.getState().select(view.selectedUid)
}
