import { useState, type ReactNode } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { ChevronDown, ChevronRight, X } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import type { ControlKind, RepeatKind, StructureKind } from './tree'
import type { DragPayload } from './dnd'
import { RolesPanel } from './RolesPanel'
import { StreamsPanel } from './StreamsPanel'
import { KindIcon } from '../ui/icons'
import { IconButton } from '../ui/IconButton'

const STRUCTURE: Array<{ kind: StructureKind; title: string }> = [
  { kind: 'serial', title: 'Serial' },
  { kind: 'parallel', title: 'Parallel' },
  { kind: 'loop', title: 'Loop' },
  { kind: 'branch', title: 'Branch' },
  { kind: 'wait', title: 'Wait' },
  { kind: 'operator_input', title: 'Operator input' },
]

const CONTROL: Array<{ kind: ControlKind; title: string }> = [
  { kind: 'compute', title: 'Compute' },
  { kind: 'record', title: 'Record' },
  { kind: 'alarm', title: 'Alarm' },
  { kind: 'abort', title: 'Abort' },
]

// for_each's ∀ (see KindIcon, ../ui/icons) cannot be confused with loop's Repeat icon (design
// 2026-07-16 §5.1); both chips drop through the SAME 'palette-structure' payload source as
// STRUCTURE/CONTROL above (PaletteKind already widened to include RepeatKind — tree.ts:13), so
// no second drag path.
const REPEAT: Array<{ kind: RepeatKind; title: string }> = [
  { kind: 'for_each', title: 'For each' },
  { kind: 'group_ref', title: 'Group ref' },
]

function Chip(props: { id: string; payload: DragPayload; children: ReactNode }) {
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
        (isDragging ? 'opacity-40' : 'hover:border-slate-400')
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
          className="w-24 rounded border border-slate-300 px-2 py-1 font-mono text-xs"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded border border-slate-300 px-2 py-1 text-xs"
        >
          <option value="">type…</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button onClick={add} className="rounded bg-slate-200 px-2 py-1 text-xs hover:bg-slate-300">
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

/** Lists declared groups for management (design §5.2's second editing scope): the scope
 * switcher (Canvas.tsx) is where a group's BODY is switched to and edited; this panel is
 * where it's found, jumped to, and removed once nothing cites it — the same "list, jump,
 * delete-with-a-refusal-reason" shape RolesPanel already gives roles. No rename control here:
 * unlike roles/streams, nothing in this task calls for one, and `renameGroup` already exists
 * on the store for a future UI to wire up without a frontend change here. */
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
    <ul className="space-y-1">
      {entries.map(([name, group]) => (
        <li key={name} className="flex items-center gap-1 text-sm">
          <button
            title="Edit this group's body"
            onClick={() => setScope(name)}
            className={
              'rounded px-1 font-mono text-xs hover:bg-slate-200 ' +
              (scope === name ? 'bg-blue-100 text-blue-700' : '')
            }
          >
            {name}
          </button>
          <span className="text-xs text-caption">
            ({group.params.join(', ')})
          </span>
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
  )
}

export function Palette() {
  const catalog = useCatalogStore((s) => s.catalog)
  const catalogError = useCatalogStore((s) => s.error)
  const roles = useDocStore((s) => s.roles)

  return (
    <aside className="w-64 shrink-0 space-y-2 overflow-y-auto border-r border-slate-200 bg-slate-50 p-2">
      <Section title="Structure">
        <div className="flex flex-wrap gap-1">
          {STRUCTURE.map((s) => (
            <Chip
              key={s.kind}
              id={`palette-structure-${s.kind}`}
              payload={{ source: 'palette-structure', kind: s.kind }}
            >
              <KindIcon kind={s.kind} className="mr-1" />
              {s.title}
            </Chip>
          ))}
        </div>
      </Section>
      <Section title="Control">
        <div className="flex flex-wrap gap-1">
          {CONTROL.map((c) => (
            <Chip
              key={c.kind}
              id={`palette-control-${c.kind}`}
              payload={{ source: 'palette-structure', kind: c.kind }}
            >
              <KindIcon kind={c.kind} className="mr-1" />
              {c.title}
            </Chip>
          ))}
        </div>
      </Section>
      <Section title="Repeat">
        <div className="flex flex-wrap gap-1">
          {REPEAT.map((r) => (
            <Chip
              key={r.kind}
              id={`palette-repeat-${r.kind}`}
              payload={{ source: 'palette-structure', kind: r.kind }}
            >
              <KindIcon kind={r.kind} className="mr-1" />
              {r.title}
            </Chip>
          ))}
        </div>
      </Section>
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
