import { useEffect, useState } from 'react'
import { deleteExperiment, getExperiment, listExperiments } from '../api/studio'
import type { ExperimentSummary } from '../types/doc'
import { loadDoc, selectDirty, useDocStore } from '../stores/docStore'
import { DocConvertError, docToTree } from './convert'
import { exportFilename, serializeDoc, triggerDownload } from './files'

export function LoadDialog(props: { onClose: () => void }) {
  const [items, setItems] = useState<ExperimentSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const refresh = () => {
    setError(null)
    listExperiments()
      .then(setItems)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }
  useEffect(refresh, [])

  const open = async (id: string) => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    try {
      const res = await getExperiment(id)
      loadDoc(docToTree(res.doc), res.id)
      props.onClose()
    } catch (e) {
      setError(
        e instanceof DocConvertError
          ? `cannot open in the builder: ${e.message}`
          : e instanceof Error
            ? e.message
            : String(e),
      )
    }
  }

  const remove = async (item: ExperimentSummary) => {
    if (!window.confirm(`Delete experiment '${item.name}'? Records are kept.`)) return
    try {
      await deleteExperiment(item.id)
      if (useDocStore.getState().serverId === item.id) {
        // server copy is gone: next Save must create, and the open doc is unsaved now
        useDocStore.setState({ serverId: null, savedSnapshot: '' })
      }
      refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const exportItem = async (item: ExperimentSummary) => {
    setError(null)
    try {
      const res = await getExperiment(item.id)
      // the STORED doc, no convert round-trip — works for docs the builder can't open
      triggerDownload(exportFilename(res.doc.name), serializeDoc(res.doc))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const shown = (items ?? []).filter(
    (i) =>
      i.name.toLowerCase().includes(search.toLowerCase()) ||
      (i.description ?? '').toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-black/30"
      onClick={props.onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[70vh] w-[28rem] overflow-y-auto rounded-lg bg-white p-4 shadow-xl"
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Load experiment</h2>
          <button onClick={props.onClose} className="text-slate-400 hover:text-slate-700">✕</button>
        </div>
        <input
          autoFocus
          value={search}
          placeholder="search…"
          onChange={(e) => setSearch(e.target.value)}
          className="mb-2 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
        {items === null && !error && <p className="text-xs text-slate-400">loading…</p>}
        {items !== null && shown.length === 0 && (
          <p className="text-xs text-slate-400">no experiments{search ? ' match' : ' saved yet'}</p>
        )}
        <ul className="divide-y divide-slate-100">
          {shown.map((item) => (
            <li key={item.id} className="flex items-center gap-2 py-1.5">
              <button onClick={() => void open(item.id)} className="min-w-0 flex-1 text-left">
                <p className="truncate text-sm">{item.name}</p>
                <p className="truncate text-xs text-slate-400">
                  {item.description ?? 'no description'} · updated {item.updated_at.slice(0, 16)}
                </p>
              </button>
              <button
                title="Export experiment as JSON"
                onClick={() => void exportItem(item)}
                className="text-xs text-slate-300 hover:text-sky-600"
              >
                ⭳
              </button>
              <button
                title="Delete experiment"
                onClick={() => void remove(item)}
                className="text-xs text-slate-300 hover:text-red-600"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
