import { describe, expect, it } from 'vitest'
import { validateInputValue } from './inputValue'
import type { PendingInput } from '../types/runs'

const req = (over: Partial<PendingInput>): PendingInput => ({
  name: 'x', type: 'int', prompt: null, min: null, max: null, choices: null,
  block_id: 'b1', ...over,
})

describe('validateInputValue', () => {
  it('int: parses integers, rejects floats and garbage, enforces bounds', () => {
    expect(validateInputValue(req({ type: 'int' }), '5')).toEqual({ ok: true, value: 5 })
    expect(validateInputValue(req({ type: 'int' }), '5.5').ok).toBe(false)
    expect(validateInputValue(req({ type: 'int' }), 'abc').ok).toBe(false)
    expect(validateInputValue(req({ type: 'int', min: 1, max: 10 }), '11').ok).toBe(false)
    expect(validateInputValue(req({ type: 'int', min: 1 }), '0').ok).toBe(false)
  })
  it('float: parses finite numbers, enforces bounds', () => {
    expect(validateInputValue(req({ type: 'float' }), '0.6')).toEqual({ ok: true, value: 0.6 })
    expect(validateInputValue(req({ type: 'float' }), 'inf').ok).toBe(false)
    expect(validateInputValue(req({ type: 'float', max: 1 }), '1.5').ok).toBe(false)
  })
  it('bool: requires an actual boolean', () => {
    expect(validateInputValue(req({ type: 'bool' }), true)).toEqual({ ok: true, value: true })
    expect(validateInputValue(req({ type: 'bool' }), 'true').ok).toBe(false)
  })
  it('enum: string must be one of choices when given', () => {
    const e = req({ type: 'enum', choices: ['a', 'b'] })
    expect(validateInputValue(e, 'a')).toEqual({ ok: true, value: 'a' })
    expect(validateInputValue(e, 'c').ok).toBe(false)
    expect(validateInputValue(req({ type: 'enum', choices: null }), 'anything').ok).toBe(true)
  })
})
