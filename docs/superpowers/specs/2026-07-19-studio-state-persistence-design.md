# Experiment Studio — draft persistence and URL state (W16)

**Status:** design, user-settled 2026-07-19
**Target:** `experiment-studio` (`main` @ `80ddc14`), W1–W15 shipped
**Predecessors:** `2026-07-18-inspector-form-structure-design.md` (W15),
`2026-07-18-canvas-visual-language-design.md` (the increment also numbered W14)

> **Numbering note.** Two increments shipped as "W14" (#41 lab-independent Builder, #43 canvas
> visual language). W15 was the Inspector form structure (#44). This increment continues from
> W15 rather than re-deriving the count, so the collision stays historical.

---

## 1. Problem

The Studio forgets everything on refresh.

`navStore.ts` hardcodes `tab: 'Builder'`. `docStore.ts` boots empty. There is no `beforeunload`
handler, so closing the tab silently discards unsaved edits — and even a *saved* document is
gone, because `serverId` lives only in memory and has to be re-opened through the Load dialog.
The only two things that survive a refresh today are the selected lab (`studio.selectedLab`)
and role colours (`studio.roleColors.v1`), both via ad-hoc `localStorage` reads.

The URL is entirely inert. The single `window.location` reference in `src/` is
`api/runSocket.ts:32`, resolving a WebSocket base. There is no `pushState`, no `popstate`, no
`URLSearchParams`. Every URL renders the same screen, which means **no view in the Studio can be
bookmarked, shared, or reopened** — a colleague cannot be sent to a specific experiment, let
alone a specific block inside it.

Two consequences the user hits directly:

1. **Refresh is destructive.** Any accidental reload, browser update, or crash loses in-progress
   authoring outright. The existing `window.confirm('Discard unsaved changes?')` guards
   (`Toolbar.tsx:117,127,145`) cover New / Load / Import only — the far more common loss path,
   the reload, is unguarded.
2. **Nothing is addressable.** "Look at the dose loop in the morbidostat experiment" is a
   sentence, not a link.

### 1.1 Two constraints that shape every choice below

**C-1. Real path routing is unavailable.** `vite.config.ts:7` sets `base: './'` with the comment
*"deployable behind a prefix-stripping proxy (lab-bridge /studio route)"*. Relative asset URLs
resolve against the current path, so at `/experiments/abc` the bundle is requested from
`/experiments/assets/index-*.js`, misses, falls through to the SPA catch-all in `app.py:186`,
and fails on MIME type. A path-segment router therefore costs the proxy-portability the
deployment is built on. The hash carries state without touching the asset base or the server.

**C-2. Tests are node-env, pure-functions-only.** From `webapp/frontend/CLAUDE.md`: *"vitest runs
in node env: pure functions only, no component rendering, no jsdom, no @testing-library."*
`localStorage` does not exist in node. So every decision in this increment must live in a pure
function that takes strings and returns values, with `window`/storage contact isolated to a thin
edge that tests do not reach. `builder/roleColorStorage.ts` (pure `parseOverrides` /
`serializeOverrides`, total parsing, unit-tested) paired with `stores/roleColorStore.ts` (the
try/catch edge) is the existing precedent, and this increment follows it exactly.

---

## 2. Settled decisions

Eight forks, settled with the user 2026-07-19.

| # | Fork | Settled |
|---|---|---|
| 1 | URL carrier | **Hash routing** — `#/builder?exp=…`. Not paths (C-1), not bare query params. |
| 2 | URL scope | **Tab + entity + view focus**: tab, experiment id, record id, group scope, selected block. Out: `collapsed{}`, scroll, panel open/closed, filter text. |
| 3 | Draft model | **Single autosaved draft, debounced ~500ms**, carrying `serverId` and `savedSnapshot` so *dirty* survives too. |
| 4 | Warnings | **Warn on erase, not on unload.** Keep the `confirm()` guards; add no `beforeunload`. |
| 5 | Selection encoding | **Structural path** (`blocks[0].children[2]`), not a uid. |
| 6 | Multi-tab | **sessionStorage primary + localStorage mirror.** |
| 7 | Boot conflict | **URL wins identity, draft wins content.** |
| 8 | History | **push** on tab/exp/rec/scope; **replace** on selection. |

Two follow-on calls made during design, not separately asked:

- **One spec, two phases.** Phase A (draft persistence) and Phase B (URL state) share the boot
  reconciliation function; splitting into two specs would duplicate its matrix. Phase A ships
  standalone value and is independently mergeable.
- **`sel` stays in Phase B.** Fork 5 chose structural paths over two alternatives that would
  have avoided writing `pathForUid`; dropping it later would quietly reverse that.

### 2.1 Why restore is automatic, not a prompt

Fork 4 removes `beforeunload` on the grounds that refresh is no longer destructive. That is only
true if restore is **automatic**. A boot-time "Restore / Discard?" modal would make refresh
destructive-with-a-prompt — the exact thing fork 4 declared unnecessary — and would put a modal
in the boot path of every session. So restore happens silently and announces itself with a
dismissible inline notice (§6.3). This is a consequence of fork 4, not an independent choice.

### 2.2 Why the uid could not go in the URL

`newUid` (`tree.ts:159`) mints uids as `crypto.randomUUID()`, falling back to
`` `uid-${Date.now().toString(36)}${Math.random().toString(36)…}` ``, and `convert.ts:108` calls
it for every node **on every `docToTree`**. Uids are therefore fresh on each server load. A uid in a URL resolves for the author's own refresh (the draft preserves
the tree verbatim, uids included) and resolves to nothing for anyone else, or for the same user
after a Load — failing precisely in the sharing case that motivates having a URL at all.

