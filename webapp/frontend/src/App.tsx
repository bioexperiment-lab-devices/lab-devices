import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { getExperiment } from './api/studio'
import { docToTree, treeToDoc } from './builder/convert'
import { TabShell } from './shell/TabShell'
import { BuilderTab } from './builder/BuilderTab'
import { DevicesTab } from './devices/DevicesTab'
import { RecordsTab } from './records/RecordsTab'
import { RunTab } from './run/RunTab'
import { RestoreNotice, type BootNotice } from './shell/RestoreNotice'
import { decideBoot, draftIsDirty } from './shell/bootstrap'
import { parseHash } from './shell/urlState'
import { viewFromUrl } from './shell/urlSyncRules'
import { useDraftAutosave } from './shell/useDraftAutosave'
import { useUrlSync } from './shell/useUrlSync'
import { loadDoc, newDoc, useDocStore } from './stores/docStore'
import { clearDraft, readDraft } from './stores/draftStorage'
import { useLabsStore } from './stores/labsStore'
import { useNavStore } from './stores/navStore'
import { useRecordsStore } from './stores/recordsStore'

export default function App() {
  const tab = useNavStore((s) => s.tab)
  const setTab = useNavStore((s) => s.setTab)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  const lab = useLabsStore((s) => s.selected)
  const [booted, setBooted] = useState(false)
  // Null until the boot effect decides otherwise, deliberately: RestoreNotice is role="status",
  // and a live region only announces content inserted AFTER assistive tech has registered the
  // page. Seeding this from readDraft() during render would bake the notice into the first
  // synchronous paint and silently make it un-announced (Task 7 review). Widened from a bare
  // `restoredAt: number | null` to a BootNotice union so this one slot can also carry the
  // second boot-time advisory design §5 requires — a fetch-failed/deleted-experiment notice —
  // without stacking a second banner or a second RestoreNotice-alike (Task 8 review, Finding 2).
  const [notice, setNotice] = useState<BootNotice | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(() => {
    // Runs exactly once. decideBoot (shell/bootstrap.ts) holds every decision; this executor
    // only performs them, plus the one outcome decideBoot cannot know in advance — a server
    // id that no longer resolves. With the hash grammar in place (Task 10) the real URL feeds
    // the matrix, so rows 1-3 — the ones where the URL names a document — are reachable.
    const url = parseHash(window.location.hash)
    const action = decideBoot(url, readDraft())

    // `tab` is seeded straight from the hash by navStore's initializer, and `exp` is what
    // decideBoot just consumed. `rec` has no such reader, so it is applied here — before
    // `booted`, like everything else below, for the reason applyUrlView documents. Without it
    // a `#/records/rec_…` link (a URL the app itself writes and a user will copy) lands on the
    // Records LIST: useUrlSync would seed `last` from an openId of null and replaceState the
    // segment away. Unconditional `open(url.rec)` would be equivalent today — openId is null
    // on mount — but the guard keeps this a no-op rather than a write for every other tab.
    if (url.rec !== null) useRecordsStore.getState().open(url.rec)

    /** Put the URL's view focus — `scope` and `sel` — into the store. Called at the END of
     * every boot branch, and always BEFORE `setBooted(true)`.
     *
     * Two orderings matter here and both are load-bearing:
     *
     * 1. Before `booted`. useUrlSync does NOT read the URL on mount: it seeds its `last` from
     *    the stores' current state and immediately `replaceState`s the address bar to match,
     *    so the STORE wins any disagreement (that hook's PRECONDITION comment). Enabling it
     *    first would erase an incoming link's scope/selection with no history entry left to
     *    recover them from.
     * 2. After the document lands. `sel` is a STRUCTURAL path (`blocks[0].children[2]`), not a
     *    uid, so it can only be resolved once there is a tree to resolve it against — hence
     *    "end of each boot branch" rather than up front.
     *
     * URL-vs-DRAFT on view focus (design §5 settles identity, not focus): the URL wins the
     * pair, but only when it actually names one of them. A draft restore has already
     * rehydrated scope/selectedUid from its own view state (Task 4's `loadDoc(content,
     * serverId, view)`), and on an ordinary refresh the two agree — useUrlSync writes the hash
     * synchronously on every store change while the draft lags a 500ms debounce, so the URL is
     * the fresher of the two whenever they differ. But a bare URL is not evidence of a null
     * focus: opening a NEW browser tab restores the localStorage mirror of the draft against
     * an empty hash, and forcing null there would throw away exactly the scope/selection Task
     * 4 exists to carry. So: silent URL -> the draft's focus stands; speaking URL -> it
     * determines BOTH fields, a null half meaning "nothing", not "no opinion". The pair is
     * applied as a unit because it is written as one (`urlStateOf` projects both from a single
     * view), and merging a fresh URL half with a stale draft half would produce a focus
     * neither ever held.
     *
     * `viewFromUrl` rather than `url.scope`/`url.sel` raw, and it is the same call useUrlSync's
     * popstate `apply` makes, so a link resolves identically whether it is followed cold or
     * arrived at by Back. It also clears rather than guesses: an unresolvable `sel` (stale
     * link, or the document changed server-side) leaves the selection null, and useUrlSync's
     * first write then drops the dead param from the URL instead of re-sharing it. And its
     * `Object.hasOwn` scope check is what stops a hand-edited `scope=toString` from naming a
     * group that does not exist — a state nothing else in the app can produce, which renders
     * as a silently empty canvas.
     */
    const applyUrlView = (): void => {
      if (url.scope === null && url.sel === null) return
      const doc = useDocStore.getState()
      const view = viewFromUrl(url, doc.tree, doc.groups)
      // Scope BEFORE selection, always: `setScope` clears `selectedUid` as a side effect
      // (docStore.ts), so selecting first would have the selection discarded by the scope
      // change that follows it.
      if (view.scope !== doc.scope) doc.setScope(view.scope)
      useDocStore.getState().select(view.selectedUid)
    }

    if (action.kind === 'restoreDraft') {
      try {
        // The draft holds the EDITOR form and goes straight into loadDoc -> setState ->
        // snapshotOf (a bare JSON.stringify): none of that inspects `content.tree`, so the
        // draft never passes through docToTree, and the DocConvertError backstop that guards
        // the server path below does NOT cover this branch. parseDraft only checks that
        // `content` is an object and then casts (draftStorage.ts), so a corrupt-but-shaped
        // draft would otherwise sail straight into the store untouched — and the throw would
        // happen later, during React render (Canvas.tsx's `activeTree.length`, reached via
        // useActiveTree/activeList), which a try/catch in this effect CANNOT catch, and there
        // is no error boundary anywhere in the app to catch it either. So treeToDoc is called
        // here, pre-flight, before loadDoc, for its throw alone — its return value is
        // discarded. It is the same validator the server path already leans on via docToTree,
        // so this gives the restore path real parity with that path rather than an
        // approximation of it. Corrupt storage must never be able to make the Studio
        // unopenable — that is strictly worse than the data loss this increment exists to
        // prevent (Task 1 review; pre-flight added Task 8 review, Finding 1).
        treeToDoc(action.draft.content)
        loadDoc(action.draft.content, action.draft.serverId, action.draft.view)
        // After loadDoc, never before: loadDoc recomputes savedSnapshot from the content it is
        // handed, which would mark a dirty draft clean and make the unsaved dot lie. zustand's
        // setState is synchronous, so this lands before anything can read the store.
        useDocStore.setState({ savedSnapshot: action.draft.savedSnapshot })
        // Announce only a draft that actually held unsaved work. A CLEAN draft is still worth
        // restoring — it carries scope/selection/collapse — but claiming "Restored unsaved
        // changes" over it would be false, and it is reachable: Toolbar's New clears the draft
        // while autosave's debounce is still armed, so the empty document immediately writes a
        // fresh clean draft back (verified in the browser — Step 5 scenario 4).
        if (draftIsDirty(action.draft)) {
          setNotice({ kind: 'restored', at: action.draft.updatedAt })
        }
      } catch {
        // Reachable now only because of the treeToDoc pre-flight above — nothing else in the
        // try block throws. clearDraft() runs before newDoc() so the poison draft does not
        // survive to reproduce this exact failure on the next refresh: recovery must not
        // depend on luck (a later autosave happening to overwrite it) — a poison draft should
        // cost exactly one boot (Task 8 review, Finding 1).
        clearDraft()
        newDoc()
      }
      // Outside the try/catch, so the poison-draft path gets the URL's focus applied too —
      // against the empty document it just fell back to, where it resolves to nothing.
      applyUrlView()
      setBooted(true)
      return
    }
    if (action.kind === 'newDoc') {
      newDoc()
      applyUrlView()
      setBooted(true)
      return
    }
    let cancelled = false
    getExperiment(action.id)
      .then((res) => {
        if (cancelled) return
        loadDoc(docToTree(res.doc), res.id)
      })
      .catch(() => {
        // A deleted or malformed experiment falls back to an empty document. It deliberately
        // does NOT fall back to an unrelated draft: the URL asked for a specific document,
        // and silently opening a different one is worse than opening none (design §5). Design
        // §5 also requires the fallback to "surface a notice": an empty document with no
        // explanation is indistinguishable from a normal cold start, so the user has no way to
        // learn that the document they asked for is actually gone (Task 8 review, Finding 2).
        if (!cancelled) {
          newDoc()
          setNotice({ kind: 'missing' })
        }
      })
      // `finally`, not the `then`: the fetch-failed branch above falls back to an empty
      // document, and that document must be reached with the SAME "focus applied, then
      // booted" ordering as the success path — otherwise useUrlSync would come up on the one
      // branch where nothing had normalized the hash. It resolves to nothing there, which is
      // the point: the stale `sel`/`scope` are dropped from the URL rather than left rotting.
      .finally(() => {
        if (cancelled) return
        applyUrlView()
        setBooted(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Both gated on `booted` so neither can race the boot executor: autosave must not mirror the
  // empty document that precedes an in-flight server load, and useUrlSync must not seed its
  // `last` from the stores until the executor has finished putting the URL's own state into
  // them (see applyUrlView above).
  useDraftAutosave(booted)
  useUrlSync(booted)

  return (
    // The notice goes through TabShell's `banner` slot rather than being stacked above
    // <TabShell/>: its root is the h-screen column, and a sibling above it overflows the
    // viewport instead of sharing it (see the prop's comment in TabShell.tsx).
    <TabShell
      active={tab}
      onSelect={setTab}
      statusLine={describeHealth(health, error)}
      lab={lab}
      banner={
        notice === null ? undefined : (
          <RestoreNotice notice={notice} onDismiss={() => setNotice(null)} />
        )
      }
    >
      {tab === 'Devices' && <DevicesTab />}
      {tab === 'Builder' && <BuilderTab />}
      {tab === 'Run' && <RunTab />}
      {tab === 'Records' && <RecordsTab />}
    </TabShell>
  )
}
