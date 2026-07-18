import { useEffect, useRef, useState } from 'react'
import { Pencil, Plus, X } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import type { Catalog } from '../types/catalog'
import { effectiveSelection, roleGroups, type RoleTypeGroup } from './roleGroups'
import { Chip } from './Chip'
import { KindIcon } from '../ui/icons'
import { badgeClass, controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'
import { useDismissable } from '../ui/useDismissable'

/** The Roles section, grouped by device type (spec §3.3): per type, radio-style role
 * badges, rename/delete acting on the selected role, the selected role's verb chips
 * rendered ONCE, and an in-place add form whose type is implied by the block — which is
 * what removed both the old type <select> (the horizontal-overflow culprit) and the
 * separate "Manage roles" section. */
export function RolesSection() {
  const catalog = useCatalogStore((s) => s.catalog)
  const roles = useDocStore((s) => s.roles)
  const groups = roleGroups(roles, catalog)
  if (groups.length === 0) {
    return <p className="px-1 text-xs text-hint">no device types in the catalog yet</p>
  }
  return (
    <div className="space-y-2">
      {groups.map((g) => (
        <RoleTypeBlock key={g.type} group={g} catalog={catalog} />
      ))}
    </div>
  )
}

function RoleTypeBlock({ group, catalog }: { group: RoleTypeGroup; catalog: Catalog | null }) {
  const renameRole = useDocStore((s) => s.renameRole)
  const removeRole = useDocStore((s) => s.removeRole)
  const focusedRole = useDocStore((s) => s.focusedRole)
  const [picked, setPicked] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cancelled = useRef(false)
  const selected = effectiveSelection(group.roles, picked)

  // A Problems-row click names a role (docStore.focusedRole). When it is one of ours,
  // make it the active badge — so the highlight and the verb chips agree on which role is
  // in view — and scroll it into view, the same jump treatment blocks get from the panel.
  useEffect(() => {
    if (focusedRole !== null && group.roles.includes(focusedRole)) {
      setPicked(focusedRole)
      document
        .getElementById(`role-${focusedRole}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [focusedRole, group.roles])

  const startRename = () => {
    if (!selected) return
    setEditing(true)
    setDraft(selected)
    setError(null)
    cancelled.current = false
  }
  const commitRename = () => {
    if (!selected) return
    const err = draft && draft !== selected ? renameRole(selected, draft) : null
    setError(err)
    if (err === null) {
      setEditing(false)
      if (draft) setPicked(draft)
    }
  }

  const verbs = group.known ? (catalog?.device_types[group.type] ?? {}) : null
  return (
    <div className="rounded border border-slate-200 bg-white p-1.5">
      <p className="mb-1 text-xs font-semibold text-slate-600">
        {group.type}
        {!group.known && <span className="ml-1 font-normal text-amber-600">— unknown device type</span>}
      </p>
      {group.roles.length === 0 ? (
        <p className="mb-1 px-1 text-xs text-hint">no roles yet — add one to use this device</p>
      ) : (
        <div className="mb-1 flex flex-wrap items-center gap-1">
          {group.roles.map((name) =>
            editing && name === selected ? (
              <input
                key={name}
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onBlur={() => {
                  if (cancelled.current) {
                    cancelled.current = false
                    return
                  }
                  commitRename()
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') commitRename()
                  if (e.key === 'Escape') {
                    cancelled.current = true
                    setEditing(false)
                  }
                }}
                className={controlClass({ mono: true, width: 'w-28' })}
              />
            ) : (
              <button
                key={name}
                id={`role-${name}`}
                onClick={() => {
                  setPicked(name)
                  setEditing(false)
                  setError(null)
                }}
                className={
                  badgeClass({ active: name === selected }) +
                  (focusedRole === name ? ' ring-2 ring-amber-400' : '')
                }
              >
                {name}
              </button>
            ),
          )}
          <span className="ml-auto flex items-center">
            <IconButton icon={Pencil} label="Rename selected role" onClick={startRename} />
            <IconButton
              icon={X}
              label="Delete selected role"
              destructive
              onClick={() => {
                if (!selected) return
                const err = removeRole(selected)
                setError(err)
                if (err === null) setPicked(null)
              }}
            />
          </span>
        </div>
      )}
      {error && <p className="mb-1 text-xs text-red-600">{error}</p>}
      {selected !== null && verbs !== null && (
        <div className="flex flex-wrap gap-1">
          {Object.entries(verbs).map(([verb, spec]) => (
            <Chip
              key={verb}
              id={`palette-verb-${selected}-${verb}`}
              payload={{ source: 'palette-verb', role: selected, verb, verbKind: spec.kind }}
            >
              <KindIcon kind={spec.kind === 'measure' ? 'measure' : 'command'} className="mr-1" />
              {verb}
            </Chip>
          ))}
        </div>
      )}
      <AddRoleForm type={group.type} onAdded={setPicked} />
    </div>
  )
}

/** "+ add role" reveal form. The type is implied by the enclosing block, so the row is
 * just name + Add — which is precisely what removed the old three-control row that
 * overflowed the 256px palette (finding 2's screenshot). Same dismiss-on-outside-click
 * boundary reasoning as Canvas's ScopeSwitcher: the trigger unmounts while the form is
 * open, so wrapping the form row alone is correct. */
function AddRoleForm({ type, onAdded }: { type: string; onAdded: (name: string) => void }) {
  const addRole = useDocStore((s) => s.addRole)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const close = () => {
    setAdding(false)
    setName('')
    setError(null)
  }
  const addingRef = useDismissable(adding, close)
  const add = () => {
    if (!name) return
    const err = addRole(name, type)
    setError(err)
    if (err === null) {
      onAdded(name)
      close()
    }
  }
  if (!adding) {
    return (
      <button onClick={() => setAdding(true)} className={inlineButtonClass({ subtle: true }) + ' mt-1'}>
        <Plus size={12} aria-hidden className="mr-0.5" />add role
      </button>
    )
  }
  return (
    <div ref={addingRef} className="mt-1 space-y-1">
      <div className="flex items-center gap-1">
        <input
          autoFocus
          value={name}
          placeholder="role name"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add()
            if (e.key === 'Escape') close()
          }}
          className={controlClass({ mono: true, width: 'w-28' })}
        />
        <button onClick={add} className={inlineButtonClass()}>
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
