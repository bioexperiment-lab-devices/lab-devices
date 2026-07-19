import { describe, expect, it } from 'vitest'
import { decideBoot, EMPTY_URL_STATE, type UrlState } from './bootstrap'
import type { Draft } from '../stores/draftStorage'
import { snapshotOf } from '../stores/docStore'
import type { DocContent } from '../builder/convert'

const content = (name: string) => ({
  name,
  description: null,
  roles: {},
  streams: {},
  tree: [],
  groups: {},
})

const draft = (serverId: string | null, dirty: boolean, name = 'doc'): Draft => ({
  v: 1,
  serverId,
  // A dirty draft's savedSnapshot deliberately disagrees with its content.
  savedSnapshot: dirty ? 'STALE' : JSON.stringify(content(name)),
  content: content(name),
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
      displaces: null,
    })
  })

  // Regression for a false-dirty read: isDirty must use snapshotOf (docStore.ts), not a raw
  // JSON.stringify(d.content), because JSON.stringify is key-insertion-order sensitive and
  // snapshotOf is not — it rebuilds the object with a FIXED key order (…persistence, defaults,
  // metadata). This content sets persistence/defaults/metadata in the OPPOSITE order
  // (metadata, then persistence, then defaults) — mirroring convert.ts's docToTree, which
  // spreads them in exactly that order. savedSnapshot is snapshotOf(orderedContent), so the
  // draft is genuinely clean; a plain JSON.stringify(d.content) would produce a differently-
  // ordered string and read this as dirty, misrouting row 2 into row 1 (restoreDraft) and
  // skipping the "server copy may be newer" fetch entirely.
  it('row 2: differently-ordered persistence/defaults/metadata keys still read as clean', () => {
    const orderedContent: DocContent = {
      name: 'doc',
      description: null,
      roles: {},
      streams: {},
      tree: [],
      groups: {},
      metadata: { name: 'doc' },
      persistence: { default: 'in_memory', format: 'jsonl' },
      defaults: { retry: { attempts: 1 } },
    }
    const d: Draft = {
      v: 1,
      serverId: 'X',
      savedSnapshot: snapshotOf(orderedContent),
      content: orderedContent,
      view: { scope: null, selectedUid: null, collapsed: {} },
      updatedAt: 1_700_000_000_000,
    }
    expect(decideBoot(url({ exp: 'X' }), d)).toEqual({
      kind: 'loadServer',
      id: 'X',
      displaces: null,
    })
  })

  it('row 3: url exp differs from the draft -> load from the server', () => {
    expect(decideBoot(url({ exp: 'X' }), draft('Y', true))).toEqual({
      kind: 'loadServer',
      id: 'X',
      displaces: { name: 'doc' },
    })
  })

  it('row 3: url exp with no draft at all -> load from the server', () => {
    expect(decideBoot(url({ exp: 'X' }), null)).toEqual({
      kind: 'loadServer',
      id: 'X',
      displaces: null,
    })
  })

  // ---- design §5.1: row 3 destroys the foreign draft, so it must name it ------------------
  // decideBoot does not clear it, but fork 3 keeps ONE draft key and useDraftAutosave
  // overwrites it on the first post-boot mutation. These four cases fix the boundary between
  // "real unsaved work is being destroyed" and "nothing of value is lost", which is the
  // difference between an actionable warning and a banner the user learns to dismiss unread.

  it('§5.1: a DIRTY draft for another document is reported, by name', () => {
    const action = decideBoot(url({ exp: 'X' }), draft('Y', true, 'Morbidostat v3'))
    expect(action).toEqual({
      kind: 'loadServer',
      id: 'X',
      displaces: { name: 'Morbidostat v3' },
    })
  })

  it('§5.1: a CLEAN draft for another document is NOT reported — nothing is being lost', () => {
    const action = decideBoot(url({ exp: 'X' }), draft('Y', false, 'Morbidostat v3'))
    expect(action).toEqual({ kind: 'loadServer', id: 'X', displaces: null })
  })

  // The highest-stakes case, and the one a `serverId === null ? notForeign` shortcut would
  // miss: a never-saved document has no server copy anywhere, so the draft IS the only copy.
  it('§5.1: a dirty NEVER-SAVED draft counts as another document', () => {
    const action = decideBoot(url({ exp: 'X' }), draft(null, true, 'Untitled scratch'))
    expect(action).toEqual({
      kind: 'loadServer',
      id: 'X',
      displaces: { name: 'Untitled scratch' },
    })
  })

  // Row 2, not row 3: the draft is for the very document being opened. Warning here would tell
  // the user their work was replaced by itself.
  it('§5.1: a draft for the SAME document is NOT reported', () => {
    const action = decideBoot(url({ exp: 'X' }), draft('X', false, 'Same doc'))
    expect(action).toEqual({ kind: 'loadServer', id: 'X', displaces: null })
  })

  it('§5.1: no draft at all is NOT reported', () => {
    expect(decideBoot(url({ exp: 'X' }), null)).toMatchObject({ displaces: null })
  })

  // An unnamed document is ordinary (Toolbar's New starts one), and the empty string must
  // reach the notice as an empty string rather than being papered over here — bootstrap.ts
  // carries content.name verbatim and RestoreNotice decides how to spell "unnamed". A null
  // `displaces` would wrongly mean "nothing was lost".
  it('§5.1: an unnamed dirty foreign draft is still reported, with an empty name', () => {
    expect(decideBoot(url({ exp: 'X' }), draft('Y', true, ''))).toEqual({
      kind: 'loadServer',
      id: 'X',
      displaces: { name: '' },
    })
  })

  // The foreign draft must survive: URL-wins-identity would otherwise destroy unsaved work
  // every time someone follows a link (design §5, row 3). There is deliberately no runtime
  // test asserting that here: `BootAction` is a closed union (restoreDraft | loadServer |
  // newDoc) whose serialized form can never contain the substring 'clear' no matter what
  // decideBoot returns, so a return-value assertion on that string cannot fail and cannot
  // exercise the requirement. `decideBoot` is also pure and returns a value — it has no way
  // to observe or report whether storage was touched, so nothing here could ever check that
  // either. What actually guarantees the requirement is structural, not behavioural:
  // bootstrap.ts imports `Draft` as a TYPE-ONLY import (`import type { Draft } from
  // '../stores/draftStorage'`) and has no runtime import from draftStorage.ts, so no
  // reference to `clearDraft` can exist in this module at all — a compile-time guarantee
  // stronger than any assertion on decideBoot's return value. The behavioural half of the
  // requirement — that the boot EXECUTOR must not clear a foreign draft when it acts on a
  // BootAction — belongs to that executor's own task, not to this pure decision matrix.

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
