import type { ParamDef } from './catalog'

/** Turn form string values into the wire params object. Optional-empty fields are omitted
 * (mirroring the library's `if x is not None` construction, design §5); required-empty or
 * unparseable-number returns null so the form keeps Run disabled. */
export function buildPayload(
  params: ParamDef[],
  values: Record<string, string>,
): Record<string, unknown> | null {
  const out: Record<string, unknown> = {}
  for (const p of params) {
    const raw = (values[p.name] ?? '').trim()
    if (raw === '') {
      if (p.required) return null
      continue
    }
    if (p.kind === 'number' || p.kind === 'int') {
      const n = Number(raw)
      if (!Number.isFinite(n)) return null
      out[p.name] = p.kind === 'int' ? Math.trunc(n) : n
    } else if (p.kind === 'bool') {
      out[p.name] = raw === 'true'
    } else {
      out[p.name] = raw
    }
  }
  return out
}
