import { describe, expect, it } from 'vitest'
import {
  displacedByReopen,
  documentToLoad,
  isNavigation,
  urlStateOf,
  viewFromUrl,
  type SyncView,
} from './urlSyncRules'
import { EMPTY_URL_STATE, type UrlState } from './bootstrap'
import type { GroupsMap } from '../builder/paths'
import type { BlockNode, LoopNode, SerialNode } from '../builder/tree'

const base = { label: null, gapAfter: null, startOffset: null }
const wait = (uid: string): BlockNode => ({ uid, kind: 'wait', duration: '1s', ...base })

const tree: BlockNode[] = [
  {
    uid: 's1', kind: 'serial', ...base,
    children: [
      wait('w1'),
      {
        uid: 'l1', kind: 'loop', mode: 'count', count: 2, until: '', check: 'after',
        pace: null, body: [wait('w2')], ...base,
      } satisfies LoopNode,
    ],
  } satisfies SerialNode,
]

const groups: GroupsMap = {
  dose: { params: [], body: [wait('g1'), wait('g2')] },
  // A name carrying BOTH quote characters: paths.ts's quoteGroupName cannot spell it, so
  // pathForUid returns null for anything inside it.
  [`it's "odd"`]: { params: [], body: [wait('q1')] },
}

const view = (over: Partial<SyncView> = {}): SyncView => ({
  tab: 'Builder',
  serverId: null,
  openRecordId: null,
  scope: null,
  selectedUid: null,
  tree,
  groups,
  ...over,
})

const url = (over: Partial<UrlState> = {}): UrlState => ({ ...EMPTY_URL_STATE, ...over })

describe('urlStateOf', () => {
  it('projects the plain fields straight through', () => {
    expect(urlStateOf(view({ tab: 'Run', serverId: 'a1b2', scope: 'dose' }))).toEqual({
      tab: 'Run', exp: 'a1b2', rec: null, scope: 'dose', sel: null,
    })
  })

  it('emits sel as a STRUCTURAL path, never the uid', () => {
    const sel = urlStateOf(view({ selectedUid: 'w2' })).sel
    expect(sel).toBe('blocks[0].children[1].body[0]')
    // The guard that matters for a shared link: uids are re-minted by docToTree (convert.ts),
    // so a uid in the URL means nothing to the recipient.
    expect(sel).not.toBe('w2')
    expect(sel).not.toContain('w2')
  })

  it('spells a selection inside a group as a groups[...] path', () => {
    expect(urlStateOf(view({ scope: 'dose', selectedUid: 'g2' })).sel)
      .toBe(`groups['dose'].body[1]`)
  })

  it('yields null — not the STRING "null" — for a uid that is not in the document', () => {
    const sel = urlStateOf(view({ selectedUid: 'ghost' })).sel
    expect(sel).toBeNull()
    expect(sel).not.toBe('null')
    expect(typeof sel).not.toBe('string')
  })

  it('yields null for a uid inside a group whose name cannot be spelled', () => {
    // pathForUid skips a group quoteGroupName returns null for; the null must survive to
    // formatHash, which then omits the param instead of writing an unresolvable sel=null.
    expect(urlStateOf(view({ scope: `it's "odd"`, selectedUid: 'q1' })).sel).toBeNull()
  })

  it('suppresses rec off the Records tab, and carries it on it', () => {
    expect(urlStateOf(view({ tab: 'Builder', openRecordId: 'rec_99' })).rec).toBeNull()
    expect(urlStateOf(view({ tab: 'Run', openRecordId: 'rec_99' })).rec).toBeNull()
    expect(urlStateOf(view({ tab: 'Records', openRecordId: 'rec_99' })).rec).toBe('rec_99')
  })

  it('keeps a record left open in the store from making two equal hashes compare unequal', () => {
    // formatHash only emits rec under /records. If the projection carried openRecordId under
    // another tab, these two would differ while formatting identically, and isNavigation would
    // report a navigation that produced no URL change.
    expect(urlStateOf(view({ tab: 'Run', openRecordId: 'rec_99' })))
      .toEqual(urlStateOf(view({ tab: 'Run', openRecordId: null })))
  })
})

describe('isNavigation', () => {
  const a = url({ tab: 'Builder', exp: 'e1', rec: null, scope: 'dose', sel: 'blocks[0]' })

  it('is true for a tab change', () => {
    expect(isNavigation(a, { ...a, tab: 'Run' })).toBe(true)
  })

  it('is true for a document change', () => {
    expect(isNavigation(a, { ...a, exp: 'e2' })).toBe(true)
    expect(isNavigation(a, { ...a, exp: null })).toBe(true)
  })

  it('is true for a record change', () => {
    expect(isNavigation(a, { ...a, rec: 'rec_7' })).toBe(true)
  })

  it('is true for a scope change', () => {
    expect(isNavigation(a, { ...a, scope: null })).toBe(true)
    expect(isNavigation(a, { ...a, scope: 'other' })).toBe(true)
  })

  it('is FALSE for a sel-only change — a cursor is not a place', () => {
    // Every canvas click moves sel. Pushing those would build a second, denser undo stack on
    // the Back button alongside zundo's real one.
    expect(isNavigation(a, { ...a, sel: 'blocks[0].children[0]' })).toBe(false)
    expect(isNavigation(a, { ...a, sel: null })).toBe(false)
  })

  it('is false for no change at all', () => {
    expect(isNavigation(a, { ...a })).toBe(false)
  })
})

