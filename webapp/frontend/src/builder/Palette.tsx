import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Pencil, X } from 'lucide-react'
import { useCatalogStore } from '../stores/catalogStore'
import { useDocStore } from '../stores/docStore'
import { BLOCK_SECTIONS, type BlockChip } from './paletteSections'
import { Chip } from './Chip'
import { RolesSection } from './RolesSection'
import { StreamsPanel } from './StreamsPanel'
import { ConstantsPanel } from './ConstantsPanel'
import { BindingsPanel } from './BindingsPanel'
import { KindIcon } from '../ui/icons'
import { IconButton } from '../ui/IconButton'

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

/** Lists declared groups for management (design §5.2's second editing scope). Each row's
 * primary interaction is now dragging its chip onto the canvas to insert a `group_ref` call
 * for that group, the same drag-from-palette pattern as the Flow/Data/Pause/Safety/Roles
 * sections above. The pencil `IconButton` beside the chip is the scope switcher: it jumps
 * (Canvas.tsx) to that group's BODY for editing and turns blue (`active`) while that group's
 * scope is the one currently being edited. The trailing `X` still removes a group once nothing
 * cites it, refusing with a reason otherwise — the same "jump, delete-with-a-refusal-reason"
 * shape the roles UI (RolesSection) already gives roles. No rename control here: unlike roles/streams, nothing
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
            {/* min-w-0 on the chip + truncate on the name+params span: a long signature must
                ellipsize inside the 256px palette (with its full text in `title`), the same
                way role badges and the device-type heading do — without this the chip sizes to
                the untruncated signature and makes the palette a horizontal scroller (the metric
                the scope-switcher-long-group capture state exercises now that it opens this
                panel). The icon stays shrink-0 so the signature is what gives. */}
            <Chip
              id={`palette-group-${name}`}
              payload={{ source: 'palette-group', name }}
              className="h-6 min-w-0"
            >
              <KindIcon kind="group_ref" className="mr-1 shrink-0" />
              {/* Name + params share one truncating region so a multi-param signature ellipsizes
                  inside the chip instead of spilling under the edit/delete icons (#3); the Chip
                  itself clips to its rounded box. Full signature in `title`. */}
              <span
                className="min-w-0 truncate font-mono"
                title={`${name}(${group.params.map((p) => p.name).join(', ')})`}
              >
                {name}
                <span className="ml-1 text-caption">
                  ({group.params.map((p) => p.name).join(', ')})
                </span>
              </span>
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
  const catalogError = useCatalogStore((s) => s.error)

  return (
    <aside className="w-64 shrink-0 space-y-2 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
      {BLOCK_SECTIONS.map((s) => (
        <BlockSection key={s.title} title={s.title} items={s.items} />
      ))}
      <Section title="Roles">
        {catalogError && <p className="text-xs text-red-600">catalog unavailable: {catalogError}</p>}
        <RolesSection />
      </Section>
      <Section title="Streams" defaultOpen={false}>
        <StreamsPanel />
      </Section>
      <Section title="Groups" defaultOpen={false}>
        <GroupsPanel />
      </Section>
      <Section title="Constants" defaultOpen={false}>
        <ConstantsPanel />
      </Section>
      <Section title="Bindings" defaultOpen={false}>
        <BindingsPanel />
      </Section>
    </aside>
  )
}
