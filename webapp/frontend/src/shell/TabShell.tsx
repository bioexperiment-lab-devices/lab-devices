import type { ReactNode } from 'react'

export const TABS = ['Devices', 'Builder', 'Run', 'Records'] as const
export type Tab = (typeof TABS)[number]

export function TabShell(props: {
  active: Tab
  onSelect: (tab: Tab) => void
  statusLine: string
  lab: string | null
  children: ReactNode
}) {
  return (
    // h-screen flex column (not min-h-screen + page scroll): <main> owns the scrolling, so
    // nothing downstream needs to know the header's height — this is what retired
    // BuilderTab's h-[calc(100vh-9rem)], which hard-coded the old two-row header.
    <div className="flex h-screen flex-col bg-slate-100 text-slate-900">
      <header className="flex shrink-0 items-stretch gap-6 border-b border-slate-200 bg-white px-6">
        <h1 className="self-center py-3 text-lg font-semibold">Experiment Studio</h1>
        {/* items-stretch + border-b-2 on each tab: the buttons run the full header height,
            so the active tab's underline sits ON the header's own border — reading as an
            attached tab, not a floating pill. */}
        <nav className="flex items-stretch gap-1">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => props.onSelect(tab)}
              className={
                'inline-flex items-center border-b-2 px-3 text-sm transition-colors ' +
                (tab === props.active
                  ? 'border-slate-900 font-medium text-slate-900'
                  : 'border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900')
              }
            >
              {/* text-hint, not opacity-60: the numeral is a keyboard hint, so it must stay
                  quieter than the tab label — but `opacity-60` fades slate-600 to a measured
                  2.88:1 (probe R5), below the 4.5:1 AA floor. slate-500 at full alpha keeps
                  the same "quieter than the label" hierarchy against both the active
                  (slate-900) and inactive (slate-600) label and clears AA on this white
                  header. Do not reintroduce opacity here — see CLAUDE.md "Text colors". */}
              <span className="mr-1.5 font-mono text-xs text-hint">{i + 1}</span>
              {tab}
            </button>
          ))}
        </nav>
        <span className="ml-auto flex min-w-0 items-center gap-3 self-center py-3">
          <span
            className={
              'shrink-0 rounded-full px-2 py-0.5 text-xs ' +
              (props.lab ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-caption')
            }
          >
            {props.lab ? `lab: ${props.lab}` : 'no lab selected'}
          </span>
          {/* truncate + title: a long health string must shorten, not wrap the single row
              at 1024px (spec §3.2). min-w-0 on the parent is what lets it shrink. */}
          <span title={props.statusLine} className="truncate text-xs text-hint">
            {props.statusLine}
          </span>
        </span>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto p-6">{props.children}</main>
    </div>
  )
}