describe('documentToLoad', () => {
  it('returns the id when the URL names a DIFFERENT document', () => {
    expect(documentToLoad(url({ exp: 'e2' }), 'e1')).toBe('e2')
  })

  it('returns the id when nothing is open yet', () => {
    expect(documentToLoad(url({ exp: 'e2' }), null)).toBe('e2')
  })

  it('is null when the open document already satisfies the URL', () => {
    // A Back press across a scope or selection change within one document must NOT refetch:
    // that would discard unsaved edits, and no confirm() guard covers a Back press.
    expect(documentToLoad(url({ exp: 'e1', scope: 'dose' }), 'e1')).toBeNull()
    expect(documentToLoad(url({ exp: 'e1', sel: 'blocks[0]' }), 'e1')).toBeNull()
  })

  it('is null when the URL names NO document, whatever is open', () => {
    // Reachable without hand-editing: saving an unsaved document moves exp null -> X, which
    // isNavigation pushes, so Back lands on the pre-save entry for the SAME document. Reading
    // that as "open a blank one" would destroy the document that was just saved.
    expect(documentToLoad(url({ exp: null }), 'e1')).toBeNull()
    expect(documentToLoad(url({ exp: null }), null)).toBeNull()
  })

  it('ignores every field except exp', () => {
    const a = url({ tab: 'Run', exp: 'e1', rec: 'r1', scope: 'dose', sel: 'blocks[0]' })
    expect(documentToLoad(a, 'e1')).toBeNull()
  })
})

describe('displacedByReopen', () => {
  it('warns, naming the document, when it is dirty', () => {
    expect(displacedByReopen(true, 'Y')).toEqual({ name: 'Y' })
  })

  it('is silent when it is clean — nothing the server does not already have', () => {
    expect(displacedByReopen(false, 'Y')).toBeNull()
  })

  it('carries the name verbatim, even an empty one — spelling it is the caller’s business', () => {
    expect(displacedByReopen(true, '')).toEqual({ name: '' })
  })
})

describe('viewFromUrl', () => {
  it('resolves a live scope and a live sel', () => {
    expect(viewFromUrl(url({ scope: 'dose', sel: `groups['dose'].body[1]` }), tree, groups))
      .toEqual({ scope: 'dose', selectedUid: 'g2' })
  })

  it('resolves a main-tree sel', () => {
    expect(viewFromUrl(url({ sel: 'blocks[0].children[1].body[0]' }), tree, groups).selectedUid)
      .toBe('w2')
  })

  it('clears a sel whose block is gone — an out-of-range index', () => {
    expect(viewFromUrl(url({ sel: 'blocks[0].children[9]' }), tree, groups).selectedUid).toBeNull()
  })

  it('clears a sel naming a group that no longer exists', () => {
    expect(viewFromUrl(url({ sel: `groups['gone'].body[0]` }), tree, groups).selectedUid).toBeNull()
  })

  it('clears a syntactically malformed sel rather than throwing', () => {
    expect(viewFromUrl(url({ sel: 'not a path at all' }), tree, groups).selectedUid).toBeNull()
    expect(viewFromUrl(url({ sel: '' }), tree, groups).selectedUid).toBeNull()
  })

  it('clears a scope naming a group that no longer exists', () => {
    expect(viewFromUrl(url({ scope: 'gone' }), tree, groups).scope).toBeNull()
  })

  it('resolves scope and sel independently — a disagreement is taken literally', () => {
    // Only reachable by hand-editing; urlStateOf/formatHash always emit the two consistently.
    expect(viewFromUrl(url({ scope: 'dose', sel: 'blocks[0]' }), tree, groups))
      .toEqual({ scope: 'dose', selectedUid: 's1' })
  })

  describe('the prototype chain is not a group', () => {
    // These names are inherited from Object.prototype, so `name in groups` is TRUE for every
    // object literal. Accepting one would put docStore.scope on a group that does not exist —
    // a state nothing else in the app can reach — and activeList's `?? []` would render it as
    // a silently empty canvas with no error anywhere.
    const inherited = ['toString', 'constructor', 'valueOf', 'hasOwnProperty', '__proto__']

    it.each(inherited)('rejects scope=%s', (name) => {
      expect(viewFromUrl(url({ scope: name }), tree, groups).scope).toBeNull()
    })

    it('is discriminating: `in` would accept every one of these', () => {
      // This is the mutation guard. If Object.hasOwn in viewFromUrl were swapped for `in`,
      // the assertions above would return the name instead of null. This asserts the premise
      // that makes them meaningful — that the operator being avoided really does pass here —
      // so the cases above cannot degrade into vacuous "an absent key is absent" checks.
      for (const name of inherited) {
        expect(name in groups).toBe(true)
        expect(Object.hasOwn(groups, name)).toBe(false)
      }
    })

    it('still accepts a group that genuinely OWNS one of those names', () => {
      // The rule is ownership, not a denylist of names: a group really called `toString` is
      // legal (convert.ts loads keys verbatim) and must still open.
      const shadowed: GroupsMap = { ...groups, toString: { params: [], body: [wait('t1')] } }
      expect(viewFromUrl(url({ scope: 'toString' }), tree, shadowed).scope).toBe('toString')
    })
  })
})
