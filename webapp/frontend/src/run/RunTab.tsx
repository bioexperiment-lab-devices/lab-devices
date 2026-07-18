import { useEffect } from 'react'
import { useRunStore } from '../stores/runStore'
import { PreflightPanel } from './PreflightPanel'
import { RunView } from './RunView'

export function RunTab() {
  const phase = useRunStore((s) => s.phase)
  useEffect(() => {
    void useRunStore.getState().attach()
  }, [])
  if (phase === 'unknown') {
    return <p className="p-6 text-sm text-caption">checking for an active run…</p>
  }
  if (phase === 'idle') return <PreflightPanel />
  // 'active' | 'terminal'
  return <RunView />
}
