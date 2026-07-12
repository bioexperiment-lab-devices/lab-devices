/** Debounced draft validation (webapp design §4.3): 500 ms after edits settle, POST the
 * doc to /api/validate and map diagnostics onto the CURRENT tree. A monotonically
 * increasing sequence guards against stale responses racing fresh edits. */
import { useEffect, useRef } from 'react'
import { validateDoc } from '../api/studio'
import { selectDoc, useDocStore } from '../stores/docStore'
import { mapDiagnostics } from './paths'

export function useValidation(): void {
  const name = useDocStore((s) => s.name)
  const description = useDocStore((s) => s.description)
  const roles = useDocStore((s) => s.roles)
  const streams = useDocStore((s) => s.streams)
  const tree = useDocStore((s) => s.tree)
  const seq = useRef(0)

  useEffect(() => {
    const id = ++seq.current
    useDocStore.getState().setValidating(true)
    const timer = setTimeout(() => {
      const doc = selectDoc(useDocStore.getState())
      validateDoc(doc)
        .then((resp) => {
          if (seq.current !== id) return
          const state = useDocStore.getState()
          state.setDiagnostics(mapDiagnostics(state.tree, resp.diagnostics))
          state.setValidationError(null)
          state.setValidating(false)
        })
        .catch((e: unknown) => {
          if (seq.current !== id) return
          const state = useDocStore.getState()
          state.setValidationError(e instanceof Error ? e.message : String(e))
          state.setValidating(false)
        })
    }, 500)
    return () => clearTimeout(timer)
  }, [name, description, roles, streams, tree])
}
