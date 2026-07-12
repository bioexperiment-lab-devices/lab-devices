import { create } from 'zustand'
import { deleteRecord, listRecords, renameRecord } from '../api/records'
import type { RecordRow } from '../types/records'

interface RecordsState {
  items: RecordRow[] | null
  error: string | null
  loading: boolean
  openId: string | null
  refresh: () => Promise<void>
  open: (id: string | null) => void
  rename: (id: string, name: string) => Promise<string | null>
  remove: (id: string) => Promise<string | null>
}

const msg = (e: unknown): string => (e instanceof Error ? e.message : String(e))

export const useRecordsStore = create<RecordsState>()((set, get) => ({
  items: null,
  error: null,
  loading: false,
  openId: null,

  refresh: async () => {
    set({ loading: true, error: null })
    try {
      set({ items: await listRecords(), loading: false })
    } catch (e) {
      set({ error: msg(e), loading: false })
    }
  },

  open: (openId) => set({ openId }),

  rename: async (id, name) => {
    try {
      const row = await renameRecord(id, name)
      set({ items: (get().items ?? []).map((r) => (r.id === id ? row : r)) })
      return null
    } catch (e) {
      return msg(e)
    }
  },

  remove: async (id) => {
    try {
      await deleteRecord(id)
      set({
        items: (get().items ?? []).filter((r) => r.id !== id),
        openId: get().openId === id ? null : get().openId,
      })
      return null
    } catch (e) {
      return msg(e)
    }
  },
}))
