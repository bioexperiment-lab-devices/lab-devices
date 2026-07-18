# Lab-independent Builder — design

**Date:** 2026-07-18
**Status:** approved (pending spec review)
**Scope:** the app shell's tab bar and header (`webapp/frontend/src/shell/TabShell.tsx`,
`stores/navStore.ts`, `App.tsx`), one copy/comment change in the Builder palette's Roles
section, and the capture harness's tab selector. No backend change.

## 1. Problem

An experiment workflow is an abstraction that suits almost every lab. It can be authored,
edited and validated with no particular lab in mind — roles are symbolic, and they are bound
to physical devices only when a run starts. The application's data flow already honours this
completely. Its user interface does not, and teaches the opposite.

**The Builder tab has no lab dependency in code.** No file under `webapp/frontend/src/builder/`
imports `stores/labsStore.ts` or `api/labs.ts`. The palette's device types and verb chips come
from `GET /api/catalog`, which the backend answers from the engine's static registry
(`webapp/backend/experiment_studio/api/catalog.py:14-16`, `lab_devices.experiment.verb_catalog()`)
— no lab parameter, no roster access. Draft validation is `POST /api/validate` with the
document as its only argument (`api/validate.py:14-17`); `docs_store.validate_doc` type-checks
the workflow by substituting *synthetic placeholder* device ids
(`roles.py:42-50`, `f"{dtype}_{i}"`) precisely so that no roster is needed. Role-to-device
binding lives exclusively in `run/PreflightPanel.tsx`.

So the abstraction holds. Two shell-level surfaces contradict it:

**D1 — the app teaches lab-first.** `navStore.ts:11` defaults to `tab: 'Devices'` and
`TabShell.tsx:3` orders the tabs `['Devices', 'Builder', 'Run', 'Records']`, so the tab bar
reads "1 Devices, 2 Builder, …". A user's first screen is a lab picker, before they have seen
an experiment. The order implies a prerequisite that does not exist.

**D2 — the header asserts a lab dependency on every tab.** `TabShell.tsx:40-48` renders a
persistent pill reading `lab: X` or `no lab selected`, including while authoring. On the
Builder tab "no lab selected" is not a neutral status line; it reads as an unmet precondition
for the work on screen.

Neither defect is a missing capability. Both are the interface describing a coupling the code
does not have.

## 2. Settled decisions

Established at the 2026-07-18 brainstorm; do not re-litigate.

- **Builder is first and is the landing tab. Devices is second.** Order becomes
  Builder, Devices, Run, Records.
- **The header lab pill appears on the Run tab only** — not on Records. See §4 for why
  Records was excluded after the brainstorm's initial answer.
- **Scope is the tab reorder plus making the independence legible.** No Run-tab gating: every
  tab stays enabled at all times. No rename of the `BlockNode.device` field (which holds a role
  name, not a device id) — that is real confusion but a much larger diff across
  `tree.ts`/`convert.ts`/`refs.ts`/`summary.ts`/`Inspector.tsx` and the backend's `roles.py`,
  and is left for a future increment.
- **The Inspector is untouched.** Its Role and Verb dropdowns are catalog-driven and were not
  among the surfaces that read as lab-specific.

## 3. Tab order, landing tab, and a pure tab module

`TABS` becomes `['Builder', 'Devices', 'Run', 'Records']`. The digit shown before each label is
derived from the array index (`TabShell.tsx:35`, `{i + 1}`), so reordering the array is the whole
of the visual renumbering — there are no hard-coded labels to keep in sync. `navStore`'s initial
value changes from `'Devices'` to `'Builder'`. Tab selection remains unpersisted, as today; only
the lab is persisted (`labsStore.ts:7`, `studio.selectedLab`).

`TABS`, the `Tab` type, and a new `labScopedTab(tab: Tab): boolean` predicate move out of
`TabShell.tsx` into a new pure module `src/shell/tabs.ts`. `TabShell.tsx` and `navStore.ts`
import from there; `TabShell.tsx` no longer exports them, so there is exactly one source.

The extraction is not decoration — it is what makes this increment testable at all. Per
`webapp/frontend/CLAUDE.md`, vitest here runs in the node environment with pure functions only:
no component rendering, no jsdom, no `@testing-library`. Logic that stays inside `TabShell.tsx`
cannot be asserted by any test in this repo. This is the same move, for the same reason, that
W12 made when it lifted the palette's chip arrays into `builder/paletteSections.ts`.

