import { describe, expect, it } from 'vitest'
import { seedParams, emptyOptionLabel } from './paramDefaults'
import type { ParamSpec } from '../types/catalog'

const p = (o: Partial<ParamSpec> & { name: string }): ParamSpec => ({
  type: 'string',
  required: false,
  ...o,
})

describe('seedParams', () => {
  it('pre-fills only params that declare a default', () => {
    expect(
      seedParams([
        p({ name: 'direction', values: ['forward', 'reverse'], default: 'forward' }),
        p({ name: 'enabled', type: 'bool', required: true, default: false }),
        p({ name: 'volume_ml', type: 'number', required: true }),
        p({ name: 'rotation', values: ['shortest'], on_omit: 'default' }),
      ]),
    ).toEqual({ direction: 'forward', enabled: false })
  })
})

describe('emptyOptionLabel', () => {
  it('omits the empty option when a default is present', () => {
    expect(emptyOptionLabel(p({ name: 'direction', default: 'forward' }))).toBeNull()
  })
  it('omits the empty option for a required param', () => {
    expect(emptyOptionLabel(p({ name: 'enabled', type: 'bool', required: true }))).toBeNull()
  })
  it('labels a deferring optional param', () => {
    expect(emptyOptionLabel(p({ name: 'rotation', on_omit: 'default' }))).toBe('— device default —')
  })
  it('labels a leave-unchanged optional param', () => {
    expect(emptyOptionLabel(p({ name: 'hold_torque', type: 'bool', on_omit: 'unchanged' }))).toBe(
      '— leave unchanged —',
    )
  })
  it('falls back to unset for a plain optional param', () => {
    expect(emptyOptionLabel(p({ name: 'x' }))).toBe('— unset —')
  })
})
