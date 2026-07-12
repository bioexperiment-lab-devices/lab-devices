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
import { redo, undo, useDocStore } from '../stores/docStore'
import { useCatalogStore } from '../stores/catalogStore'
import { parseSlotDroppableId, type DragPayload } from './dnd'
import { findNode, newStructureNode, newVerbNode } from './tree'
import { blockSummary } from './summary'
import { Palette } from './Palette'
import { Canvas } from './Canvas'
import { Inspector } from './Inspector'

const STRUCTURE_TITLES: Record<string, string> = {
  serial: 'Serial',
  parallel: 'Parallel',
  loop: 'Loop',
  branch: 'Branch',
  wait: 'Wait',
  operator_input: 'Operator input',
}

function dragLabel(payload: DragPayload): string {
  if (payload.source === 'palette-structure') return STRUCTURE_TITLES[payload.kind] ?? payload.kind
  if (payload.source === 'palette-verb') return `${payload.role} · ${payload.verb}`
  const node = findNode(useDocStore.getState().tree, payload.uid)
  return node ? blockSummary(node) : 'block'
}

export function BuilderTab() {
  const loadCatalog = useCatalogStore((s) => s.load)
  const catalog = useCatalogStore((s) => s.catalog)
  useEffect(() => {
    void loadCatalog()
  }, [loadCatalog])

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
      s.insertBlock(newStructureNode(payload.kind), at)
      return
    }
    const roleType = s.roles[payload.role]?.type
    const spec = roleType ? catalog?.device_types[roleType]?.[payload.verb] : undefined
    if (spec) s.insertBlock(newVerbNode(payload.role, payload.verb, spec), at)
  }

  return (
    <div className="flex h-[calc(100vh-9rem)] flex-col gap-2">
      <div data-slot="toolbar" />
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
          {dragPayload && (
            <div className="rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow-lg">
              {dragLabel(dragPayload)}
            </div>
          )}
        </DragOverlay>
      </DndContext>
    </div>
  )
}
