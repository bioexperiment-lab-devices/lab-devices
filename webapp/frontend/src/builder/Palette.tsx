import { useState, type ReactNode } from 'react'
import { useDraggable } from '@dnd-kit/core'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import type { StructureKind } from './tree'
import type { DragPayload } from './dnd'
import { RolesPanel } from './RolesPanel'
import { StreamsPanel } from './StreamsPanel'

const STRUCTURE: Array<{ kind: StructureKind; title: string; icon: string }> = [
  { kind: 'serial', title: 'Serial', icon: '≡' },
  { kind: 'parallel', title: 'Parallel', icon: '∥' },
  { kind: 'loop', title: 'Loop', icon: '↻' },
  { kind: 'branch', title: 'Branch', icon: '⑂' },
  { kind: 'wait', title: 'Wait', icon: '⏱' },
  { kind: 'operator_input', title: 'Operator input', icon: '⌨' },
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
        'cursor-grab select-none rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-sm ' +
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
        <span>{open ? '−' : '+'}</span>
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
          className="w-24 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
        />
        <select
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded border border-slate-300 px-1 py-0.5 text-xs"
        >
          <option value="">type…</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <button onClick={add} className="rounded bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300">
          Add
        </button>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
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
              <span className="mr-1 opacity-60">{s.icon}</span>
              {s.title}
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
                {role} <span className="text-slate-400">· {def.type}</span>
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
                      <span className="mr-1 opacity-60">{spec.kind === 'measure' ? '◉' : '▸'}</span>
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
    </aside>
  )
}
