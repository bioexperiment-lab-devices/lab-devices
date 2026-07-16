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

/** compute/record `value` is a ValueExpr (engine blocks.py:8 — str | int | float | bool) with no
 * catalog kind to key on, so coerce on shape alone: a bare numeric or boolean literal becomes its
 * JSON type, anything else stays an expression string. Without this the Inspector rewrites
 * {"value": 12} to {"value": "15"} on the first edit — semantically identical to the engine (a
 * literal string parses to the same value) but a silent loss of the literal fidelity
 * convert.test.ts pins. */
export function coerceValueInput(text: string): ParamValue {
  const t = text.trim()
  if (/^-?\d+(\.\d+)?$/.test(t)) return Number(t)
  if (t === 'true') return true
  if (t === 'false') return false
  return text
}
