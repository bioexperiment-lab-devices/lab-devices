import { describe, expect, it } from 'vitest'
import { parseOverrides, serializeOverrides } from './roleColorStorage'
import { ROLE_SWATCH_CLASSES } from './roleColors'

describe('parseOverrides', () => {
  it('returns an empty map for absent storage', () => {
    expect(parseOverrides(null)).toEqual({})
  })

  // Role colour is a reading aid, never document state. Corrupt storage must degrade to
  // "everything auto-assigned", never throw and take the canvas down with it.
  it('returns an empty map for unparseable JSON', () => {
    expect(parseOverrides('{not json')).toEqual({})
  })

  it('returns an empty map for JSON that is not an object', () => {
    expect(parseOverrides('[1,2,3]')).toEqual({})
    expect(parseOverrides('"a string"')).toEqual({})
    expect(parseOverrides('null')).toEqual({})
  })

  it('keeps class strings and explicit nulls', () => {
    const raw = JSON.stringify({ 'pump:a': ROLE_SWATCH_CLASSES[2], 'pump:b': null })
    expect(parseOverrides(raw)).toEqual({ 'pump:a': ROLE_SWATCH_CLASSES[2], 'pump:b': null })
  })

  // A colour class that is not in the ramp would render as an unknown Tailwind class —
  // i.e. no background at all — which looks identical to "cleared" but is not.
  it('drops values that are neither null nor a ramp class', () => {
    const raw = JSON.stringify({ 'pump:a': 'bg-red-500', 'pump:b': 42, 'pump:c': null })
    expect(parseOverrides(raw)).toEqual({ 'pump:c': null })
  })

  // Stale keys are inert BY DESIGN and must not be pruned: a rename followed by an undo
  // has to recover the original colour (spec §5).
  it('keeps keys for roles that no longer exist', () => {
    const raw = JSON.stringify({ 'pump:deleted': ROLE_SWATCH_CLASSES[1] })
    expect(parseOverrides(raw)).toEqual({ 'pump:deleted': ROLE_SWATCH_CLASSES[1] })
  })
})

describe('serializeOverrides', () => {
  it('round-trips through parseOverrides', () => {
    const o = { 'pump:a': ROLE_SWATCH_CLASSES[0], 'sensor:b': null }
    expect(parseOverrides(serializeOverrides(o))).toEqual(o)
  })
})
