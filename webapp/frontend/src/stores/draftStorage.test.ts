import { describe, expect, it } from 'vitest'
import { parseDraft, serializeDraft, type Draft } from './draftStorage'

const sample = (): Draft => ({
  v: 1,
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
})
