/** Mirrors the open document into browser storage ~500ms after it stops changing (design §6.3).
 *
 * Subscribes to the store rather than reading it in an effect body: zustand's subscribe fires
 * on every mutation regardless of which component rendered, which is exactly the coverage this
 * needs — an edit made from the Inspector, the canvas, or an undo must all land in the draft.
 *
 * This freshness guarantee is silently dependent on `useDocStore.subscribe` staying the
 * UNFILTERED, whole-store form used below — if docStore ever adopts `subscribeWithSelector` or
 * an equality function here, mutations to fields the selector/equality check ignores would stop
 * rescheduling the debounce and this hook would break quietly, with no type error to catch it.
 */
import { useEffect } from 'react'
import { useDocStore, selectContent } from '../stores/docStore'
import { writeDraft } from '../stores/draftStorage'

const DEBOUNCE_MS = 500

export function useDraftAutosave(enabled: boolean): void {
  useEffect(() => {
    // Held off until the boot executor has finished, so an in-flight server load cannot be
    // raced by an autosave of the empty document that precedes it.
    if (!enabled) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const unsubscribe = useDocStore.subscribe((s) => {
      if (timer !== null) clearTimeout(timer)
      timer = setTimeout(() => {
        writeDraft({
          v: 2,
          serverId: s.serverId,
          savedSnapshot: s.savedSnapshot,
          content: selectContent(s),
          view: { scope: s.scope, selectedUid: s.selectedUid, collapsed: s.collapsed },
          updatedAt: Date.now(),
        })
      }, DEBOUNCE_MS)
    })
    return () => {
      if (timer !== null) clearTimeout(timer)
      unsubscribe()
    }
  }, [enabled])
}
