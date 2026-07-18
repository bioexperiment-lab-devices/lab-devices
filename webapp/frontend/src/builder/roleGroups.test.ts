import { describe, expect, it } from 'vitest'
import { effectiveSelection, roleGroups } from './roleGroups'
import type { Catalog } from '../types/catalog'

const catalog = {
  device_types: { pump: {}, densitometer: {}, thermostat: {} },
} as unknown as Catalog

describe('roleGroups', () => {
  it('emits every catalog type in catalog order, with roles in doc order', () => {
    const groups = roleGroups(
      { od: { type: 'densitometer' }, drug_b: { type: 'pump' }, drug_a: { type: 'pump' } },
      catalog,
    )
    expect(groups.map((g) => g.type)).toEqual(['pump', 'densitometer', 'thermostat'])
    expect(groups[0]).toEqual({ type: 'pump', known: true, roles: ['drug_b', 'drug_a'] })
    expect(groups[1].roles).toEqual(['od'])
    expect(groups[2]).toEqual({ type: 'thermostat', known: true, roles: [] })
  })
  it('appends unknown types cited by roles, flagged and in first-appearance order', () => {
    const groups = roleGroups(
      { x: { type: 'zz_gone' }, y: { type: 'aa_gone' } },
      catalog,
    )
    expect(groups.slice(3)).toEqual([
      { type: 'zz_gone', known: false, roles: ['x'] },
      { type: 'aa_gone', known: false, roles: ['y'] },
    ])
  })
  it('with a null catalog, groups only what the roles cite, all unknown', () => {
    expect(roleGroups({ p: { type: 'pump' } }, null)).toEqual([
      { type: 'pump', known: false, roles: ['p'] },
    ])
  })
})

describe('effectiveSelection', () => {
  it('keeps the current pick while it exists', () => {
    expect(effectiveSelection(['a', 'b'], 'b')).toBe('b')
  })
  it('falls back to the first role when the pick is gone (deleted/renamed)', () => {
    expect(effectiveSelection(['a', 'b'], 'zz')).toBe('a')
  })
  it('is null for an empty role list', () => {
    expect(effectiveSelection([], null)).toBeNull()
  })
})
