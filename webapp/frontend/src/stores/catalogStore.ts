/** Fetch-once cache of GET /api/catalog. The palette and inspector generate themselves
 * from this payload (webapp design §4.4) — there is no other source of verb truth. */
import { create } from 'zustand'
import { getCatalog } from '../api/studio'
import type { Catalog } from '../types/catalog'

interface CatalogState {
  catalog: Catalog | null
  error: string | null
  loading: boolean
  load: () => Promise<void>
}

export const useCatalogStore = create<CatalogState>()((set, get) => ({
  catalog: null,
  error: null,
  loading: false,
  load: async () => {
    if (get().catalog !== null || get().loading) return
    set({ loading: true, error: null })
    try {
      set({ catalog: await getCatalog(), loading: false })
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e), loading: false })
    }
  },
}))
