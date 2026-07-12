/** Lab roster + per-lab device view. The selected lab is app-global (shown in the shell
 * header, spec §9.1) and persists across reloads via localStorage. */
import { create } from 'zustand'
import { labDevices, labDiscover, listLabs } from '../api/labs'
import type { LabDevice, LabSummary } from '../types/labs'

const STORAGE_KEY = 'studio.selectedLab'

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e))

interface LabsState {
  labs: LabSummary[] | null
  labsError: string | null
  loadingLabs: boolean
  selected: string | null
  devices: LabDevice[] | null
  devicesError: string | null
  loadingDevices: boolean
  discovering: boolean
  refreshLabs: () => Promise<void>
  selectLab: (name: string | null) => void
  refreshDevices: () => Promise<void>
  rediscover: () => Promise<void>
}

export const useLabsStore = create<LabsState>()((set, get) => ({
  labs: null,
  labsError: null,
  loadingLabs: false,
  selected: localStorage.getItem(STORAGE_KEY),
  devices: null,
  devicesError: null,
  loadingDevices: false,
  discovering: false,

  refreshLabs: async () => {
    set({ loadingLabs: true, labsError: null })
    try {
      set({ labs: await listLabs(), loadingLabs: false })
    } catch (e) {
      set({ labsError: message(e), loadingLabs: false })
    }
  },

  selectLab: (name) => {
    if (name === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, name)
    set({ selected: name, devices: null, devicesError: null })
    if (name !== null) void get().refreshDevices()
  },

  refreshDevices: async () => {
    const lab = get().selected
    if (lab === null) return
    set({ loadingDevices: true, devicesError: null })
    try {
      const devices = await labDevices(lab)
      if (get().selected !== lab) return
      set({ devices, loadingDevices: false })
    } catch (e) {
      if (get().selected !== lab) return
      set({ devicesError: message(e), loadingDevices: false })
    }
  },

  rediscover: async () => {
    const lab = get().selected
    if (lab === null) return
    set({ discovering: true, devicesError: null })
    try {
      const devices = await labDiscover(lab)
      if (get().selected !== lab) return
      set({ devices, discovering: false })
    } catch (e) {
      if (get().selected !== lab) return
      set({ devicesError: message(e), discovering: false })
    }
  },
}))
