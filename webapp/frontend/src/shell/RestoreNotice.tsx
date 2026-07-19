/** Announces boot-time advisories the user cannot otherwise discover: unsaved work restored
 * from browser storage (design §6.3), a requested experiment that no longer resolves
 * (design §5 — a 404'd `loadServer(X)` falls back to `newDoc()` "and surfaces a notice"), or
 * unsaved work on a DIFFERENT document that opening this one has just cost (design §5.1).
 *
 * Inline and dismissible rather than a modal: restore is automatic precisely so that refresh
 * is non-destructive (design §2.1), and a boot-time modal would put the interruption back.
 * Not a self-hiding toast either — all three variants report that state on screen is not what
 * the caller expected, which the user should be able to read at their own pace.
 */
import { X } from 'lucide-react'
import { IconButton } from '../ui/IconButton'

const time = (at: number): string =>
  new Date(at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

// App.tsx has exactly one boot-time advisory slot, and the outcomes are near-exclusive by
// construction (decideBoot picks one BootAction branch). A discriminated union keeps that an
// invariant of the type rather than something callers have to remember — independent optional
// props could be set together with nothing to stop it (Task 8 review, Finding 2). The one pair
// that CAN both be true — a displaced draft plus a 404 on the document that displaced it — is
// resolved by precedence at the single set site in App.tsx, not by widening this type.
// `missing` and `unavailable` are the same server outcome — a requested experiment that does not
// resolve — reached from the two paths that must answer it DIFFERENTLY, so they are two variants
// rather than one. At boot nothing is open yet, so the executor opens a blank document. Mid-
// navigation (useUrlSync's popstate `apply`) the store holds a real, possibly-dirty document the
// user never agreed to discard, so it is kept. One shared message would have to lie about one of
// the two, and the difference — whether your work is still there — is exactly what the reader
// needs to know.
export type BootNotice =
  | { kind: 'restored'; at: number }
  | { kind: 'missing' }
  | { kind: 'unavailable' }
  | { kind: 'displaced'; name: string }

// The draft carries content.name verbatim, and an unnamed document is ordinary — Toolbar's New
// starts one — so an empty name gets a phrase rather than a pair of empty quotes. Trimmed
// because a whitespace-only name reads as absent on screen even though it is not empty.
const named = (name: string): string => (name.trim() === '' ? 'an untitled document' : `“${name}”`)

const message = (notice: BootNotice): string => {
  switch (notice.kind) {
    case 'restored':
      return `Restored unsaved changes from ${time(notice.at)}.`
    case 'missing':
      return `That experiment could not be found. Opened a new document instead.`
    case 'unavailable':
      return `That experiment could not be found. Kept the document you had open.`
    case 'displaced':
      // Names the document so this is actionable information rather than an alarm: the user
      // can go back to it and redo the edit knowing exactly what was lost. Past tense because
      // by the time this is read the autosave has already overwritten the stored draft.
      return `Opening this document replaced unsaved changes to ${named(notice.name)}.`
  }
}

export function RestoreNotice(props: { notice: BootNotice; onDismiss: () => void }) {
  const { notice, onDismiss } = props
  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-3 py-1 text-xs text-caption"
    >
      <span>{message(notice)}</span>
      <span className="ml-auto">
        <IconButton icon={X} label="Dismiss notice" onClick={onDismiss} />
      </span>
    </div>
  )
}
