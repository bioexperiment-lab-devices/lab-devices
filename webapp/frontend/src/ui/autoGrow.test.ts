import { describe, expect, it } from 'vitest'
import { autoGrowHeight, collapseNewlines } from './autoGrow'

describe('autoGrowHeight', () => {
  it('grows to fit content below the cap and hides the scrollbar', () => {
    expect(autoGrowHeight({ scrollHeight: 48, lineHeight: 16, maxLines: 8 })).toEqual({
      height: 48,
      overflow: 'hidden',
    })
  })

  it('stops at the cap and hands scrolling back to the browser', () => {
    expect(autoGrowHeight({ scrollHeight: 400, lineHeight: 16, maxLines: 8 })).toEqual({
      height: 128,
      overflow: 'auto',
    })
  })

  it('treats exactly-at-cap as fitting, not overflowing', () => {
    // Off-by-one here shows up as a scrollbar flickering on and off as the user types.
    expect(autoGrowHeight({ scrollHeight: 128, lineHeight: 16, maxLines: 8 })).toEqual({
      height: 128,
      overflow: 'hidden',
    })
  })

  it('never returns a height below one line', () => {
    expect(autoGrowHeight({ scrollHeight: 0, lineHeight: 16, maxLines: 8 }).height).toBe(16)
  })
})

describe('collapseNewlines', () => {
  it('collapses pasted newlines into spaces', () => {
    // The expression grammar has no newlines. A user pasting a formatted expression from
    // a doc must get a valid single-line value, not a parse error.
    expect(collapseNewlines('last(od_1) > od_thr\nand blanks_ready')).toBe(
      'last(od_1) > od_thr and blanks_ready',
    )
  })

  it('collapses CRLF and runs of newlines to a single space', () => {
    expect(collapseNewlines('a\r\n\r\nb')).toBe('a b')
  })

  it('leaves an already single-line value untouched', () => {
    expect(collapseNewlines('mean(od_1, last=5) > 0.6')).toBe('mean(od_1, last=5) > 0.6')
  })
})
