/** Param input coercion for the "smart" inspector fields: numeric literals become JSON
 * numbers, anything else is kept as an expression string (the engine accepts expression
 * strings for number/int/bool params — that is how operator-input bindings are used).
 * String params are literal-only per the engine validator. */
import type { ParamValue } from '../types/doc'
import type { ParamKind } from '../types/catalog'

export const DURATION_RE = /^\d+(\.\d+)?(ms|s|min|h)$/

export function coerceParamInput(text: string, kind: ParamKind): ParamValue | undefined {
  const t = text.trim()
  if (t === '') return undefined
  if (kind === 'string') return text
  if (kind === 'int' && /^-?\d+$/.test(t)) return Number(t)
  if (kind === 'number' && /^-?\d+(\.\d+)?$/.test(t)) return Number(t)
  if (kind === 'bool') {
    if (t === 'true') return true
    if (t === 'false') return false
  }
  return text
}

export function paramInputText(value: ParamValue | undefined): string {
  return value === undefined ? '' : String(value)
}
