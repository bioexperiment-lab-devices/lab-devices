import { useState, type ReactNode } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { ChevronDown, ChevronRight, Pencil, X } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import { BLOCK_SECTIONS, type BlockChip } from './paletteSections'
import type { DragPayload } from './dnd'
import { RolesPanel } from './RolesPanel'
import { StreamsPanel } from './StreamsPanel'
import { KindIcon } from '../ui/icons'
import { controlClass, inlineButtonClass } from '../ui/controls'
import { IconButton } from '../ui/IconButton'

function Chip(props: { id: string; payload: DragPayload; className?: string; children: ReactNode }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: props.id,
    data: props.payload,
  })
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      className={
        'flex cursor-grab select-none items-center rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-sm ' +
        (isDragging ? 'opacity-40' : 'hover:border-slate-400') +
        (props.className ? ' ' + props.className : '')
      }
    >
      {props.children}
    </div>
  )
}

function Section(props: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(props.defaultOpen ?? true)
  return (
    <section className="border-b border-slate-200 pb-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-1 py-1 text-xs font-semibold uppercase tracking-wide text-slate-500"
      >
        {props.title}
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
      </button>
      {open && <div className="px-1">{props.children}</div>}
    </section>
  )
}

/** All four block sections differ only by title and contents, so they render through one
 * helper. Four near-identical JSX blocks is what let Structure/Control/Repeat drift apart
 * independently in the first place (design 2026-07-18 §5). */
function BlockSection(props: { title: string; items: readonly BlockChip[] }) {
  return (
    <Section title={props.title}>
      <div className="flex flex-wrap gap-1">
        {props.items.map((item) => (
          <Chip
            key={item.kind}
            id={`palette-block-${item.kind}`}
            payload={{ source: 'palette-block', kind: item.kind }}
          >
            <KindIcon kind={item.kind} className="mr-1" />
            {item.title}
          </Chip>
        ))}
      </div>
    </Section>
  )
}

function AddRoleForm() {
  const catalog = useCatalogStore((s) => s.catalog)
  const addRole = useDocStore((s) => s.addRole)
  const [name, setName] = useState('')
  const [type, setType] = useState('')
  const [error, setError] = useState<string | null>(null)
  const types = Object.keys(catalog?.device_types ?? {})
  const add = () => {
    if (!name || !type) return
    const err = addRole(name, type)
    setError(err)
    if (!err) setName('')
  }
  return (
    <div className="mt-2 space-y-1">
      <div className="flex items-center gap-1">
        <input
          value={name}
          placeholder="role name"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          className={controlClass({ mono: true, width: 'w-24' })}
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className={controlClass()}
        >
          <option value="">type…</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button onClick={add} className={inlineButtonClass()}>
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

/** Lists declared groups for management (design §5.2's second editing scope). Each row's
 * primary interaction is now dragging its chip onto the canvas to insert a `group_ref` call
 * for that group, the same drag-from-palette pattern as the Structure/Control/Repeat/Roles
 * sections above. The pencil `IconButton` beside the chip is the scope switcher: it jumps
 * (Canvas.tsx) to that group's BODY for editing and turns blue (`active`) while that group's
 * scope is the one currently being edited. The trailing `X` still removes a group once nothing
 * cites it, refusing with a reason otherwise — the same "jump, delete-with-a-refusal-reason"
 * shape RolesPanel already gives roles. No rename control here: unlike roles/streams, nothing
 * in this task calls for one, and `renameGroup` already exists on the store for a future UI to
 * wire up without a frontend change here. */
function GroupsPanel() {
  const groups = useDocStore((s) => s.groups)
  const scope = useDocStore((s) => s.scope)
  const setScope = useDocStore((s) => s.setScope)
  const removeGroup = useDocStore((s) => s.removeGroup)
  const [error, setError] = useState<string | null>(null)
  const entries = Object.entries(groups)
  if (entries.length === 0) {
    return (
      <p className="px-1 text-xs text-hint">
        No groups yet — add one from the scope switcher above the canvas.
      </p>
    )
  }
  return (
    <>
      <ul className="space-y-1">
        {entries.map(([name, group]) => (
          <li key={name} className="flex items-center gap-1 text-sm">
            <Chip
              id={`palette-group-${name}`}
              payload={{ source: 'palette-group', name }}
              className="h-6"
            >
              <KindIcon kind="group_ref" className="mr-1" />
              <span className="font-mono">{name}</span>
              <span className="ml-1 text-caption">({group.params.join(', ')})</span>
            </Chip>
            <IconButton
              icon={Pencil}
              label="Edit this group's body"
              active={scope === name}
              onClick={() => setScope(name)}
            />
            <IconButton
              icon={X}
              label="Delete group"
              destructive
              className="ml-auto"
              onClick={() => setError(removeGroup(name))}
            />
          </li>
        ))}
        {error && <li className="text-xs text-red-600">{error}</li>}
      </ul>
      <p className="px-1 pt-1 text-xs text-hint">Drag a group onto the canvas to call it.</p>
    </>
  )
}

export function Palette() {
  const catalog = useCatalogStore((s) => s.catalog)
  const catalogError = useCatalogStore((s) => s.error)
  const roles = useDocStore((s) => s.roles)

  return (
    <aside className="w-64 shrink-0 space-y-2 overflow-y-auto border-r border-slate-200 bg-slate-50 p-2">
      {BLOCK_SECTIONS.map((s) => (
        <BlockSection key={s.title} title={s.title} items={s.items} />
      ))}
      <Section title="Roles">
        {catalogError && <p className="text-xs text-red-600">catalog unavailable: {catalogError}</p>}
        {Object.entries(roles).map(([role, def]) => {
          const verbs = catalog?.device_types[def.type]
          return (
            <div key={role} className="mb-2">
              <p className="py-1 font-mono text-xs text-slate-600">
                {role} <span className="text-caption">· {def.type}</span>
              </p>
              {verbs ? (
                <div className="flex flex-wrap gap-1">
                  {Object.entries(verbs).map(([verb, spec]) => (
                    <Chip
                      key={verb}
                      id={`palette-verb-${role}-${verb}`}
                      payload={{
                        source: 'palette-verb',
                        role,
                        verb,
                        verbKind: spec.kind,
                      }}
                    >
                      <KindIcon kind={spec.kind === 'measure' ? 'measure' : 'command'} className="mr-1" />
                      {verb}
                    </Chip>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-amber-600">unknown device type '{def.type}'</p>
              )}
            </div>
          )
        })}
        <AddRoleForm />
      </Section>
      <Section title="Manage roles" defaultOpen={false}>
        <RolesPanel />
      </Section>
      <Section title="Streams" defaultOpen={false}>
        <StreamsPanel />
      </Section>
      <Section title="Groups" defaultOpen={false}>
        <GroupsPanel />
      </Section>
    </aside>
  )
}