`labScopedTab` is backed by an exhaustive `Record<Tab, boolean>` rather than a set membership
check or a comparison against a literal. A fifth tab added later then fails to compile until it
states whether it depends on a lab, which is the property a hand-maintained array cannot give
(W12's lesson: an exhaustive mapped type forces every member's classification at compile time,
where an `ALL_KINDS` array silently accepts a missing or wrong entry).

## 4. The header pill becomes tab-scoped

`TabShell` renders the lab pill only when `labScopedTab(props.active)` is true — that is, on Run.
The health status line beside it is unaffected and stays on every tab: it describes the server,
not the lab. When the pill is hidden the surrounding `ml-auto` flex span still lays out the
status line correctly, because the span sizes to its content.

**Why Records is excluded, against the brainstorm's first answer.** `RecordsTab` performs no
lab filtering of any kind — it lists every record regardless of lab, and `RecordsTable.tsx:122`
already renders a per-row `lab` column. A single global `lab: X` pill above an unfiltered table
asserts a scoping that does not exist, and would be read as a filter. The per-row column is
already the accurate presentation. Making the pill honest on that tab would mean actually
filtering the table by selected lab, which needs a filter control, an all-labs escape hatch, and
a decision about records from labs no longer in the roster — out of scope here.

After this change the pill means "the lab this run is bound to", which is true wherever it
appears.

## 5. Making the independence legible in the Builder

Two changes, both in the palette's Roles section.

**A one-line hint** at the top of the Roles section, in `text-hint` per the project's text-colour
rule, reading:

> Roles are symbolic — you bind them to real devices when you start a run.

The
Roles section is the only place in the Builder where hardware is conceptually adjacent — device
types name real equipment and the verb chips name real operations — so it is the one location
where a reader can reasonably wonder which lab they are looking at. One sentence there is what
makes the whole abstraction click; the same sentence anywhere else in the Builder would be
answering a question the user did not have.

**The stale comment at `roleGroups.ts:3`**, which says a type with no roles still gets a block
"so the user sees what the lab offers", is corrected to name the catalog. That line is the single
place in the Builder source that claims a lab dependency, and it is how a future reader would
conclude one exists.

## 6. Run remains the only lab gate

No change to `run/PreflightPanel.tsx`. It already renders "Select a lab first" with a "Go to
Devices" button when `lab === null` (`:94-103`), and its `useNavStore.getState().setTab('Devices')`
jump remains correct under the new order because it targets the tab by name, not by index.

After this increment that empty state is the only place in the application that demands a lab,
which is the intended flow: author freely, choose a lab when you are ready to run.

## 7. Capture harness

`webapp/frontend/tools/capture.mjs:41` selects the Builder tab with
`page.getByRole('button', { name: /^2\s*Builder$/ })`. Every capture state routes through
`gotoBuilder`, so all of them break the moment Builder becomes tab 1. The regex becomes
`/^1\s*Builder$/`.

`npm run capture` is re-run after the change, because removing the pill alters the header row's
composition and the probe's `sibling-height-mismatch` rule (R4) measures controls sharing a
visual row. The expected result is the same zero violations W11 established.

## 8. Compatibility

No document-format, API, schema, or engine change. No persisted state changes meaning: the
`studio.selectedLab` key keeps its semantics, and a user with a lab already selected sees no
behavioural difference except that the pill is now absent while authoring. Nothing reads the tab
order at runtime other than the header's index digit.

The W5 UI-testing recipe recorded in project memory notes that "after `page.reload()` the app
lands on the Devices tab". That becomes false with this change and should be re-recorded as
Builder; `capture.mjs` is unaffected by it because it clicks the Builder tab explicitly rather
than relying on the landing tab.

## 9. Testing

- **New `src/shell/tabs.test.ts`** (vitest, node env, pure): asserts the tab order with Builder
  first and Devices second, and pins the lab-scoping map so that Builder, Devices and Records are
  false and Run is true. The map is typed `Record<Tab, boolean>` so a future tab is a compile
  error until classified.
- **Existing gate**, unchanged: `cd webapp/frontend && npm run lint && npm run typecheck &&
  npm test -- --run && npm run build` (two known oxlint fast-refresh warnings, exit 0).
- **Harness**: `npm run capture` at 1024/1440/1920, confirming zero probe violations and, by
  inspection of the captures, that the pill is absent on Builder and Devices and present on Run.
- **Backend**: untouched, so its gate is a no-op regression check rather than part of this work.

## 10. Out of scope

- Gating or disabling the Run tab until a lab is chosen.
- Renaming `BlockNode.device` to `role`.
- Filtering the Records tab by lab, and any lab-picker control in the header.
- Persisting the selected tab across reloads.
- Any change to the Inspector, to validation, or to the catalog endpoint.
