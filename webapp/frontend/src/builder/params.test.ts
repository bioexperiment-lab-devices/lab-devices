import { describe, expect, it } from 'vitest'
import { DURATION_RE, coerceParamInput, coerceValueInput, paramInputText } from './params'

describe('coerceParamInput', () => {
  it('removes params on empty input', () => {
    expect(coerceParamInput('', 'number')).toBeUndefined()
    expect(coerceParamInput('   ', 'string')).toBeUndefined()
  })

  it('keeps string params literal', () => {
    expect(coerceParamInput('cw', 'string')).toBe('cw')
    expect(coerceParamInput('5', 'string')).toBe('5')
  })

  it('commits numeric literals as numbers and everything else as expressions', () => {
    expect(coerceParamInput('5', 'number')).toBe(5)
    expect(coerceParamInput('-2.5', 'number')).toBe(-2.5)
    expect(coerceParamInput('5', 'int')).toBe(5)
    expect(coerceParamInput('2.5', 'int')).toBe('2.5') // not an int literal → expression
    expect(coerceParamInput('feed_ml * 2', 'number')).toBe('feed_ml * 2')
  })

  it('handles bool literals and bool expressions', () => {
    expect(coerceParamInput('true', 'bool')).toBe(true)
    expect(coerceParamInput('false', 'bool')).toBe(false)
    expect(coerceParamInput('mean(od) > 1', 'bool')).toBe('mean(od) > 1')
  })
})

describe('paramInputText', () => {
  it('is the inverse presentation of stored values', () => {
    expect(paramInputText(undefined)).toBe('')
    expect(paramInputText(5)).toBe('5')
    expect(paramInputText(true)).toBe('true')
    expect(paramInputText('feed_ml * 2')).toBe('feed_ml * 2')
  })
})

describe('DURATION_RE', () => {
  it('matches the engine duration grammar (ms|s|min|h — NOT m)', () => {
    for (const ok of ['30s', '5min', '250ms', '1.5h']) expect(DURATION_RE.test(ok)).toBe(true)
    for (const bad of ['2m', '5 s', 's', '5', '5sec']) expect(DURATION_RE.test(bad)).toBe(false)
  })
})

describe('coerceValueInput', () => {
  it('coerces a numeric literal to a JSON number', () => {
    expect(coerceValueInput('15')).toBe(15)
    expect(typeof coerceValueInput('15')).toBe('number')
  })

  it('coerces a decimal literal to a JSON number', () => {
    expect(coerceValueInput('12.5')).toBe(12.5)
  })

  it('coerces a negative literal to a JSON number', () => {
    expect(coerceValueInput('-3')).toBe(-3)
  })

  it('coerces bool literals to JSON booleans', () => {
    expect(coerceValueInput('true')).toBe(true)
    expect(coerceValueInput('false')).toBe(false)
  })

  it('keeps an expression as a string, not coerced', () => {
    expect(coerceValueInput('c * 0.9')).toBe('c * 0.9')
  })

  it('keeps a bare binding/stream name as a string', () => {
    expect(coerceValueInput('od')).toBe('od')
  })

  it('keeps the empty seed value as an empty string', () => {
    expect(coerceValueInput('')).toBe('')
  })
})
