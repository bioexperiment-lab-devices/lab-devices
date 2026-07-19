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
    expect(decideBoot(url({ exp: 'X' }), d)).toEqual({ kind: 'loadServer', id: 'X' })
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