The structural grammar `paths.ts` already documents for backend diagnostics is stable against
that, and `resolveDiagnosticPath` (`paths.ts:102`) already reads it. Only the inverse is missing.

---

## 3. Architecture

Four pure modules; two glue hooks. The split is dictated by C-2.

| File | Kind | Responsibility |
|---|---|---|
| `src/shell/urlState.ts` | **pure**, new | `parseHash(hash) → UrlState`, `formatHash(UrlState) → string` |
| `src/builder/paths.ts` | **pure**, extend | `pathForUid(tree, groups, uid) → string \| null` |
| `src/stores/draftStorage.ts` | **pure** + edge, new | `parseDraft` / `serializeDraft`; guarded `readDraft` / `writeDraft` / `clearDraft` |
| `src/shell/bootstrap.ts` | **pure**, new | `decideBoot(url, draft) → BootAction` |
| `src/shell/useUrlSync.ts` | glue, new | mount-parse, `popstate` listener, store→hash writer |
| `src/shell/useDraftAutosave.ts` | glue, new | debounced docStore subscriber |

`decideBoot` being pure is the load-bearing structural choice. The reconciliation matrix (§5) is
the part of this increment most likely to be subtly wrong — five branches, each with a different
notion of "who wins" — and making it a total function from two plain values to a tagged action
puts all five rows under vitest without a browser. The executor that runs a `BootAction` is
then dumb enough not to need tests.

### 3.1 Data flow

```
boot:   location.hash ──parseHash──▶ UrlState ─┐
        storage ───────readDraft────▶ Draft ───┴─▶ decideBoot ─▶ BootAction ─▶ executor
                                                                                 │
                                                          ┌──────────────────────┤
                                                          ▼                      ▼
                                                     docStore.loadDoc      navStore.setTab
                                                          │
                                              (post-load) resolveDiagnosticPath(sel) ─▶ select(uid)

steady: docStore ──debounce 500ms──▶ writeDraft
        docStore/navStore/recordsStore ──formatHash──▶ push|replaceState
        popstate ──parseHash──▶ apply (guarded against the writer)
```

The writer and the `popstate` reader form a loop. It is broken with an `applying` ref in
`useUrlSync`: while a URL-originated update is being applied to stores, the store→hash writer is
suppressed. This is the one piece of genuinely stateful glue in the increment and the reason
`useUrlSync` is a hook rather than a module-level subscription.

**`apply` handles `exp` too** (user-settled 2026-07-19). Every other field resolves synchronously
against state already in memory; `exp` does not — reopening a document is a server fetch. Without
it, a hand-edited `exp=` snapped back within a tick and Back across two documents *rewrote* the
older history entry instead of reopening it. Handling it means the `applying` guard must be held
across an `await`, which is a genuine widening: the guard's original soundness argument leaned on
every mutation being a synchronous zustand `set`. The durable half of that argument — `last` being
recomputed after the apply, so a late write compares against fresh state — is what still holds,
and is why this is safe to widen. A stale in-flight fetch must not be allowed to land after a
newer one.

---

## 4. URL grammar

```
#/builder?exp=a1b2&scope=dose&sel=groups['dose'].body[1]
#/builder?exp=a1b2&sel=blocks[0].children[2]
#/records/rec_99
#/run
#/devices
```

