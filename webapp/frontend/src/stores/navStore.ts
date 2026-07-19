/** App-global tab selection so any feature (e.g. the run terminal panel) can jump tabs.
 *
 * The initial tab comes from the URL hash (design §4) rather than a hardcoded 'Builder', so a
 * refresh or a shared link lands on the tab it names. `parseHash` is total, so a malformed
 * hash still yields 'Builder'.
 */
import { create } from 'zustand'
import type { Tab } from '../shell/tabs'
import { parseHash } from '../shell/urlState'

/** A `typeof window` check rather than a try/catch: vitest runs in the node environment here
 * (webapp/frontend/CLAUDE.md), and this initializer runs at import time for every test that
 * transitively pulls this module in. A bare `window.location.hash` would throw a ReferenceError
 * there — catchable, but the catch would then also swallow a genuine parse bug and fall back to
 * 'Builder' in the browser, where the URL really did name another tab. */
const initialTab = (): Tab =>
  typeof window === 'undefined' ? 'Builder' : parseHash(window.location.hash).tab

interface NavState {
  tab: Tab
  setTab: (tab: Tab) => void
}

export const useNavStore = create<NavState>()((set) => ({
  tab: initialTab(),
  setTab: (tab) => set({ tab }),
}))
