# Experiment Studio — UI-audit fixes (W10) — design

**Date:** 2026-07-17 · **Status:** approved (brainstorm forks user-settled 2026-07-17)
**Input:** the UI-audit report `docs/ui-audit/2026-07-17.md` (24 verified findings: 0 S1 / 11 S2 /
13 S3), merged as PR #33 with fixes explicitly deferred to this increment.
**Repo context:** all paths under `webapp/frontend/src/` unless stated. Base: `main` after #33.

## 1. Goal

Fix all 24 audit findings plus the dialog-accessibility gap the audit recorded as limitation
(e-i), in one increment (one PR), verified by a full re-run of the audit's mechanical probe.

## 2. Scope

**In:** all 24 findings; `role="dialog"`-equivalent semantics + focus trap for LoadDialog and
InputDialog; a project-wide icon-system migration to lucide-react (user-directed, see §3); the
overflow *affordance* half of settled-item 10.

**Out (explicitly):**
- The parallel-lane layout redesign (lane wrapping / new arrangement). Settled-item 10 stays open
  as its own future increment; this one only makes the existing `overflow-x-auto` scroll visible.
- The lab-bridge host-chrome pill overlapping record content (limitation e-ii) — cross-repo,
  belongs to `lab_devices_server`.
- Keyboard-order / screen-reader / ARIA work beyond the two dialogs (limitation d stands).

## 3. Icon system (cross-cutting; fixes findings 2 and 3 by construction)

**User-settled rule (record in a new `webapp/frontend/CLAUDE.md`):** interactive icons come from
**lucide-react** only; brand marks (if ever needed) from **Simple Icons**; no raw glyph characters
for interactive controls. Semantic/mathematical *notation* is exempt and stays typographic.

Add dependency `lucide-react` (latest). New `src/ui/` module:

- **`ui/IconButton.tsx`** — the one component for every per-row/per-card icon action.
  Contract: ≥ 24×24 px hit area on both axes (padding around a 14–16 px Lucide icon); resting
  `text-slate-500`; hover `text-slate-700`, destructive hover `text-red-600`; `focus-visible`
  ring; `title` + `aria-label` required. Replaces the five-file `text-xs text-slate-300` idiom
  (`builder/Canvas.tsx`, `builder/DropSlot.tsx`, `records/RecordsTable.tsx`,
  `builder/LoadDialog.tsx`, `records/WorkflowSnapshot.tsx`).

**Glyph → Lucide mapping** (the double-duty `⧉` is deliberately split):

| Today | Meaning | Replacement |
|---|---|---|
| `✕` | delete / remove / close | `X` |
| `⧉` (action) | duplicate | `Copy` |
| `⧉` (card marker) | group_ref card | `Group` |
| `✎` | edit / record marker | `Pencil` |
| `▾` / `▸` | collapse toggles | `ChevronDown` / `ChevronRight` |
| `↻` (action) | refresh / retry | `RefreshCw` |
| `↻` (card marker) | loop card | `Repeat` |
| `⚠` | alarm | `TriangleAlert` |
| `⛔` | abort | `OctagonX` |
| `⭳` | export/download | `Download` |
| `✓` | valid / ok | `Check` |
| `←` `→` (interactive) | navigation | `ArrowLeft` / `ArrowRight` |
| leading `+` in button labels | add | `Plus` + text |
| `—` (InputDialog hide) | hide | `Minus` |

