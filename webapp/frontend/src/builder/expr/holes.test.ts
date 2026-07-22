import { describe, expect, it } from 'vitest'
import { maskHoles } from './holes'

describe('maskHoles', () => {
  it('replaces a hole with an equal-length identifier and records its span', () => {
    const { masked, holes } = maskHoles('{od}')
    expect(masked).toBe('_od_')
    expect(masked.length).toBe('{od}'.length)
    expect(holes).toEqual([{ start: 0, end: 4, name: 'od' }])
  })

  it('preserves positions of surrounding tokens', () => {
    const { masked, holes } = maskHoles('mean({od}, last=5)')
    expect(masked).toBe('mean(_od_, last=5)')
    expect(holes).toEqual([{ start: 5, end: 9, name: 'od' }])
  })

  it('masks multiple holes', () => {
    const { masked, holes } = maskHoles('{a} + {bee}')
    expect(masked).toBe('_a_ + _bee_')
    expect(holes.map((h) => h.name)).toEqual(['a', 'bee'])
  })

  it('never turns a hole into a keyword', () => {
    expect(maskHoles('{not}').masked).toBe('_not_')
    expect(maskHoles('{and}').masked).toBe('_and_')
  })

  it('leaves an unclosed or empty brace untouched', () => {
    expect(maskHoles('{od').masked).toBe('{od')
    expect(maskHoles('{}').masked).toBe('{}')
    expect(maskHoles('no braces here').holes).toEqual([])
  })
})
