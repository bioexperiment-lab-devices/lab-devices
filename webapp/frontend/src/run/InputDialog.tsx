/** Modal for a pending OperatorInput (§9.4). Not dismissable by Escape/backdrop — the
 * run is parked on it — but it can be hidden behind the banner button and reopened. A
 * server 422 (invalid_value) keeps it open: the request stays pending (§7.4). */
import { useState } from 'react'
import { useRunStore } from '../stores/runStore'
import type { PendingInput } from '../types/runs'
import { validateInputValue } from './inputValue'

function Widget(props: {
  input: PendingInput
  raw: string | boolean
  setRaw: (v: string | boolean) => void
}) {
  const { input, raw, setRaw } = props
  if (input.type === 'bool') {
    return (
      <div className="flex gap-3 text-sm">
        {[true, false].map((v) => (
          <label key={String(v)} className="flex items-center gap-1">
            <input type="radio" checked={raw === v} onChange={() => setRaw(v)} />
            {v ? 'yes' : 'no'}
          </label>
        ))}
      </div>
    )
  }
  if (input.type === 'enum') {
    return (
      <select
        value={typeof raw === 'string' ? raw : ''}
        onChange={(e) => setRaw(e.target.value)}
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="" disabled>pick…</option>
        {(input.choices ?? []).map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    )
  }
  const hint = [
    input.min !== null ? `min ${input.min}` : null,
    input.max !== null ? `max ${input.max}` : null,
  ].filter(Boolean).join(', ')
  return (
    <div>
      <input
        autoFocus
        value={typeof raw === 'string' ? raw : ''}
        onChange={(e) => setRaw(e.target.value)}
        inputMode={input.type === 'int' ? 'numeric' : 'decimal'}
        className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-sm"
      />
      {hint && <p className="mt-0.5 text-[10px] text-slate-400">{hint}</p>}
    </div>
  )
}

export function InputDialog() {
  const pending = useRunStore((s) => s.pendingInput)
  const serverError = useRunStore((s) => s.inputError)
  const [raw, setRaw] = useState<string | boolean>('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [hidden, setHidden] = useState(false)
  const [busy, setBusy] = useState(false)
  const [forName, setForName] = useState<string | null>(null)

  if (pending === null) return null
  if (forName !== pending.name) {
    // a new request arrived — reset widget state for it
    setForName(pending.name)
    setRaw(pending.type === 'bool' ? true : '')
    setLocalError(null)
    setHidden(false)
    return null
  }
  if (hidden) {
    return (
      <button
        onClick={() => setHidden(false)}
        className="w-full rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-left text-sm text-amber-800"
      >
        ⌨ Operator input required: '{pending.name}' — click to answer
      </button>
    )
  }

  const submit = async () => {
    const check = validateInputValue(pending, raw)
    if (!check.ok) {
      setLocalError(check.error)
      return
    }
    setLocalError(null)
    setBusy(true)
    await useRunStore.getState().submit(check.value)
    setBusy(false)
  }

  return (
    <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/30">
      <div className="w-96 rounded-lg bg-white p-4 shadow-xl">
        <div className="mb-2 flex items-start justify-between">
          <h2 className="text-sm font-semibold">Operator input: {pending.name}</h2>
          <button onClick={() => setHidden(true)} title="Hide (the run stays paused on this input)"
            className="text-slate-400 hover:text-slate-700">—</button>
        </div>
        {pending.prompt && <p className="mb-2 text-sm text-slate-600">{pending.prompt}</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
        >
          <Widget input={pending} raw={raw} setRaw={setRaw} />
          {(localError ?? serverError) && (
            <p className="mt-1 text-xs text-red-600">{localError ?? serverError}</p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="mt-3 w-full rounded bg-blue-600 py-1.5 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-40"
          >
            Submit
          </button>
        </form>
      </div>
    </div>
  )
}
