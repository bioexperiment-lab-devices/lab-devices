import { describe, expect, it } from 'vitest'
import { parseDraft, resolveDraft, serializeDraft, type Draft } from './draftStorage'

const sample = (): Draft => ({
  v: 2,
  serverId: 'a1b2',
  savedSnapshot: '{"name":"x"}',
  content: {
    name: 'x',
    description: null,
    roles: {},
    streams: {},
    tree: [],
    groups: {},
  },
  view: { scope: null, selectedUid: null, collapsed: {} },
  updatedAt: 1_700_000_000_000,
})

describe('parseDraft', () => {
  it('round-trips a draft', () => {
    expect(parseDraft(serializeDraft(sample()))).toEqual(sample())
  })

  it('preserves view state and a null serverId', () => {
    const d = sample()
    d.serverId = null
    d.view = { scope: 'dose', selectedUid: 'u1', collapsed: { u1: true, u2: false } }
    expect(parseDraft(serializeDraft(d))).toEqual(d)
  })

  // Totality: corrupt storage must never take the app down. Same contract as
  // parseOverrides in builder/roleColorStorage.ts.
  it.each([
    ['null input', null],
    ['empty string', ''],
    ['truncated json', '{'],
    ['an array', '[]'],
    ['a bare number', '7'],
    ['json null', 'null'],
    ['wrong version', '{"v":99,"serverId":null,"savedSnapshot":"","content":{},"view":{},"updatedAt":0}'],
    ['missing version', '{"serverId":null,"savedSnapshot":"","content":{},"view":{},"updatedAt":0}'],
    ['missing content', '{"v":1,"serverId":null,"savedSnapshot":"","view":{},"updatedAt":0}'],
    ['missing view', '{"v":1,"serverId":null,"savedSnapshot":"","content":{},"updatedAt":0}'],
    ['content is not an object', '{"v":1,"serverId":null,"savedSnapshot":"","content":3,"view":{},"updatedAt":0}'],
    ['serverId is a number', '{"v":1,"serverId":3,"savedSnapshot":"","content":{},"view":{},"updatedAt":0}'],
  ])('returns null for %s', (_label, raw) => {
    expect(parseDraft(raw)).toBeNull()
  })

  it('defaults a missing collapsed map rather than rejecting the draft', () => {
    const raw = JSON.stringify({
      ...sample(),
      view: { scope: null, selectedUid: null },
    })
    expect(parseDraft(raw)?.view.collapsed).toEqual({})
  })

  it('discards a v1 draft (schema-2 guard, design §7)', () => {
    const stale = JSON.stringify({ ...sample(), v: 1 })
    expect(parseDraft(stale)).toBeNull()
  })
})

describe('resolveDraft', () => {
  it('prefers a valid session copy over a different valid mirror', () => {
    const sessionDraft = sample()
    const mirrorDraft = { ...sample(), serverId: 'zzzz' }
    expect(resolveDraft(serializeDraft(sessionDraft), serializeDraft(mirrorDraft))).toEqual(sessionDraft)
  })

  // Regression guard: a corrupt session copy must not fall through to the mirror and be
  // presented, via the restore notice, as this tab's own authoritative work — the mirror is
  // read only when the session slot is genuinely empty (design §6.2), not merely unparseable.
  // Fails under the old `parseDraft(session) ?? parseDraft(local)`.
  it('returns null for a corrupt session copy without falling back to a valid mirror', () => {
    expect(resolveDraft('{not json', serializeDraft(sample()))).toBeNull()
  })

  it('falls back to a valid mirror when session is absent', () => {
    const mirrorDraft = sample()
    expect(resolveDraft(null, serializeDraft(mirrorDraft))).toEqual(mirrorDraft)
  })

  it('returns null when both session and mirror are absent', () => {
    expect(resolveDraft(null, null)).toBeNull()
  })

  it('returns null when session is absent and the mirror is corrupt', () => {
    expect(resolveDraft(null, '{not json')).toBeNull()
  })
})
