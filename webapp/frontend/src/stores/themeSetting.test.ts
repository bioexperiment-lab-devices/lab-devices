import { describe, expect, it } from 'vitest'
import {
  THEME_STORAGE_KEY,
  cycleSetting,
  parseThemeSetting,
  resolveTheme,
} from './themeSetting'

describe('parseThemeSetting', () => {
  it('accepts the three settings', () => {
    expect(parseThemeSetting('system')).toBe('system')
    expect(parseThemeSetting('light')).toBe('light')
    expect(parseThemeSetting('dark')).toBe('dark')
  })
  it('falls back to system on null, junk, and legacy values', () => {
    expect(parseThemeSetting(null)).toBe('system')
    expect(parseThemeSetting('')).toBe('system')
    expect(parseThemeSetting('DARK')).toBe('system')
    expect(parseThemeSetting('auto')).toBe('system')
  })
})

describe('resolveTheme', () => {
  it('explicit settings ignore the system preference', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })
  it('system follows the media query', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
  })
})

describe('cycleSetting', () => {
  it('cycles system → light → dark → system', () => {
    expect(cycleSetting('system')).toBe('light')
    expect(cycleSetting('light')).toBe('dark')
    expect(cycleSetting('dark')).toBe('system')
  })
})

it('storage key follows the studio.* convention', () => {
  expect(THEME_STORAGE_KEY).toBe('studio.theme')
})
