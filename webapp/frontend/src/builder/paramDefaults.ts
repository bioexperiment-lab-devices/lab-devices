import type { ParamSpec } from '../types/catalog'
import type { ParamValue } from '../types/doc'

/** Params to pre-fill a freshly-created device-command/measure node with: every spec that
 * declares a `default`. Seeding at creation (not on load) keeps the authored doc explicit
 * while leaving legacy omitted params byte-stable. */
export function seedParams(specs: ParamSpec[]): Record<string, ParamValue> {
  const out: Record<string, ParamValue> = {}
  for (const s of specs) if (s.default !== undefined) out[s.name] = s.default
  return out
}

/** The empty ("omit this param") option's label for an enum/bool select, or null when the
 * option must not be shown. Hidden when the param has a canonical `default` or is `required`
 * (omission is pointless or invalid); otherwise labelled from `on_omit`. */
export function emptyOptionLabel(spec: ParamSpec): string | null {
  if (spec.default !== undefined || spec.required) return null
  if (spec.on_omit === 'default') return '— device default —'
  if (spec.on_omit === 'unchanged') return '— leave unchanged —'
  return '— unset —'
}
