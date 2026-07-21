import { describe, expect, it } from 'vitest'
import { argEditorFor, asRequired, defaultArgValue, emptyRow, rolesOfType } from './groupArgs'

describe('argEditorFor', () => {
  it('maps each kind to its editor', () => {
    expect(argEditorFor('int')).toBe('integer')
    expect(argEditorFor('number')).toBe('number')
    expect(argEditorFor('bool')).toBe('bool')
    expect(argEditorFor('string')).toBe('text')
    expect(argEditorFor('binding')).toBe('text')
    expect(argEditorFor('stream')).toBe('stream')
    expect(argEditorFor('role')).toBe('role')
  })
})
describe('asRequired', () => {
  it('is true only when the group declares locals (design §6)', () => {
    expect(asRequired(undefined)).toBe(false)
    expect(asRequired({ locals: {} })).toBe(false)
    expect(asRequired({ locals: { c: { kind: 'binding' } } })).toBe(true)
  })
})
describe('rolesOfType', () => {
  it('returns only role names whose declared type matches', () => {
    const roles = { od_meter_1: { type: 'densitometer' }, od_meter_2: { type: 'densitometer' }, p: { type: 'pump' } }
    expect(rolesOfType(roles, 'densitometer')).toEqual(['od_meter_1', 'od_meter_2'])
    expect(rolesOfType(roles, 'pump')).toEqual(['p'])
    expect(rolesOfType(roles, undefined)).toEqual([])
  })
})
describe('emptyRow', () => {
  it('seeds one typed cell per declared var', () => {
    expect(emptyRow([{ name: 'tube', kind: 'int' }, { name: 'meter', kind: 'role', device_type: 'densitometer' }, { name: 'ok', kind: 'bool' }]))
      .toEqual({ tube: 0, meter: '', ok: false })
  })
})
describe('defaultArgValue', () => {
  it('is a typed zero-value per kind', () => {
    expect(defaultArgValue('int')).toBe(0)
    expect(defaultArgValue('bool')).toBe(false)
    expect(defaultArgValue('stream')).toBe('')
  })
})
