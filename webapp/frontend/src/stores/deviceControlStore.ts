/** Manual device-control session state (design §8): the selected target device, an ephemeral
 * activity log, and the fire+poll command runner. The pure logic it leans on — payload
 * building, job classification — lives in src/devices/{buildPayload,jobStatus}.ts and is unit
 * tested there; this module is the async wiring (not unit tested, per the repo's node-env rule).
 */
import { create } from 'zustand'
import { ApiError } from '../api/client'
import { pollJob, runCommand } from '../api/deviceControl'
import { CATALOG, LOCATE, type DeviceType } from '../devices/catalog'
import { classifyJob } from '../devices/jobStatus'

const POLL_INTERVAL_MS = 1000
const MAX_DETAIL = 200

export type ActivityState = 'started' | 'running' | 'ok' | 'error'

export interface ActivityEntry {
  key: number
  at: string
  device: string
  cmd: string
  state: ActivityState
  detail: string
  progress: number | null
}

const truncate = (s: string): string => (s.length > MAX_DETAIL ? s.slice(0, MAX_DETAIL) + '…' : s)

const describe = (result: unknown): string => {
  if (result === null || result === undefined) return 'ok'
  if (typeof result === 'object') return truncate(JSON.stringify(result))
  return truncate(String(result))
}

const errorText = (e: unknown): string => {
  if (e instanceof ApiError) return e.code ? `${e.code}: ${e.message}` : e.message
  return e instanceof Error ? e.message : String(e)
}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

interface DeviceControlState {
  selectedId: string | null
  activity: ActivityEntry[]
  busy: boolean
  /** Bumped on every run/stop so a superseded poll loop drops out (design §8). */
  pollGen: number
  seq: number
  select: (id: string | null) => void
  run: (
    lab: string,
    id: string,
    cmd: string,
    params: Record<string, unknown> | null,
    isJob: boolean,
  ) => Promise<void>
  stop: (lab: string, id: string) => Promise<void>
  locate: (lab: string, device: { id: string; type: string }) => Promise<void>
  clearActivity: () => void
}

export const useDeviceControlStore = create<DeviceControlState>()((set, get) => {
  const push = (device: string, cmd: string): number => {
    const key = get().seq + 1
    const entry: ActivityEntry = {
      key,
      at: new Date().toISOString(),
      device,
      cmd,
      state: 'started',
      detail: '',
      progress: null,
    }
    set((s) => ({ seq: key, activity: [entry, ...s.activity] }))
    return key
  }

  const update = (key: number, patch: Partial<ActivityEntry>): void => {
    set((s) => ({
      activity: s.activity.map((e) => (e.key === key ? { ...e, ...patch } : e)),
    }))
  }

  const pollLoop = async (
    lab: string,
    id: string,
    jobId: string,
    gen: number,
    key: number,
  ): Promise<void> => {
    update(key, { state: 'running' })
    for (;;) {
      await sleep(POLL_INTERVAL_MS)
      if (get().pollGen !== gen) return // superseded by a newer run/stop
      let cls
      try {
        const res = await pollJob(lab, id, jobId)
        cls = classifyJob(res.result)
        if (get().pollGen !== gen) return
        update(key, { progress: cls.progress })
        if (cls.done) {
          update(key, {
            state: cls.phase === 'succeeded' ? 'ok' : 'error',
            detail: cls.phase,
          })
          return
        }
      } catch (e) {
        if (get().pollGen !== gen) return
        update(key, { state: 'error', detail: errorText(e) })
        return
      }
    }
  }

  const execute = async (
    lab: string,
    id: string,
    cmd: string,
    params: Record<string, unknown> | null,
    isJob: boolean,
  ): Promise<void> => {
    if (get().busy) return
    const gen = get().pollGen + 1
    set({ pollGen: gen, busy: true })
    const key = push(id, cmd)
    try {
      const res = await runCommand(lab, id, cmd, params)
      if (get().pollGen !== gen) return
      if (isJob) {
        const cls = classifyJob(res.result)
        if (cls.jobId !== null && !cls.done) {
          await pollLoop(lab, id, cls.jobId, gen, key)
          return
        }
        update(key, {
          state: cls.done && cls.phase !== 'succeeded' ? 'error' : 'ok',
          detail: cls.done ? cls.phase : describe(res.result),
        })
      } else {
        update(key, { state: 'ok', detail: describe(res.result) })
      }
    } catch (e) {
      if (get().pollGen !== gen) return
      update(key, { state: 'error', detail: errorText(e) })
    } finally {
      if (get().pollGen === gen) set({ busy: false })
    }
  }

  return {
    selectedId: null,
    activity: [],
    busy: false,
    pollGen: 0,
    seq: 0,

    select: (id) => set({ selectedId: id }),

    run: (lab, id, cmd, params, isJob) => execute(lab, id, cmd, params, isJob),

    // Stop is a distinct command that supersedes any poll in flight; it bypasses the `busy`
    // guard so it can always interrupt (design §6.3, §8).
    stop: async (lab, id) => {
      const gen = get().pollGen + 1
      set({ pollGen: gen })
      const key = push(id, 'stop')
      try {
        const res = await runCommand(lab, id, 'stop', null)
        update(key, { state: 'ok', detail: describe(res.result) })
      } catch (e) {
        update(key, { state: 'error', detail: errorText(e) })
      } finally {
        if (get().pollGen === gen) set({ busy: false })
      }
    },

    locate: (lab, device) => {
      const type = device.type as DeviceType
      const preset = LOCATE[type]
      if (preset === undefined) return Promise.resolve()
      const def = (CATALOG[type] ?? []).find((c) => c.cmd === preset.cmd)
      return execute(lab, device.id, preset.cmd, preset.params, def?.isJob ?? false)
    },

    clearActivity: () => set({ activity: [] }),
  }
})
