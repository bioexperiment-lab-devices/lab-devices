# Experiment Studio W16 — draft persistence and URL state: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Studio survive a page refresh — the in-progress document restores from browser storage, and the active tab / open experiment / open record / group scope / selected block round-trip through the URL hash.

**Architecture:** Four pure modules carry every decision (`urlState.ts` parses and formats the hash, `paths.ts` gains the uid→structural-path inverse, `draftStorage.ts` parses and serializes the draft record, `bootstrap.ts` decides what to load) and two thin React hooks make the only contact with `window`, `sessionStorage`, and `localStorage`. Nothing here is testable through the DOM, so nothing here *decides* anything in a component.

**Tech Stack:** React 19, Zustand 5 (+ zundo temporal), TypeScript 6, Vite 8, vitest 4 (node environment), Tailwind 4, oxlint.

**Spec:** `docs/superpowers/specs/2026-07-19-studio-state-persistence-design.md`

## Global Constraints

- **All work happens in `webapp/frontend/`.** No backend change in this increment.
- **vitest runs in the node environment.** Pure functions only — no component rendering, no jsdom, no `@testing-library`. `localStorage` and `sessionStorage` do not exist in tests. (`webapp/frontend/CLAUDE.md`)
- **No new dependencies.** No router library. The hash router is hand-written against `URLSearchParams`.
- **No `beforeunload` handler.** Settled fork 4.
- **Storage access is always wrapped in `try/catch`** and degrades silently. Never copy `labsStore.ts`'s unguarded read.
- **Parsing is total.** Every parse function returns a valid value or `null` for *any* input string, and never throws. Precedent: `parseOverrides` in `builder/roleColorStorage.ts`.
- **Query strings are built with `URLSearchParams`, never string concatenation.** Group names may legally contain spaces, apostrophes, and `->` (`paths.ts:19-31`).
- **Storage keys:** `studio.draft.v1` in both `sessionStorage` and `localStorage`.
- **Interactive icons come from lucide-react via `ui/IconButton.tsx`;** controls render at 24px via `ui/controls.ts`. Never concatenate a width or colour onto a helper's output — helpers *select* one class per property. (`webapp/frontend/CLAUDE.md`)
- **Gate before every commit:** `cd webapp/frontend && npm run lint && npm test`. Full gate before the PR: `npm run lint && npm test && npm run build`.

---

## File Structure

**Phase A — draft persistence**

| File | Status | Responsibility |
|---|---|---|
| `src/stores/draftStorage.ts` | create | `Draft` type; pure `parseDraft`/`serializeDraft`; guarded `readDraft`/`writeDraft`/`clearDraft` |
| `src/stores/draftStorage.test.ts` | create | parse totality, round-trip |
| `src/shell/bootstrap.ts` | create | `UrlState`, `BootAction`, pure `decideBoot` |
| `src/shell/bootstrap.test.ts` | create | all five matrix rows |
| `src/stores/docStore.ts` | modify | `loadDoc` gains optional `view` argument |
| `src/stores/docStore.test.ts` | modify | view-rehydration cases |
| `src/shell/useDraftAutosave.ts` | create | debounced docStore→storage subscriber |
| `src/shell/RestoreNotice.tsx` | create | dismissible "Restored unsaved changes" bar |
| `src/builder/Toolbar.tsx` | modify | `clearDraft()` at the four erase sites |
| `src/App.tsx` | modify | run the boot executor, mount the autosave hook |

**Phase B — URL state**

| File | Status | Responsibility |
|---|---|---|
| `src/builder/paths.ts` | modify | add `pathForUid` |
| `src/builder/paths.test.ts` | modify | inverse property against the torture fixture |
| `src/shell/urlState.ts` | create | `parseHash`, `formatHash` |
| `src/shell/urlState.test.ts` | create | round-trip, hostile group names, malformed input |
| `src/shell/useUrlSync.ts` | create | mount-parse, `popstate`, store→hash writer |
| `src/stores/navStore.ts` | modify | `tab` seeded at boot |
| `src/App.tsx` | modify | feed the real `UrlState` into `decideBoot`; mount `useUrlSync` |

---

# PHASE A — DRAFT PERSISTENCE

### Task 1: Draft record — pure parse and serialize

**Files:**
- Create: `webapp/frontend/src/stores/draftStorage.ts`
- Test: `webapp/frontend/src/stores/draftStorage.test.ts`

**Interfaces:**
- Consumes: `DocContent` from `../builder/convert`.
- Produces: `interface Draft`, `DRAFT_STORAGE_KEY`, `parseDraft(raw: string | null): Draft | null`, `serializeDraft(d: Draft): string`.

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/stores/draftStorage.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/stores/draftStorage.test.ts`
Expected: FAIL — `Failed to resolve import "./draftStorage"`.

- [ ] **Step 3: Write minimal implementation**

Create `webapp/frontend/src/stores/draftStorage.ts`:

```ts
/** The in-progress document draft (design §6).
 *
 * Two layers (design §6.2, fork 6): sessionStorage is authoritative and per-tab, so two tabs
 * can never clobber each other's unsaved work; localStorage is a best-effort mirror read only
 * when the session copy is absent — a genuinely new tab or a new browser session.
 *
 * Parsing is total: every failure degrades to "no draft", i.e. a normal cold start. Corrupt
 * storage must never be able to take the Studio down. Same contract as parseOverrides in
 * builder/roleColorStorage.ts.
 */
import type { DocContent } from '../builder/convert'

export const DRAFT_STORAGE_KEY = 'studio.draft.v1'

export interface DraftView {
  scope: string | null
  selectedUid: string | null
  collapsed: Record<string, boolean>
}

export interface Draft {
  v: 1
  serverId: string | null
  // Stored, not recomputed: selectDirty (docStore.ts:153) compares live content against this
  // string, so a restored draft without it would read as clean and the unsaved dot would lie.
  savedSnapshot: string
  // The EDITOR form, not ExperimentDocJson: the wire form would round-trip through docToTree
  // on restore and remint every uid (convert.ts:108), invalidating view.selectedUid and every
  // key in view.collapsed.
  content: DocContent
  view: DraftView
  updatedAt: number
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v)

const nullableString = (v: unknown): v is string | null => v === null || typeof v === 'string'

function parseView(v: unknown): DraftView | null {
  if (!isRecord(v)) return null
  if (!nullableString(v.scope) || !nullableString(v.selectedUid)) return null
  const collapsed: Record<string, boolean> = {}
  // A missing or malformed collapsed map degrades to "nothing collapsed" rather than
  // rejecting the whole draft: losing the document to recover a display preference would be
  // a far worse trade than the one it is protecting against.
  if (isRecord(v.collapsed)) {
    for (const [key, value] of Object.entries(v.collapsed)) {
      if (typeof value === 'boolean') collapsed[key] = value
    }
  }
  return { scope: v.scope, selectedUid: v.selectedUid, collapsed }
}

