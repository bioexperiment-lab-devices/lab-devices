/** Two-way binding between the hash and the stores (design §3.1, §4).
 *
 * Wiring only. Every judgement this binding makes — the projection of the three stores onto a
 * `UrlState`, which changes earn a history entry, and what a URL naming things the document no
 * longer contains resolves to — lives in urlSyncRules.ts, where the node-environment tests can
 * reach it (webapp/frontend/CLAUDE.md). What is left here is what genuinely needs a browser:
 * two listeners, three subscriptions, and the one piece of mutable state in W16.
 *
 * That state is `applying`. The store->hash writer and the URL->store reader form a loop:
 * applying a URL fires the subscriptions that write the URL. While a URL-originated update is
 * landing, the writer is suppressed. Today all four mutators `apply` calls (`setTab`, `open`,
 * `setScope`, `select`) are plain synchronous zustand `set`s, and zundo's `temporal` wrapper is
 * configured with only partialize/equality/limit — no handleSet/throttle — so nothing async sits
 * between a URL landing and the store reflecting it. But what actually makes the guard robust is
 * not that synchrony: it's that `apply` recomputes `last` from the store's own state at the end,
 * rather than trusting the `UrlState` it started from. A write the guard failed to suppress would
 * therefore diff against a FRESH projection, not a stale one — at worst an extra history entry,
 * never a corrupted one. (Every effect reachable from a URL-applied change — useValidation,
 * RecordsTab's refresh, RecordViewer, RunTab's attach — was audited and none touches a
 * URL-projected field, so no such write exists today; that audit, not the synchrony argument
 * above, is the thing to redo if a future effect starts writing tab/exp/rec/scope/sel.)
 * A ref rather than a module-level `let` so a remount cannot inherit a flag left true by a throw.
 *
 * PRECONDITION: this hook does not read the URL on mount. `last` is seeded from the stores'
 * CURRENT state and the address bar is immediately `replaceState`d to match it — the store
 * wins any disagreement with an incoming link's `scope`/`sel`. That is correct only because the
 * caller has already applied `url.scope`/`url.sel` to the stores before this hook is enabled
 * (App.tsx's boot sequence, before `booted` flips true). Enabling this hook ahead of that would
 * silently discard the link's view focus, with no history entry left to recover it from.
 */
import { useEffect, useRef } from 'react'
import { useDocStore } from '../stores/docStore'
import { useNavStore } from '../stores/navStore'
import { useRecordsStore } from '../stores/recordsStore'
import { formatHash, parseHash } from './urlState'
import { isNavigation, urlStateOf, viewFromUrl, type SyncView } from './urlSyncRules'

function currentView(): SyncView {
  const doc = useDocStore.getState()
  return {
    tab: useNavStore.getState().tab,
    serverId: doc.serverId,
    openRecordId: useRecordsStore.getState().openId,
    scope: doc.scope,
    selectedUid: doc.selectedUid,
    tree: doc.tree,
    groups: doc.groups,
  }
}

const hrefWith = (hash: string): string =>
  `${window.location.pathname}${window.location.search}${hash}`

export function useUrlSync(enabled: boolean): void {
  const applying = useRef(false)

  useEffect(() => {
    if (!enabled) return

    // `last` is the URL state the current history entry stands for. It is updated by BOTH
    // directions: a popstate that changes the tab must not leave the next canvas click looking
    // like a tab change, which would push a history entry for a mere selection move.
    let last = urlStateOf(currentView())

    const write = (): void => {
      if (applying.current) return
      const next = urlStateOf(currentView())
      const prev = last
      last = next
      // `formatHash` has already percent-encoded every value through URLSearchParams (a '#'
      // is now '%23'). Assign it whole: a second encodeURIComponent pass would make that
      // '%2523' and name a group `a%23b`.
      const hash = formatHash(next)
      if (hash === window.location.hash) return
      if (isNavigation(prev, next)) window.history.pushState(null, '', hrefWith(hash))
      else window.history.replaceState(null, '', hrefWith(hash))
    }

    const apply = (hash: string): void => {
      applying.current = true
      try {
        const url = parseHash(hash)
        useNavStore.getState().setTab(url.tab)
        useRecordsStore.getState().open(url.rec)
        const doc = useDocStore.getState()
        const view = viewFromUrl(url, doc.tree, doc.groups)
        // Scope BEFORE selection, always: docStore's `setScope` clears `selectedUid` as a
        // side effect (docStore.ts), so selecting first would have the selection silently
        // discarded by the scope change that follows it.
        if (view.scope !== doc.scope) doc.setScope(view.scope)
        useDocStore.getState().select(view.selectedUid)
      } finally {
        applying.current = false
      }
      last = urlStateOf(currentView())
      // The URL may name a param the resolution above just dropped (a `sel` pointing at a
      // block deleted since the link was made, viewFromUrl's doc comment). `last` is already
      // the fresh projection, so `write` compares it against itself: `isNavigation` reads
      // false and this replaces the current history entry in place — no extra Back step —
      // instead of leaving the address bar advertising a param the store no longer holds.
      write()
    }

    const onPopState = (): void => apply(window.location.hash)
    window.addEventListener('popstate', onPopState)
    // Also covers a hand-edited hash, which fires hashchange but not popstate everywhere.
    window.addEventListener('hashchange', onPopState)

    // The initial URL is normalized in place — replaceState, not push — so Back still leaves
    // the app rather than stepping through the boot state.
    window.history.replaceState(null, '', hrefWith(formatHash(last)))

    const unsubDoc = useDocStore.subscribe(write)
    const unsubNav = useNavStore.subscribe(write)
    const unsubRec = useRecordsStore.subscribe(write)

    return () => {
      window.removeEventListener('popstate', onPopState)
      window.removeEventListener('hashchange', onPopState)
      unsubDoc()
      unsubNav()
      unsubRec()
    }
  }, [enabled])
}
