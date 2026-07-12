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
  rows.length > 0 && rows.every((r) => r.selected !== null)
