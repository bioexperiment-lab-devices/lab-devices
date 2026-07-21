import { describe, it, expect } from 'vitest'
import {
  hole,
  activeGroup,
  rolesInScope,
  groupRoleParamNames,
  groupStreamRefs,
  scopeStreamNames,
  scopeBindingNames,
} from './scopeRefs'
import type { GroupDef } from './convert'

const G = (over: Partial<GroupDef> = {}): GroupDef => ({ params: [], locals: {}, body: [], ...over })

// A group like morbidostat's `service` plus a role param and value params, exercising every kind.
const svc = G({
  params: [
    { name: 'param_pump', kind: 'role', device_type: 'pump' },
    { name: 'param_stream', kind: 'stream' },
    { name: 'tube', kind: 'int' },
    { name: 'note', kind: 'string' },
  ],
  locals: {
    local_stream: { kind: 'stream', units: 'AU' },
    c: { kind: 'binding', init: '0' },
  },
})

describe('hole', () => {
  it('wraps a name in braces', () => {
    expect(hole('param_pump')).toBe('{param_pump}')
  })
})

describe('activeGroup', () => {
  it('is null at the workflow scope', () => {
    expect(activeGroup(null, { svc })).toBeNull()
  })
  it('is null when scope names a group that does not exist', () => {
    expect(activeGroup('gone', {})).toBeNull()
  })
  it('returns the named group', () => {
    expect(activeGroup('svc', { svc })).toBe(svc)
  })
})

describe('rolesInScope', () => {
  const roles = { top_pump: { type: 'pump' }, valve1: { type: 'valve' } }
  it('returns the given roles unchanged at the workflow scope', () => {
    expect(rolesInScope(roles, null)).toBe(roles)
  })
  it('adds role-kind params as {hole} -> { type }, keeping top-level roles', () => {
    const r = rolesInScope(roles, svc)
    expect(r['{param_pump}']).toEqual({ type: 'pump' })
    expect(r.top_pump).toEqual({ type: 'pump' })
    expect(Object.keys(r)).toHaveLength(3)
  })
  it('ignores non-role params', () => {
    const r = rolesInScope(roles, svc)
    expect(r['{param_stream}']).toBeUndefined()
    expect(r['{tube}']).toBeUndefined()
  })
  it('does not mutate the input roles', () => {
    rolesInScope(roles, svc)
    expect(roles).not.toHaveProperty('{param_pump}')
  })
  it('skips a role param missing its device_type', () => {
    const g = G({ params: [{ name: 'p', kind: 'role' }] })
    expect(rolesInScope({}, g)).toEqual({})
  })
})

describe('groupRoleParamNames', () => {
  it('is empty at the workflow scope', () => {
    expect(groupRoleParamNames(null).size).toBe(0)
  })
  it('is the set of role-param holes', () => {
    const s = groupRoleParamNames(svc)
    expect(s.has('{param_pump}')).toBe(true)
    expect(s.size).toBe(1)
  })
})

describe('groupStreamRefs', () => {
  it('is empty at the workflow scope', () => {
    expect(groupStreamRefs(null)).toEqual([])
  })
  it('lists stream params then stream locals as holes, carrying units', () => {
    expect(groupStreamRefs(svc)).toEqual([
      { ref: '{param_stream}', origin: 'param', units: null },
      { ref: '{local_stream}', origin: 'local', units: 'AU' },
    ])
  })
})

describe('scopeStreamNames', () => {
  it('is the bare top-level stream names at the workflow scope', () => {
    expect(scopeStreamNames({ od: {}, blank: {} }, null)).toEqual(['od', 'blank'])
  })
  it('appends the group stream params & locals as holes', () => {
    expect(scopeStreamNames({ od: {} }, svc)).toEqual(['od', '{param_stream}', '{local_stream}'])
  })
})

describe('scopeBindingNames', () => {
  it('is empty at the workflow scope', () => {
    expect(scopeBindingNames(null)).toEqual([])
  })
  it('lists value/binding params then binding locals as holes, excluding role & stream', () => {
    expect(scopeBindingNames(svc)).toEqual(['{tube}', '{note}', '{c}'])
  })
})
