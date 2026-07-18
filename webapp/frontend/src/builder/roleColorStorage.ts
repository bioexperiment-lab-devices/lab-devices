/** Reading and writing the role-colour overrides (design §5).
 *
 * User-settled 2026-07-18: these live in browser localStorage keyed by `type:name`, NOT in
 * the document. Role colour is a per-user reading aid, so a colleague opening the same doc
 * on the shared stack sees different colours and the assignment does not survive a new
 * machine — both accepted. Nothing here is exported, imported, validated, or sent to the
 * backend, which is what keeps this increment frontend-only.
 *
 * Parsing is total: every failure degrades to "no overrides", i.e. everything auto-assigned
 * from the ramp. Corrupt storage must never be able to take the canvas down.
 */
import { ROLE_SWATCH_CLASSES } from './roleColors'

export const ROLE_COLOR_STORAGE_KEY = 'studio.roleColors.v1'

const RAMP: readonly string[] = ROLE_SWATCH_CLASSES

export function parseOverrides(raw: string | null): Record<string, string | null> {
  if (raw === null) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return {}
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return {}
  const out: Record<string, string | null> = {}
  for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
    // A value outside the ramp would compile to no Tailwind class, rendering as no
    // background at all — indistinguishable on screen from "cleared", but not the same
    // state. Dropping it re-auto-assigns, which is the honest recovery.
    if (value === null) out[key] = null
    else if (typeof value === 'string' && RAMP.includes(value)) out[key] = value
  }
  return out
}

export function serializeOverrides(o: Record<string, string | null>): string {
  return JSON.stringify(o)
}
