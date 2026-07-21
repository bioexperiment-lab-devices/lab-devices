import { describe, expect, it } from 'vitest'
import { buildPayload } from './buildPayload'
import type { ParamDef } from './catalog'

const p = (o: Partial<ParamDef> & { name: string; kind: ParamDef['kind'] }): ParamDef => ({
  label: o.name,
  ...o,
})

describe('buildPayload', () => {
  it('omits optional empty fields, coerces numbers', () => {
    const params = [
      p({ name: 'volume_ml', kind: 'number', required: true }),
      p({ name: 'speed_ml_min', kind: 'number' }),
      p({ name: 'direction', kind: 'enum', options: ['forward'], required: true }),
    ]
    expect(buildPayload(params, { volume_ml: '10', speed_ml_min: '', direction: 'forward' })).toEqual({
      volume_ml: 10,
      direction: 'forward',
    })
  })

  it('coerces int (truncates) and bool', () => {
    const params = [p({ name: 'position', kind: 'int' }), p({ name: 'enabled', kind: 'bool' })]
    expect(buildPayload(params, { position: '3.9', enabled: 'true' })).toEqual({
      position: 3,
      enabled: true,
    })
  })

  it('returns null when a required field is empty', () => {
    const params = [p({ name: 'volume_ml', kind: 'number', required: true })]
    expect(buildPayload(params, { volume_ml: '' })).toBeNull()
  })

  it('returns null when a number is unparseable', () => {
    const params = [p({ name: 'volume_ml', kind: 'number', required: true })]
    expect(buildPayload(params, { volume_ml: 'abc' })).toBeNull()
  })

  it('missing key is treated as empty', () => {
    const params = [p({ name: 'speed', kind: 'number' })]
    expect(buildPayload(params, {})).toEqual({})
  })

  it('empty params → empty object', () => {
    expect(buildPayload([], {})).toEqual({})
  })
})
