import { describe, expect, it } from 'vitest'
import { deviceLabel } from './deviceLabel'

describe('deviceLabel', () => {
  it('uses "name — id" when named', () => {
    expect(deviceLabel({ id: 'pump_1', name: 'Culture pump' })).toBe('Culture pump — pump_1')
  })
  it('falls back to the bare id', () => {
    expect(deviceLabel({ id: 'pump_1', name: null })).toBe('pump_1')
    expect(deviceLabel({ id: 'pump_1', name: '' })).toBe('pump_1')
  })
})
