import {
  CircleDot,
  Columns2,
  Group,
  Keyboard,
  OctagonX,
  Pencil,
  Play,
  Repeat,
  Split,
  SquareFunction,
  TextAlignJustify,
  Timer,
  TriangleAlert,
  type LucideIcon,
} from 'lucide-react'
import type { BlockNode } from '../builder/tree'

/** Block-kind → Lucide icon (spec §3). One map feeds the canvas cards, the palette
 * chips and the record snapshot, so the same kind always wears the same mark.
 * for_each is null: ∀ has no Lucide equivalent and stays typographic (settled 6). */
export const BLOCK_ICONS: Record<BlockNode['kind'], LucideIcon | null> = {
  command: Play,
  measure: CircleDot,
  wait: Timer,
  operator_input: Keyboard,
  serial: TextAlignJustify,
  parallel: Columns2,
  loop: Repeat,
  branch: Split,
  compute: SquareFunction,
  record: Pencil,
  abort: OctagonX,
  alarm: TriangleAlert,
  for_each: null,
  group_ref: Group,
}

/** abort keeps its heavier red mark (audit settled-item 5); alarm stays amber. */
const KIND_COLOR: Partial<Record<BlockNode['kind'], string>> = {
  abort: 'text-red-600',
  alarm: 'text-amber-600',
}

export function KindIcon(props: { kind: BlockNode['kind']; className?: string }) {
  const { kind, className } = props
  const color = KIND_COLOR[kind] ?? 'text-slate-500'
  const cls = `shrink-0 ${color} ${className ?? ''}`
  const Icon = BLOCK_ICONS[kind]
  if (Icon === null) {
    return (
      <span aria-hidden className={cls}>
        ∀
      </span>
    )
  }
  return <Icon size={14} aria-hidden className={cls} />
}
