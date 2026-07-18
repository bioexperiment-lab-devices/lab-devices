import { useEffect, useRef, useState } from 'react'
import { Download, X } from 'lucide-react'
import { deleteExperiment, getExperiment, listExperiments } from '../api/studio'
import type { ExperimentSummary } from '../types/doc'
import { loadDoc, selectDirty, useDocStore } from '../stores/docStore'
import { IconButton } from '../ui/IconButton'
import { DocConvertError, docToTree } from './convert'
import { exportFilename, serializeDoc, triggerDownload } from './files'

export function LoadDialog(props: { onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    ref.current?.showModal()
    inputRef.current?.focus()
  }, [])
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
    <dialog
      ref={ref}
      onClose={props.onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) props.onClose()
      }}
      className="m-auto w-[28rem] rounded-lg bg-white p-0 shadow-xl backdrop:bg-black/30"
    >
      <div className="flex max-h-[70vh] flex-col">
        <div className="shrink-0 p-4 pb-2">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Load experiment</h2>
            <IconButton icon={X} label="Close" onClick={props.onClose} />
          </div>
          <input
            ref={inputRef}
            value={search}
            placeholder="search…"
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          {error && <p className="mb-2 text-xs text-red-600">{error}</p>}
          {items === null && !error && <p className="text-xs text-hint">loading…</p>}
          {items !== null && shown.length === 0 && (
            <p className="text-xs text-hint">no experiments{search ? ' match' : ' saved yet'}</p>
          )}
          <ul className="divide-y divide-slate-100">
            {shown.map((item) => (
              <li key={item.id} className="flex items-center gap-2 py-1.5">
                <button
                  onClick={() => void open(item.id)}
                  className="min-w-0 flex-1 rounded px-1 text-left hover:bg-slate-100"
                >
                  <p className="truncate text-sm" title={item.name}>
                    {item.name}
                  </p>
                  <p className="truncate text-xs text-caption" title={item.description ?? 'no description'}>
                    {item.description ?? 'no description'} · updated {item.updated_at.slice(0, 16)}
                  </p>
                </button>
                <IconButton
                  icon={Download}
                  label="Export experiment as JSON"
                  onClick={() => void exportItem(item)}
                />
                <IconButton
                  icon={X}
                  label="Delete experiment"
                  destructive
                  onClick={() => void remove(item)}
                />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </dialog>
  )
}
