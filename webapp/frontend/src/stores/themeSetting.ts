/** Pure theme-setting logic, split from themeStore so vitest (node env) can import it —
 * the store itself touches matchMedia/localStorage/document at module scope. */

export type ThemeSetting = 'system' | 'light' | 'dark'
export type EffectiveTheme = 'light' | 'dark'

/** Same `studio.*` namespace as `studio.selectedLab` / `studio.draft.v1`. The inline boot
 * script in index.html reads this key BY LITERAL — keep the two in sync by hand. */
export const THEME_STORAGE_KEY = 'studio.theme'

export function parseThemeSetting(raw: string | null): ThemeSetting {
  return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system'
}

export function resolveTheme(setting: ThemeSetting, systemDark: boolean): EffectiveTheme {
  if (setting === 'system') return systemDark ? 'dark' : 'light'
  return setting
}

export function cycleSetting(s: ThemeSetting): ThemeSetting {
  return s === 'system' ? 'light' : s === 'light' ? 'dark' : 'system'
}
