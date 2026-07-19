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
 * landing, the writer is suppressed. What makes the guard robust is NOT that the mutators are
 * synchronous: it's that `apply` recomputes `last` from the store's own state at the end, rather
 * than trusting the `UrlState` it started from. A write the guard failed to suppress would
 * therefore diff against a FRESH projection, not a stale one — at worst an extra history entry,
 * never a corrupted one. (Every effect reachable from a URL-applied change — useValidation,
 * RecordsTab's refresh, RecordViewer, RunTab's attach — was audited and none touches a
 * URL-projected field, so no such write exists today; that audit is the thing to redo if a
 * future effect starts writing tab/exp/rec/scope/sel.) That audit is scoped to writes the
 * URL-apply chain itself triggers. It says nothing about a genuinely independent user action —
 * a tab click, say — landing inside the same now-async window: the guard suppresses that write
 * too, indiscriminately, and when `apply`'s trailing `write()` (below) finally runs it diffs the
 * fresh post-fetch projection against itself (`last` was just refreshed from that same
 * projection), so `isNavigation` reads false. The action's own history entry is silently
 * downgraded from `pushState` to `replaceState` — one lost Back step, not a corrupted one.
 * Under the old synchronous guard no user action could land inside the window at all; this is
 * the price of holding it across an await, judged acceptable because the STORE is never wrong,
 * only the history entry standing in for one of the actions that produced it.
 * A ref rather than a module-level `let` so a remount cannot inherit a flag left true by a throw.
 *
 * THE GUARD IS HELD ACROSS AN AWAIT (design §3.1). `exp` is the one URL field that does not
 * resolve against state already in memory — reopening a document is a server fetch — so `apply`
 * is async and the suppression window is genuinely wider than the synchronous one the original
 * argument assumed. Three things keep that safe, and all three are load-bearing:
 *
 *  1. `generation`, a ref bumped by every `apply`. Only the newest generation may write to the
 *     stores, release the guard, or touch history; a slower earlier fetch resolving afterwards
 *     returns without doing anything. Two rapid Back presses across three documents therefore
 *     end on the document the URL names, not on whichever response happened to return last. A
 *     ref and not an effect-local `let` because `applying` is a ref too: a counter scoped to the
 *     effect would restart at 0 on a re-run, and a fetch left over from the previous run would
 *     match the new run's generation and release a guard it does not own. AbortController was
 *     the alternative; it would need a `signal` threaded through api/client.ts's four helpers,
 *     and it would still need this check, since an abort cannot un-deliver a response that has
 *     already resolved. The counter is the whole correctness story, so it is the only mechanism.
 *  2. `finally`, unconditionally. A leaked `applying === true` freezes the URL writer for the
 *     rest of the session — a silent, total failure — so the release is in a `finally` that
 *     covers the fetch, the JSON conversion (`docToTree` throws DocConvertError) and the store
 *     writes alike. The generation check gates only WHICH apply owns the flag, never whether
 *     the release runs.
 *  3. `disposed`, set by the effect cleanup. Effect-local, unlike the two refs above, because it
 *     asks a per-binding question: this binding's listeners are gone, so an in-flight fetch must
 *     not call `loadDoc` or `pushState` into a torn-down app. It gates the store write and the
 *     trailing `write`, but never the guard release.
 *
 * PRECONDITION: this hook does not read the URL on mount. `last` is seeded from the stores'
 * CURRENT state and the address bar is immediately `replaceState`d to match it — the store
 * wins any disagreement with an incoming link's `scope`/`sel`. That is correct only because the
 * caller has already applied `url.scope`/`url.sel` to the stores before this hook is enabled
 * (App.tsx's boot sequence, before `booted` flips true). Enabling this hook ahead of that would
 * silently discard the link's view focus, with no history entry left to recover it from.
 */
import { useEffect, useRef } from 'react'
import { getExperiment } from '../api/studio'
import { docToTree } from '../builder/convert'
import { loadDoc, selectDirty, useDocStore } from '../stores/docStore'
import { useNavStore } from '../stores/navStore'
import { useRecordsStore } from '../stores/recordsStore'
import { applyUrlFocus } from './urlFocus'
import { formatHash, parseHash } from './urlState'
import {
  displacedByReopen,
  documentToLoad,
  isNavigation,
  urlStateOf,
  type SyncView,
} from './urlSyncRules'

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

/** `onMissing` fires when the URL names an experiment the server no longer has — see `apply`'s
 * 404 decision below. `onDisplaced` fires when a successful reopen is about to discard unsaved
 * work in the document that is open right now — the identical loss design §5.1 already warns
 * about at boot, reached here mid-session (see `displacedByReopen`, urlSyncRules.ts). `onOpened`
 * fires on every OTHER successful cross-document reopen — one that does not displace anything —
 * so the caller can retire an advisory left behind by an earlier, unrelated navigation: a
 * `displaced` banner is otherwise undismissable evidence of nothing once the user has moved on,
 * and left standing it silently outranks every notice a later navigation would otherwise raise
 * (Finding N2, W16 final review). All three held in a ref so the effect can stay on `[enabled]`
 * and an unstable caller cannot leave any of them stale. */
export function useUrlSync(
  enabled: boolean,
  onMissing?: () => void,
  onDisplaced?: (name: string) => void,
  onOpened?: () => void,
): void {
  const applying = useRef(false)
  const generation = useRef(0)
  const onMissingRef = useRef(onMissing)
  onMissingRef.current = onMissing
  const onDisplacedRef = useRef(onDisplaced)
  onDisplacedRef.current = onDisplaced
  const onOpenedRef = useRef(onOpened)
  onOpenedRef.current = onOpened

  useEffect(() => {
    if (!enabled) return
    let disposed = false

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

    const apply = async (hash: string): Promise<void> => {
      const url = parseHash(hash)
      const gen = (generation.current += 1)
      applying.current = true
      try {
        // Tab and record resolve against memory, so they land immediately — the tab must not
        // sit on the old one for the length of a fetch.
        useNavStore.getState().setTab(url.tab)
        useRecordsStore.getState().open(url.rec)

        const id = documentToLoad(url, useDocStore.getState().serverId)
        if (id !== null) {
          let content
          try {
            const res = await getExperiment(id)
            // Inside the try WITH the fetch: docToTree throws DocConvertError on a malformed
            // doc, and a malformed document is as unopenable as a missing one. Treating only
            // the fetch as fallible would turn that throw into an unhandled rejection.
            content = docToTree(res.doc)
          } catch {
            // 404 (or malformed) MID-NAVIGATION: keep the document that is open. Deliberately
            // NOT the boot executor's `newDoc()` fallback, and the difference is the point. At
            // boot there is no document yet, so a blank one costs nothing. Here the store holds
            // a real, possibly-dirty document that the user never consented to discard — a Back
            // press passes none of the four `confirm('Discard unsaved changes?')` guards
            // (Toolbar.tsx's three, LoadDialog.tsx's one), so blanking it would be data loss
            // caused by the Back button. The `finally` below then re-projects `exp` from the
            // unchanged `serverId`, so the address bar returns to naming what is genuinely
            // open: the URL and the store still agree, which is the property this whole task
            // exists to restore. Silence would be the wrong half of that trade — Back appearing
            // to do nothing is indistinguishable from a broken button — so the caller gets a
            // notice naming the outcome.
            if (gen === generation.current && !disposed) onMissingRef.current?.()
            return
          }
          // A newer apply (another Back press) or a teardown happened while this was in
          // flight. Return before touching the store: this response is now history. This is
          // also why the displaced check below sits AFTER this line rather than before it: a
          // stale apply must not warn about a loss it is not the one causing.
          if (gen !== generation.current || disposed) return
          // Sample BEFORE `loadDoc` replaces the store on the next line: this is the document
          // about to be destroyed. The generation check just above guarantees this apply owns
          // the flag, so no OTHER apply could have reopened a different document in the
          // meantime — only the open document's own content could have changed, via the user's
          // own edits, which is exactly the state this warning is about. design §5.1 already
          // warns for the identical loss at boot (`displacedByReopen` mirrors `displacedBy`,
          // bootstrap.ts); `apply` must not be silent about it just because the loss happens
          // mid-session, on a Back press, instead (Important 1, W16 Task 15 review).
          //
          // The two callbacks are mutually exclusive by construction — this is a single `if`
          // deciding between them, never a "clear, then maybe set" sequence — so there is no
          // ordering hazard between retiring a stale advisory and raising the one THIS reopen
          // is about: a winning, document-replacing apply either raises its own `displaced`
          // warning, or, having nothing to warn about, is the proof that whatever advisory was
          // on screen belongs to a navigation that is now over (Finding N2, W16 final review).
          const open = useDocStore.getState()
          const displaced = displacedByReopen(selectDirty(open), open.name)
          if (displaced !== null) onDisplacedRef.current?.(displaced.name)
          else onOpenedRef.current?.()
          loadDoc(content, id)
        }
        if (disposed) return
        // AFTER the document lands, never before: `scope` and `sel` are structural, so they can
        // only be resolved against the tree that is now in the store (design §3.1). On the
        // no-reload path this is the same synchronous position it always held.
        applyUrlFocus(url)
      } finally {
        // Unconditional for THIS generation, on every path — resolved, rejected, or returned
        // early. A leaked `true` freezes the URL writer permanently. A stale generation must
        // NOT release: the newest apply owns the flag and may still be mid-fetch.
        if (gen === generation.current) {
          applying.current = false
          if (!disposed) {
            last = urlStateOf(currentView())
            // The URL may name a param the resolution above just dropped (a `sel` pointing at
            // a block deleted since the link was made, viewFromUrl's doc comment; or an `exp`
            // that no longer resolves). `last` is already the fresh projection, so `write`
            // compares it against itself: `isNavigation` reads false and this replaces the
            // current history entry in place — no extra Back step — instead of leaving the
            // address bar advertising state the store does not hold.
            write()
          }
        }
      }
    }

    // A same-document Back fires BOTH `popstate` and `hashchange` in Chromium (measured), and
    // that was free while `apply` was synchronous and idempotent — the second run redid the
    // same `set`s. It is not free now: the second run would issue a DUPLICATE document fetch
    // whose response the generation check then throws away, doubling the request count on every
    // cross-document navigation. So an event naming a hash an apply is already in flight for is
    // dropped. Keyed on the hash rather than a bare in-flight flag, so a genuinely different
    // URL arriving mid-fetch still applies and still wins by generation; and cleared when that
    // apply settles, so hand-editing back to the same hash later is applied again rather than
    // being swallowed as a duplicate.
    //
    // `pendingToken` — not a re-comparison of `hash` — decides who is allowed to clear
    // `pending`, because a hash string is not a unique name for one specific apply: A -> B -> A
    // revisits the same string. Without the token, apply#1(A)'s `finally` would see
    // `pending === 'A'` (apply#3(A) having just set it back) and null it out from under
    // apply#3, un-coalescing a `hashchange` that arrives while apply#3 is still in flight.
    // Efficiency only — the generation counter still discards whichever response loses — but
    // comparing the token apply#N itself captured means only apply#N's own settling can ever
    // clear the `pending` it set.
    let pending: string | null = null
    let pendingToken = 0
    const onUrlEvent = (): void => {
      const hash = window.location.hash
      if (hash === pending) return
      pending = hash
      const token = (pendingToken += 1)
      // `void`: nothing awaits an apply. Only the fetch and `docToTree` are actually caught
      // inside `apply` (its inner try/catch) — a throw from `loadDoc`, `applyUrlFocus`, the
      // missing-document callback, or `write()` would otherwise escape this `void` as an
      // unhandled rejection. Harmless rather than broken: `apply`'s `finally` still releases
      // `applying` on every one of those paths before the throw propagates, so the guard is
      // never leaked — but an unhandled rejection is still noise a test environment or a
      // stricter host could turn into a hard failure, so it is swallowed here explicitly
      // rather than left to rely on nothing downstream ever observing the rejection.
      void apply(hash)
        .finally(() => {
          if (pendingToken === token) pending = null
        })
        .catch(() => {})
    }
    window.addEventListener('popstate', onUrlEvent)
    // Also covers a hand-edited hash, which fires hashchange but not popstate everywhere.
    window.addEventListener('hashchange', onUrlEvent)

    // The initial URL is normalized in place — replaceState, not push — so Back still leaves
    // the app rather than stepping through the boot state.
    window.history.replaceState(null, '', hrefWith(formatHash(last)))

    const unsubDoc = useDocStore.subscribe(write)
    const unsubNav = useNavStore.subscribe(write)
    const unsubRec = useRecordsStore.subscribe(write)

    return () => {
      disposed = true
      // Defensive, and specifically for the re-run case rather than unmount: a fetch left in
      // flight owns `applying` (a ref, so it outlives this closure) and would otherwise hand
      // the next binding a writer that is already suppressed. Clearing it here means the next
      // binding always starts from a known state; the in-flight apply's own `finally` clearing
      // it again is a harmless no-op, and its `disposed` check keeps it off the stores.
      applying.current = false
      window.removeEventListener('popstate', onUrlEvent)
      window.removeEventListener('hashchange', onUrlEvent)
      unsubDoc()
      unsubNav()
      unsubRec()
    }
  }, [enabled])
}
