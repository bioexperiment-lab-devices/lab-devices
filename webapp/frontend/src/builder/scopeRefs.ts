/** Scope-aware reference derivations (design 2026-07-21). While a group's body is the active
 * editing scope, the Builder's reference surfaces must offer that group's own typed params &
 * locals IN ADDITION to the top-level roles/streams — the group's shown as {name} holes, since
 * that is how a group body references them (engine expand.py `_HOLE_RE`). Kept pure (no React)
 * so the derivations are unit-testable; the one hook at the bottom is the single React entry
 * point. At the workflow scope (group === null) every function collapses to exactly the
 * top-level behavior, so nothing outside a group scope changes. */
import { useDocStore } from '../stores/docStore'
import type { GroupDef } from './convert'
import type { RoleDeclJson } from '../types/doc'

/** The {name} hole form a group body uses to reference its own param/local. */
export const hole = (name: string): string => `{${name}}`

/** The group currently being edited, or null at the workflow scope (or if scope names a group
 * that no longer exists). */
export function activeGroup(
  scope: string | null,
  groups: Record<string, GroupDef>,
): GroupDef | null {
  return scope === null ? null : (groups[scope] ?? null)
}

/** Role references usable in the active scope: every top-level role, PLUS the active group's
 * role-kind params keyed by their {hole} form -> { type: device_type }. Shaped exactly like
 * `s.roles` so ActionForm/RetrySection/roleGroups/rolesOfType consume it unchanged. Returns the
 * given `roles` (same reference) at the workflow scope. A role param missing its device_type is
 * skipped defensively — the engine requires it, but a half-typed row must not crash the UI. */
export function rolesInScope(
  roles: Record<string, RoleDeclJson>,
  group: GroupDef | null,
): Record<string, RoleDeclJson> {
  if (group === null) return roles
  const out: Record<string, RoleDeclJson> = { ...roles }
  for (const p of group.params) {
    if (p.kind === 'role' && p.device_type) out[hole(p.name)] = { type: p.device_type }
  }
  return out
}

/** The set of {hole} names contributed by the active group's role params — lets a consumer
 * partition a `rolesInScope` map's names into top-level vs. this-group entries for the additive
 * Roles display. Empty at the workflow scope. */
export function groupRoleParamNames(group: GroupDef | null): Set<string> {
  const names = new Set<string>()
  if (group !== null) {
    for (const p of group.params) if (p.kind === 'role') names.add(hole(p.name))
  }
  return names
}

export interface ScopeStreamRef {
  /** The name a body block uses to reference it — always the {hole} form here. */
  ref: string
  origin: 'param' | 'local'
  units: string | null
}

/** The active group's OWN stream references (its stream-kind params, then its stream-kind
 * locals), each as a {hole}. Empty at the workflow scope. Feeds the StreamsPanel "In this group"
 * subsection and (mapped to `.ref`) the Measure/Record Into picker's extra options. */
export function groupStreamRefs(group: GroupDef | null): ScopeStreamRef[] {
  if (group === null) return []
  const out: ScopeStreamRef[] = []
  for (const p of group.params) {
    if (p.kind === 'stream') out.push({ ref: hole(p.name), origin: 'param', units: null })
  }
  for (const [name, l] of Object.entries(group.locals)) {
    if (l.kind === 'stream') out.push({ ref: hole(name), origin: 'local', units: l.units ?? null })
  }
  return out
}

/** Stream names for expression help: bare top-level names + the active group's stream params &
 * locals as {holes}. */
export function scopeStreamNames(
  streams: Record<string, unknown>,
  group: GroupDef | null,
): string[] {
  return [...Object.keys(streams), ...groupStreamRefs(group).map((r) => r.ref)]
}

/** Scalar names usable in expressions, all as {holes}: the active group's VALUE params
 * (int/number/bool/string) and its binding params, then its binding locals. role/stream refs are
 * excluded — a role is a device name and a stream is offered under Streams, not as a scalar
 * binding. Callers union this with `collectBindings(activeTree)`. Empty at the workflow scope. */
export function scopeBindingNames(group: GroupDef | null): string[] {
  if (group === null) return []
  const out: string[] = []
  for (const p of group.params) {
    if (p.kind !== 'role' && p.kind !== 'stream') out.push(hole(p.name))
  }
  for (const [name, l] of Object.entries(group.locals)) {
    if (l.kind === 'binding') out.push(hole(name))
  }
  return out
}

/** The single React entry point: the active group plus the derivations every consumer needs,
 * subscribing to `roles`/`scope`/`groups` as separate slices (the same shape `useActiveTree`
 * uses) so a render fires only when one of those actually changes. */
export function useScopeRefs(): {
  scope: string | null
  group: GroupDef | null
  roles: Record<string, RoleDeclJson>
  streamHoles: string[]
  roleParamNames: Set<string>
} {
  const scope = useDocStore((s) => s.scope)
  const groups = useDocStore((s) => s.groups)
  const roles = useDocStore((s) => s.roles)
  const group = activeGroup(scope, groups)
  return {
    scope,
    group,
    roles: rolesInScope(roles, group),
    streamHoles: groupStreamRefs(group).map((r) => r.ref),
    roleParamNames: groupRoleParamNames(group),
  }
}