- Route segment ↔ `Tab` (`shell/tabs.ts` — `Builder | Devices | Run | Records`), lowercased.
- `exp` — `docStore.serverId`. Absent for an unsaved new document.
- `rec` — carried as a path segment on `#/records/<id>` (`recordsStore.openId`), because a
  record id *is* the thing being viewed rather than a qualifier on a view.
- `scope` — `docStore.scope`; a key into `groups`, or absent for the main workflow.
- `sel` — structural path (§4.1).

**Query construction goes through `URLSearchParams`, never string concatenation.** `paths.ts:19-31`
documents that a group name may contain a literal space, an apostrophe, or `->`: non-identifier
names are reachable via Import, because `GROUP_NAME_RE` (`docStore.ts:40`) is enforced only on
add/rename and `convert.ts` loads keys verbatim. Both `scope` and `sel` can therefore carry
characters that a hand-rolled encoder would mangle into a different, valid-looking group name.

Unknown or malformed input never throws: unknown tab → `Builder`, malformed hash → all-defaults.
Parsing is total, the same contract `parseOverrides` holds.

### 4.1 `pathForUid`

The inverse of `resolveDiagnosticPath`, emitting the subset of the grammar the builder can
originate:

- `blocks[i]` + `.children[i]` / `.body[i]` / `.then[i]` / `.else[i]` trailer — main tree.
- `groups['name'].body[i]` + trailer — a group body, quoted exactly as Python `repr()` spells
  it, which means **single quotes normally but double quotes when the name contains an
  apostrophe**. This flip is load-bearing, not cosmetic: `groups['o'brien'].body[0]` does not
  match `GROUP_HEAD_RE` at all (the `'([^']*)'` alternative consumes `'o'`, then demands `]`
  and finds `b`), so it resolves to `uid: null` — and worse, `quotedGroupHeadEnd` would end the
  opaque head at that apostrophe and resume the space/arrow scans *inside* the name, which is
  the Finding-1 bug class `paths.ts`'s header warns about. Emitting `repr()`'s spelling keeps
  the writer byte-identical to the backend's `f"groups[{name!r}].body"`.
  A name containing *both* quote characters is unrepresentable (the reader has no escape
  handling); `pathForUid` returns `null` for it rather than emitting a path that would resolve
  to nothing or, worse, to a different node.

It does **not** emit the compound `blocks[i]->name.body[i]` form. That form is produced by a
validator walk crossing from a call site into a plain group's body (`validate.py:894,940`); it
describes a *rendering* of a group at a call site, not an authored location, and the builder's
selection always refers to an authored node. `resolveDiagnosticPath` keeps reading it for
diagnostics; `pathForUid` never writes it.

Traversal uses `childSlots` (`tree.ts:157`), not a local slot list, for the same reason the
torture walker does: a hand-listed `['children','body','then','else']` silently stops descending
the day a new container kind lands.

Returns `null` when the uid is not in the tree — the caller omits `sel` rather than emitting a
path that resolves to something else.

---

## 5. Boot reconciliation

`decideBoot(url: UrlState, draft: Draft | null) → BootAction`, total, pure.

| # | URL | Draft | Action | Rationale |
|---|---|---|---|---|
| 1 | `exp=X` | `serverId=X`, content differs from `savedSnapshot` | `restoreDraft` | The user's unsaved work, on the document the URL names. |
| 2 | `exp=X` | `serverId=X`, content matches `savedSnapshot` | `loadServer(X)` | Draft is clean; the server copy may be newer. |
| 3 | `exp=X` | `serverId=Y` (Y ≠ X), or none | `loadServer(X)` + **warn if Y's draft is dirty** | Fork 7: URL wins identity. `decideBoot` itself never clears Y's draft — but see §5.1, because storage does not actually preserve it. |
| 4 | no `exp` | any draft | `restoreDraft` | The URL names no document, so the draft is the only candidate — whether it is an unsaved new doc (`serverId=null`, the highest-value case: no server copy exists at all) or a saved-then-edited one (`serverId=X`, which the URL writer then reflects back as `exp=X`). |
| 5 | no `exp` | none | `newDoc` | Cold start. |

Row 4 deliberately does **not** split on the draft's `serverId`. An earlier draft of this matrix
did, restoring only when `serverId === null`, which silently made Phase A a no-op for every
saved-then-edited document — the exact case the increment exists to protect, and unreachable by
Phase A's tests because Phase A supplies no `exp` at all.

