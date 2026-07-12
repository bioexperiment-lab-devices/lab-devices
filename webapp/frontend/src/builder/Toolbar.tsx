import { useState } from 'react'
import { ApiError } from '../api/client'
import { createExperiment, duplicateExperiment, replaceExperiment } from '../api/studio'
import {
  loadDoc,
  newDoc,
  redo,
  selectContent,
  selectDirty,
  selectDoc,
  snapshotOf,
  undo,
  useDocStore,
  useTemporal,
} from '../stores/docStore'
import { docToTree } from './convert'
import { TextField } from './fields'
import { LoadDialog } from './LoadDialog'

function ValidationChip() {
  const validating = useDocStore((s) => s.validating)
  const validationError = useDocStore((s) => s.validationError)
  const count = useDocStore((s) => s.diagnostics.length)
  if (validating) {
    return <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-500">validating…</span>
  }
  if (validationError !== null) {
    return <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">validation unavailable</span>
  }
  if (count > 0) {
    return (
      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-700">
        {count} problem{count === 1 ? '' : 's'}
      </span>
    )
  }
  return <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">valid</span>
}

const buttonClass =
  'rounded border border-slate-300 bg-white px-2 py-1 text-xs hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-white'

export function Toolbar() {
  const name = useDocStore((s) => s.name)
  const setName = useDocStore((s) => s.setName)
  const serverId = useDocStore((s) => s.serverId)
  const markSaved = useDocStore((s) => s.markSaved)
  const dirty = useDocStore(selectDirty)
  const canUndo = useTemporal((t) => t.pastStates.length > 0)
  const canRedo = useTemporal((t) => t.futureStates.length > 0)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadOpen, setLoadOpen] = useState(false)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'name_conflict') {
        setError(`name already taken — rename the experiment or use Save as`)
      } else {
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setBusy(false)
    }
  }

  const save = () =>
    run(async () => {
      const state = useDocStore.getState()
      const doc = selectDoc(state)
      const snapshot = snapshotOf(selectContent(state))
      const res = state.serverId
        ? await replaceExperiment(state.serverId, doc)
        : await createExperiment(doc)
      markSaved(res.id, snapshot)
    })

  const saveAs = () => {
    const newName = window.prompt('Save as…', `${name} (copy)`)
    if (!newName) return
    const previousName = useDocStore.getState().name
    void run(async () => {
      useDocStore.getState().setName(newName)
      const snapshot = snapshotOf(selectContent(useDocStore.getState()))
      try {
        const res = await createExperiment(selectDoc(useDocStore.getState()))
        markSaved(res.id, snapshot)
      } catch (e) {
        useDocStore.getState().setName(previousName)
        throw e
      }
    })
  }

  const duplicate = () => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    return run(async () => {
      const id = useDocStore.getState().serverId
      if (!id) return
      const res = await duplicateExperiment(id)
      loadDoc(docToTree(res.doc), res.id)
    })
  }

  const fresh = () => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    newDoc()
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="w-64">
        <TextField value={name} onCommit={setName} placeholder="experiment name" />
      </div>
      {dirty && <span title="Unsaved changes" className="text-amber-500">●</span>}
      <ValidationChip />
      {error && <span className="truncate text-xs text-red-600">{error}</span>}
      <span className="ml-auto flex items-center gap-1">
        <button className={buttonClass} disabled={!canUndo} onClick={undo} title="Undo (⌘Z)">
          ↶
        </button>
        <button className={buttonClass} disabled={!canRedo} onClick={redo} title="Redo (⇧⌘Z)">
          ↷
        </button>
        <button className={buttonClass} disabled={busy} onClick={fresh}>
          New
        </button>
        <button className={buttonClass} disabled={busy} onClick={() => setLoadOpen(true)}>
          Load
        </button>
        <button className={buttonClass} disabled={busy} onClick={() => void save()}>
          Save
        </button>
        <button className={buttonClass} disabled={busy} onClick={saveAs}>
          Save as
        </button>
        <button
          className={buttonClass}
          disabled={busy || serverId === null}
          title={serverId === null ? 'Save first' : 'Duplicate on the server and open the copy'}
          onClick={() => void duplicate()}
        >
          Duplicate
        </button>
      </span>
      {loadOpen && <LoadDialog onClose={() => setLoadOpen(false)} />}
    </div>
  )
}
