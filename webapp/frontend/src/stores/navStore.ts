/** App-global tab selection so any feature (e.g. the run terminal panel) can jump tabs. */
import { create } from 'zustand'
import type { Tab } from '../shell/tabs'

interface NavState {
  tab: Tab
  setTab: (tab: Tab) => void
}

export const useNavStore = create<NavState>()((set) => ({
  tab: 'Builder',
  setTab: (tab) => set({ tab }),
}))
