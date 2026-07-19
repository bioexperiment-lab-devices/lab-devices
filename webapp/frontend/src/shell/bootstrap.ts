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
import { snapshotOf } from '../stores/docStore'
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

// Must be snapshotOf (docStore.ts), NOT JSON.stringify(d.content) directly: snapshotOf
// rebuilds the content object with a FIXED key order (name, description, roles, streams,
// tree, groups, persistence, defaults, metadata), independent of whatever order the content
// happened to be constructed in. JSON.stringify is key-insertion-order sensitive, and
// convert.ts's docToTree builds DocContent in a DIFFERENT order (...groups, metadata,
// persistence, defaults) than snapshotOf's canonical one — so a raw JSON.stringify here would
// agree with selectDirty (docStore.ts) only by coincidence, and diverge the moment a draft's
// content was built by a path that orders those trailing keys differently, misclassifying a
// semantically clean draft as dirty. Do not "simplify" this back to JSON.stringify.
// Exported for the boot executor (App.tsx), which needs the same predicate for a different
// question: decideBoot uses it to choose a branch, the executor uses it to decide whether the
// restore is worth ANNOUNCING. Restoring a clean draft is a harmless no-op that still carries
// view state, but telling the user "Restored unsaved changes" when there were none is a lie —
// and it is reachable, because Toolbar's New does newDoc() + clearDraft() while autosave's
// 500ms debounce is still armed, so the empty document writes a fresh clean draft right back.
// One definition, not two: the snapshotOf-vs-JSON.stringify rule above must not be re-derived.
export const draftIsDirty = (d: Draft): boolean => snapshotOf(d.content) !== d.savedSnapshot

export function decideBoot(url: UrlState, draft: Draft | null): BootAction {
  if (url.exp !== null) {
    // Rows 1-3: the URL names a document, so it wins on identity. A draft only applies when
    // it is FOR that document and actually holds unsaved work; otherwise the server copy may
    // be newer. A draft for some other document is left in storage untouched — no branch
    // here clears it — so navigating back to it still restores it.
    if (draft !== null && draft.serverId === url.exp && draftIsDirty(draft)) {
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
