/** Client-side mirror of the engine's validate_input_value (§7.4) so obviously-bad
 * values never round-trip; the server 422 (invalid_value) remains the authority. */
import type { PendingInput } from '../types/runs'

export type InputCheck =
  | { ok: true; value: boolean | number | string }
  | { ok: false; error: string }

const bounds = (input: PendingInput, n: number): InputCheck => {
  if (input.min !== null && n < input.min) return { ok: false, error: `must be ≥ ${input.min}` }
  if (input.max !== null && n > input.max) return { ok: false, error: `must be ≤ ${input.max}` }
  return { ok: true, value: n }
}

export function validateInputValue(input: PendingInput, raw: string | boolean): InputCheck {
  switch (input.type) {
    case 'bool':
      return typeof raw === 'boolean'
        ? { ok: true, value: raw }
        : { ok: false, error: 'pick yes or no' }
    case 'enum': {
      if (typeof raw !== 'string' || raw === '') return { ok: false, error: 'pick a choice' }
      if (input.choices !== null && !input.choices.includes(raw)) {
        return { ok: false, error: `must be one of: ${input.choices.join(', ')}` }
      }
      return { ok: true, value: raw }
    }
    case 'int': {
      const text = typeof raw === 'string' ? raw.trim() : ''
      if (!/^[+-]?\d+$/.test(text)) return { ok: false, error: 'enter a whole number' }
      return bounds(input, Number(text))
    }
    case 'float': {
      const text = typeof raw === 'string' ? raw.trim() : ''
      const n = Number(text)
      if (text === '' || !Number.isFinite(n)) return { ok: false, error: 'enter a number' }
      return bounds(input, n)
    }
  }
}