Row 3 must not call `clearDraft`. That is necessary but, as §5.1 records, not sufficient.

### 5.1 Row 3 cannot actually preserve the foreign draft (user-settled 2026-07-19)

An earlier version of row 3 promised that "Y's draft is left in storage untouched, so navigating
back to Y still restores it." **That promise was false, and it contradicted fork 3.** Fork 3
chose a *single* autosaved draft over per-document drafts; with one storage key,
`useDraftAutosave` overwrites Y's draft with X on the first post-boot mutation. (The trigger is
`BuilderTab` mounting: `useValidation` unconditionally calls `setValidating(true)`, and `loadDoc`
has just set `validating: false`, so it is a real state change. Opening X on `#/devices` instead
leaves Y's draft intact — the A/B split that isolated this.)

This matters more than a stale doc comment, because the three
`confirm('Discard unsaved changes?')` guards cover New / Load / Import / Duplicate only.
**Following a shared link is a fresh page load and hits none of them**, so unsaved work on Y
disappears with no prompt at all.

Settled: **keep the single draft and warn before clobbering.** When boot takes row 3 and the
stored draft is dirty and belongs to a different document, surface a notice naming that document.
This makes the loss visible rather than preventing it — a deliberate trade, taken over
per-document draft keys, which would have reversed fork 3. The notice is a third `BootNotice`
variant (§6.3).

Fork 7 is otherwise unchanged: the URL still wins identity, and `decideBoot` still never clears a
foreign draft.

**`loadServer(X)` where X 404s** (deleted, or a stale link) is handled by the executor, not
`decideBoot` — it is an async outcome, not a decision over known inputs. The executor falls back
to `newDoc()` and surfaces a notice; it does not fall back to an unrelated draft.

**Draft staleness.** Row 1 restores regardless of the server's `updated_at`. Detecting a
server-side change would require a fetch before deciding, putting a race in the boot path to
serve a case (a shared stack where two people edit one experiment) that the Studio has no
concurrent-editing story for anyway. Out of scope; noted so it is a decision rather than an
oversight.

---

## 6. Draft persistence

### 6.1 Record

```ts
interface Draft {
  v: 1
  serverId: string | null
  savedSnapshot: string                      // dirty survives refresh, not just content
  content: DocContent                        // editor form — preserves uids
  view: {
    scope: string | null
    selectedUid: string | null
    collapsed: Record<string, boolean>
  }
  updatedAt: number
}
```

`savedSnapshot` is stored rather than recomputed because `selectDirty` compares live state to it;
without it a restored draft would read as clean and the unsaved-dot would lie.

`content` is `DocContent` (editor form, `convert.ts:29`) rather than `ExperimentDocJson`. Storing
the wire form would round-trip through `docToTree` on restore and remint every uid, invalidating
`view.selectedUid` and every key in `view.collapsed`.

`view` exists because fork 2 keeps `collapsed{}` out of the URL — correctly, it is noise — but
losing every collapsed block on refresh is highly visible on a large workflow. The URL and the
draft are complementary: the URL carries what is *shareable*, the draft carries what is *yours*.

### 6.2 Storage layers (fork 6)

| Layer | Key | Role |
|---|---|---|
| `sessionStorage` | `studio.draft.v1` | Primary. Per-tab by definition and survives reload and tab-restore, so two tabs can never clobber each other. |
| `localStorage` | `studio.draft.v1` | Best-effort mirror. Read **only** when sessionStorage is empty — i.e. a genuinely new tab or a new browser session. |

Both writes are `try/catch` and degrade silently on quota or disabled storage, as
`roleColorStore` does. A failed mirror write is not an error state: the session copy is
authoritative and the app is fully functional without the mirror.

Note `labsStore.ts` reads `localStorage` **unguarded** in its initializer today and throws in
disabled-storage contexts. Out of scope to fix here, but the new code must not copy it.

### 6.3 Write and restore

Autosave subscribes to the `DocSnapshot` fields of `docStore` and writes debounced ~500ms.
View-state changes (`scope`, `selectedUid`, `collapsed`) are included in the same subscription.

`clearDraft()` is called on the three existing `confirm()` guard sites plus Duplicate — the
actions that legitimately erase the draft. It is **not** called on unload.

On restore, a dismissible inline notice appears in the Builder toolbar row: *"Restored unsaved
changes from 14:32"*. Not a modal (§2.1), not a toast that vanishes before it is read.

---

## 7. Changes to existing code

