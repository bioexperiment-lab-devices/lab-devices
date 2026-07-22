/** Theme selection, persisted to localStorage — view state, same family as
 * roleColorStore: never document state, never in the zundo snapshot.
 *
 * The store is the ONLY writer of <html data-theme> after boot (index.html's inline
 * script stamps the same attribute before first paint so the app never flashes light;
 * this module re-applies on init, which is idempotent and also corrects a stale stamp
 * if the OS preference changed between the boot script and module evaluation). */
import { create } from 'zustand'
import {
  THEME_STORAGE_KEY,
  cycleSetting,
  parseThemeSetting,
  resolveTheme,
  type EffectiveTheme,
  type ThemeSetting,
} from './themeSetting'

const media = window.matchMedia('(prefers-color-scheme: dark)')

function apply(theme: EffectiveTheme): void {
  if (theme === 'dark') document.documentElement.dataset.theme = 'dark'
  else delete document.documentElement.dataset.theme
}

function loadSetting(): ThemeSetting {
  try {
    return parseThemeSetting(localStorage.getItem(THEME_STORAGE_KEY))
  } catch {
    // Private-mode / disabled storage: follow the OS for the session.
    return 'system'
  }
}

type ThemeState = {
  setting: ThemeSetting
  effective: EffectiveTheme
  /** System → Light → Dark → System; persists and re-stamps <html>. */
  cycle: () => void
}

export const useThemeStore = create<ThemeState>((set, get) => {
  media.addEventListener('change', (e) => {
    if (get().setting !== 'system') return
    const effective = resolveTheme('system', e.matches)
    apply(effective)
    set({ effective })
  })
  const setting = loadSetting()
  const effective = resolveTheme(setting, media.matches)
  apply(effective)
  return {
    setting,
    effective,
    cycle: () => {
      const next = cycleSetting(get().setting)
      try {
        localStorage.setItem(THEME_STORAGE_KEY, next)
      } catch {
        // Quota or disabled storage — the in-memory setting still drives this session.
      }
      const effective = resolveTheme(next, media.matches)
      apply(effective)
      set({ setting: next, effective })
    },
  }
})
