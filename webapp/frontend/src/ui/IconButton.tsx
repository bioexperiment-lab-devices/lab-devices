import type { MouseEvent } from 'react'
import type { LucideIcon } from 'lucide-react'

/** The one component for per-row/per-card icon actions (spec §3). Contract:
 * ≥24×24px hit area (h-6 w-6), 14px icon, resting slate-500, hover slate-700
 * (destructive: red-600), focus-visible ring, title+aria-label always set.
 * Raw glyph characters for interactive controls are banned — see CLAUDE.md. */

export function iconButtonClass(destructive = false): string {
  return (
    'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-500 ' +
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ' +
    'disabled:opacity-40 ' +
    (destructive
      ? 'hover:bg-red-50 hover:text-red-600 '
      : 'hover:bg-slate-200 hover:text-slate-700 ')
  )
}

export function IconButton(props: {
  icon: LucideIcon
  label: string
  onClick: (e: MouseEvent<HTMLButtonElement>) => void
  destructive?: boolean
  disabled?: boolean
  className?: string
}) {
  const { icon: Icon, label, onClick, destructive, disabled, className } = props
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className={iconButtonClass(destructive) + (className ?? '')}
    >
      <Icon size={14} aria-hidden />
    </button>
  )
}
