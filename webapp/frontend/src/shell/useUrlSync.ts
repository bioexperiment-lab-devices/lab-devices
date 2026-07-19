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
 * landing, the writer is suppressed. The guard is sound because every store mutation below is
 * a synchronous zustand `set`, and zustand notifies subscribers synchronously inside `set` —
 * so every write the reader can provoke happens before the `finally` clears the flag. A ref
 * rather than a module-level `let` so a remount cannot inherit a flag left true by a throw.
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
    }

    const onPopState = (): void => apply(window.location.hash)
    window.addEventListener('popstate', onPopState)
    // Also covers a hand-edited hash, which fires hashchange but not popstate everywhere.
    window.addEventListener('hashchange', onPopState)

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