**Stays typographic (semantic notation, not icons):** `∀` for_each (no Lucide equivalent; audit
settled-item 6 holds), `ƒ` compute → use Lucide `SquareFunction` (keeps the four control-section
marks distinct, settled-item 5's actual requirement), `R×N` retry marker, `×N` loop multiplier,
the `●` unsaved dot (a shape — darkened per §4, not iconified), `…` ellipses, prose arrows/dashes.

## 4. Color tokens (findings 1, 9, 12, 14, 16, 24)

Tailwind 4 `@utility` classes in `index.css`:

- `text-caption` — default **slate-600**. For all *meaning-carrying* secondary text currently
  slate-400/500: on-canvas block labels, lane/branch/then/else captions, EventLog timestamps,
  Inspector section headers (the finding-1 list: `Canvas.tsx:193,199,286-287,329,345-346`,
  `run/EventLog.tsx:61`, `Inspector.tsx:137-139,463,321`).
- `text-hint` — **slate-500**. Only for genuinely incidental text (placeholders, empty-state
  copy, DropSlot's "drop here"), and only where it *measures* ≥ 4.5:1 against its actual
  rendered background; where it doesn't, use `text-caption`.

Contrast numbers are **probe-verified, not assumed** (Tailwind 4 emits oklch; the probe's pixel
readback is the referee). Spot fixes riding the same pass:

- Problem-count badge (F12): `bg-red-500` → `red-600`, or `red-700` if red-600 measures < 4.5:1.
- Validating chip (F14): text → `slate-700`; unsaved dot ● → `amber-600` (≥ 3:1 graphic floor).
- Offline lab dot (F9): `slate-300` → `slate-500`, **plus** a persistent `offline` text label
  (`text-caption`); online keeps the emerald dot; both keep the `title`.
- `unused` stream tag (F16): distinct amber tint (e.g. `bg-amber-100 text-amber-700`,
  probe-verified); `measure`/`record` tags stay neutral.
- Fatal record error (F24): red treatment matching `RunView.tsx:103` and the "failed" chip;
  tolerated_errors / alarms panels stay amber.

## 5. Behavioral fixes

Each has a settled design choice; each ships with a test (see §8 testing strategy).

- **F5 — gap_after eligibility** (`Inspector.tsx:131`): parents `loop` and `branch` become
  gap-after-eligible (the engine honors it there — `execute.py:451` shared runner; audit-verified).
  Bounded check during implementation: if `expand.py` provably preserves `gap_after` on for_each
  *body children* through splicing, include `for_each` as a parent too; otherwise leave it with
  the existing explanatory hint. The `for_each` block itself stays ineligible
  (`validate.py:117-120` rejects it) and `start_offset` stays parallel-only (that half of the raw
  finding was refuted).
- **F6 — DevicesTab central panel** (`DevicesTab.tsx:79-82`): when `labsError` is set, the
  central placeholder shows error-specific copy instead of "Pick a lab to see its devices."
- **F7 — roster retry** (`DevicesTab.tsx:41-45`): inline "retry" link inside the `labsError`
  banner, mirroring the device-level one (`:107-109`).
- **F8 — rediscover in-flight**: while `s.discovering`, dim the device table
  (reduced opacity + `pointer-events-none`) and show an inline "Rediscovering devices — takes a
  few seconds" note; the button label alone no longer carries the state.
- **F23 — refresh affordances**: labs "↻ refresh" text link becomes a bordered button identical
  in style to the devices "Refresh" button (both with `RefreshCw`).
- **F10 — streams filter** (`StreamsPanel.tsx:39`): case-insensitive substring filter input above
  the list, same pattern as LoadDialog's search box.
- **F15 — Record "into stream"** (`Inspector.tsx:746-763`): extract Measure's IntoPicker (picker
  + inline "+ new stream…" mini-form) into a shared component; Record uses it; label unified to
  "Into stream".
- **F17 — tick labels** (`charts/StreamChart.tsx:38`): blank consecutive duplicate x-axis labels
  after `formatElapsed` (keep the first of each run).
- **F18 — role errors** (`RolesPanel.tsx:93`): rename/delete errors render under the specific
  failing row, not in one shared slot.
- **F20 + F4 — truncation titles**: `title={...}` on every truncating span: canvas summary/label
  (`Canvas.tsx:198-199`), LoadDialog name/description (`LoadDialog.tsx:98-101`), the Records
  name cell (`RecordsTable.tsx`, the preprod `max-w-64` instance).
- **F13 — AddRoleForm sizing** (`Palette.tsx:86-107`): the role-name input, type select, and Add
  button move from `py-0.5` to the Chip/Toolbar standard `px-2 py-1`, matching the palette chips
  above them.
- **F19 — LoadDialog open action** (`LoadDialog.tsx:97`): the row's primary open button gets a
  hover background/border so the primary action is at least as indicated as the Export/Delete
  icons beside it.
- **F21 — LoadDialog scroll**: header + search sticky; only the results `ul` gets
  `overflow-y-auto` (natural fit with the §7 `<dialog>` conversion).
- **F22 — preflight** (`PreflightPanel.tsx:172-175`): keep "✓ workflow valid" (it is true —
  scoped to validation); add an amber "N roles unmapped — Start disabled" line whenever
  `diagnostics.length === 0 && !mappingComplete`.

## 6. Lane strip (F11 + settled-10 affordance)

- **F11 (the click-stealer):** give the "+ lane" button its own reserved, opaque, correctly
  z-ordered slot in the strip (`Canvas.tsx:277,307`) so it can never paint over an adjacent
  card's `Copy`/`X` icons at any viewport. Acceptance is behavioral, reproducing the audit's
  proof at 1280×800 on `inspector/loop`: `document.elementFromPoint` at each icon's centre
  returns the icon's own button, and a scripted click on Duplicate *duplicates the subtree*
  (block count +subtree, not +1 empty lane).
- **Overflow affordance (settled-10, this increment's share):** the strip already scrolls
  (`overflow-x-auto`, `Canvas.tsx:277`) — hidden lanes are reachable today but nothing says so.
  Add a lane count to the parallel card header (e.g. "4 lanes") and an edge fade / scroll shadow
  on the strip when content overflows. The scroll behavior and dnd geometry are untouched.

## 7. Dialog accessibility (limitation e-i)

Convert LoadDialog and InputDialog from bare `.fixed.inset-0` overlays to native `<dialog>` +
`showModal()`: focus trap, Esc (cancel event), and implicit `aria-modal`/dialog role come from
the platform. Styling stays Tailwind (`::backdrop` for the scrim); click-on-backdrop-closes is
preserved (event target === the dialog element). Behavior parity otherwise.

**Harness note:** the audit probe identified dialogs by `.fixed.inset-0`; the re-run harness
(§8) must key off `dialog[open]` instead.

## 8. Verification

**Probe re-run (the headline gate).** Rebuild the Track A harness in the scratchpad from the
audit plan's Task 2 blocks (`docs/superpowers/plans/2026-07-17-experiment-studio-ui-audit.md`) —
it already bakes in the two hard-won rules: oklch pixel-readback for contrast, clip-aware
overlap testing (clip-chain intersection + `elementFromPoint`). Re-run **all 42 states × 3
viewports**. Gate:

1. Every root-cause selector cited in findings 1–4, 12 measures clean (≥ 4.5:1 normal text,
   ≥ 3:1 graphics, ≥ 24px both axes on the cited controls).
2. The F11 scripted click duplicates (see §6).
3. No **new** S2-class rows relative to the committed baseline `docs/ui-audit/2026-07-17/probe.json.gz`
   (the icon migration must not introduce fresh contrast/target violations).
4. Truncation rows for the F4/F20 spans report a recovery path (`title` present).

**Tests.** The frontend suite is node-env pure-function vitest (no @testing-library/react; do
not add it). Strategy: extract each behavioral decision into a pure function and test that —
gap-after eligibility (F5), central-placeholder state selection (F6), tick-label dedupe (F17),
stream filtering (F10), unmapped-count line (F22), per-row error keying (F18). DOM wiring is
verified by the probe re-run plus scripted browser checks (F11 click; dialog focus trap, Esc,
sticky header). Every test must be **mutation-verified**: shown to fail against the unfixed
behavior (TDD order or demonstrated revert).

**Standard gates.** Backend: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Frontend: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`.

**Ship + preprod.** One PR, squash title `feat(studio): …` → release-please bumps to 0.8.0
(streams filter + affordances are features, not only fixes). After the ghcr image is public:
bump the `studio_image` pin in `lab_devices_server` (companion checkout), deploy, and spot-check
the three preprod-only findings on real data — F9 (offline labels on the real roster), F24 (red
fatal box on the real failed record), F4 (Records cell titles). Preprod access:
`ssh khamit@111.88.145.138`; `windows_arm64_test_client` is the sanctioned test lab.

## 9. Settled decisions (do not re-litigate)

1. Scope = all 24 + dialog a11y; lane redesign and e-ii excluded (user, 2026-07-17).
2. Lane strip = gutter fix + overflow affordance; existing horizontal scroll kept (user's
   conditional resolved by `Canvas.tsx:277` already being `overflow-x-auto`).
3. Icons = lucide-react everywhere as a standing project rule; Simple Icons for brand marks;
   semantic notation (`∀`, `R×N`, `×N`, `●`) stays typographic; `ƒ` → `SquareFunction`.
4. Verification = full 42-state probe re-run, not spot checks (user).
5. F5 shows the row (engine honors it) rather than explaining its absence.
6. F22 keeps the green check truthful and *adds* the unmapped-count line.
7. `⧉` splits: `Copy` for the duplicate action, `Group` for the group_ref card marker.
8. Dialogs use native `<dialog>`/`showModal()`, not a hand-rolled focus trap.
9. No @testing-library/react — pure-function extraction + browser-level probe checks.
10. Audit settled-items 1–9 all continue to hold; nothing here reverses them.

## 10. Risks / implementer gotchas

- **Tailwind 4 emits oklch** for every palette color — never eyeball or string-parse; the probe's
  pixel readback is the only trusted contrast measure.
- **Overlap rows are 99.6% geometric false positives** — only clip-aware + `elementFromPoint`
  evidence counts (audit limitation a).
- The app has **no `data-*` attributes**; the harness keys off `.cursor-grab`, tab names like
  `"1 Devices"`, and (after §7) `dialog[open]`.
- Card headers are ~28px tall; a 24px IconButton fits, but watch for header-height creep in
  dense canvases (torture fixtures render hundreds of cards).
- `validate_doc` short-circuits after role diagnostics (`docs_store.py:264`) — fixture states
  relying on engine diagnostics need role refs valid.
- The torture fixtures (`webapp/fixtures/`) are the render-proof corpus; `gen_run.py`'s doc is
  the only one that runs against FakeLab.
