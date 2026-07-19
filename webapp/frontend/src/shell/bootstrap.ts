/** What to open at boot, decided from the URL and the stored draft (design §5).
 *
 * Pure and total on purpose. The matrix below is the part of W16 most likely to be subtly
 * wrong — five branches, each with a different notion of who wins — so it is a plain function
 * from two values to a tagged action, fully assertable without a browser. The executor that
 * runs a BootAction is then dumb enough not to need tests.
 *
 * UrlState is declared HERE rather than in urlState.ts so Phase A can compile and test the
 * whole matrix before any hash parsing exists (design §9). urlState.ts merely produces it.
 */
import type { Draft } from '../stores/draftStorage'
import type { Tab } from './tabs'

export interface UrlState {
  tab: Tab
  exp: string | null
  rec: string | null
  scope: string | null
  sel: string | null
}

export const EMPTY_URL_STATE: UrlState = {
  tab: 'Builder',
  exp: null,
  rec: null,
  scope: null,
  sel: null,
}

export type BootAction =
  | { kind: 'restoreDraft'; draft: Draft }
  | { kind: 'loadServer'; id: string }
  | { kind: 'newDoc' }

const isDirty = (d: Draft): boolean => JSON.stringify(d.content) !== d.savedSnapshot

export function decideBoot(url: UrlState, draft: Draft | null): BootAction {
  if (url.exp !== null) {
    // Rows 1-3: the URL names a document, so it wins on identity. A draft only applies when
    // it is FOR that document and actually holds unsaved work; otherwise the server copy may
    // be newer. A draft for some other document is left in storage untouched — no branch
    // here clears it — so navigating back to it still restores it.
    if (draft !== null && draft.serverId === url.exp && isDirty(draft)) {
      return { kind: 'restoreDraft', draft }
    }
    return { kind: 'loadServer', id: url.exp }
  }
  // Rows 4-5: the URL names nothing, so the draft is the only candidate, whatever its
  // serverId. Splitting on serverId === null here would silently make Phase A a no-op for
  // every saved-then-edited document, since Phase A supplies no exp at all.
  if (draft !== null) return { kind: 'restoreDraft', draft }
  return { kind: 'newDoc' }
}
