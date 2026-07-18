import { describe, expect, it } from 'vitest'
import { filterStreamNames } from './streamFilter'

describe('filterStreamNames', () => {
  const names = ['od_01', 'od_02', 'c_series', 'pump_rate']
  it('matches case-insensitive substrings', () => {
    expect(filterStreamNames(names, 'OD')).toEqual(['od_01', 'od_02'])
    expect(filterStreamNames(names, 'seri')).toEqual(['c_series'])
  })
  it('returns all for an empty/whitespace query', () => {
    expect(filterStreamNames(names, '')).toEqual(names)
    expect(filterStreamNames(names, '  ')).toEqual(names)
  })
  it('returns empty when nothing matches', () => {
    expect(filterStreamNames(names, 'zzz')).toEqual([])
  })
})
