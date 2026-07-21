/** Pure helpers behind the typed group/for_each/role editors (design §9.2). Kept out of
 * Inspector.tsx's DOM wiring so the kind→editor mapping, arity/zero-value defaults, and the
 * role-filter/row-shape logic are unit-testable — the forms themselves are DOM wiring the
 * probe harness verifies, not vitest (webapp/frontend/CLAUDE.md "Testing"). */
import type { LocalDeclJson, ParamDeclJson, ParamKind, ParamValue, RoleDeclJson } from '../types/doc'

export type ArgEditor = 'role' | 'stream' | 'number' | 'integer' | 'bool' | 'text'

export function argEditorFor(kind: ParamKind): ArgEditor {
  switch (kind) {
    case 'role':
      return 'role'
    case 'stream':
      return 'stream'
    case 'int':
      return 'integer'
    case 'number':
      return 'number'
    case 'bool':
      return 'bool'
    case 'string':
    case 'binding':
      return 'text'
  }
}

export function defaultArgValue(kind: ParamKind): ParamValue {
  if (kind === 'int' || kind === 'number') return 0
  if (kind === 'bool') return false
  return ''
}

/** `as` (the call-site local-namespace prefix) is required iff the target group declares at
 * least one local (design §6) — a group with no locals has nothing to namespace, so `as` stays
 * optional for it. `undefined` covers an unpicked/unknown group name. */
export function asRequired(group: { locals: Record<string, LocalDeclJson> } | undefined): boolean {
  return group !== undefined && Object.keys(group.locals).length > 0
}

export function rolesOfType(roles: Record<string, RoleDeclJson>, deviceType: string | undefined): string[] {
  if (deviceType === undefined) return []
  return Object.entries(roles)
    .filter(([, r]) => r.type === deviceType)
    .map(([name]) => name)
}

export function emptyRow(vars: ParamDeclJson[]): Record<string, ParamValue> {
  const row: Record<string, ParamValue> = {}
  for (const v of vars) row[v.name] = defaultArgValue(v.kind)
  return row
}

/** Mirrors the engine's `_WHOLE_HOLE_RE` (validate.py/expand.py, design 2026-07-20 §3): a
 * group_ref/for_each arg carries a typed-substitution hole only when the ENTIRE string is
 * `{identifier}` — unlike the free-form `string` kind, a non-string-kind arg (int/number/bool)
 * or a reference-kind arg (role/stream/binding) never partially interpolates, so `{tube}` is a
 * hole but `tube_{tube}` is not a legal value for those kinds. Used by `ArgField` to decide
 * whether a role/stream slot must show its raw hole text instead of the picker it usually
 * renders — a picker's `<option>`s only cover real names, so a hole value matches none of
 * them and would otherwise render as whatever the first option happens to be. */
export function isHole(value: ParamValue | undefined): boolean {
  return typeof value === 'string' && /^\{[A-Za-z_][A-Za-z0-9_]*\}$/.test(value)
}
