import { useRef, useState } from 'react'
import { Redo2, Undo2 } from 'lucide-react'
import { ApiError } from '../api/client'
import { inlineButtonClass } from '../ui/controls'
import {
  createExperiment,
  duplicateExperiment,
  importExperiment,
  replaceExperiment,
} from '../api/studio'
import {
  loadDoc,
  newDoc,
  pauseHistory,
  redo,
  resumeHistory,
  selectContent,
  selectDirty,
  selectDoc,
  snapshotOf,
  undo,
  useDocStore,
  useTemporal,
} from '../stores/docStore'
import { clearDraft } from '../stores/draftStorage'
import { DocConvertError, docToTree } from './convert'
import { exportFilename, parseDocFile, serializeDoc, triggerDownload } from './files'
import { TextField } from './fields'
import { LoadDialog } from './LoadDialog'

function ValidationChip() {
  const validating = useDocStore((s) => s.validating)
  const validationError = useDocStore((s) => s.validationError)
  const count = useDocStore((s) => s.diagnostics.length)
  if (validating) {
    return <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-700">validating…</span>
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

const buttonClass = inlineButtonClass()

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
  const [note, setNote] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setNote(null)
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
      pauseHistory()
      try {
        useDocStore.getState().setName(newName)
        const snapshot = snapshotOf(selectContent(useDocStore.getState()))
        try {
          const res = await createExperiment(selectDoc(useDocStore.getState()))
          markSaved(res.id, snapshot)
        } catch (e) {
          useDocStore.getState().setName(previousName)
          throw e
        }
      } finally {
        resumeHistory()
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
      clearDraft()
    })
  }

  const fresh = () => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    setError(null)
    setNote(null)
    newDoc()
    // The draft described the document just discarded. Autosave will write a fresh one for
    // the new document on its next tick; leaving the old one would resurrect it on refresh.
    clearDraft()
  }

  const exportDoc = () => {
    setError(null)
    setNote(null)
    try {
      const state = useDocStore.getState()
      triggerDownload(exportFilename(state.name), serializeDoc(selectDoc(state)))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const importFile = (file: File) => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    return run(async () => {
      const res = await importExperiment(parseDocFile(await file.text()))
      try {
        loadDoc(docToTree(res.doc), res.id)
        clearDraft()
        setNote(`imported as '${res.doc.name}'`)
      } catch (e) {
        if (!(e instanceof DocConvertError)) throw e
        // §7: it IS saved and runnable — it just can't render as a block tree.
        setNote(
          `imported as '${res.doc.name}' — saved, but can't open in the Builder: ${e.message}`,
        )
      }
    })
  }

  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="w-64">
        <TextField value={name} onCommit={setName} placeholder="experiment name" />
      </div>
      {/* amber-700, not amber-600: the dot is the only rendering of "unsaved", so it is
          meaning-carrying text and owes AA. amber-600 measured 3.20:1 (probe R5). */}
      {dirty && <span title="Unsaved changes" className="text-amber-700">●</span>}
      <ValidationChip />
      {error && (
        <span title={error} className="truncate text-xs text-red-600">
          {error}
        </span>
      )}
      {note && (
        <span title={note} className="truncate text-xs text-emerald-700">
          {note}
        </span>
      )}
      <span className="ml-auto flex items-center gap-3">
        <span className="flex items-center gap-1">
          <button
            className={buttonClass}
            disabled={!canUndo}
            onClick={undo}
            title="Undo (⌘Z)"
            aria-label="Undo"
          >
            <Undo2 size={16} aria-hidden />
          </button>
          <button
            className={buttonClass}
            disabled={!canRedo}
            onClick={redo}
            title="Redo (⇧⌘Z)"
            aria-label="Redo"
          >
            <Redo2 size={16} aria-hidden />
          </button>
        </span>
        <span aria-hidden className="h-4 w-px bg-slate-200" />
        <span className="flex items-center gap-1">
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
        <span aria-hidden className="h-4 w-px bg-slate-200" />
        <span className="flex items-center gap-1">
          <button
            className={buttonClass}
            disabled={busy}
            title="Download this experiment as a JSON file"
            onClick={exportDoc}
          >
            Export
          </button>
          <button
            className={buttonClass}
            disabled={busy}
            title="Import an experiment from a JSON file"
            onClick={() => fileRef.current?.click()}
          >
            Import
          </button>
        </span>
      </span>
      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = '' // re-importing the same file must re-fire change
          if (file) void importFile(file)
        }}
      />
      {loadOpen && <LoadDialog onClose={() => setLoadOpen(false)} />}
    </div>
  )
}
