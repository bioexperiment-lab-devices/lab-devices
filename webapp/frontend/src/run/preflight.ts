/** Pure preflight-mapping helpers (§9.4): options filtered by role type, saved-mapping
 * pre-fill applies only where the device still exists in the roster with the right type. */
import type { LabDevice } from '../types/labs'

export interface MappingRow {
  role: string
  type: string
  options: LabDevice[]
  selected: string | null
}

export function buildMappingRows(
  roles: Record<string, { type: string }>,
  devices: LabDevice[] | null,
  chosen: Record<string, string>,
): MappingRow[] {
  return Object.entries(roles).map(([role, def]) => {
    const options = (devices ?? []).filter((d) => d.type === def.type)
    const candidate = chosen[role]
    const selected =
      candidate !== undefined && options.some((d) => d.id === candidate) ? candidate : null
    return { role, type: def.type, options, selected }
  })
}

export function prefillMapping(
  roles: Record<string, { type: string }>,
  devices: LabDevice[] | null,
  saved: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {}
  for (const row of buildMappingRows(roles, devices, saved)) {
    if (row.selected !== null) out[row.role] = row.selected
  }
  return out
}

export const mappingComplete = (rows: MappingRow[]): boolean =>
  rows.every((r) => r.selected !== null)

/** W6 (a): apply the prefill once the roster arrives without clobbering user picks —
 * loadSelection snapshots the devices list once; a slow roster fetch used to silently
 * drop the saved S2 mapping. */
export function mergePrefill(
  chosen: Record<string, string>,
  roles: Record<string, { type: string }>,
  devices: LabDevice[] | null,
  saved: Record<string, string>,
): Record<string, string> {
  if (devices === null || Object.keys(chosen).length > 0) return chosen
  return prefillMapping(roles, devices, saved)
}

/** How many roles still lack a device — shown beside the green check so "workflow
 * valid" can't read as "ready to start" while Start stays disabled (audit F22). */
export function unmappedCount(rows: MappingRow[]): number {
  return rows.filter((r) => r.selected === null).length
}
