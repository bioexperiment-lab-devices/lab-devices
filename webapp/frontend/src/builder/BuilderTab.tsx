import { useEffect, useState } from 'react'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { activeList, redo, undo, useDocStore } from '../stores/docStore'
import { useCatalogStore } from '../stores/catalogStore'
import { parseSlotDroppableId, type DragPayload } from './dnd'
import { findNode, newGroupRefNode, newPaletteNode, newVerbNode, type BlockNode } from './tree'
import { blockSummary } from './summary'
import { Palette } from './Palette'
import { Canvas } from './Canvas'
import { Inspector } from './Inspector'
import { Toolbar } from './Toolbar'
import { ProblemsPanel } from './ProblemsPanel'
import { useValidation } from './useValidation'
import { KindIcon } from '../ui/icons'
import { BLOCK_SECTIONS } from './paletteSections'

// Derived from BLOCK_SECTIONS (the palette's own data, paletteSections.ts) rather than
// hand-maintained, so the drag overlay can never disagree with the palette: renaming a chip's
// title there updates this map for free instead of leaving a second, silently stale registry.
// `group_ref` has no chip in BLOCK_SECTIONS (it drives per-group chips instead — design
// 2026-07-18 §6/§7), so it never appears here; `dragOverlayInfo`'s `palette-group` arm handles
// that case separately.
const BLOCK_TITLES: Record<string, string> = Object.fromEntries(
  BLOCK_SECTIONS.flatMap((s) => s.items.map((i) => [i.kind, i.title])),
)

/** Label + kind for the drag overlay (spec §3: the overlay is a consumer of the
 * kind-icon map, same as canvas cards and palette chips). `kind` is null only when
 * a canvas drag's uid can't be resolved (shouldn't happen, but the overlay degrades
 * to text-only rather than crash). */
function dragOverlayInfo(payload: DragPayload): { label: string; kind: BlockNode['kind'] | null } {
  if (payload.source === 'palette-block') {
    return { label: BLOCK_TITLES[payload.kind] ?? payload.kind, kind: payload.kind }
  }
  // A dragged group shows its own name rather than the generic "Group ref" — the whole point
  // of per-group chips (design 2026-07-18 §6) is that the author picked a specific group.
  if (payload.source === 'palette-group') {
    return { label: payload.name, kind: 'group_ref' }
  }
  if (payload.source === 'palette-verb') {
    return { label: `${payload.role} · ${payload.verb}`, kind: payload.verbKind }
  }
  // A canvas drag can originate from a group's body, not just the main tree (design §5.2's
  // scope switcher) — look the dragged uid up in whichever list `scope` currently names, or
  // the overlay silently falls back to the generic 'block' label for every in-group drag.
  // Reads via `activeList` (docStore.ts) rather than re-deriving the ternary here — this is a
  // plain function call, not the `useDocStore` hook, because this runs inside a plain render
  // helper (not a hook-eligible component) against `useDocStore.getState()`.
  const activeTree = activeList(useDocStore.getState())
  const node = findNode(activeTree, payload.uid)
  return { label: node ? blockSummary(node) : 'block', kind: node?.kind ?? null }
}

export function BuilderTab() {
  const loadCatalog = useCatalogStore((s) => s.load)
  const catalog = useCatalogStore((s) => s.catalog)
  useEffect(() => {
    void loadCatalog()
  }, [loadCatalog])
  useValidation()

  const [dragPayload, setDragPayload] = useState<DragPayload | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (
        t &&
        (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)
      ) {
        return
      }
      const mod = e.metaKey || e.ctrlKey
      if (mod && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        if (e.shiftKey) redo()
        else undo()
        return
      }
      if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        redo()
        return
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const s = useDocStore.getState()
        if (s.selectedUid) {
          e.preventDefault()
          s.removeBlock(s.selectedUid)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const onDragStart = (e: DragStartEvent) =>
    setDragPayload((e.active.data.current ?? null) as DragPayload | null)

  const onDragEnd = (e: DragEndEvent) => {
    setDragPayload(null)
    const payload = (e.active.data.current ?? null) as DragPayload | null
    if (!payload || !e.over) return
    const at = parseSlotDroppableId(String(e.over.id))
    if (!at) return
    const s = useDocStore.getState()
    if (payload.source === 'canvas') {
      s.moveBlock(payload.uid, at)
      return
    }
    if (payload.source === 'palette-block') {
      s.insertBlock(newPaletteNode(payload.kind), at)
      return
    }
    if (payload.source === 'palette-group') {
      s.insertBlock(newGroupRefNode(payload.name), at)
      return
    }
    const roleType = s.roles[payload.role]?.type
    const spec = roleType ? catalog?.device_types[roleType]?.[payload.verb] : undefined
    if (spec) s.insertBlock(newVerbNode(payload.role, payload.verb, spec), at)
  }

  return (
    <div className="flex h-full flex-col gap-2">
      <Toolbar />
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDragPayload(null)}
      >
        <div className="flex min-h-0 flex-1 gap-2">
          <Palette />
          <Canvas />
          <Inspector />
        </div>
        <DragOverlay>
          {dragPayload && (() => {
            const { label, kind } = dragOverlayInfo(dragPayload)
            return (
              <div className="flex items-center gap-1.5 rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-lg">
                {kind && <KindIcon kind={kind} />}
                {label}
              </div>
            )
          })()}
        </DragOverlay>
      </DndContext>
      <ProblemsPanel />
    </div>
  )
}
