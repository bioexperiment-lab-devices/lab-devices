import { useCallback, useEffect, useRef, useState } from 'react'
import { getExperiment, listExperiments, validateDoc } from '../api/studio'
import { savedMapping } from '../api/runs'
import { useDocStore } from '../stores/docStore'
import { useLabsStore } from '../stores/labsStore'
import { useNavStore } from '../stores/navStore'
import { useRunStore } from '../stores/runStore'
import { Check } from 'lucide-react'
import type { Diagnostic, ExperimentDocJson, ExperimentSummary } from '../types/doc'
import {
  buildMappingRows,
  mappingComplete,
  mergePrefill,
  prefillMapping,
  unmappedCount,
} from './preflight'

export function PreflightPanel() {
  const lab = useLabsStore((s) => s.selected)
  const devices = useLabsStore((s) => s.devices)
  const devicesError = useLabsStore((s) => s.devicesError)
  const startBusy = useRunStore((s) => s.startBusy)
  const startError = useRunStore((s) => s.startError)
  const startDiagnostics = useRunStore((s) => s.startDiagnostics)

  const [experiments, setExperiments] = useState<ExperimentSummary[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [doc, setDoc] = useState<ExperimentDocJson | null>(null)
  const [docError, setDocError] = useState<string | null>(null)
  const [diagnostics, setDiagnostics] = useState<Diagnostic[] | null>(null)
  const [validating, setValidating] = useState(false)
  const [chosen, setChosen] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState<Record<string, string>>({})
  const gen = useRef(0)

  const loadExperiments = useCallback(() => {
    setListError(null)
    listExperiments()
      .then((items) => {
        setExperiments(items)
        const builderId = useDocStore.getState().serverId
        const fallback = items.length > 0 ? items[0].id : null
        setSelectedId(items.some((i) => i.id === builderId) ? builderId : fallback)
      })
      .catch((e: unknown) => setListError(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(() => {
    loadExperiments()
    if (useLabsStore.getState().selected !== null) void useLabsStore.getState().refreshDevices()
  }, [loadExperiments])

  const loadSelection = useCallback((id: string, currentLab: string | null) => {
    const token = ++gen.current
    setDoc(null)
    setDocError(null)
    setDiagnostics(null)
    setChosen({})
    setSaved({})
    useRunStore.setState({ startError: null, startDiagnostics: null })
    setValidating(true)
    getExperiment(id)
      .then(async (res) => {
        if (gen.current !== token) return
        setDoc(res.doc)
        const [validation, savedMap] = await Promise.all([
          validateDoc(res.doc),
          currentLab !== null ? savedMapping(id, currentLab).catch(() => ({})) : Promise.resolve({}),
        ])
        if (gen.current !== token) return
        setDiagnostics(validation.diagnostics)
        setSaved(savedMap)
        setChosen(prefillMapping(res.doc.workflow.roles ?? {}, useLabsStore.getState().devices, savedMap))
      })
      .catch((e: unknown) => {
        if (gen.current === token) setDocError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (gen.current === token) setValidating(false)
      })
  }, [])

  useEffect(() => {
    if (selectedId !== null) loadSelection(selectedId, lab)
  }, [selectedId, lab, loadSelection])

  // W6 (a): re-apply the prefill when the roster lands after loadSelection resolved.
  useEffect(() => {
    if (doc === null) return
    setChosen((c) => mergePrefill(c, doc.workflow.roles ?? {}, devices, saved))
  }, [doc, devices, saved])

  if (lab === null) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-500">
        <p className="mb-2">Select a lab first.</p>
        <button onClick={() => useNavStore.getState().setTab('Devices')} className="rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100">
          Go to Devices
        </button>
      </div>
    )
  }

  const rows = doc !== null ? buildMappingRows(doc.workflow.roles ?? {}, devices, chosen) : []
  const unmapped = unmappedCount(rows)
  const clean = diagnostics !== null && diagnostics.length === 0
  const canStart = clean && mappingComplete(rows) && !startBusy && selectedId !== null
  const problems = [...(diagnostics ?? []), ...(startDiagnostics ?? [])]

  return (
    <div className="mx-auto max-w-2xl space-y-4 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="text-sm font-semibold">Start a run on {lab}</h2>
      {listError && (
        <div className="text-xs text-red-600">
          <p>{listError}</p>
          <button
            onClick={loadExperiments}
            className="mt-1 rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100"
          >
            Retry
          </button>
        </div>
      )}
      {experiments !== null && experiments.length === 0 && (
        <p className="text-sm text-slate-500">No saved experiments — build one first.</p>
      )}
      {experiments !== null && experiments.length > 0 && (
        <label className="block text-xs">
          <span className="mb-0.5 block text-slate-500">Experiment</span>
          <select
            value={selectedId ?? ''}
            onChange={(e) => setSelectedId(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          >
            {experiments.map((e) => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
        </label>
      )}
      {docError && (
        <div className="text-xs text-red-600">
          <p>{docError}</p>
          <button
            onClick={() => selectedId !== null && loadSelection(selectedId, lab)}
            className="mt-1 rounded border border-slate-300 px-3 py-1 text-xs hover:bg-slate-100"
          >
            Retry
          </button>
        </div>
      )}
      {devicesError && <p className="text-xs text-red-600">{devicesError}</p>}
      {doc !== null && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-caption">Role mapping</p>
          {rows.length === 0 && <p className="text-xs text-hint">this experiment defines no roles</p>}
          {rows.map((row) => (
            <label key={row.role} className="flex items-center gap-2 text-xs">
              <span className="w-32 truncate font-mono">{row.role}</span>
              <span className="w-24 text-caption">{row.type}</span>
              <select
                value={row.selected ?? ''}
                onChange={(e) =>
                  setChosen((c) => ({ ...c, [row.role]: e.target.value }))
                }
                className="flex-1 rounded border border-slate-300 px-2 py-1"
              >
                <option value="" disabled>
                  {row.options.length === 0 ? `no ${row.type} devices in ${lab}` : 'pick a device…'}
                </option>
                {row.options.map((d) => (
                  <option key={d.id} value={d.id}>{d.id}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
      <div className="text-xs">
        {validating && <span className="text-hint">validating…</span>}
        {clean && !validating && (
          <>
            <span className="inline-flex items-center gap-1 text-emerald-700">
              <Check size={14} aria-hidden /> workflow valid
            </span>
            {unmapped > 0 && (
              <p className="mt-1 text-amber-700">
                {unmapped} role{unmapped === 1 ? '' : 's'} unmapped — Start
                stays disabled until every role has a device.
              </p>
            )}
          </>
        )}
      </div>
      {problems.length > 0 && (
        <ul className="max-h-40 space-y-0.5 overflow-y-auto rounded border border-red-100 bg-red-50 p-2 text-xs">
          {problems.map((d, i) => (
            <li key={i}>
              <span className="mr-1 rounded bg-white px-1 font-mono text-[10px]">{d.category}</span>
              <span className="mr-1 font-mono text-[10px] text-caption">{d.path}</span>
              {d.message}
            </li>
          ))}
        </ul>
      )}
      {startError && <p className="text-xs text-red-600">{startError}</p>}
      <button
        disabled={!canStart}
        onClick={() => {
          if (selectedId === null) return
          const role_mapping = Object.fromEntries(
            rows.filter((r) => r.selected !== null).map((r) => [r.role, r.selected as string]),
          )
          void useRunStore.getState().start({ experiment_id: selectedId, lab, role_mapping })
        }}
        className="w-full rounded bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-40"
      >
        {startBusy ? 'Starting…' : 'Start run'}
      </button>
    </div>
  )
}
