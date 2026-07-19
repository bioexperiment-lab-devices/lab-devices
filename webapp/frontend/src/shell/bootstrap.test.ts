import { describe, expect, it } from 'vitest'
import { decideBoot, EMPTY_URL_STATE, type UrlState } from './bootstrap'
import type { Draft } from '../stores/draftStorage'

const content = (name: string) => ({
  name,
  description: null,
  roles: {},
  streams: {},
  tree: [],
  groups: {},
})

const draft = (serverId: string | null, dirty: boolean): Draft => ({
  v: 1,
  serverId,
  // A dirty draft's savedSnapshot deliberately disagrees with its content.
  savedSnapshot: dirty ? 'STALE' : JSON.stringify(content('doc')),
  content: content('doc'),
  view: { scope: null, selectedUid: null, collapsed: {} },
  updatedAt: 1_700_000_000_000,
})

const url = (over: Partial<UrlState> = {}): UrlState => ({ ...EMPTY_URL_STATE, ...over })

describe('decideBoot', () => {
  it('row 1: url exp matches a dirty draft -> restore the draft', () => {
    const d = draft('X', true)
    expect(decideBoot(url({ exp: 'X' }), d)).toEqual({ kind: 'restoreDraft', draft: d })
  })

  it('row 2: url exp matches a clean draft -> load from the server', () => {
    expect(decideBoot(url({ exp: 'X' }), draft('X', false))).toEqual({
      kind: 'loadServer',
      id: 'X',
    })
  })

  it('row 3: url exp differs from the draft -> load from the server', () => {
    expect(decideBoot(url({ exp: 'X' }), draft('Y', true))).toEqual({
      kind: 'loadServer',
      id: 'X',
    })
  })

  it('row 3: url exp with no draft at all -> load from the server', () => {
    expect(decideBoot(url({ exp: 'X' }), null)).toEqual({ kind: 'loadServer', id: 'X' })
  })

  // The foreign draft must survive: URL-wins-identity would otherwise destroy unsaved work
  // every time someone follows a link (design §5, row 3).
  it('row 3: never asks for the foreign draft to be cleared', () => {
    const action = decideBoot(url({ exp: 'X' }), draft('Y', true))
    expect(JSON.stringify(action)).not.toContain('clear')
  })

  it('row 4: no url exp, unsaved new-doc draft -> restore it', () => {
    const d = draft(null, true)
    expect(decideBoot(url(), d)).toEqual({ kind: 'restoreDraft', draft: d })
  })

  // The Phase A case: no URL exists yet, so a saved-then-edited document arrives here with
  // exp=null and serverId=X. Splitting row 4 on serverId would make Phase A a no-op for
  // every saved document (design §5).
  it('row 4: no url exp, draft belongs to a saved doc -> restore it anyway', () => {
    const d = draft('X', true)
    expect(decideBoot(url(), d)).toEqual({ kind: 'restoreDraft', draft: d })
  })

  it('row 4: no url exp, clean draft -> restore it', () => {
    const d = draft('X', false)
    expect(decideBoot(url(), d)).toEqual({ kind: 'restoreDraft', draft: d })
  })

  it('row 5: nothing anywhere -> a new document', () => {
    expect(decideBoot(url(), null)).toEqual({ kind: 'newDoc' })
  })

  it('is total over every combination of exp and draft presence', () => {
    for (const exp of [null, 'X']) {
      for (const d of [null, draft(null, true), draft('X', true), draft('Y', false)]) {
        expect(() => decideBoot(url({ exp }), d)).not.toThrow()
      }
    }
  })
})
