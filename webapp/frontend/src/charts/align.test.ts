import { describe, expect, it } from 'vitest'
import { alignSeries } from './align'

describe('alignSeries', () => {
  it('merges timestamps into a sorted union x with null gaps', () => {
    const data = alignSeries([
      { label: 'od', t: [0, 10, 20], v: [1, 2, 3] },
      { label: 'temp', t: [10, 30], v: [37, 38] },
    ])
    expect(data[0]).toEqual([0, 10, 20, 30])
    expect(data[1]).toEqual([1, 2, 3, null])
    expect(data[2]).toEqual([null, 37, null, 38])
  })
  it('handles a single series and empty input', () => {
    expect(alignSeries([{ label: 'od', t: [1], v: [5] }])).toEqual([[1], [5]])
    expect(alignSeries([])).toEqual([[]])
  })
  it('deduplicates shared timestamps', () => {
    const data = alignSeries([
      { label: 'a', t: [1, 2], v: [10, 20] },
      { label: 'b', t: [2], v: [99] },
    ])
    expect(data[0]).toEqual([1, 2])
    expect(data[2]).toEqual([null, 99])
  })
})
