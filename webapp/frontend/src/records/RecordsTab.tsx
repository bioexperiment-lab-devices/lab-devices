import { useEffect } from 'react'
import { useRecordsStore } from '../stores/recordsStore'
import { RecordsTable } from './RecordsTable'

export function RecordsTab() {
  const openId = useRecordsStore((s) => s.openId)
  useEffect(() => {
    void useRecordsStore.getState().refresh()
  }, [])
  if (openId !== null) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        <button onClick={() => useRecordsStore.getState().open(null)} className="mb-2 text-xs hover:underline">← back to records</button>
        <p>record viewer lands in a later task</p>
      </div>
    )
  }
  return <RecordsTable />
}
