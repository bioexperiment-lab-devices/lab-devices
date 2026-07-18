import { describe, expect, it } from 'vitest'
import { ROLE_SWATCH_CLASSES, assignRoleColors, roleColorKey } from './roleColors'

const roles = (...entries: [string, string][]) =>
  Object.fromEntries(entries.map(([name, type]) => [name, { type }]))

describe('ROLE_SWATCH_CLASSES', () => {
  it('is eight distinct, fully-written-out background classes', () => {
    expect(ROLE_SWATCH_CLASSES).toHaveLength(8)
    expect(new Set(ROLE_SWATCH_CLASSES).size).toBe(8)
    // Tailwind 4 scans source text: an interpolated class compiles to no CSS at all.
    for (const c of ROLE_SWATCH_CLASSES) expect(c).toMatch(/^bg-[a-z]+-\d{3}$/)
  })

  it('avoids every reserved state hue', () => {
    const reserved = ['blue', 'indigo', 'sky', 'red', 'rose', 'amber', 'orange',
                      'yellow', 'emerald', 'green']
    for (const c of ROLE_SWATCH_CLASSES) {
      for (const family of reserved) expect(c).not.toContain(`-${family}-`)
    }
  })
})

describe('roleColorKey', () => {
  it('keys on type and name together', () => {
    expect(roleColorKey('pump1', 'pump')).toBe('pump:pump1')
  })

  it('separates same-named roles of different types', () => {
    expect(roleColorKey('x', 'pump')).not.toBe(roleColorKey('x', 'sensor'))
  })
})

describe('assignRoleColors', () => {
  it('assigns from the ramp in declaration order', () => {
    const got = assignRoleColors(roles(['a', 'pump'], ['b', 'pump'], ['c', 'sensor']), {})
    expect(got).toEqual({
      a: ROLE_SWATCH_CLASSES[0],
      b: ROLE_SWATCH_CLASSES[1],
      c: ROLE_SWATCH_CLASSES[2],
    })
  })

  it('wraps to the start of the ramp past the eighth role', () => {
    const nine: [string, string][] = Array.from({ length: 9 }, (_, i) => [`r${i}`, 'pump'])
    const got = assignRoleColors(roles(...nine), {})
    expect(got.r8).toBe(ROLE_SWATCH_CLASSES[0])
  })

  it('lets an override replace the auto-assigned colour', () => {
    const got = assignRoleColors(roles(['a', 'pump']), {
      'pump:a': ROLE_SWATCH_CLASSES[5],
    })
    expect(got.a).toBe(ROLE_SWATCH_CLASSES[5])
  })

  // A null override is "the user removed this role's colour" and must render as today's
  // plain white card — it is NOT the same as having no entry, which means "never touched".
  it('treats a null override as explicitly colourless', () => {
    const got = assignRoleColors(roles(['a', 'pump'], ['b', 'pump']), { 'pump:a': null })
    expect(got.a).toBeNull()
    expect(got.b).toBe(ROLE_SWATCH_CLASSES[1])
  })

  // Auto-assignment is positional, so clearing one role must not renumber the others.
  it('does not shift other roles when one is cleared', () => {
    const all = assignRoleColors(roles(['a', 'pump'], ['b', 'pump'], ['c', 'pump']), {})
    const cleared = assignRoleColors(
      roles(['a', 'pump'], ['b', 'pump'], ['c', 'pump']),
      { 'pump:b': null },
    )
    expect(cleared.a).toBe(all.a)
    expect(cleared.c).toBe(all.c)
  })

  it('ignores overrides whose role no longer exists', () => {
    const got = assignRoleColors(roles(['a', 'pump']), { 'pump:gone': ROLE_SWATCH_CLASSES[3] })
    expect(got).toEqual({ a: ROLE_SWATCH_CLASSES[0] })
  })

  it('returns an empty map for an empty roles record', () => {
    expect(assignRoleColors({}, {})).toEqual({})
  })
})
