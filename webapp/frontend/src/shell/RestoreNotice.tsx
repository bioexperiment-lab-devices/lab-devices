/** Announces that unsaved work was restored from browser storage (design §6.3).
 *
 * Inline and dismissible rather than a modal: restore is automatic precisely so that refresh
 * is non-destructive (design §2.1), and a boot-time modal would put the interruption back.
 * Not a self-hiding toast either — it reports that state on screen is not what the server has,
 * which the user should be able to read at their own pace.
 */
import { X } from 'lucide-react'
import { IconButton } from '../ui/IconButton'

const time = (at: number): string =>
  new Date(at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

export function RestoreNotice(props: { at: number; onDismiss: () => void }) {
  const { at, onDismiss } = props
  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-3 py-1 text-xs text-caption"
    >
      <span>Restored unsaved changes from {time(at)}.</span>
      <span className="ml-auto">
        <IconButton icon={X} label="Dismiss restore notice" onClick={onDismiss} />
      </span>
    </div>
  )
}
