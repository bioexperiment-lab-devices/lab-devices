import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { TabShell, type Tab } from './shell/TabShell'

const PLACEHOLDERS: Record<Tab, string> = {
  Devices: 'Lab roster and device discovery arrive in increment W1/W3.',
  Builder: 'The visual experiment builder arrives in increment W3.',
  Run: 'Run controls, live chart, and prompts arrive in increment W5.',
  Records: 'Run records arrive in increment W5.',
}

export default function App() {
  const [tab, setTab] = useState<Tab>('Devices')
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <TabShell active={tab} onSelect={setTab} statusLine={describeHealth(health, error)}>
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
        {PLACEHOLDERS[tab]}
      </div>
    </TabShell>
  )
}
