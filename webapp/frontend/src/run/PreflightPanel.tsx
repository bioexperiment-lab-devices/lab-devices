import { useCallback, useEffect, useRef, useState } from 'react'
import { getExperiment, listExperiments, validateDoc } from '../api/studio'
import { savedMapping } from '../api/runs'
import { useDocStore } from '../stores/docStore'
import { useLabsStore } from '../stores/labsStore'
import { useNavStore } from '../stores/navStore'
import { useRunStore } from '../stores/runStore'
import type { Diagnostic, ExperimentDocJson, ExperimentSummary } from '../types/doc'
import { buildMappingRows, mappingComplete, prefillMapping } from './preflight'

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
  const gen = useRef(0)

  useEffect(() => {
    listExperiments()
      .then((items) => {
        setExperiments(items)
        const builderId = useDocStore.getState().serverId
        const fallback = items.length > 0 ? items[0].id : null
        setSelectedId(items.some((i) => i.id === builderId) ? builderId : fallback)
      })
      .catch((e: unknown) => setListError(e instanceof Error ? e.message : String(e)))
    if (useLabsStore.getState().selected !== null) void useLabsStore.getState().refreshDevices()
  }, [])

  const loadSelection = useCallback((id: string, currentLab: string | null) => {
    const token = ++gen.current
    setDoc(null)
    setDocError(null)
    setDiagnostics(null)
    setChosen({})
    setValidating(true)
    getExperiment(id)
      .then(async (res) => {
        if (gen.current !== token) return
        setDoc(res.doc)
        const [validation, saved] = await Promise.all([
          validateDoc(res.doc),
          currentLab !== null ? savedMapping(id, currentLab).catch(() => ({})) : Promise.resolve({}),
        ])
        if (gen.current !== token) return
        setDiagnostics(validation.diagnostics)
        setChosen(prefillMapping(res.doc.roles, useLabsStore.getState().devices, saved))
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

  const rows = doc !== null ? buildMappingRows(doc.roles, devices, chosen) : []
  const clean = diagnostics !== null && diagnostics.length === 0
  const canStart = clean && mappingComplete(rows) && !startBusy && selectedId !== null
  const problems = [...(diagnostics ?? []), ...(startDiagnostics ?? [])]

  return (
    <div className="mx-auto max-w-2xl space-y-4 rounded-lg border border-slate-200 bg-white p-6">
      <h2 className="text-sm font-semibold">Start a run on {lab}</h2>
      {listError && <p className="text-xs text-red-600">{listError}</p>}
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
      {docError && <p className="text-xs text-red-600">{docError}</p>}
      {devicesError && <p className="text-xs text-red-600">{devicesError}</p>}
      {doc !== null && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-slate-500">Role mapping</p>
          {rows.length === 0 && <p className="text-xs text-slate-400">this experiment defines no roles</p>}
          {rows.map((row) => (
            <label key={row.role} className="flex items-center gap-2 text-xs">
              <span className="w-32 truncate font-mono">{row.role}</span>
              <span className="w-24 text-slate-400">{row.type}</span>
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
        {validating && <span className="text-slate-400">validating…</span>}
        {clean && !validating && <span className="text-emerald-700">✓ workflow valid</span>}
      </div>
      {problems.length > 0 && (
        <ul className="max-h-40 space-y-0.5 overflow-y-auto rounded border border-red-100 bg-red-50 p-2 text-xs">
          {problems.map((d, i) => (
            <li key={i}>
              <span className="mr-1 rounded bg-white px-1 font-mono text-[10px]">{d.category}</span>
              <span className="mr-1 font-mono text-[10px] text-slate-400">{d.path}</span>
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
