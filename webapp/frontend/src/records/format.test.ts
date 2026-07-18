import { describe, expect, it } from 'vitest'
import { dedupeConsecutive, formatDuration, formatElapsed, formatWhen } from './format'

describe('format helpers', () => {
  it('formatWhen renders local-ish compact stamps', () => {
    expect(formatWhen('2026-07-12T14:03:22.123456+00:00')).toContain('2026-07-12')
  })
  it('formatElapsed renders s / m / h forms', () => {
    expect(formatElapsed(4)).toBe('4s')
    expect(formatElapsed(75)).toBe('1m 15s')
    expect(formatElapsed(3675)).toBe('1h 01m 15s')
  })
  it('formatDuration diffs ISO stamps and dashes when open-ended', () => {
    expect(formatDuration('2026-07-12T14:00:00+00:00', '2026-07-12T14:01:15+00:00')).toBe('1m 15s')
    expect(formatDuration('2026-07-12T14:00:00+00:00', null)).toBe('—')
  })
})

describe('dedupeConsecutive', () => {
  it('blanks repeated neighbours, keeps the first of each run (audit F17)', () => {
    expect(dedupeConsecutive(['0s', '0s', '0s', '1s', '1s', '2s'])).toEqual([
      '0s', '', '', '1s', '', '2s',
    ])
  })
  it('leaves already-unique labels alone', () => {
    expect(dedupeConsecutive(['0s', '5s', '10s'])).toEqual(['0s', '5s', '10s'])
  })
  it('handles empty input', () => {
    expect(dedupeConsecutive([])).toEqual([])
  })
})
