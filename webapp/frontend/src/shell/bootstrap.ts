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

/** The unsaved work a `loadServer` boot is about to destroy (design §5.1).
 *
 * `name` is `content.name` VERBATIM and may be empty — how an unnamed document is spelled to
 * the user is the notice's business, not this module's. Carried as an object rather than a bare
 * `displacedName: string | null` so "there is nothing to warn about" is a null OBJECT, distinct
 * from "there is a document being displaced and it happens to have no name" (an empty string).
 * Flattening the two would make the highest-stakes case — a never-saved, never-named document,
 * where no server copy exists at all — indistinguishable from the no-op case.
 */
export interface DisplacedDraft {
  name: string
}

export type BootAction =
  | { kind: 'restoreDraft'; draft: Draft }
  // `displaces` is part of the ACTION rather than a separate predicate the executor has to
  // remember to call, because it is a property of this boot decision and nothing else: row 3 is
  // the only row that reaches it, and row 3 is only identifiable here. A sibling
  // `shouldWarnAboutDisplacedDraft(url, draft)` export would be a smaller diff, but it would be
  // a second traversal of the same matrix that a future edit to decideBoot could silently
  // desynchronise from — and, being optional at the call site, could simply be dropped. As a
  // required field of the variant, TypeScript makes the case impossible to construct without
  // answering it.
  | { kind: 'loadServer'; id: string; displaces: DisplacedDraft | null }
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

/** Row 3's casualty: the dirty draft of a DIFFERENT document than the URL names (design §5.1).
 *
 * `decideBoot` still never clears it — fork 7 is unchanged — but fork 3 stores exactly ONE
 * draft, so `useDraftAutosave` eventually overwrites it with the incoming document. BuilderTab
 * mounting is NOT enough on its own to trigger that (an earlier version of this comment said
 * it was — disproved by browser measurement, then independently re-traced): `useDraftAutosave`
 * is gated on `booted` (App.tsx), and `booted` is only set true in the boot effect's
 * `.finally()` — AFTER the `.then()`'s `loadDoc` and after `applyUrlView()`'s
 * `setScope`/`select`. So `useValidation`'s unconditional `setValidating(true)` on mount,
 * `loadDoc` itself, and `applyUrlView` all fire while `booted` is still false: there is no
 * autosave subscription yet to observe any of them. The `loadDoc`-triggered re-run of
 * `useValidation` loses the race too — React flushes passive effects child-first, so
 * BuilderTab's `useValidation` effect runs before App's `useDraftAutosave` effect within a
 * shared commit, and if the two land in separate commits the validation effect is still in the
 * earlier one. The first mutation the subscription actually observes is the ASYNC VALIDATION
 * RESULT landing — `setDiagnostics` + `setValidating(false)` on the success arm, or
 * `setValidationError` + `setValidating(false)` on the failure arm — which is useValidation's
 * 500ms debounce, plus one server round trip, THEN autosave's own 500ms debounce. That gap is
 * why sampling the foreign draft at ~1s to check whether it survived proves nothing: measured
 * intact at +900ms, gone by +5s. The loss is still certain regardless of which arm validation
 * lands on, since both mutate the store. The user settled on making the loss VISIBLE rather
 * than preventing it — preventing it would need per-document keys, reversing fork 3.
 *
 * Why this is the boot path that needs it: the three `confirm('Discard unsaved changes?')`
 * guards cover New / Load / Import / Duplicate, all of which are in-app actions. Following a
 * shared link is a fresh page load and hits none of them.
 *
 * `draft.serverId !== url.exp` deliberately treats a serverId of NULL as foreign. That is a
 * never-saved document, so unlike every other row-3 draft there is no server copy of it
 * anywhere — the single most valuable thing this warning can name.
 *
 * A CLEAN foreign draft returns null: it will still be overwritten, but it holds nothing the
 * server does not already have, so warning about it would be noise that trains the user to
 * dismiss the banner unread.
 *
 * Deliberately not gated on the active tab. Every post-boot docStore mutation lives under
 * src/builder/ (verified by grep — outside builder/, nothing mutates docStore after boot;
 * PreflightPanel's setValidating/setDiagnostics are local useState), so a boot at
 * `#/devices?exp=X` or `#/run?exp=X` warns that unsaved work "was replaced" before anything
 * has actually overwritten it — the loss lands only once the user opens Builder. Tab-gating
 * the decision would add a second variable to this matrix for little gain, so leaving it as is
 * is a deliberate choice, not an oversight.
 */
function displacedBy(url: UrlState, draft: Draft | null): DisplacedDraft | null {
  if (draft === null) return null
  // Unreachable-as-load-bearing: a dirty same-document draft is intercepted by decideBoot's
  // row-1 guard and never reaches displacedBy, so mutation-testing this line (delete it) leaves
  // all 16 tests green. Keep it anyway — it is the only thing that would stop a future
  // decideBoot edit that calls displacedBy for a same-document draft from mislabeling it foreign.
  if (draft.serverId === url.exp) return null
  if (!draftIsDirty(draft)) return null
  // parseDraft shape-checks `content` and then casts (draftStorage.ts), so `name` is only
  // typed as a string, not proven to be one. Degrade to unnamed rather than rendering
  // "undefined" into the notice.
  const name = typeof draft.content.name === 'string' ? draft.content.name : ''
  return { name }
}

export function decideBoot(url: UrlState, draft: Draft | null): BootAction {
  if (url.exp !== null) {
    // Rows 1-3: the URL names a document, so it wins on identity. A draft only applies when
    // it is FOR that document and actually holds unsaved work; otherwise the server copy may
    // be newer. A draft for some other document is not cleared by any branch here — but see
    // displacedBy above: storage does not actually preserve it either, so row 3 reports what
    // it is about to cost instead of pretending nothing happens.
    if (draft !== null && draft.serverId === url.exp && draftIsDirty(draft)) {
      return { kind: 'restoreDraft', draft }
    }
    return { kind: 'loadServer', id: url.exp, displaces: displacedBy(url, draft) }
  }
  // Rows 4-5: the URL names nothing, so the draft is the only candidate, whatever its
  // serverId. Splitting on serverId === null here would silently make Phase A a no-op for
  // every saved-then-edited document, since Phase A supplies no exp at all.
  if (draft !== null) return { kind: 'restoreDraft', draft }
  return { kind: 'newDoc' }
}
