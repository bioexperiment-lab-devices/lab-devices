/** Role-colour overrides, persisted to localStorage.
 *
 * Deliberately a SEPARATE store from docStore: role colour is view state, never document
 * state, so it must not enter the zundo snapshot (the same family as `selectedUid` and
 * `scope`, W9-settled). Undo must not undo a colour choice, and a colour choice must not
 * make the document dirty.
 *
 * Stale keys are never garbage-collected — a rename followed by an undo has to recover the
 * original colour (design §5).
 */
import { create } from 'zustand'
import {
  ROLE_COLOR_STORAGE_KEY,
  parseOverrides,
  serializeOverrides,
} from '../builder/roleColorStorage'

function load(): Record<string, string | null> {
  try {
    return parseOverrides(localStorage.getItem(ROLE_COLOR_STORAGE_KEY))
  } catch {
    // Private-mode / disabled storage: colours degrade to auto-assigned for the session.
    return {}
  }
}

function save(o: Record<string, string | null>): void {
  try {
    localStorage.setItem(ROLE_COLOR_STORAGE_KEY, serializeOverrides(o))
  } catch {
    // Quota or disabled storage — the in-memory value still drives this session's render.
  }
}

type RoleColorState = {
  overrides: Record<string, string | null>
  /** Pin a role to a specific ramp class. */
  setColor: (key: string, cls: string) => void
  /** Explicit "no colour" — renders as a plain white card, as before this increment. */
  clearColor: (key: string) => void
  /** Forget the override entirely, returning the role to positional auto-assignment. */
  resetColor: (key: string) => void
}

export const useRoleColorStore = create<RoleColorState>((set) => ({
  overrides: load(),
  setColor: (key, cls) =>
    set((s) => {
      const next = { ...s.overrides, [key]: cls }
      save(next)
      return { overrides: next }
    }),
  clearColor: (key) =>
    set((s) => {
      const next = { ...s.overrides, [key]: null }
      save(next)
      return { overrides: next }
    }),
  resetColor: (key) =>
    set((s) => {
      const next = { ...s.overrides }
      delete next[key]
      save(next)
      return { overrides: next }
    }),
}))
