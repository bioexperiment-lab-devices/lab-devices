# Experiment Studio — UI improvements, round 2 (W12)

**Date:** 2026-07-18
**Status:** approved (forks user-settled 2026-07-18)
**Input:** `docs/ui-improvements-2/improvements.md` — four issues found by hand against v0.8.1, after W11 closed the previous six.
**Scope:** frontend-only. No backend change, no document-format change, no store-API change to roles/streams/groups.

## 1. Findings and root causes

| # | Finding | Root cause |
|---|---------|-----------|
| 1 | Palette/Canvas/Inspector sit in one big box, separated by vertical lines | `BuilderTab.tsx` wraps all three in a single `rounded-lg border` container with internal `border-r`/`border-l`. Every other surface in the app (Toolbar, ProblemsPanel, the other tabs) already uses freestanding boxes; Builder is the outlier. |
| 2 | Roles add-form overflows the palette horizontally (`screenshots/1.png`); roles section scales badly | The form is one flex row of `name input + type select + Add` inside the 256px palette — a long device-type name pushes past the edge. Separately, every role repeats its full verb-chip list, so N same-type roles render N identical chip sets. |
| 3 | Two-row header wastes vertical space | `TabShell.tsx`: row 1 = title + platform info, row 2 = pill nav. `BuilderTab`'s `h-[calc(100vh-9rem)]` hard-codes that header height. |
| 4 | Parallel lanes can't be created empty; deleting the Serial inside destroys the lane | A lane **is** a child block of the Parallel node. `+ lane` / a fresh Parallel seed lanes as empty `serial` nodes, and the UI renders that serial as a full Serial card inside the lane box — the "wrapper" is the lane itself. **Other elements checked (per the finding's ask): Branch then/else, Loop body, For-each body are genuine block lists that can be empty — Parallel is the only element with this defect.** |

## 2. User-settled forks (2026-07-18 — don't re-litigate)

- **F1 role actions:** rename/delete = one pencil + one cross per device-type block, acting on the *selected* role, at the end of the badge row. The `Manage roles` section is **removed**.
- **F2 header tabs:** underline style (browser-tab look), active underline meeting the header's bottom border — not inline pills.
- **F3 lanes:** unwrap **all** serial-under-parallel children (not only "plain" ones; not the keep-card variant). Lane header = the serial's select/drag handle and shows its label/markers. Non-serial drops at lane level auto-wrap in a fresh plain serial.

## 3. Design

### 3.1 Separate panel boxes (finding 1)

`BuilderTab`'s middle row becomes `flex min-h-0 flex-1 gap-2`; the shared wrapper box is deleted. Each panel gets its own `rounded-lg border border-slate-200` box:

- **Palette:** `w-64 shrink-0`, keeps `bg-slate-50`, own `overflow-y-auto`, drops `border-r`.
- **Canvas:** the existing `relative min-w-0 flex-1` wrapper gains `rounded-lg border border-slate-200 overflow-hidden` so the slate-100 scroller clips to the rounded corners. Scroll fades are absolute overlays inside that wrapper and are unaffected.
- **Inspector:** `w-80 shrink-0`, keeps `bg-slate-50`, drops `border-l`.

### 3.2 Single-row header + height refactor (finding 3)

`TabShell` header becomes one row: **title → underline tabs → right-aligned platform info** (lab pill + status line). Tab styling: `border-b-2 border-transparent`, active `border-slate-900 text-slate-900`, inactive `text-slate-600 hover:text-slate-900`; tabs bottom-aligned so the active underline meets the header's `border-b`. The `1 Devices`-style accessible names (mono digit + label) are **kept** — the probe/preprod recipes key off them. The status line gets `truncate` + `title` so a long health string cannot wrap the row at 1024px.

Height refactor rides along: shell root becomes `h-screen flex flex-col` (was `min-h-screen`), `main` becomes `flex-1 min-h-0 overflow-y-auto p-6`, and BuilderTab's `h-[calc(100vh-9rem)]` becomes `h-full`. Consequence: Devices/Run/Records scroll inside `main` rather than the page — visually identical, and the Builder's height can no longer silently break when the header changes.

### 3.3 Roles grouped by device type (finding 2)

