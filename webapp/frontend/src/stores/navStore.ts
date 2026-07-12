/** App-global tab selection so any feature (e.g. the run terminal panel) can jump tabs. */
import { create } from 'zustand'
import type { Tab } from '../shell/TabShell'

interface NavState {
  tab: Tab
  setTab: (tab: Tab) => void
}

export const useNavStore = create<NavState>()((set) => ({
  tab: 'Devices',
  setTab: (tab) => set({ tab }),
}))
