import { describe, expect, it } from 'vitest'
import {
  buildMappingRows,
  mappingComplete,
  mergePrefill,
  prefillMapping,
  unmappedCount,
  type MappingRow,
} from './preflight'
import type { LabDevice } from '../types/labs'

const dev = (id: string, type: string): LabDevice =>
  ({ id, type, port: null, connected: true, model: null, firmware: null, name: null })
const DEVICES = [dev('pump_1', 'pump'), dev('pump_2', 'pump'), dev('densitometer_1', 'densitometer')]
const ROLES = { feed: { type: 'pump' }, meter: { type: 'densitometer' } }

describe('buildMappingRows', () => {
  it('filters options by role type and keeps only valid selections', () => {
    const rows = buildMappingRows(ROLES, DEVICES, { feed: 'pump_2', meter: 'thermostat_1' })
    expect(rows.map((r) => r.role)).toEqual(['feed', 'meter'])
    expect(rows[0].options.map((d) => d.id)).toEqual(['pump_1', 'pump_2'])
    expect(rows[0].selected).toBe('pump_2')
    expect(rows[1].selected).toBeNull() // wrong-type selection dropped
  })
  it('handles a null roster', () => {
    const rows = buildMappingRows(ROLES, null, {})
    expect(rows[0].options).toEqual([])
  })
})

describe('prefillMapping', () => {
  it('keeps saved entries only when present in the roster with the right type', () => {
    expect(
      prefillMapping(ROLES, DEVICES, { feed: 'pump_9', meter: 'densitometer_1', ghost: 'x_1' }),
    ).toEqual({ meter: 'densitometer_1' })
  })
})

describe('mappingComplete', () => {
  it('true only when every role has a selection', () => {
    const rows = buildMappingRows(ROLES, DEVICES, { feed: 'pump_1', meter: 'densitometer_1' })
    expect(mappingComplete(rows)).toBe(true)
    expect(mappingComplete(buildMappingRows(ROLES, DEVICES, { feed: 'pump_1' }))).toBe(false)
  })

  describe('with no roles', () => {
    it('is vacuously complete — a no-roles experiment has nothing to map', () => {
      expect(mappingComplete([])).toBe(true)
    })
  })
})

describe('mergePrefill', () => {
  const roles = { feed: { type: 'pump' } }
  const devices = [{ id: 'pump_1', type: 'pump' }] as LabDevice[]

  it('fills an empty selection once the roster arrives', () => {
    expect(mergePrefill({}, roles, devices, { feed: 'pump_1' })).toEqual({ feed: 'pump_1' })
  })
  it('does nothing while the roster is still loading', () => {
    expect(mergePrefill({}, roles, null, { feed: 'pump_1' })).toEqual({})
  })
  it('never clobbers an existing selection', () => {
    const chosen = { feed: 'pump_2' }
    expect(mergePrefill(chosen, roles, devices, { feed: 'pump_1' })).toBe(chosen)
  })
})

describe('unmappedCount', () => {
  it('counts rows without a device (audit F22)', () => {
    const rows: MappingRow[] = [
      { role: 'a', type: 't', options: [], selected: 'dev1' },
      { role: 'b', type: 't', options: [], selected: null },
      { role: 'c', type: 't', options: [], selected: null },
    ]
    expect(unmappedCount(rows)).toBe(2)
    expect(unmappedCount([])).toBe(0)
  })
})
