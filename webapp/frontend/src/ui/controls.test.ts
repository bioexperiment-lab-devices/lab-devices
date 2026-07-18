import { describe, expect, it } from 'vitest'
import { iconButtonClass } from './IconButton'
import { CONTROL_H, controlClass, inlineButtonClass, textAreaClass } from './controls'

/** The height classes present in a class string. */
const heights = (cls: string) => cls.split(/\s+/).filter((c) => /^h-\d/.test(c))

describe('control height token', () => {
  it('pins every control family to the same single height', () => {
    // This is the whole point of the token: an input, an inline button and an
    // icon button sitting in one flex row must agree, or they disagree by 2-4px
    // like the twelve sites the 2026-07-18 sweep found.
    expect(heights(controlClass())).toEqual([CONTROL_H])
    expect(heights(inlineButtonClass())).toEqual([CONTROL_H])
    expect(heights(iconButtonClass())).toEqual([CONTROL_H])
  })

  it('always carries a border so bordered and borderless controls cannot differ by 2px', () => {
    expect(controlClass()).toContain('border')
    expect(inlineButtonClass()).toContain('border')
  })

  it('adds font-mono only when asked', () => {
    expect(controlClass({ mono: true })).toContain('font-mono')
    expect(controlClass()).not.toContain('font-mono')
  })

  it('signals invalid with a border colour, not a height change', () => {
    expect(controlClass({ invalid: true })).toContain('border-red-400')
    expect(heights(controlClass({ invalid: true }))).toEqual([CONTROL_H])
  })
})

describe('textarea class', () => {
  it('carries no h-* class — a textarea grows with its content, not a fixed token', () => {
    expect(heights(textAreaClass())).toEqual([])
  })

  it('shares the border and focus-ring fragment with controlClass', () => {
    // The two families must not drift apart, or a textarea sitting beside an input
    // reads as a visually different control despite being the same field type.
    const shared = [
      'rounded',
      'border',
      'border-slate-300',
      'bg-white',
      'text-xs',
      'focus:border-blue-400',
      'focus:outline-none',
    ]
    for (const cls of shared) {
      expect(controlClass()).toContain(cls)
      expect(textAreaClass()).toContain(cls)
    }
  })

  it('adds font-mono only when asked', () => {
    expect(textAreaClass({ mono: true })).toContain('font-mono')
    expect(textAreaClass()).not.toContain('font-mono')
  })

  it('adds max-h-full only when fillParent is set', () => {
    expect(textAreaClass({ fillParent: true })).toContain('max-h-full')
    expect(textAreaClass()).not.toContain('max-h-full')
  })
})
