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
import { findNode, newPaletteNode, newVerbNode, type BlockNode } from './tree'
import { blockSummary } from './summary'
import { Palette } from './Palette'
import { Canvas } from './Canvas'
import { Inspector } from './Inspector'
import { Toolbar } from './Toolbar'
import { ProblemsPanel } from './ProblemsPanel'
import { useValidation } from './useValidation'
import { KindIcon } from '../ui/icons'

const STRUCTURE_TITLES: Record<string, string> = {
  serial: 'Serial',
  parallel: 'Parallel',
  loop: 'Loop',
  branch: 'Branch',
  wait: 'Wait',
  operator_input: 'Operator input',
  compute: 'Compute',
  record: 'Record',
  abort: 'Abort',
  alarm: 'Alarm',
  for_each: 'For each',
  group_ref: 'Group ref',
}

/** Label + kind for the drag overlay (spec §3: the overlay is a consumer of the
 * kind-icon map, same as canvas cards and palette chips). `kind` is null only when
 * a canvas drag's uid can't be resolved (shouldn't happen, but the overlay degrades
 * to text-only rather than crash). */
function dragOverlayInfo(payload: DragPayload): { label: string; kind: BlockNode['kind'] | null } {
  if (payload.source === 'palette-structure') {
    return { label: STRUCTURE_TITLES[payload.kind] ?? payload.kind, kind: payload.kind }
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
    if (payload.source === 'palette-structure') {
      s.insertBlock(newPaletteNode(payload.kind), at)
      return
    }
    const roleType = s.roles[payload.role]?.type
    const spec = roleType ? catalog?.device_types[roleType]?.[payload.verb] : undefined
    if (spec) s.insertBlock(newVerbNode(payload.role, payload.verb, spec), at)
  }

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col gap-2">
      <Toolbar />
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDragPayload(null)}
      >
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-slate-200 bg-white">
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
