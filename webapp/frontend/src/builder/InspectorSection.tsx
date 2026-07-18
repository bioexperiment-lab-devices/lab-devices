import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { sectionHeaderClass } from '../ui/controls'

/** A collapsible tail section of the block form (design 2026-07-18 §4).
 *
 * Collapsed by default, EXCEPT when `summary` is non-null — a section holding a non-default
 * value opens itself. The caller passes `timingSummary(...)`/`failureSummary(...)`, whose
 * null-means-all-defaults contract makes `summary !== null` the whole auto-open rule.
 *
 * Collapsing a section that holds a value is allowed, because the collapsed header renders
 * that value. The promise is that a configured value is never HIDDEN, not that a section is
 * never closed — locking a non-default section open would trade an honest affordance for a
 * control that mysteriously refuses to work.
 *
 * Open state is deliberately NOT lifted or persisted: `Inspector` mounts `BlockForm` with
 * `key={node.uid}`, so selecting another block remounts this and the auto-open computation
 * re-runs against the new node. No disclosure state carries between blocks, and two people
 * looking at one document see the same panel. */
export function InspectorSection(props: {
  title: string
  summary: string | null
  children: ReactNode
}) {
  const [open, setOpen] = useState(props.summary !== null)
  const Chevron = open ? ChevronDown : ChevronRight
  return (
    <div className="mt-2 border-t border-slate-200 pt-2">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={sectionHeaderClass()}
      >
        <Chevron size={12} aria-hidden className="shrink-0" />
        <span className="shrink-0">{props.title}</span>
        {!open && props.summary !== null && (
          <span
            title={props.summary}
            className="min-w-0 truncate font-normal normal-case text-caption"
          >
            · {props.summary}
          </span>
        )}
      </button>
      {open && <div className="pt-1">{props.children}</div>}
    </div>
  )
}
