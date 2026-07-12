/** Run-tab state: adopts the active run (refresh-proof via GET /runs/active + WS replay
 * from seq -1), folds the WS feed with the pure reducer, owns controls and the pending
 * operator input, and resolves the terminal report from the record row (§7, §9.4). */
import { create } from 'zustand'
import { ApiError } from '../api/client'
import {
  abortRun, getActiveRun, pauseRun, resumeRun, startRun, submitRunInput,
  type StartRunBody,
} from '../api/runs'
import { getRecord } from '../api/records'
import { RunSocket, type RunSocketHandlers } from '../api/runSocket'
import { applyMessage, emptyFeed, type FeedState } from '../run/reducer'
import type { Diagnostic, ExperimentDocJson } from '../types/doc'
import type { ActiveRunPayload, PendingInput, RunWsMsg } from '../types/runs'
import type { RecordReport } from '../types/records'

interface SocketLike {
  connect: () => void
  close: () => void
}
export type SocketFactory = (
  runId: string, lastSeq: () => number, handlers: RunSocketHandlers,
) => SocketLike

let socketFactory: SocketFactory = (runId, lastSeq, handlers) =>
  new RunSocket(runId, lastSeq, handlers)
export function setSocketFactoryForTests(f: SocketFactory | null): void {
  socketFactory = f ?? ((runId, lastSeq, handlers) => new RunSocket(runId, lastSeq, handlers))
}

export interface RunUiState {
  phase: 'unknown' | 'idle' | 'active' | 'terminal'
  runId: string | null
  recordId: string | null
  experiment: { id: string; name: string } | null
  lab: string | null
  feed: FeedState
  lastWallMs: number | null
  pendingInput: PendingInput | null
  inputError: string | null
  streamUnits: Record<string, string | null>
  report: RecordReport | null
  recordName: string | null
  startBusy: boolean
  controlBusy: boolean
  startError: string | null
  startDiagnostics: Diagnostic[] | null
  attach: () => Promise<void>
  start: (body: StartRunBody) => Promise<void>
  pause: () => Promise<void>
  resume: () => Promise<void>
  abort: () => Promise<void>
  submit: (value: boolean | number | string) => Promise<boolean>
  dismiss: () => void
}

let socket: SocketLike | null = null

const unitsOf = (doc: ExperimentDocJson | null): Record<string, string | null> =>
  Object.fromEntries(
    Object.entries(doc?.workflow.streams ?? {}).map(([k, s]) => [k, s.units ?? null]),
  )

export const useRunStore = create<RunUiState>()((set, get) => {
  const receive = (msg: RunWsMsg): void => {
    set((s) => ({ feed: applyMessage(s.feed, msg), lastWallMs: Date.now() }))
    if (msg.type !== 'event') return
    if (msg.kind === 'input_requested') {
      void getActiveRun().then((p) => {
        if (p !== null && p.run_id === get().runId && p.pending_input !== null) {
          set({ pendingInput: p.pending_input, inputError: null })
        }
      })
    } else if (msg.kind === 'input_bound') {
      set({ pendingInput: null, inputError: null })
    }
  }

  const openSocket = (runId: string): void => {
    socket?.close()
    socket = socketFactory(runId, () => get().feed.lastSeq, {
      onMessage: receive,
      onTerminal: () => {
        const recordId = get().recordId
        if (recordId === null) {
          set({ phase: 'terminal' })
          return
        }
        // Fold phase + report into one set() so observers that poll for phase === 'terminal'
        // (e.g. the terminal-report screen) never see terminal without the report attached.
        void getRecord(recordId)
          .then((d) => {
            if (get().runId === runId) set({ phase: 'terminal', report: d.report, recordName: d.name })
          })
          .catch(() => {
            if (get().runId === runId) set({ phase: 'terminal', report: null })
          })
      },
      onGone: () => void get().attach(),
    })
    socket.connect()
  }

  const adopt = (payload: ActiveRunPayload): Promise<void> => {
    set({
      phase: 'active',
      runId: payload.run_id,
      recordId: payload.record_id,
      experiment: payload.experiment,
      lab: payload.lab,
      feed: emptyFeed(payload.status),
      lastWallMs: null,
      pendingInput: payload.pending_input,
      inputError: null,
      report: null,
      recordName: null,
      startError: null,
      startDiagnostics: null,
    })
    openSocket(payload.run_id) // connect immediately; WS replay from lastSeq covers the gap
    // attach() awaits this so callers observe a fully adopted run (streamUnits included).
    return getRecord(payload.record_id)
      .then((d) => set({ streamUnits: unitsOf(d.doc) }))
      .catch(() => set({ streamUnits: {} }))
  }

  return {
    phase: 'unknown',
    runId: null,
    recordId: null,
    experiment: null,
    lab: null,
    feed: emptyFeed(),
    lastWallMs: null,
    pendingInput: null,
    inputError: null,
    streamUnits: {},
    report: null,
    recordName: null,
    startBusy: false,
    controlBusy: false,
    startError: null,
    startDiagnostics: null,

    attach: async () => {
      try {
        const payload = await getActiveRun()
        if (payload === null) {
          if (get().phase !== 'terminal') set({ phase: 'idle' })
        } else if (payload.run_id !== get().runId || get().phase !== 'active') {
          await adopt(payload)
        }
      } catch (e) {
        set({ phase: 'idle', startError: e instanceof Error ? e.message : String(e) })
      }
    },

    start: async (body) => {
      set({ startBusy: true, startError: null, startDiagnostics: null })
      try {
        await startRun(body)
        await get().attach()
      } catch (e) {
        if (e instanceof ApiError && e.code === 'run_active') {
          await get().attach() // adopt whoever is running (S8: one run per instance)
        } else if (e instanceof ApiError && e.diagnostics !== null) {
          set({ startError: e.message, startDiagnostics: e.diagnostics })
        } else {
          set({ startError: e instanceof Error ? e.message : String(e) })
        }
      } finally {
        set({ startBusy: false })
      }
    },

    pause: async () => {
      const id = get().runId
      if (id === null) return
      set({ controlBusy: true })
      try {
        await pauseRun(id)
      } catch {
        // status frame (or 404 on a just-finished run) resolves the true state
      } finally {
        set({ controlBusy: false })
      }
    },
    resume: async () => {
      const id = get().runId
      if (id === null) return
      set({ controlBusy: true })
      try {
        await resumeRun(id)
      } catch {
        // see pause()
      } finally {
        set({ controlBusy: false })
      }
    },
    abort: async () => {
      const id = get().runId
      if (id === null) return
      set({ controlBusy: true })
      try {
        await abortRun(id)
      } catch {
        // idempotent server-side; terminal frame arrives via WS
      } finally {
        set({ controlBusy: false })
      }
    },

    submit: async (value) => {
      const id = get().runId
      if (id === null) return false
      try {
        await submitRunInput(id, value)
        set({ pendingInput: null, inputError: null })
        return true
      } catch (e) {
        set({ inputError: e instanceof Error ? e.message : String(e) })
        return false // 422 invalid_value: request stays pending server-side (§7.4)
      }
    },

    dismiss: () => {
      socket?.close()
      socket = null
      set({
        phase: 'idle', runId: null, recordId: null, experiment: null, lab: null,
        feed: emptyFeed(), lastWallMs: null, pendingInput: null, inputError: null,
        streamUnits: {}, report: null, recordName: null,
        startBusy: false, controlBusy: false, startError: null, startDiagnostics: null,
      })
    },
  }
})