export function parseDraft(raw: string | null): Draft | null {
  if (raw === null || raw === '') return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isRecord(parsed)) return null
  if (parsed.v !== 1) return null
  if (!nullableString(parsed.serverId)) return null
  if (typeof parsed.savedSnapshot !== 'string') return null
  if (!isRecord(parsed.content)) return null
  if (typeof parsed.updatedAt !== 'number') return null
  const view = parseView(parsed.view)
  if (view === null) return null
  return {
    v: 1,
    serverId: parsed.serverId,
    savedSnapshot: parsed.savedSnapshot,
    // Trusted as DocContent after the shape check above. A deep validation here would
    // duplicate convert.ts's grammar; the executor's docToTree/loadDoc path is what actually
    // has to survive a malformed tree, and it already reports DocConvertError.
    content: parsed.content as unknown as DocContent,
    view,
    updatedAt: parsed.updatedAt,
  }
}

export function serializeDraft(d: Draft): string {
  return JSON.stringify(d)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/stores/draftStorage.test.ts`
Expected: PASS, 16 tests.

- [ ] **Step 5: Commit**

```bash
cd webapp/frontend && npm run lint && npm test
git add src/stores/draftStorage.ts src/stores/draftStorage.test.ts
git commit -m "feat(studio): draft record parse/serialize (W16 Task 1)"
```

---

### Task 2: Storage edge — read, write, clear

**Files:**
- Modify: `webapp/frontend/src/stores/draftStorage.ts`

**Interfaces:**
- Consumes: `parseDraft`, `serializeDraft`, `DRAFT_STORAGE_KEY` from Task 1.
- Produces: `readDraft(): Draft | null`, `writeDraft(d: Draft): void`, `clearDraft(): void`.

This task has **no tests**: `sessionStorage` and `localStorage` do not exist in the node test environment, and this is exactly the untested edge the pure/edge split exists to isolate. All logic worth asserting lives in Task 1.

- [ ] **Step 1: Append the storage edge**

Append to `webapp/frontend/src/stores/draftStorage.ts`:

```ts
/* ---- storage edge (design §6.2) -------------------------------------------------------
 * Untested by design: neither Storage API exists in the node vitest environment
 * (webapp/frontend/CLAUDE.md). Everything decidable lives in parseDraft above.
 */

const session = (): Storage | null => {
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

const local = (): Storage | null => {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

const readKey = (s: Storage | null): string | null => {
  if (s === null) return null
  try {
    return s.getItem(DRAFT_STORAGE_KEY)
  } catch {
    return null
  }
}

/** Session first (this tab's own work), then the cross-session mirror. */
export function readDraft(): Draft | null {
  return parseDraft(readKey(session())) ?? parseDraft(readKey(local()))
}

export function writeDraft(d: Draft): void {
  const raw = serializeDraft(d)
  try {
    session()?.setItem(DRAFT_STORAGE_KEY, raw)
  } catch {
    // Quota or disabled storage. The app stays fully functional without a draft; a failed
    // write is not an error state worth surfacing mid-keystroke.
  }
  try {
    local()?.setItem(DRAFT_STORAGE_KEY, raw)
  } catch {
    // Mirror is best-effort by definition — the session copy above is authoritative.
  }
}

export function clearDraft(): void {
  try {
    session()?.removeItem(DRAFT_STORAGE_KEY)
  } catch {
    /* nothing to recover: the draft is already unreachable */
  }
  try {
    local()?.removeItem(DRAFT_STORAGE_KEY)
  } catch {
    /* as above */
  }
}
```

- [ ] **Step 2: Verify the existing suite still passes**

Run: `cd webapp/frontend && npm run lint && npm test`
Expected: PASS — no test imports the edge, so the node environment never touches `window`.

- [ ] **Step 3: Commit**

```bash
git add src/stores/draftStorage.ts
git commit -m "feat(studio): guarded session+local draft storage edge (W16 Task 2)"
```

---

### Task 3: Boot reconciliation — pure `decideBoot`

**Files:**
- Create: `webapp/frontend/src/shell/bootstrap.ts`
- Test: `webapp/frontend/src/shell/bootstrap.test.ts`

**Interfaces:**
- Consumes: `Draft` from `../stores/draftStorage`; `Tab` from `./tabs`.
- Produces: `interface UrlState`, `EMPTY_URL_STATE`, `type BootAction`, `decideBoot(url: UrlState, draft: Draft | null): BootAction`.

`UrlState` is declared **here**, not in `urlState.ts`, so Phase A can compile and test the full matrix before any URL parsing exists (spec §9).

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/shell/bootstrap.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/shell/bootstrap.test.ts`
Expected: FAIL — `Failed to resolve import "./bootstrap"`.

- [ ] **Step 3: Write minimal implementation**

Create `webapp/frontend/src/shell/bootstrap.ts`:

```ts
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/shell/bootstrap.test.ts`
Expected: PASS, 10 tests.

- [ ] **Step 5: Commit**

```bash
cd webapp/frontend && npm run lint && npm test
git add src/shell/bootstrap.ts src/shell/bootstrap.test.ts
git commit -m "feat(studio): pure boot reconciliation matrix (W16 Task 3)"
```

---

### Task 4: `loadDoc` accepts view state

**Files:**
- Modify: `webapp/frontend/src/stores/docStore.ts` (the `loadDoc` function at the file tail)
- Test: `webapp/frontend/src/stores/docStore.test.ts`

**Interfaces:**
- Consumes: `DraftView` from `./draftStorage`.
- Produces: `loadDoc(content: DocContent, serverId: string | null, view?: DraftView): void` — behaviour with `view` omitted is byte-identical to today, keeping the existing 517-line test contract intact.

- [ ] **Step 1: Write the failing test**

Append to `webapp/frontend/src/stores/docStore.test.ts` (match the file's existing import style; it already imports from `./docStore`):

```ts
describe('loadDoc view rehydration', () => {
  it('leaves view state cleared when no view is supplied', () => {
    loadDoc({ ...emptyDocContent(), name: 'a' }, 'srv1')
    const s = useDocStore.getState()
    expect(s.scope).toBeNull()
    expect(s.selectedUid).toBeNull()
    expect(s.collapsed).toEqual({})
  })

  it('rehydrates scope, selection and the collapsed map from a draft view', () => {
    loadDoc({ ...emptyDocContent(), name: 'a', groups: { dose: { params: [], body: [] } } }, 'srv1', {
      scope: 'dose',
      selectedUid: 'u7',
      collapsed: { u7: true },
    })
    const s = useDocStore.getState()
    expect(s.scope).toBe('dose')
    expect(s.selectedUid).toBe('u7')
    expect(s.collapsed).toEqual({ u7: true })
  })

  // Rehydrating view state must not reintroduce the cross-document contamination that the
  // explicit undefined-writes in loadDoc exist to prevent (2026-07-14 review, I1).
  it('clears a previous document view state when the next load supplies none', () => {
    loadDoc({ ...emptyDocContent(), name: 'a' }, 'srv1', {
      scope: null,
      selectedUid: 'u7',
      collapsed: { u7: true },
    })
    loadDoc({ ...emptyDocContent(), name: 'b' }, 'srv2')
    const s = useDocStore.getState()
    expect(s.selectedUid).toBeNull()
    expect(s.collapsed).toEqual({})
  })

  it('still clears undo history when a view is supplied', () => {
    loadDoc({ ...emptyDocContent(), name: 'a' }, 'srv1', {
      scope: null,
      selectedUid: null,
      collapsed: {},
    })
    expect(useDocStore.temporal.getState().pastStates).toHaveLength(0)
  })
})
```

If the test file has no `emptyDocContent` helper, add this above the new `describe`:

```ts
const emptyDocContent = () => ({
  name: '',
  description: null,
  roles: {},
  streams: {},
  tree: [],
  groups: {},
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/stores/docStore.test.ts -t "loadDoc view rehydration"`
Expected: FAIL — `loadDoc` ignores the third argument, so `scope` is `null` where `'dose'` is expected.

- [ ] **Step 3: Write minimal implementation**

In `webapp/frontend/src/stores/docStore.ts`, add the import near the other local imports:

```ts
import type { DraftView } from './draftStorage'
```

Then change the `loadDoc` signature and the four view fields it sets:

```ts
export function loadDoc(content: DocContent, serverId: string | null, view?: DraftView): void {
```

and replace these four lines inside the `setState` call:

```ts
    selectedUid: null,
    scope: null,
    focusedRole: null,
    scrollToUid: null,
    collapsed: {},
```

with:

```ts
    // View state is restored only when a caller supplies it (a draft restore, design §6.1).
    // Omitting `view` must clear it exactly as before, for the same reason the explicit
    // undefined-writes above exist: document B must never inherit document A's view.
    // focusedRole and scrollToUid are transient scroll/highlight requests, not persisted
    // state — they always clear.
    selectedUid: view?.selectedUid ?? null,
    scope: view?.scope ?? null,
    focusedRole: null,
    scrollToUid: null,
    collapsed: view?.collapsed ?? {},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run src/stores/docStore.test.ts`
Expected: PASS — all pre-existing cases plus the four new ones.

- [ ] **Step 5: Commit**

```bash
cd webapp/frontend && npm run lint && npm test
git add src/stores/docStore.ts src/stores/docStore.test.ts
git commit -m "feat(studio): loadDoc rehydrates view state from a draft (W16 Task 4)"
```

---

### Task 5: Debounced autosave hook

**Files:**
- Create: `webapp/frontend/src/shell/useDraftAutosave.ts`

**Interfaces:**
- Consumes: `writeDraft` from `../stores/draftStorage`; `useDocStore`, `selectContent` from `../stores/docStore`.
- Produces: `useDraftAutosave(): void`.

No tests — glue with no decisions, and it touches storage. Verified by hand in Task 8.

- [ ] **Step 1: Confirm `selectContent` is exported**

Run: `cd webapp/frontend && grep -n "export const selectContent" src/stores/docStore.ts`
Expected: one match. If it is not exported, add `export` to its declaration and include that file in Step 3's commit.

- [ ] **Step 2: Write the hook**

Create `webapp/frontend/src/shell/useDraftAutosave.ts`:

```ts
/** Mirrors the open document into browser storage ~500ms after it stops changing (design §6.3).
 *
 * Subscribes to the store rather than reading it in an effect body: zustand's subscribe fires
 * on every mutation regardless of which component rendered, which is exactly the coverage this
 * needs — an edit made from the Inspector, the canvas, or an undo must all land in the draft.
 */
import { useEffect } from 'react'
import { useDocStore, selectContent } from '../stores/docStore'
import { writeDraft } from '../stores/draftStorage'

const DEBOUNCE_MS = 500

export function useDraftAutosave(enabled: boolean): void {
  useEffect(() => {
    // Held off until the boot executor has finished, so an in-flight server load cannot be
    // raced by an autosave of the empty document that precedes it.
    if (!enabled) return
    let timer: ReturnType<typeof setTimeout> | null = null
    const unsubscribe = useDocStore.subscribe((s) => {
      if (timer !== null) clearTimeout(timer)
      timer = setTimeout(() => {
        writeDraft({
          v: 1,
          serverId: s.serverId,
          savedSnapshot: s.savedSnapshot,
          content: selectContent(s),
          view: { scope: s.scope, selectedUid: s.selectedUid, collapsed: s.collapsed },
          updatedAt: Date.now(),
        })
      }, DEBOUNCE_MS)
    })
    return () => {
      if (timer !== null) clearTimeout(timer)
      unsubscribe()
    }
  }, [enabled])
}
```

- [ ] **Step 3: Verify it compiles and the suite is green**

Run: `cd webapp/frontend && npm run lint && npm test && npx tsc --noEmit`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/shell/useDraftAutosave.ts
git commit -m "feat(studio): debounced draft autosave hook (W16 Task 5)"
```

---

### Task 6: Clear the draft at the erase sites

**Files:**
- Modify: `webapp/frontend/src/builder/Toolbar.tsx`

**Interfaces:**
- Consumes: `clearDraft` from `../stores/draftStorage`.

The three `window.confirm('Discard unsaved changes?')` guards (lines ~117, ~127, ~145) plus Duplicate are the actions that legitimately erase the draft (spec §6.3). The guards themselves are unchanged — only a `clearDraft()` call is added after each confirmation passes and the store has been reset.

- [ ] **Step 1: Add the import**

In `webapp/frontend/src/builder/Toolbar.tsx`, alongside the other store imports:

```ts
import { clearDraft } from '../stores/draftStorage'
```

- [ ] **Step 2: Call `clearDraft()` after each erasing action**

For **New** (the handler calling `newDoc()`), add immediately after `newDoc()`:

```ts
    newDoc()
    // The draft described the document just discarded. Autosave will write a fresh one for
    // the new document on its next tick; leaving the old one would resurrect it on refresh.
    clearDraft()
```

For **Load** and **Import** (the handlers calling `loadDoc(docToTree(res.doc), res.id)`), add `clearDraft()` immediately after each `loadDoc(...)` call, with no comment (the reason is stated once above):

```ts
      loadDoc(docToTree(res.doc), res.id)
      clearDraft()
```

For **Duplicate**, add `clearDraft()` after whichever of `loadDoc`/`markSaved` the handler ends with.

- [ ] **Step 3: Verify**

Run: `cd webapp/frontend && npm run lint && npm test && npx tsc --noEmit`
Expected: all pass.

Then confirm every site is covered:

Run: `grep -c "clearDraft()" src/builder/Toolbar.tsx`
Expected: `4`

- [ ] **Step 4: Commit**

```bash
git add src/builder/Toolbar.tsx
git commit -m "feat(studio): clear the draft on new/load/import/duplicate (W16 Task 6)"
```

---

### Task 7: Restore notice

**Files:**
- Create: `webapp/frontend/src/shell/RestoreNotice.tsx`

**Interfaces:**
- Consumes: `IconButton` from `../ui/IconButton`.
- Produces: `<RestoreNotice at={number} onDismiss={() => void} />`.

Restore is silent and automatic (spec §2.1), so this bar is how the user learns it happened. It is a dismissible inline row, not a modal and not a self-hiding toast.

- [ ] **Step 1: Check the IconButton signature before writing against it**

Run: `cd webapp/frontend && sed -n '1,40p' src/ui/IconButton.tsx`
Expected: the prop names for icon, label, and click handler. Use exactly those in Step 2 — the sketch below assumes `icon`, `label`, and `onClick`; correct it to match.

- [ ] **Step 2: Write the component**

Create `webapp/frontend/src/shell/RestoreNotice.tsx`:

```tsx
/** Announces that unsaved work was restored from browser storage (design §6.3).
 *
 * Inline and dismissible rather than a modal: restore is automatic precisely so that refresh
 * is non-destructive (design §2.1), and a boot-time modal would put the interruption back.
 * Not a self-hiding toast either — it reports that state on screen is not what the server has,
 * which the user should be able to read at their own pace.
 */
import { X } from 'lucide-react'
import { IconButton } from '../ui/IconButton'

const time = (at: number): string =>
  new Date(at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

export function RestoreNotice({
  at,
  onDismiss,
}: {
  at: number
  onDismiss: () => void
}): React.ReactElement {
  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-3 py-1 text-xs text-caption"
    >
      <span>Restored unsaved changes from {time(at)}.</span>
      <span className="ml-auto">
        <IconButton icon={X} label="Dismiss restore notice" onClick={onDismiss} />
      </span>
    </div>
  )
}
```

Note the colour choice: amber is a **state** hue, which is the sanctioned use (`CLAUDE.md` — hue is reserved for state; this is a transient advisory, not construct identity). Text uses `text-caption`, not `text-hint`, because it carries meaning.

- [ ] **Step 3: Verify**

Run: `cd webapp/frontend && npm run lint && npm test && npx tsc --noEmit`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/shell/RestoreNotice.tsx
git commit -m "feat(studio): restore notice bar (W16 Task 7)"
```

---

### Task 8: Wire the boot executor into App

**Files:**
- Modify: `webapp/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `decideBoot`, `EMPTY_URL_STATE` (Task 3); `readDraft` (Task 2); `loadDoc`, `newDoc` (Task 4); `useDraftAutosave` (Task 5); `RestoreNotice` (Task 7); `getExperiment` from `api/studio`.

This is the executor described in spec §5 — the dumb half of the decision. Phase A passes `EMPTY_URL_STATE`, so only rows 4 and 5 fire; Task 12 replaces that with the parsed hash.

- [ ] **Step 1: Read App.tsx to find the mount point**

Run: `cd webapp/frontend && cat src/App.tsx`
Note where `TabShell` renders and what the file already imports.

- [ ] **Step 2: Add the boot effect**

In `webapp/frontend/src/App.tsx`, add inside the `App` component, before the returned JSX:

```tsx
  const [booted, setBooted] = useState(false)
  const [restoredAt, setRestoredAt] = useState<number | null>(null)

  useEffect(() => {
    // Runs exactly once. decideBoot (shell/bootstrap.ts) holds every decision; this executor
    // only performs them, plus the one outcome decideBoot cannot know in advance — a server
    // id that no longer resolves.
    const action = decideBoot(EMPTY_URL_STATE, readDraft())
    if (action.kind === 'restoreDraft') {
      loadDoc(action.draft.content, action.draft.serverId, action.draft.view)
      useDocStore.setState({ savedSnapshot: action.draft.savedSnapshot })
      setRestoredAt(action.draft.updatedAt)
      setBooted(true)
      return
    }
    if (action.kind === 'newDoc') {
      newDoc()
      setBooted(true)
      return
    }
    let cancelled = false
    getExperiment(action.id)
      .then((res) => {
        if (cancelled) return
        loadDoc(docToTree(res.doc), res.id)
      })
      .catch(() => {
        // A deleted or malformed experiment falls back to an empty document. It deliberately
        // does NOT fall back to an unrelated draft: the URL asked for a specific document,
        // and silently opening a different one is worse than opening none (design §5).
        if (!cancelled) newDoc()
      })
      .finally(() => {
        if (!cancelled) setBooted(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useDraftAutosave(booted)
```

Add the corresponding imports at the top of the file:

```tsx
import { useEffect, useState } from 'react'
import { decideBoot, EMPTY_URL_STATE } from './shell/bootstrap'
import { readDraft } from './stores/draftStorage'
import { useDocStore, loadDoc, newDoc } from './stores/docStore'
import { docToTree } from './builder/convert'
import { getExperiment } from './api/studio'
import { useDraftAutosave } from './shell/useDraftAutosave'
import { RestoreNotice } from './shell/RestoreNotice'
```

Merge with whatever `App.tsx` already imports rather than duplicating lines. Check the exported name of the single-experiment fetch first:

Run: `grep -n "^export" src/api/studio.ts`

and use the actual name in place of `getExperiment` if it differs.

`loadDoc` sets `savedSnapshot` from the restored content, which would mark a dirty draft clean — hence the explicit `setState` restoring the draft's own snapshot immediately after.

- [ ] **Step 3: Render the notice**

Above the tab shell in the returned JSX:

```tsx
      {restoredAt !== null && (
        <RestoreNotice at={restoredAt} onDismiss={() => setRestoredAt(null)} />
      )}
```

- [ ] **Step 4: Verify**

Run: `cd webapp/frontend && npm run lint && npm test && npx tsc --noEmit && npm run build`
Expected: all pass.

- [ ] **Step 5: Verify by hand in the browser**

Run: `cd webapp/frontend && npm run dev`

Then, in the browser:
1. Add two blocks to a new experiment. Wait ~1s. Refresh.
   Expected: both blocks are still there, the unsaved dot is still shown, and the amber restore notice reads "Restored unsaved changes from HH:MM".
2. Collapse a block and select another. Refresh.
   Expected: the collapse and the selection survive.
3. Save the experiment, edit it, refresh.
   Expected: the edit survives and the document is still associated with its server id (Save updates rather than creating a second copy).
4. Click New and confirm the discard. Refresh.
   Expected: an empty document, no notice.
5. Open a second browser tab alongside the first and edit each differently. Refresh both.
   Expected: each tab keeps its own work (sessionStorage is per-tab).

- [ ] **Step 6: Probe the notice**

With the dev server still running, in a second terminal:

Run: `cd webapp/frontend && npm run capture`
Expected: no new R5 (`text-contrast`) or R4 (`sibling-height-mismatch`) findings. Fix any that name `RestoreNotice` before committing.

- [ ] **Step 7: Commit**

```bash
git add src/App.tsx
git commit -m "feat(studio): restore the in-progress document at boot (W16 Task 8)"
```

**Phase A is now independently shippable:** refresh no longer destroys work.

---

# PHASE B — URL STATE

### Task 9: `pathForUid` — the structural-path inverse

**Files:**
- Modify: `webapp/frontend/src/builder/paths.ts`
- Test: `webapp/frontend/src/builder/paths.test.ts`

**Interfaces:**
- Consumes: `childSlots`, `BlockNode` from `./tree`; `GroupsMap`, `resolveDiagnosticPath` (already in `paths.ts`).
- Produces: `pathForUid(tree: BlockNode[], groups: GroupsMap, uid: string): string | null`.

The inverse of `resolveDiagnosticPath` (`paths.ts:102`), emitting only the two forms the builder can originate — never the compound `blocks[i]->name.body[i]` form, which describes a group *rendered at a call site* rather than an authored location (spec §4.1).

- [ ] **Step 1: Write the failing test**

Append to `webapp/frontend/src/builder/paths.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { docToTree } from '../convert'
import { visitNodes } from '../tree'
import { pathForUid } from '../paths'
import type { ExperimentDocJson } from '../../types/doc'

// Adjust the two relative paths above if paths.test.ts sits at a different depth than
// __tests__/torture.test.ts, which resolves the fixture as '../../../../fixtures/...'.
const FIXTURE = fileURLToPath(new URL('../../../fixtures/ui-audit-torture.json', import.meta.url))

describe('pathForUid', () => {
  it('emits blocks[i] for a top-level node', () => {
    const tree = docToTree({
      doc_version: 1,
      name: 't',
      description: null,
      roles: {},
      workflow: {
        schema_version: 1,
        blocks: [{ wait: { seconds: 1 } }],
      },
    } as unknown as ExperimentDocJson).tree
    expect(pathForUid(tree, {}, tree[0].uid)).toBe('blocks[0]')
  })

  it('returns null for a uid that is not in the tree', () => {
    expect(pathForUid([], {}, 'nope')).toBeNull()
  })

  // The property that matters: whatever pathForUid writes, resolveDiagnosticPath must read
  // back to the same node. The torture fixture is type-forced to contain every BlockKind
  // (__tests__/torture.test.ts), so this covers every container shape childSlots knows.
  it('round-trips every node in the torture fixture', () => {
    const doc = JSON.parse(readFileSync(FIXTURE, 'utf8')) as ExperimentDocJson
    const { tree, groups } = docToTree(doc)
    const uids: string[] = []
    visitNodes(tree, (n) => uids.push(n.uid))
    for (const body of Object.values(groups)) visitNodes(body.body, (n) => uids.push(n.uid))
    expect(uids.length).toBeGreaterThan(10)
    for (const uid of uids) {
      const path = pathForUid(tree, groups, uid)
      expect(path, `no path for ${uid}`).not.toBeNull()
      expect(resolveDiagnosticPath(tree, groups, path!).uid, `round-trip failed for ${path}`).toBe(
        uid,
      )
    }
  })

  // Non-identifier group names are reachable via Import: GROUP_NAME_RE (docStore.ts:40) is
  // enforced only on add/rename, and convert.ts loads keys verbatim (paths.ts:19-31).
  it.each(["a b", "a'b", 'a->b'])('round-trips inside a group named %j', (name) => {
    const groups = {
      [name]: { params: [], body: docToTree({
        doc_version: 1,
        name: 't',
        description: null,
        roles: {},
        workflow: { schema_version: 1, blocks: [{ wait: { seconds: 1 } }] },
      } as unknown as ExperimentDocJson).tree },
    }
    const uid = groups[name].body[0].uid
    const path = pathForUid([], groups, uid)
    expect(path).not.toBeNull()
    expect(resolveDiagnosticPath([], groups, path!).uid).toBe(uid)
  })
})
```

Ensure `describe`, `it`, `expect` and `resolveDiagnosticPath` are imported at the top of the file — they will already be there if the file has existing tests; add only what is missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/builder/paths.test.ts -t pathForUid`
Expected: FAIL — `pathForUid is not a function`.

If it instead fails on `ENOENT` for the fixture, correct `FIXTURE`'s relative depth and re-run.

- [ ] **Step 3: Write minimal implementation**

Append to `webapp/frontend/src/builder/paths.ts`:

```ts
/** The inverse of resolveDiagnosticPath: the structural path addressing a node (design §4.1).
 *
 * Emits only the two forms the BUILDER can originate — `blocks[i]` + trailer, and
 * `groups['name'].body[i]` + trailer. It never emits the compound `blocks[i]->name.body[i]`
 * form: that is produced by a validator walk crossing from a call site into a plain group's
 * body (validate.py:894,940) and describes a group RENDERED at a call site, not an authored
 * location. Selection always refers to an authored node, so the compound form has no writer.
 *
 * Single-quoted group names match Python's repr() as docs_store.py produces it. A name
 * containing an apostrophe would need repr()'s double-quote flip to survive a round trip
 * through the backend, but this path is only ever read back by resolveDiagnosticPath in this
 * file, which is quote-tolerant either way — so single quotes are always emitted and the
 * grammar stays one-to-one.
 *
 * Descends via childSlots (tree.ts:157) rather than a local slot list, for the same reason
 * the torture walker does: a hand-listed set silently stops descending the day a new
 * container kind lands.
 */
function findPath(list: BlockNode[], uid: string, prefix: string): string | null {
  for (let i = 0; i < list.length; i++) {
    const node = list[i]
    const here = `${prefix}[${i}]`
    if (node.uid === uid) return here
    for (const [slot, children] of childSlots(node)) {
      const found = findPath(children, uid, `${here}.${slot}`)
      if (found !== null) return found
    }
  }
  return null
}

export function pathForUid(tree: BlockNode[], groups: GroupsMap, uid: string): string | null {
  const inMain = findPath(tree, uid, 'blocks')
  if (inMain !== null) return inMain
  for (const [name, group] of Object.entries(groups)) {
    const inGroup = findPath(group.body, uid, `groups['${name}'].body`)
    if (inGroup !== null) return inGroup
  }
  return null
}
```

Add `childSlots` to the existing `./tree` import if it is not already there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp/frontend && npx vitest run src/builder/paths.test.ts`
Expected: PASS — existing cases plus the new ones.

- [ ] **Step 5: Commit**

```bash
cd webapp/frontend && npm run lint && npm test
git add src/builder/paths.ts src/builder/paths.test.ts
git commit -m "feat(studio): pathForUid, the structural-path inverse (W16 Task 9)"
```

---

### Task 10: Hash parse and format

**Files:**
- Create: `webapp/frontend/src/shell/urlState.ts`
- Test: `webapp/frontend/src/shell/urlState.test.ts`

**Interfaces:**
- Consumes: `UrlState`, `EMPTY_URL_STATE` from `./bootstrap`; `TABS`, `Tab` from `./tabs`.
- Produces: `parseHash(hash: string): UrlState`, `formatHash(s: UrlState): string`.

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/shell/urlState.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { formatHash, parseHash } from './urlState'
import { EMPTY_URL_STATE, type UrlState } from './bootstrap'

const st = (over: Partial<UrlState> = {}): UrlState => ({ ...EMPTY_URL_STATE, ...over })

describe('parseHash', () => {
  it.each([
    ['', st()],
    ['#', st()],
    ['#/', st()],
    ['#/builder', st()],
    ['#/run', st({ tab: 'Run' })],
    ['#/devices', st({ tab: 'Devices' })],
    ['#/records', st({ tab: 'Records' })],
    ['#/records/rec_99', st({ tab: 'Records', rec: 'rec_99' })],
    ['#/builder?exp=a1b2', st({ exp: 'a1b2' })],
    ['#/builder?exp=a1b2&scope=dose', st({ exp: 'a1b2', scope: 'dose' })],
    [
      '#/builder?exp=a1b2&sel=blocks%5B0%5D.children%5B2%5D',
      st({ exp: 'a1b2', sel: 'blocks[0].children[2]' }),
    ],
  ])('parses %j', (hash, expected) => {
    expect(parseHash(hash)).toEqual(expected)
  })

  // Totality: a hand-edited or truncated URL must land on a usable screen, never throw.
  it.each(['#/nope', '#/BUILDER/x/y/z', '#?????', '#/builder?exp', '#/builder?=&&='])(
    'degrades %j to a usable state without throwing',
    (hash) => {
      expect(() => parseHash(hash)).not.toThrow()
      expect(TABS_SET.has(parseHash(hash).tab)).toBe(true)
    },
  )
})

const TABS_SET = new Set(['Builder', 'Devices', 'Run', 'Records'])

describe('formatHash', () => {
  it('omits every absent field', () => {
    expect(formatHash(st())).toBe('#/builder')
  })

  it('puts a record id in the path, not the query', () => {
    expect(formatHash(st({ tab: 'Records', rec: 'rec_99' }))).toBe('#/records/rec_99')
  })

  it('round-trips through parseHash', () => {
    const cases: UrlState[] = [
      st(),
      st({ tab: 'Run' }),
      st({ tab: 'Records', rec: 'rec_99' }),
      st({ exp: 'a1b2' }),
      st({ exp: 'a1b2', scope: 'dose', sel: "groups['dose'].body[1]" }),
    ]
    for (const c of cases) expect(parseHash(formatHash(c))).toEqual(c)
  })

  // Group names may legally contain a space, an apostrophe, or '->' (paths.ts:19-31), which
  // is why URLSearchParams does the encoding and no string is concatenated by hand.
  it.each(['a b', "a'b", 'a->b', 'a&b=c', 'a#b'])(
    'round-trips a group named %j in scope and sel',
    (name) => {
      const s = st({ exp: 'x', scope: name, sel: `groups['${name}'].body[0]` })
      expect(parseHash(formatHash(s))).toEqual(s)
    },
  )
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp/frontend && npx vitest run src/shell/urlState.test.ts`
Expected: FAIL — `Failed to resolve import "./urlState"`.

- [ ] **Step 3: Write minimal implementation**

Create `webapp/frontend/src/shell/urlState.ts`:

```ts
/** The hash grammar (design §4).
 *
 *   #/builder?exp=a1b2&scope=dose&sel=groups['dose'].body[1]
 *   #/records/rec_99
 *   #/run
 *
 * A hash rather than real paths because vite.config.ts pins `base: './'` so the bundle stays
 * deployable behind the lab-bridge prefix-stripping proxy at /studio/. Under a relative base,
 * a path segment makes the browser request assets from that segment, which 404s into the SPA
 * catch-all and fails on MIME type (design §1.1, C-1).
 *
 * Every query value goes through URLSearchParams. Group names may legally contain a space, an
 * apostrophe, '&', '#', or '->' — non-identifier names are reachable via Import, since
 * GROUP_NAME_RE (docStore.ts:40) is enforced only on add/rename and convert.ts loads keys
 * verbatim (paths.ts:19-31). A hand-rolled encoder would silently turn one group name into a
 * different, valid-looking one.
 *
 * Parsing is total. A hand-edited or truncated URL lands on a usable screen.
 */
import { TABS, type Tab } from './tabs'
import { EMPTY_URL_STATE, type UrlState } from './bootstrap'

const SLUG_TO_TAB = new Map<string, Tab>(TABS.map((t) => [t.toLowerCase(), t]))

export function parseHash(hash: string): UrlState {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash
  const [pathPart = '', queryPart = ''] = raw.split('?', 2)
  const segments = pathPart.split('/').filter((s) => s !== '')
  const tab = SLUG_TO_TAB.get((segments[0] ?? '').toLowerCase()) ?? EMPTY_URL_STATE.tab

  let params: URLSearchParams
  try {
    params = new URLSearchParams(queryPart)
  } catch {
    params = new URLSearchParams()
  }
  const get = (key: string): string | null => {
    const value = params.get(key)
    return value === null || value === '' ? null : value
  }

  return {
    tab,
    exp: get('exp'),
    // A record id is the thing being viewed rather than a qualifier on a view, so it is a
    // path segment. Only meaningful under /records.
    rec: tab === 'Records' ? (segments[1] ?? null) : null,
    scope: get('scope'),
    sel: get('sel'),
  }
}

export function formatHash(s: UrlState): string {
  const path = s.tab === 'Records' && s.rec !== null
    ? `/records/${encodeURIComponent(s.rec)}`
    : `/${s.tab.toLowerCase()}`

  const params = new URLSearchParams()
  if (s.exp !== null) params.set('exp', s.exp)
  if (s.scope !== null) params.set('scope', s.scope)
  if (s.sel !== null) params.set('sel', s.sel)
  const query = params.toString()
  return query === '' ? `#${path}` : `#${path}?${query}`
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd webapp/frontend && npx vitest run src/shell/urlState.test.ts`
Expected: PASS.

If the `'a#b'` group-name case fails, the cause is `parseHash` receiving a truncated string from a real `location.hash`; the fix belongs in `useUrlSync` (Task 11), which must read `location.hash` once and pass it whole. Keep the test.

- [ ] **Step 5: Commit**

```bash
cd webapp/frontend && npm run lint && npm test
git add src/shell/urlState.ts src/shell/urlState.test.ts
git commit -m "feat(studio): hash parse and format (W16 Task 10)"
```

---

### Task 11: URL sync hook

**Files:**
- Create: `webapp/frontend/src/shell/useUrlSync.ts`
- Modify: `webapp/frontend/src/stores/navStore.ts`

**Interfaces:**
- Consumes: `parseHash`, `formatHash` (Task 10); `pathForUid` (Task 9); `resolveDiagnosticPath` (`paths.ts`); `useDocStore`, `useNavStore`, `useRecordsStore`.
- Produces: `useUrlSync(enabled: boolean): void`.

Glue, untested — it owns the feedback-loop guard, which is the only stateful piece in the increment.

- [ ] **Step 1: Seed navStore from the URL**

Replace the body of `webapp/frontend/src/stores/navStore.ts`:

```ts
/** App-global tab selection so any feature (e.g. the run terminal panel) can jump tabs.
 *
 * The initial tab comes from the URL hash (design §4) rather than a hardcoded 'Builder', so a
 * refresh or a shared link lands on the tab it names. Parsing is total, so a malformed hash
 * still yields 'Builder'.
 */
import { create } from 'zustand'
import type { Tab } from '../shell/tabs'
import { parseHash } from '../shell/urlState'

const initialTab = (): Tab => {
  try {
    return parseHash(window.location.hash).tab
  } catch {
    // No window (SSR, or a node-env test importing this module transitively).
    return 'Builder'
  }
}

interface NavState {
  tab: Tab
  setTab: (tab: Tab) => void
}

export const useNavStore = create<NavState>()((set) => ({
  tab: initialTab(),
  setTab: (tab) => set({ tab }),
}))
```

- [ ] **Step 2: Write the sync hook**

Create `webapp/frontend/src/shell/useUrlSync.ts`:

```ts
/** Two-way binding between the hash and the stores (design §3.1, §4).
 *
 * The store->hash writer and the popstate reader form a loop: applying a URL to the stores
 * fires the subscriptions that write the URL. `applying` breaks it — while a URL-originated
 * update is landing, the writer is suppressed. This is the only genuinely stateful glue in
 * W16, and the reason this is a hook rather than a module-level subscription.
 *
 * History granularity (fork 8): pushState for tab/exp/rec/scope, which are navigation;
 * replaceState for selection, which is not — pushing it would make Back an erratic second
 * undo stack alongside the real one.
 */
import { useEffect, useRef } from 'react'
import { useDocStore } from '../stores/docStore'
import { useNavStore } from '../stores/navStore'
import { useRecordsStore } from '../stores/recordsStore'
import { pathForUid, resolveDiagnosticPath } from '../builder/paths'
import { formatHash, parseHash } from './urlState'
import type { UrlState } from './bootstrap'

function currentUrlState(): UrlState {
  const doc = useDocStore.getState()
  return {
    tab: useNavStore.getState().tab,
    exp: doc.serverId,
    rec: useRecordsStore.getState().openId,
    scope: doc.scope,
    sel:
      doc.selectedUid === null
        ? null
        : pathForUid(doc.tree, doc.groups, doc.selectedUid),
  }
}

/** Fields whose change is navigation, and so earns a history entry. */
const isNavigation = (a: UrlState, b: UrlState): boolean =>
  a.tab !== b.tab || a.exp !== b.exp || a.rec !== b.rec || a.scope !== b.scope

export function useUrlSync(enabled: boolean): void {
  const applying = useRef(false)

  useEffect(() => {
    if (!enabled) return

    const apply = (url: UrlState): void => {
      applying.current = true
      try {
        useNavStore.getState().setTab(url.tab)
        useRecordsStore.getState().open(url.rec)
        const doc = useDocStore.getState()
        if (url.scope !== doc.scope) doc.setScope(url.scope)
        // Resolved against the tree that is loaded NOW: an unresolvable path (the document
        // changed server-side, or the link is stale) clears the selection rather than
        // guessing, and the writer below then drops the dead param.
        const uid =
          url.sel === null
            ? null
            : resolveDiagnosticPath(doc.tree, doc.groups, url.sel).uid
        useDocStore.getState().select(uid)
      } finally {
        applying.current = false
      }
    }

    const onPopState = (): void => apply(parseHash(window.location.hash))
    window.addEventListener('popstate', onPopState)
    // Also covers a manual hash edit, which fires hashchange but not popstate in every browser.
    window.addEventListener('hashchange', onPopState)

    let last = currentUrlState()
    const write = (): void => {
      if (applying.current) return
      const next = currentUrlState()
      const hash = formatHash(next)
      if (hash === window.location.hash) return
      const url = `${window.location.pathname}${window.location.search}${hash}`
      if (isNavigation(last, next)) window.history.pushState(null, '', url)
      else window.history.replaceState(null, '', url)
      last = next
    }

    // The initial URL is normalized without a history entry, so Back still leaves the app
    // rather than stepping through the boot state.
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${formatHash(last)}`)

    const unsubDoc = useDocStore.subscribe(write)
    const unsubNav = useNavStore.subscribe(write)
    const unsubRec = useRecordsStore.subscribe(write)

    return () => {
      window.removeEventListener('popstate', onPopState)
      window.removeEventListener('hashchange', onPopState)
      unsubDoc()
      unsubNav()
      unsubRec()
    }
  }, [enabled])
}
```

- [ ] **Step 3: Verify**

Run: `cd webapp/frontend && npm run lint && npm test && npx tsc --noEmit`
Expected: all pass. `navStore.test.ts` must still pass — if it fails because `window` is undefined in node, the `try/catch` in Step 1 is not covering the access; change `initialTab` to check `typeof window === 'undefined'` first.

- [ ] **Step 4: Commit**

```bash
git add src/shell/useUrlSync.ts src/stores/navStore.ts
git commit -m "feat(studio): two-way hash <-> store sync (W16 Task 11)"
```

---

### Task 12: Feed the real URL into boot, and mount the sync

**Files:**
- Modify: `webapp/frontend/src/App.tsx`

**Interfaces:**
- Consumes: `parseHash` (Task 10), `useUrlSync` (Task 11).

- [ ] **Step 1: Replace the empty URL state in the boot effect**

In `webapp/frontend/src/App.tsx`, change:

```tsx
    const action = decideBoot(EMPTY_URL_STATE, readDraft())
```

to:

```tsx
    const url = parseHash(window.location.hash)
    const action = decideBoot(url, readDraft())
```

Rows 1–3 of the matrix are now reachable. Drop the `EMPTY_URL_STATE` import if nothing else uses it, and add:

```tsx
import { parseHash } from './shell/urlState'
import { useUrlSync } from './shell/useUrlSync'
```

- [ ] **Step 2: Apply the URL's view focus after the document lands**

The selection and scope in the URL can only be resolved once a tree exists, so they are applied at the end of each boot branch, not up front. After the `restoreDraft` branch's `setBooted(true)` and inside the `getExperiment(...).then(...)` after `loadDoc(...)`, add:

```tsx
      if (url.scope !== null) useDocStore.getState().setScope(url.scope)
      if (url.sel !== null) {
        const doc = useDocStore.getState()
        // Unresolvable (stale link, or the document changed server-side) leaves the selection
        // null; useUrlSync's next write then drops the dead param from the URL.
        doc.select(resolveDiagnosticPath(doc.tree, doc.groups, url.sel).uid)
      }
```

Import `resolveDiagnosticPath` from `./builder/paths`.

Note ordering: `setScope` clears `selectedUid` (`docStore.ts:343`), so scope must be applied **before** selection or the selection is discarded.

- [ ] **Step 3: Mount the sync hook**

Beside the existing `useDraftAutosave(booted)` call:

```tsx
  useUrlSync(booted)
```

Both are gated on `booted` so neither can race the boot executor.

- [ ] **Step 4: Verify**

Run: `cd webapp/frontend && npm run lint && npm test && npx tsc --noEmit && npm run build`
Expected: all pass.

- [ ] **Step 5: Verify by hand in the browser**

Run: `cd webapp/frontend && npm run dev`

1. Switch to Run, then Records. Refresh.
   Expected: lands on Records; the URL reads `#/records`.
2. Open a record. Expected: `#/records/rec_…`. Press Back. Expected: returns to `#/records`.
3. In the Builder, save an experiment. Expected: `#/builder?exp=…`.
4. Select a block. Expected: `sel=blocks[…]` appears **without** adding a history entry — one Back press should leave the Builder, not step through selections.
5. Enter a group scope. Expected: `scope=` appears and Back exits the scope.
6. Copy the full URL into a new browser tab (a fresh session, no draft).
   Expected: the same experiment opens, in the same scope, with the same block selected.
7. Hand-edit the URL to `?exp=does-not-exist`. Refresh.
   Expected: an empty document, no crash.
8. With unsaved edits to experiment X, hand-edit the URL to a different experiment Y and refresh, then navigate back to X.
   Expected: Y opens clean; returning to X restores the unsaved edits (matrix row 3).

- [ ] **Step 6: Commit**

```bash
git add src/App.tsx
git commit -m "feat(studio): boot from the URL and keep it in sync (W16 Task 12)"
```

---

### Task 13: Documentation and final gate

**Files:**
- Modify: `webapp/README.md`

- [ ] **Step 1: Document the URL grammar**

Add to `webapp/README.md`, in the section describing the four tabs:

```markdown
### URLs and persistence

The Studio's state lives in the hash, so views are bookmarkable and shareable:

| URL | Opens |
|---|---|
| `#/builder?exp=<id>` | an experiment in the Builder |
| `#/builder?exp=<id>&scope=<group>&sel=blocks[0].children[2]` | …in a group scope, with a block selected |
| `#/records/<id>` | a record |
| `#/run`, `#/devices` | those tabs |

A hash rather than real paths: `vite.config.ts` pins `base: './'` so the bundle is deployable
behind the lab-bridge prefix-stripping proxy at `/studio/`, and a relative base cannot support
path segments.

The in-progress document is mirrored to browser storage ~500ms after it stops changing, so a
refresh or a crash does not lose unsaved work. `sessionStorage` is authoritative and per-tab
(two tabs never clobber each other); `localStorage` holds a mirror read only when the session
copy is absent. New / Load / Import / Duplicate clear the draft after their existing
"Discard unsaved changes?" confirmation. There is deliberately no `beforeunload` prompt —
refresh is not destructive, so warning about it would be a lie.
```

- [ ] **Step 2: Run the full gate**

```bash
cd webapp/frontend && npm run lint && npm test && npm run build
```
Expected: all pass.

Then the backend gate, unchanged by this increment but run because CI does:

```bash
cd webapp/backend && .venv/bin/python -m pytest && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
```
Expected: all pass.

- [ ] **Step 3: Probe the running app**

With `npm run dev` running, in a second terminal:

```bash
cd webapp/frontend && npm run capture
```
Expected: no new findings versus `main`. Investigate anything naming `RestoreNotice`.

- [ ] **Step 4: Commit**

```bash
git add webapp/README.md
git commit -m "docs(studio): URL grammar and draft persistence (W16 Task 13)"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| §3 `urlState.ts` | 10 |
| §3 `paths.ts` extension | 9 |
| §3 `draftStorage.ts` | 1 (pure), 2 (edge) |
| §3 `bootstrap.ts` | 3 |
| §3 `useUrlSync.ts` | 11 |
| §3 `useDraftAutosave.ts` | 5 |
| §4 URL grammar, `URLSearchParams` | 10 |
| §4.1 `pathForUid`, no compound form | 9 |
| §5 matrix rows 1–5 | 3 (decided), 8 + 12 (executed) |
| §5 404 fallback | 8 |
| §6.1 draft record | 1 |
| §6.2 session + local layers | 2 |
| §6.3 autosave, `clearDraft`, notice | 5, 6, 7 |
| §7 navStore seeding | 11 |
| §7 `loadDoc` view argument | 4 |
| §7 Toolbar `clearDraft` | 6 |
| §7 App wiring | 8, 12 |
| §8 inverse property test | 9 |
| §8 urlState / bootstrap / draftStorage tests | 10, 3, 1 |
| §8 probe | 8, 13 |
| §9 phase split | Phase A = 1–8, Phase B = 9–13 |

No spec requirement is unassigned. §10 (out of scope) has no tasks by design.

**Type consistency** — `Draft`, `DraftView`, `UrlState`, `BootAction` are each defined once (Tasks 1, 1, 3, 3) and consumed by name thereafter. `decideBoot`'s signature is fixed in Task 3 and unchanged in Task 12 — only its *arguments* change, which is the whole point of declaring `UrlState` in `bootstrap.ts`. `clearDraft` is spelled identically in Tasks 2 and 6. `loadDoc`'s third parameter is `DraftView` in both Task 4 and Task 8.

**Known soft spots, flagged for the implementer rather than guessed at**

1. Task 7 sketches `IconButton`'s props; Step 1 of that task reads the real signature first.
2. Task 9's fixture path depth is asserted by a failing-run check in Step 2 rather than assumed.
3. Task 8 assumes the single-experiment fetch is `getExperiment`; Step 2 greps `api/studio.ts` for the real name.
4. Task 6 assumes four erase sites; Step 3 asserts the count with `grep -c`.
