import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { getExperiment } from './api/studio'
import { docToTree } from './builder/convert'
import { TabShell } from './shell/TabShell'
import { BuilderTab } from './builder/BuilderTab'
import { DevicesTab } from './devices/DevicesTab'
import { RecordsTab } from './records/RecordsTab'
import { RunTab } from './run/RunTab'
import { RestoreNotice } from './shell/RestoreNotice'
import { decideBoot, draftIsDirty, EMPTY_URL_STATE } from './shell/bootstrap'
import { useDraftAutosave } from './shell/useDraftAutosave'
import { loadDoc, newDoc, useDocStore } from './stores/docStore'
import { readDraft } from './stores/draftStorage'
import { useLabsStore } from './stores/labsStore'
import { useNavStore } from './stores/navStore'

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
  // synchronous paint and silently make it un-announced (Task 7 review).
  const [restoredAt, setRestoredAt] = useState<number | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(() => {
    // Runs exactly once. decideBoot (shell/bootstrap.ts) holds every decision; this executor
    // only performs them, plus the one outcome decideBoot cannot know in advance — a server
    // id that no longer resolves. EMPTY_URL_STATE is deliberate in Phase A: no URL is parsed
    // yet (urlState.ts does not exist), so only the draft/new rows can fire.
    const action = decideBoot(EMPTY_URL_STATE, readDraft())
    if (action.kind === 'restoreDraft') {
      try {
        // The draft holds the EDITOR form and goes straight into the store, so it never passes
        // through docToTree and the DocConvertError backstop that guards the server path below
        // does NOT cover this branch. parseDraft only checks that `content` is an object and
        // then casts (draftStorage.ts), so a corrupt-but-shaped draft would otherwise put junk
        // into the store and take the canvas down on first render. Corrupt storage must never
        // be able to make the Studio unopenable — that is strictly worse than the data loss
        // this increment exists to prevent (Task 1 review).
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
        if (draftIsDirty(action.draft)) setRestoredAt(action.draft.updatedAt)
      } catch {
        newDoc()
      }
      setBooted(true)
      return
    }
    if (action.kind === 'newDoc') {
      newDoc()
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
        // and silently opening a different one is worse than opening none (design §5).
        if (!cancelled) newDoc()
      })
      .finally(() => {
        if (!cancelled) setBooted(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useDraftAutosave(booted)

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
        restoredAt === null ? undefined : (
          <RestoreNotice at={restoredAt} onDismiss={() => setRestoredAt(null)} />
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
