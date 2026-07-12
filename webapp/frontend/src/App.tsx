import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { TabShell, type Tab } from './shell/TabShell'
import { BuilderTab } from './builder/BuilderTab'

const PLACEHOLDERS: Partial<Record<Tab, string>> = {
  Devices: 'Lab roster and device discovery arrive with the Devices tab (this increment).',
  Run: 'Run controls, live chart, and prompts arrive in increments W4-W5.',
  Records: 'Run records arrive in increment W5.',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('Builder')
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <TabShell active={tab} onSelect={setTab} statusLine={describeHealth(health, error)}>
      {tab === 'Builder' ? (
        <BuilderTab />
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          {PLACEHOLDERS[tab]}
        </div>
      )}
    </TabShell>
  )
}
