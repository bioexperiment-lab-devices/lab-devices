/** Pure grouping for the palette's Roles section (spec §3.3): one entry per catalog
 * device type in catalog order — a type with no roles still gets a block, so the user
 * sees what the lab offers and can create the first role in place — then one entry per
 * unknown type cited by the doc's roles (first-appearance order, rendered amber by the
 * consumer). A null catalog (still loading, or errored) yields only the cited types, all
 * flagged unknown, rather than pretending to know their verbs. */
import type { Catalog } from '../types/catalog'

export interface RoleTypeGroup {
  type: string
  known: boolean
  roles: string[]
}

export function roleGroups(
  roles: Record<string, { type: string }>,
  catalog: Catalog | null,
): RoleTypeGroup[] {
  const known = new Set(Object.keys(catalog?.device_types ?? {}))
  const byType = new Map<string, string[]>([...known].map((t) => [t, []]))
  for (const [name, def] of Object.entries(roles)) {
    const list = byType.get(def.type)
    if (list) list.push(name)
    else byType.set(def.type, [name])
  }
  return [...byType.entries()].map(([type, rs]) => ({ type, known: known.has(type), roles: rs }))
}

/** Which badge is active inside a type block: the current pick while it still exists,
 * else the first role, else null. Pure so the fallback-on-delete rule is testable. */
export function effectiveSelection(roles: string[], current: string | null): string | null {
  if (current !== null && roles.includes(current)) return current
  return roles[0] ?? null
}
