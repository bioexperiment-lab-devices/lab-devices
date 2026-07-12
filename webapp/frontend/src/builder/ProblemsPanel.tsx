import { useState } from 'react'
import { useDocStore } from '../stores/docStore'

/** Bottom problems strip: every diagnostic from the last validate call. Rows that
 * resolved to a block select it and scroll it into view; doc-level rows (path
 * `workflow`, unknown structural paths) are listed under their raw path. */
export function ProblemsPanel() {
  const diagnostics = useDocStore((s) => s.diagnostics)
  const validationError = useDocStore((s) => s.validationError)
  const select = useDocStore((s) => s.select)
  const [open, setOpen] = useState(false)
  if (diagnostics.length === 0 && validationError === null) return null
  return (
    <div className="rounded-lg border border-red-200 bg-white">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-red-700"
      >
        <span>⚠ {validationError ? 'validation unavailable' : `${diagnostics.length} problem${diagnostics.length === 1 ? '' : 's'}`}</span>
        <span className="ml-auto text-slate-400">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <ul className={`max-h-40 overflow-y-auto border-t border-red-100 px-3 py-1${validationError ? ' opacity-50' : ''}`}>
          {validationError && (
            <li className="py-0.5 text-xs text-amber-700">
              {validationError} — the problems below are from the last successful check and may be stale
            </li>
          )}
          {diagnostics.map((d, i) => (
            <li key={i} className="py-0.5 text-xs">
              <button
                disabled={d.uid === null}
                onClick={() => {
                  if (!d.uid) return
                  select(d.uid)
                  document
                    .getElementById(`block-${d.uid}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                }}
                className="text-left enabled:hover:underline disabled:cursor-default"
              >
                <span className="mr-1 rounded bg-slate-200 px-1 font-mono text-[10px]">{d.category}</span>
                <span className="mr-1 font-mono text-[10px] text-slate-400">{d.path}</span>
                {d.message}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