The palette's Roles section is rebuilt as **one sub-block per device type**: every type in the catalog, in catalog order, plus one amber-flagged block per unknown type that appears in the doc's roles (replaces today's per-role `unknown device type` warning). Per block:

- **Header:** the device-type name.
- **Role badges as radio buttons.** Selected badge styled like the groups panel's active scope (`bg-blue-100 text-blue-700`). Selection is *view state, local to the block* (never persisted, never in undo — same family as `selectedUid`/`scope`): defaults to the first role, follows a rename, falls back to first on delete.
- **Selected-role actions:** pencil + cross `IconButton`s at the end of the badge row (F1). Pencil swaps the selected badge for the existing inline-rename input (Enter commits, Esc cancels; cascade-rename in one undo step — `renameRole` unchanged). Cross calls `removeRole` and shows the existing refusal reason inline when the role is referenced.
- **Verb chips rendered once, for the selected role only.** Drag payload = `{source:'palette-verb', role: <selected>, verb, verbKind}` — unchanged shape, so the verb-drop path needs no change.
- **`+ add role`** inline button revealing `name input + Add` (Esc or blur-empty collapses). No type select — the block *is* the type. This structurally removes the overflow in `screenshots/1.png`.
- **No roles for the type:** no chips, a one-line hint, the `+ add role` affordance.

Removed: the `Manage roles` section and `RolesPanel.tsx`. Retargeted: the ProblemsPanel jump (`focusedRole`) now selects the role in its type block, scrolls it into view, and applies the amber ring highlight to the badge.

A pure helper (e.g. `builder/roleGroups.ts`) computes the grouped structure — `(roles, catalog) → ordered [{type, known, roles[]}]` — so ordering, unknown-type handling, and selection fallback are node-testable.

### 3.4 Serial-under-parallel renders as the lane (finding 4)

`ParallelLanes` branches on the lane child's kind:

- **`serial` child (the seeded/normal case):** the lane box renders the serial's `children` directly via `BlockList parentUid={lane.uid} slot="children"` — no Serial card chrome. The `lane n` header row becomes the serial's handle: click selects it (Inspector still edits label / on_error / retry), drag moves/reorders the lane, and the header shows the serial's label and retry/tolerated markers when present. The empty-lane ✕ keeps its current rule (visible only when the lane is empty). An empty lane shows a drop hint. **Emptying a lane never destroys it.** Explicit deletion still exists: lane ✕, or select-header + Delete.
- **Non-serial child** (imported/legacy docs): rendered exactly as today — lane box + `BlockView` card. Such a lane holds that one block.

**Lane-level drops auto-wrap (F3):** any insert or move landing on a parallel's `children` slot — palette chip, canvas move, either horizontal DropSlot — wraps a non-serial block in a fresh plain serial; a serial becomes the lane directly. The wrap lives in the **pure tree layer** (`tree.ts`'s insert/move path, guarded to parallel `children` targets), not in `onDragEnd`: both `insertBlock` and `moveBlock` get it through the one code path, each remains a single store action and therefore a single zundo snapshot (one undo restores the pre-drop shape), and duplicating a bare-block lane wraps the copy for free. Every other slot's semantics are untouched.

`docToTree`/`treeToDoc` are **untouched** — open+save stays a byte no-op. A freshly dragged Parallel (two empty serials, S1) now shows two genuinely empty lanes, which serves "parallelism immediately visible" better than two empty cards. `gapAfterEligible` is already correct for unwrapped lanes: blocks inside a lane have `parentKind === 'serial'`.

## 4. Out of scope

- Full lane-strip redesign for many lanes (audit note "S1 worth revisiting" — 8 lanes overflow at every width). Canvas single-scroller handling from W11 stands.
- `ScopeSwitcher` intrinsic-width cosmetic issue (known-open from W11).
- Backend, doc format, roles/streams/groups store APIs.
- Preprod pin bump mechanics (separate lab-bridge two-PR recipe; currently blocked by the dirty `lab_devices_server` working tree).

## 5. Verification

- **Pure logic → vitest (node-env rule respected):** the lane-drop wrap helper (non-serial wraps, serial passes through, non-parallel slots untouched); `roleGroups` (catalog order, unknown types, selection fallback semantics as pure data).
- **DOM truth → committed W11 probe harness:** `npm run capture` + probe across the standard state/viewport matrix; `sibling-height-mismatch` and clip rules stay at **0**; screenshots at 1024/1440/1920 land in `docs/ui-improvements-2/after/`.
- **Manual/scripted spot checks:** verb-chip drag carries the *selected* role; lane header drag/select/label round-trip; header at 1024 with a long status line; morbidostat + torture fixtures still open and render. Both fixtures exercise the non-serial lane path and must keep rendering those lanes as cards (verified 2026-07-18: torture has an 8-serial-lane parallel plus `loop`-as-lane; morbidostat has `command`-as-lane and `for_each`-as-lane parallels).
- **Gates:** full frontend + backend suites before PR (backend untouched but run anyway).
- **Release:** ships as `feat` via release-please.
