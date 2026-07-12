import { useState } from 'react'
import { useDocStore } from '../stores/docStore'

/** Inline rename/delete list for roles (spec §4.2): rename cascades through every
 * referencing block in one undo step; delete is refused with a reference count. */
export function RolesPanel() {
  const roles = useDocStore((s) => s.roles)
  const renameRole = useDocStore((s) => s.renameRole)
  const removeRole = useDocStore((s) => s.removeRole)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const commitRename = (from: string) => {
    const err = draft && draft !== from ? renameRole(from, draft) : null
    setError(err)
    if (!err) setEditing(null)
  }

  const entries = Object.entries(roles)
  if (entries.length === 0) {
    return <p className="px-1 text-xs text-slate-400">No roles yet — add one above.</p>
  }
  return (
    <ul className="space-y-1">
      {entries.map(([name, role]) => (
        <li key={name} className="flex items-center gap-1 text-sm">
          {editing === name ? (
            <input
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => commitRename(name)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename(name)
                if (e.key === 'Escape') setEditing(null)
              }}
              className="w-28 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
            />
          ) : (
            <button
              title="Rename role"
              onClick={() => {
                setEditing(name)
                setDraft(name)
                setError(null)
              }}
              className="rounded px-1 font-mono text-xs hover:bg-slate-200"
            >
              {name}
            </button>
          )}
          <span className="text-xs text-slate-400">{role.type}</span>
          <button
            title="Delete role"
            onClick={() => setError(removeRole(name))}
            className="ml-auto rounded px-1 text-xs text-slate-400 hover:bg-red-50 hover:text-red-600"
          >
            ✕
          </button>
        </li>
      ))}
      {error && <li className="text-xs text-red-600">{error}</li>}
    </ul>
  )
}
