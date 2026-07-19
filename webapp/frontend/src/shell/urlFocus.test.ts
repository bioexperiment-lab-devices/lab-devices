/** Drives the REAL docStore — it is plain zustand and touches no browser API, so the ordering
 * rule `applyUrlFocus` exists to hold is assertable in the node environment. Every test here is
 * written to fail if either half of that rule is flipped; the two `setScope`-spy cases are the
 * explicit mutation guards. */
import { beforeEach, describe, expect, it } from 'vitest'
import { applyUrlFocus } from './urlFocus'
import { EMPTY_URL_STATE, type UrlState } from './bootstrap'
import { loadDoc, useDocStore } from '../stores/docStore'
import type { BlockNode } from '../builder/tree'

const base = { label: null, gapAfter: null, startOffset: null }
const wait = (uid: string): BlockNode => ({ uid, kind: 'wait', duration: '1s', ...base })

const url = (over: Partial<UrlState> = {}): UrlState => ({ ...EMPTY_URL_STATE, ...over })

const load = (): void =>
  loadDoc(
    {
      name: 'doc',
      description: null,
      roles: {},
      streams: {},
      tree: [wait('w1'), wait('w2')],
      groups: { dose: { params: [], body: [wait('g1'), wait('g2')] } },
    },
    'srv1',
  )

describe('applyUrlFocus', () => {
  beforeEach(load)

  it('applies a live scope and a live sel together', () => {
    applyUrlFocus(url({ scope: 'dose', sel: `groups['dose'].body[1]` }))
    expect(useDocStore.getState().scope).toBe('dose')
    expect(useDocStore.getState().selectedUid).toBe('g2')
  })

  it('applies a main-tree selection', () => {
    applyUrlFocus(url({ sel: 'blocks[1]' }))
    expect(useDocStore.getState().scope).toBeNull()
    expect(useDocStore.getState().selectedUid).toBe('w2')
  })

  it('CLEARS a selection when the URL names none', () => {
    // The unguarded `select` is what makes this work: a Back press to a selection-less entry
    // must deselect, not leave the previous cursor standing. Guarding `select` the way
    // `setScope` is guarded would silently break exactly this.
    applyUrlFocus(url({ sel: 'blocks[0]' }))
    expect(useDocStore.getState().selectedUid).toBe('w1')
    applyUrlFocus(url())
    expect(useDocStore.getState().selectedUid).toBeNull()
  })

  it('clears the scope when the URL names none', () => {
    applyUrlFocus(url({ scope: 'dose' }))
    expect(useDocStore.getState().scope).toBe('dose')
    applyUrlFocus(url())
    expect(useDocStore.getState().scope).toBeNull()
  })

  it('does not call setScope when the scope already matches', () => {
    // The guard's whole purpose: `setScope` clears `selectedUid`, so an unguarded call would
    // wipe the selection resolved for the SAME scope. Spied rather than inferred, so deleting
    // the `if` fails here and not only through a downstream symptom.
    applyUrlFocus(url({ scope: 'dose' }))
    let calls = 0
    const real = useDocStore.getState().setScope
    useDocStore.setState({ setScope: (s) => { calls += 1; real(s) } })
    applyUrlFocus(url({ scope: 'dose', sel: `groups['dose'].body[0]` }))
    useDocStore.setState({ setScope: real })
    expect(calls).toBe(0)
    expect(useDocStore.getState().selectedUid).toBe('g1')
  })

  it('applies the scope BEFORE the selection', () => {
    // Selecting first would have the selection discarded by the scope change that follows.
    // Asserted on ORDER, not just the end state: the spy records what the selection was at the
    // moment setScope ran, which is null only if scope genuinely went first.
    const real = useDocStore.getState().setScope
    let selectedWhenScopeRan: string | null | undefined
    useDocStore.setState({
      setScope: (s) => {
        selectedWhenScopeRan = useDocStore.getState().selectedUid
        real(s)
      },
    })
    applyUrlFocus(url({ scope: 'dose', sel: `groups['dose'].body[1]` }))
    useDocStore.setState({ setScope: real })
    expect(selectedWhenScopeRan).toBeNull()
    expect(useDocStore.getState().selectedUid).toBe('g2')
  })

  it('clears rather than guesses when the URL outlived what it names', () => {
    applyUrlFocus(url({ scope: 'gone', sel: 'blocks[9]' }))
    expect(useDocStore.getState().scope).toBeNull()
    expect(useDocStore.getState().selectedUid).toBeNull()
  })
})
