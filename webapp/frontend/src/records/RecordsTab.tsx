import { useEffect } from 'react'
import { useRecordsStore } from '../stores/recordsStore'
import { RecordsTable } from './RecordsTable'
import { RecordViewer } from './RecordViewer'

export function RecordsTab() {
  const openId = useRecordsStore((s) => s.openId)
  useEffect(() => {
    void useRecordsStore.getState().refresh()
  }, [])
  if (openId !== null) return <RecordViewer id={openId} />
  return <RecordsTable />
}