| File | Change |
|---|---|
| `stores/navStore.ts` | `tab` seeded from the URL at boot instead of the hardcoded `'Builder'`. |
| `stores/docStore.ts` | `loadDoc(content, serverId, view?)` — optional third argument so a restore can rehydrate `scope` / `selectedUid` / `collapsed`. Today it hardcodes them empty. Default behaviour unchanged when omitted, keeping the 517-line `docStore.test.ts` contract intact. |
| `builder/Toolbar.tsx` | New, Import and Duplicate also `clearDraft()` after the store reset. Guards themselves unchanged. |
| `builder/LoadDialog.tsx` | Load's handler lives **here**, not in `Toolbar.tsx` — the toolbar's Load button only opens the dialog, and `open(id)` carries both the confirm guard and the `loadDoc` call. It gets the fourth `clearDraft()`. |
| `builder/paths.ts` | Gains `pathForUid` (§4.1). |
| `App.tsx` | Mounts `useUrlSync` and `useDraftAutosave`; runs the boot executor. |

No backend change. No `beforeunload`. No new dependency — no router library is added; the hash
router is ~80 lines of pure code against `URLSearchParams`.

---

## 8. Testing

Node-env vitest only (C-2), plus the Playwright probe for the one new visual surface.

**`paths.test.ts` — the inverse property.** For every node in the torture fixture
(`webapp/fixtures/ui-audit-torture.json`, which `torture.test.ts` already type-forces to cover
every `BlockKind`), assert:

```
resolveDiagnosticPath(tree, groups, pathForUid(tree, groups, uid)!).uid === uid
```

This is the strongest available check on the riskiest new code, and it reuses a fixture that is
already exhaustive by construction. Add explicit cases for group names containing a space, an
apostrophe, and `->`.

**`urlState.test.ts`** — round-trip `formatHash(parseHash(h)) === h` for canonical inputs;
unknown tab → Builder; malformed/empty hash → defaults; encoding of the three hostile group
names; `sel` preserved verbatim through encode/decode.

**`bootstrap.test.ts`** — one case per row of §5, plus row 3 asserting the foreign draft is *not*
cleared.

**`draftStorage.test.ts`** — `parseDraft` totality: `null`, `""`, `"{"`, `[]`, `{"v":99}`,
missing `content`, missing `view` → all `null`, never a throw. `serializeDraft` round-trip.

**Probe** — `npm run capture` for the restore notice, R5 (`text-contrast`) and R4
(`sibling-height-mismatch`) against the toolbar row it joins.

**Gates** — `npm run lint && npm test && npm run build` in `webapp/frontend`; `npm run capture`
after the notice lands. Backend gates unaffected (no backend change), but run them once before
the PR since CI does.

---

## 9. Phases

**Phase A — draft persistence.** `draftStorage.ts`, `useDraftAutosave.ts`, `loadDoc` view
argument, `clearDraft` at the guard sites, the restore notice, and **all of `bootstrap.ts`** —
the `UrlState` type and the complete five-row `decideBoot`. Ships standalone: refresh stops
being destructive. Independently mergeable.

Building the whole matrix in Phase A rather than "the draft half" avoids rewriting a pure
function that Phase B would immediately widen. Phase A's executor simply passes the empty
`UrlState` (`{tab:'Builder', exp:null, rec:null, scope:null, sel:null}`), so only rows 4 and 5
are *reachable* at runtime; rows 1–3 are tested from the start and become live in Phase B. This
is why `UrlState` is declared in `bootstrap.ts` and merely *produced* by `urlState.ts`, rather
than the other way round.

**Phase B — URL state.** `urlState.ts`, `pathForUid`, `useUrlSync.ts`, navStore seeding, and
feeding a real `UrlState` into the existing `decideBoot`.

**Phase C — two defects Phase B's browser checks exposed**, both settled with the user
2026-07-19 rather than papered over: the row-3 clobber warning (§5.1) and `exp` handling in
`apply` (§3.1). Neither was foreseeable from the design alone; both were found by driving the
real app, which is why the plan's per-task browser verification earns its cost.

## 10. Out of scope

- Fixing `labsStore.ts`'s unguarded `localStorage` read (§6.2).
- Server-side draft sync or any concurrent-editing story (§5).
- Multiple named drafts, one per experiment (considered in fork 3, rejected: reconciliation cost).
- Panel/filter/scroll state in the URL (considered in fork 2, rejected: noise and history churn).
- `beforeunload` (fork 4).
