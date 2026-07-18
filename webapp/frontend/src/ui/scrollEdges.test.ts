import { describe, expect, it } from 'vitest'
import { scrollEdges } from './scrollEdges'

describe('scrollEdges', () => {
  it('reports no overflow when content fits', () => {
    expect(scrollEdges({ scrollLeft: 0, scrollWidth: 500, clientWidth: 500 })).toEqual({
      overflowing: false,
      atStart: true,
      atEnd: true,
    })
  })

  it('at the left end, only the right edge continues', () => {
    expect(scrollEdges({ scrollLeft: 0, scrollWidth: 1000, clientWidth: 500 })).toEqual({
      overflowing: true,
      atStart: true,
      atEnd: false,
    })
  })

  it('scrolled to the middle, both edges continue', () => {
    expect(scrollEdges({ scrollLeft: 250, scrollWidth: 1000, clientWidth: 500 })).toEqual({
      overflowing: true,
      atStart: false,
      atEnd: false,
    })
  })

  it('at the right end, only the left edge continues', () => {
    expect(scrollEdges({ scrollLeft: 500, scrollWidth: 1000, clientWidth: 500 })).toEqual({
      overflowing: true,
      atStart: false,
      atEnd: true,
    })
  })

  it('tolerates sub-pixel rounding at both ends', () => {
    // Browsers hand back fractional scrollLeft on zoom / HiDPI. Without tolerance a fade
    // stays painted at a fully-scrolled edge, which is exactly the artifact we are removing.
    expect(scrollEdges({ scrollLeft: 0.4, scrollWidth: 1000, clientWidth: 500 }).atStart).toBe(true)
    expect(scrollEdges({ scrollLeft: 499.6, scrollWidth: 1000, clientWidth: 500 }).atEnd).toBe(true)
  })

  it('does not tolerate a real gap just past the tolerance boundary', () => {
    // The sub-pixel case above proves SOME tolerance exists but never pins its size — a
    // tolerance accidentally widened past 1px would still pass it. 1.5px is a real, scrollable
    // gap, not rounding noise, so the fade must stay shown (edge not reached) here.
    expect(scrollEdges({ scrollLeft: 1.5, scrollWidth: 1000, clientWidth: 500 }).atStart).toBe(false)
    expect(scrollEdges({ scrollLeft: 498.5, scrollWidth: 1000, clientWidth: 500 }).atEnd).toBe(false)
  })
})
