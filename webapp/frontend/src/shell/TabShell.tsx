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
    <div className="min-h-screen bg-slate-100 text-slate-900">
      <header className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-baseline justify-between">
          <h1 className="text-lg font-semibold">Experiment Studio</h1>
          <span className="flex items-center gap-3">
            <span
              className={
                'rounded-full px-2 py-0.5 text-xs ' +
                (props.lab ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-caption')
              }
            >
              {props.lab ? `lab: ${props.lab}` : 'no lab selected'}
            </span>
            <span className="text-xs text-hint">{props.statusLine}</span>
          </span>
        </div>
        <nav className="mt-3 flex gap-2">
          {TABS.map((tab, i) => (
            <button
              key={tab}
              onClick={() => props.onSelect(tab)}
              className={
                'rounded-full px-4 py-1.5 text-sm transition-colors ' +
                (tab === props.active
                  ? 'bg-slate-900 text-white'
                  : 'bg-slate-200 text-slate-600 hover:bg-slate-300')
              }
            >
              <span className="mr-1.5 font-mono text-xs opacity-60">{i + 1}</span>
              {tab}
            </button>
          ))}
        </nav>
      </header>
      <main className="p-6">{props.children}</main>
    </div>
  )
}
