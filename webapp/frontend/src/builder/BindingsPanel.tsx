import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useActiveTree, useDocStore } from '../stores/docStore'
import { useScopeRefs } from './scopeRefs'
import { bindingIndex, type BindingRow, type WriterKind, type WriterRef } from './bindings'
import { KindIcon } from '../ui/icons'
import { IconButton } from '../ui/IconButton'

const WRITER_NOUN: Record<WriterKind, string> = { operator_input: 'input', compute: 'compute' }

function writerLabel(w: WriterRef): string {
  return w.label ? `${WRITER_NOUN[w.kind]} · ${w.label}` : WRITER_NOUN[w.kind]
}

function TypeBadge({ type }: { type: BindingRow['type'] }) {
  if (type === null) return <span className="shrink-0 text-xs text-hint">—</span>
  const showUnit = type.unit !== 'unitless' && (type.base === 'int' || type.base === 'number')
  return (
    <span
      className="shrink-0 rounded bg-slate-100 px-1 text-xs text-caption"
      title={showUnit ? `${type.base} in ${type.unit}` : type.base}
    >
      {type.base}
      {showUnit && <span className="text-hint">{`<${type.unit}>`}</span>}
    </span>
  )
}

function WriterIndicator({ row }: { row: BindingRow }) {
  if (row.writers.length === 0) {
    return row.decl ? (
      <span className="shrink-0 rounded bg-slate-100 px-1 text-xs text-caption">{row.decl}</span>
    ) : null
  }
  return (
    <span
      className="flex shrink-0 items-center gap-0.5"
      title={row.writers.map(writerLabel).join(', ')}
    >
      <KindIcon kind={row.writers[0].kind} />
      {row.writers.length > 1 && (
        <span className="text-xs text-caption">×{row.writers.length}</span>
      )}
    </span>
  )
}

/** Read-only overview of the active scope's bindings (design 2026-07-21). Names/writers/readers
 * come from the tree; type+unit from docStore.bindingTypes. Clicking a row (or a child) selects
 * and scrolls to that block, reusing ProblemsPanel's setScope -> select -> scrollToBlock order. */
export function BindingsPanel() {
  const { scope, group } = useScopeRefs()
  const activeTree = useActiveTree()
  const bindingTypes = useDocStore((s) => s.bindingTypes)
  const select = useDocStore((s) => s.select)
  const setScope = useDocStore((s) => s.setScope)
  const scrollToBlock = useDocStore((s) => s.scrollToBlock)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const rows = useMemo(
    () => bindingIndex(activeTree, group, bindingTypes),
    [activeTree, group, bindingTypes],
  )

  const jump = (uid: string): void => {
    setScope(scope) // rows are all in the active scope; keeps the ProblemsPanel navigation shape
    select(uid)
    scrollToBlock(uid)
  }
  const toggle = (name: string): void =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })

  if (rows.length === 0) {
    return (
      <p className="px-1 text-xs text-hint">
        No bindings in this scope yet — created by operator_input and compute blocks.
      </p>
    )
  }

  return (
    <ul className="space-y-1">
      {rows.map((row) => {
        const hasDetail = row.writers.length > 0 || row.readers.length > 0
        const isOpen = expanded.has(row.name)
        return (
          <li key={row.name}>
            <div className="flex items-center gap-1 text-sm">
              {hasDetail ? (
                <IconButton
                  icon={isOpen ? ChevronDown : ChevronRight}
                  label={isOpen ? 'Hide writers and readers' : 'Show writers and readers'}
                  onClick={() => toggle(row.name)}
                />
              ) : (
                <span className="inline-block h-6 w-6 shrink-0" aria-hidden />
              )}
              <button
                type="button"
                title={row.writers.length > 0 ? 'Go to where this binding is written' : row.name}
                disabled={row.writers.length === 0}
                onClick={() => row.writers[0] && jump(row.writers[0].uid)}
                className="flex min-w-0 flex-1 items-center gap-1 text-left enabled:hover:underline disabled:cursor-default"
              >
                <span className="min-w-0 flex-1 truncate font-mono text-caption" title={row.name}>
                  {row.name}
                </span>
              </button>
              <TypeBadge type={row.type} />
              <WriterIndicator row={row} />
            </div>
            {isOpen && hasDetail && (
              <ul className="ml-6 mt-0.5 space-y-0.5">
                {row.writers.map((w, i) => (
                  <li key={`w${i}`}>
                    <button
                      type="button"
                      onClick={() => jump(w.uid)}
                      className="flex w-full items-center gap-1 text-left text-xs text-caption hover:underline"
                    >
                      <KindIcon kind={w.kind} />
                      <span className="min-w-0 truncate">{writerLabel(w)}</span>
                    </button>
                  </li>
                ))}
                {row.readers.map((r, i) => (
                  <li key={`r${i}`}>
                    <button
                      type="button"
                      onClick={() => jump(r.uid)}
                      className="flex w-full items-center gap-1 text-left text-xs text-hint hover:underline"
                    >
                      <span className="min-w-0 truncate">read by {r.label ?? r.field}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </li>
        )
      })}
    </ul>
  )
}
