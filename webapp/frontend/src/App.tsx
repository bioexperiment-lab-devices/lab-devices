import { useEffect, useState } from 'react'
import { getHealth, type Health } from './api/client'
import { describeHealth } from './api/health'
import { TabShell } from './shell/TabShell'
import { BuilderTab } from './builder/BuilderTab'
import { DevicesTab } from './devices/DevicesTab'
import { RecordsTab } from './records/RecordsTab'
import { useLabsStore } from './stores/labsStore'
import { useNavStore } from './stores/navStore'

export default function App() {
  const tab = useNavStore((s) => s.tab)
  const setTab = useNavStore((s) => s.setTab)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  const lab = useLabsStore((s) => s.selected)

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  return (
    <TabShell active={tab} onSelect={setTab} statusLine={describeHealth(health, error)} lab={lab}>
      {tab === 'Devices' && <DevicesTab />}
      {tab === 'Builder' && <BuilderTab />}
      {tab === 'Run' && (
        <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          Run controls land in the next task.
        </div>
      )}
      {tab === 'Records' && <RecordsTab />}
    </TabShell>
  )
}
