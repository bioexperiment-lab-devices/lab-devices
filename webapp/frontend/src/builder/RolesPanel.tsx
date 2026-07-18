import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { useDocStore } from '../stores/docStore'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'

/** Inline rename/delete list for roles (spec §4.2): rename cascades through every
 * referencing block in one undo step; delete is refused with a reference count.
 *
 * `focusedRole` (docStore.ts) is set by a Problems row click on a role diagnostic
 * (paths.ts's `MappedDiagnostic.role`) — it scrolls the matching row into view and
 * highlights it, the same jump-to-block treatment ProblemsPanel already gives a uid. */
export function RolesPanel() {
  const roles = useDocStore((s) => s.roles)
  const renameRole = useDocStore((s) => s.renameRole)
  const removeRole = useDocStore((s) => s.removeRole)
  const focusedRole = useDocStore((s) => s.focusedRole)
  const [error, setError] = useState<{ role: string; message: string } | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const cancelled = useRef(false)

  useEffect(() => {
    if (!focusedRole) return
    document
      .getElementById(`role-${focusedRole}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focusedRole])

  const commitRename = (from: string) => {
    const err = draft && draft !== from ? renameRole(from, draft) : null
    setError(err === null ? null : { role: from, message: err })
    if (!err) setEditing(null)
  }

  const entries = Object.entries(roles)
  if (entries.length === 0) {
    return <p className="px-1 text-xs text-hint">No roles yet — add one above.</p>
  }
  return (
    <ul className="space-y-1">
      {entries.map(([name, role]) => (
        <li key={name} id={`role-${name}`} className="text-sm">
          <div
            className={
              'flex items-center gap-1 rounded ' +
              (focusedRole === name ? 'ring-2 ring-amber-400 bg-amber-50' : '')
            }
          >
            {editing === name ? (
              <input
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => {
                  if (cancelled.current) {
                    cancelled.current = false
                    return
                  }
                  commitRename(name)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename(name)
                  if (e.key === 'Escape') {
                    cancelled.current = true
                    setEditing(null)
                  }
                }}
                className={controlClass({ mono: true }) + ' w-28'}
              />
            ) : (
              <button
                title="Rename role"
                onClick={() => {
                  setEditing(name)
                  setDraft(name)
                  setError(null)
                  cancelled.current = false
                }}
                className={inlineButtonClass()}
              >
                {name}
              </button>
            )}
            <span className="text-xs text-caption">{role.type}</span>
            <IconButton
              icon={X}
              label="Delete role"
              destructive
              className="ml-auto"
              onClick={() => {
                const err = removeRole(name)
                setError(err === null ? null : { role: name, message: err })
              }}
            />
          </div>
          {error?.role === name && <p className="mt-0.5 text-xs text-red-600">{error.message}</p>}
        </li>
      ))}
    </ul>
  )
}
