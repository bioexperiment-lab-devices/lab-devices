import { describe, expect, it } from 'vitest'
import { insertFragment } from './insert'

describe('insertFragment', () => {
  it('inserts at the caret', () => {
    expect(insertFragment('a > ', 4, 'od')).toEqual({ text: 'a > od', caret: 6 })
  })
  it('pads with a space against an adjacent identifier', () => {
    expect(insertFragment('not', 3, 'od')).toEqual({ text: 'not od', caret: 6 })
    expect(insertFragment('od', 0, 'not')).toEqual({ text: 'not od', caret: 3 })
  })
  it('does not pad against operators or parens', () => {
    expect(insertFragment('mean(', 5, 'od')).toEqual({ text: 'mean(od', caret: 7 })
  })
  it('replaces a range and honours caretBack', () => {
    expect(
      insertFragment('me > 2', 2, 'mean()', { replace: { start: 0, end: 2 }, caretBack: 1 }),
    ).toEqual({ text: 'mean() > 2', caret: 5 })
  })
})
