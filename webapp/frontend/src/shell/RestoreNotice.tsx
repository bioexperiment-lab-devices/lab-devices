/** Announces boot-time advisories the user cannot otherwise discover: unsaved work restored
 * from browser storage (design §6.3), or a requested experiment that no longer resolves
 * (design §5 — a 404'd `loadServer(X)` falls back to `newDoc()` "and surfaces a notice").
 *
 * Inline and dismissible rather than a modal: restore is automatic precisely so that refresh
 * is non-destructive (design §2.1), and a boot-time modal would put the interruption back.
 * Not a self-hiding toast either — both variants report that state on screen is not what the
 * caller expected, which the user should be able to read at their own pace.
 */
import { X } from 'lucide-react'
import { IconButton } from '../ui/IconButton'

const time = (at: number): string =>
  new Date(at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

// App.tsx has exactly one boot-time advisory slot, and the two outcomes are mutually
// exclusive by construction (decideBoot picks one BootAction branch). A discriminated union
// keeps that an invariant of the type rather than something callers have to remember —
// two independent optional props could be set together with nothing to stop it
// (Task 8 review, Finding 2).
export type BootNotice = { kind: 'restored'; at: number } | { kind: 'missing' }

const message = (notice: BootNotice): string =>
  notice.kind === 'restored'
    ? `Restored unsaved changes from ${time(notice.at)}.`
    : `That experiment could not be found. Opened a new document instead.`

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
