# Experiment Studio — UI improvements (W11)

**Status:** design, user-settled 2026-07-18
**Target:** `experiment-studio` 0.8.0 (`main` @ `3f32ab1`), W1–W10 shipped
**Predecessors:** `2026-07-17-experiment-studio-ui-audit-design.md` (the audit workflow),
`2026-07-17-experiment-studio-ui-fixes-design.md` (W10, the audit's 24 findings)
**Source of findings:** `docs/ui-improvements/improvements.md` — six defects found by hand
against 0.8.0, with screenshots, after W10 shipped.

---

## 1. Problem

W10 closed all 24 findings of the automated + rubric audit. The user then used the Builder by
hand and immediately found six more defects. That is the interesting fact about this increment:
**the audit's two tracks were structurally blind to most of what a user hits in five minutes of
real editing.**

Track A measured boundaries — clipped overflow, contrast, hit-target size. Track B judged static
screenshots against a rubric. Neither could see:

- a decoration that is *technically* painted correctly but reads as a rendering artifact (#1),
- nine buttons in a row with no grouping (#2),
- a field that holds a paragraph but is one line tall (#4),
- a panel that wastes 800px of vertical space (#5a),
- a popover that never closes (#6) — because nothing in a *static screenshot* is un-dismissable.

Only #3 (misalignment) is the kind of defect the probe could in principle have caught, and it
did not, because the probe had no rule for "sibling controls disagree about height."

So this increment has two deliverables. The obvious one is fixing the six findings. The
load-bearing one is **fixing the three shared causes underneath them**, because five of the six
are symptoms of defects that recur at sites the user has not looked at yet.

### 1.1 The three shared causes

**C-A. There is no control-height token.** Four independent height scales coexist:

| Source | Class | Rendered height |
|---|---|---|
| `ui/IconButton.tsx:10` | `h-6 w-6` | 24px (pinned) |
| `builder/fields.tsx:8` `inputClass` | `px-1.5 py-0.5 text-xs` + border | ~22px |
| `builder/Toolbar.tsx:49` `buttonClass` | `px-2 py-1 text-xs` + border | ~26px |
| ad-hoc add-buttons (`bg-slate-200 px-2 py-0.5`, no border) | — | ~20px |

Finding #3 is one visible consequence. The sweep found **eleven more** (§4.3, C1–C11),
including two rows whose height *changes* when entering rename mode, and the Toolbar's own name
field sitting 4px shorter than every button beside it.

**C-B. The scroll shadow is a `background`, not an overlay.** `index.css:18` paints the fade
via `background:` on the scroll container. Backgrounds render *behind* child boxes, so the white
block cards paint over it and the fade survives only in the gutters between them. This is
finding #1 exactly, and it is why it reads as an artifact: a gradient that appears in the gaps
between cards and nowhere else is indistinguishable from a rendering bug. **No amount of tuning
the gradient fixes this** — as long as it is a background it cannot cover inner elements.

**C-C. Rigid 50/50 branch arms plus nested scrollers.** `Canvas.tsx:336,340` give both branch
arms `min-w-48 flex-1`, so an empty ELSE arm holding one small button claims half the card while
the THEN arm's nested content scrolls inside a cramped box (`overflow-x-auto`, added in W10 to
fix audit finding F11). Finding #5b is the user seeing both halves of this at once: wasted space
on the right, hidden content on the left.

### 1.2 What is narrower than expected

Two findings asked "check for similar problems before fixing" and the answer was *fewer than
feared*:

- **#6 has no true siblings.** The expression popover is the **only** absolutely-positioned
  floating overlay in the app (a grep for `absolute|fixed inset|z-10|z-20|z-50` across every
  `.tsx` returns one hit). The one close analogue is `StreamIntoPicker`'s inline "new stream"
  mode, which is worse — once opened it has *no* exit at all, not even Escape.
- **`run/InputDialog.tsx` must stay non-dismissable.** Its `onCancel` preventDefault is
  deliberate and documented: the run is parked on that prompt. It is listed here so a future
  reader does not "fix" it.

---

## 2. Scope

**In:** the Builder tab — Canvas, Inspector, Toolbar, Palette, Roles/Streams panels, and the
shared `src/ui/` primitives. The six findings plus every site the three sweeps found sharing
their cause.

**Out:** Devices/Run/Records tabs except where they consume a changed shared primitive
(`RecordsTable`'s rename cell adopts the control token; nothing else changes). No new features.
No backend change. The engine, the doc schema, and the wire format are untouched — this
increment changes only how the existing document is rendered and edited.

**Explicitly out:** the "focus/zoom into a subtree" idea raised while settling #5b. It is a
feature, not a layout fix, and §5.2's scope switcher already covers the underlying need.

---

## 3. Settled decisions

Presented with options 2026-07-18; these are the user's answers.

| # | Question | Settled |
|---|---|---|
| 1 | Scroll-fade affordance | **Overlay fade, per-edge, conditional.** The fade appears at an edge *only* while more content exists that way. No chevron buttons — the conditional fade *is* the signal. |
| 2 | Toolbar grouping | **Spacing + dividers.** All nine buttons stay visible; tighter gap within a group, thin divider between groups. No overflow menu, no per-button icons. |
| 3 | Branch width (#5b) | **Arms size to content + single outer scroller.** Nested containers stop clipping; the canvas becomes the one horizontal scroller. |
| 4 | Long text fields | **Auto-grow textareas.** Grow with content to a cap, then scroll internally. |

Two calls made autonomously and accepted:

- **One increment (W11)**, not a split. #5b carries the most risk (§7) but is coupled to #1 —
  both concern the same scroll containers — and splitting them would mean touching
  `ParallelLanes`/`BranchLanes` twice.
- **Commit the capture harness** under `webapp/frontend/tools/` rather than leaving it in
  scratchpad as the audit did (§6.2).

### 3.1 Why no chevrons (recording a rejected option)

The recommended option paired the overlay fade with edge chevron buttons that scroll on click.
The user narrowed it to the fade alone, conditional per edge. The consequence to accept: the
affordance is *passive* — it signals that content continues but is not itself a click target.
This matches the existing design's intent (the current CSS already tries to be per-edge
conditional via `background-attachment: local`) and keeps the lane strips visually quiet.

**Implementation consequence:** the `local`-attachment trick cannot be reproduced by an overlay,
because an overlay does not scroll with content. Per-edge conditionality must therefore be
computed from scroll position in JS. This is the single reason `ScrollX` needs state at all.

---

## 4. Design

### 4.1 New shared primitives (`src/ui/`)

The repo's vitest runs in **node env — no jsdom, no component rendering** (frontend
`CLAUDE.md`). Every primitive below is therefore split into a *pure function holding the
decision* and a *thin component holding the wiring*. The pure half is unit-tested; the wired
half is verified by the capture harness (§6.2). This is not ceremony: it is the only way this
repo can test any of this logic at all.

| File | Pure part | Component part |
|---|---|---|
| `ui/controls.ts` | `controlClass(opts)` → class string | — (consumed by every field/button) |
| `ui/autoGrow.ts` + `ui/AutoGrowTextArea.tsx` | `autoGrowHeight({scrollHeight, lineHeight, maxLines})` → `{height, overflow}` | sets the measured height in a layout effect |
| `ui/useDismissable.ts` | `shouldDismiss(event, {insideRef})` → boolean | registers `pointerdown` + `keydown` while open |
| `ui/scrollEdges.ts` + `ui/ScrollX.tsx` | `scrollEdges({scrollLeft, scrollWidth, clientWidth})` → `{atStart, atEnd, overflowing}` | renders the two fade overlays |

**`controls.ts` — the control-height token.** One exported height (`h-6`, 24px, matching the
`IconButton` contract W10 already established) plus padding/border that every input, select, and
inline button adopts. This is deliberately the *same* 24px as `IconButton` so that an icon
button beside a text field is flush by construction rather than by coincidence.

**`ScrollX.tsx`.** A `relative` wrapper around an `overflow-x-auto` strip, rendering up to two
`pointer-events-none absolute inset-y-0 w-10 z-10` gradient overlays. Because they are
overlays, they paint **above** the block cards — which is the entire fix for #1. Each is
rendered only when `scrollEdges` says content continues that way, per §3. Scroll position is
read on `scroll` and on `ResizeObserver`, both passive.

`index.css`'s `scroll-x-shadow` utility is **deleted**, not kept alongside — leaving a broken
background-based fade in the stylesheet is how it comes back.

### 4.2 Per-finding changes

**#1 — overflow gradient.** `ParallelLanes` and `BranchLanes` wrap their strips in `ScrollX`.
Utility deleted.

**#2 — toolbar grouping.** `Toolbar.tsx`'s action row becomes three `<div>` groups separated by
`<span aria-hidden className="h-4 w-px bg-slate-200">` dividers: **history** (Undo, Redo) ·
**document** (New, Load, Save, Save as, Duplicate) · **transfer** (Export, Import). `gap-1`
within, `gap-3` between. Costs no extra width. The name field adopts the control token, fixing
C11 (it currently sits 4px shorter than every button beside it).

**#3 — alignment.** Three distinct fixes:

- `+ add else` (`Canvas.tsx:342`) becomes a **full-width dashed block** carrying a real
  `<p>else</p>` header matching the THEN arm's, replacing the hand-tuned `mt-4` that stood in
  for that missing header. Full width is what makes it read as "this adds a block here", per the
  user's own suggestion.
- `+ lane` (`Canvas.tsx:310`) drops `self-center` (which opts out of the container's
  `items-stretch`, so it drifts further off-centre the taller the lanes get) and adopts the
  lane's `min-w-48` floor.
- The `ƒ` button (`fields.tsx:159`) becomes `<IconButton icon={SquareFunction} label="Expression
  help">`. This fixes three things at once: the raw glyph (banned by frontend `CLAUDE.md`), the
  missing `aria-label`, and the height mismatch (it currently has `px-1` and **no vertical
  padding at all**). `Inspector.tsx:477` already renders this exact semantic correctly with the
  same icon — the two renderings are unified on the correct one.

**#4 — long text.** `AutoGrowTextArea` replaces the single-line input at all ten sites:
`prompt`, abort/alarm `message`, catalog `string` params, and the six expression fields that all
share `ExpressionInput`.

Expression fields carry an extra constraint: the grammar is single-line, so the textarea
**strips newlines on input** and **Enter still commits** (rather than inserting a newline).
Escape still reverts, blur still commits. Soft wrapping is what gives long expressions full
visibility — no newline ever enters the value.

**#5a — Inspector layout.** The `<aside>` becomes `flex flex-col`; `DocProperties` and
`GroupProperties` become `flex flex-1 flex-col min-h-0`, with the description row `flex-1` and
the stats + "Select a block…" lines pinned to the bottom via `mt-auto`. The description grows
into the free space and scrolls past it.

**#5b — branch width.** Arms change from `min-w-48 flex-1` — which is `flex: 1 1 0%`, a hard
equal split regardless of content — to `flex: 0 1 auto` with the `min-w-48` floor retained, so
an arm's width follows what it holds and a light arm no longer claims half the card. Nested
`overflow-x-auto` is removed from `ParallelLanes`/`BranchLanes`; the Canvas keeps its
`overflow-auto` and becomes the single horizontal scroller, with the block lists inside it
sizing to content (`w-max`) instead of being capped at the viewport. Inner content is then never
hidden inside a nested box — it is always reachable by scrolling the canvas.

The `min-w-0` on `BlockView` (`Canvas.tsx:187`) **stays**. It was added for audit finding F11 to
stop a card forcing its lane wide, and it remains correct: cards still must shrink to their
container. What changes is that the container is no longer a clipping scroller.

**#6 — dismissal.** `useDismissable` lands on `ExpressionInput`'s popover and on
`StreamIntoPicker`'s inline adding mode. `Canvas.tsx`'s group creator already has Escape and
gains the outside-click half.

### 4.3 The eleven bonus sites (cause C-A)

Fixed by adopting `controls.ts`; listed so the plan can assert each one:

| # | Site | Defect |
|---|---|---|
| C1 | `Inspector.tsx:464` | select ~22px beside a 24px `IconButton`; `px-1` vs `inputClass`'s `px-1.5` |
| C2 | `Inspector.tsx:428` | unknown-param row: bare 16px span beside a 24px `IconButton` |
| C3 | `StreamsPanel.tsx:141` | borderless add button, 2px short of its inputs |
| C4 | `StreamsPanel.tsx:60` | **four** different control heights in one row; lone `border-slate-200` input |
| C5 | `StreamsPanel.tsx:80` | row height *changes* entering rename mode |
| C6 | `RolesPanel.tsx:68` | same latent bug as C5 |
| C7 | `Palette.tsx:89` | borderless button; `px-2 py-1` where the equivalent Streams form uses `px-1 py-0.5` |
| C8 | `StreamIntoPicker.tsx:48` | borderless button beside bordered inputs |
| C9 | `Canvas.tsx:291,353` | lane/else header height changes as the lane fills or empties |
| C10 | `Canvas.tsx:192` | container blocks get a leading chevron, non-containers do not → label column starts ~28px further left on a `wait` card than a `serial` card in the same list |
| C11 | `Toolbar.tsx:163` | name field ~4px shorter than every button beside it |
| A4 | `Inspector.tsx:656` | `+ add else lane`: content-width in a full-width stack; literal `"+"` string where Canvas uses the Lucide icon; `text-slate-500` where `CLAUDE.md` mandates `text-caption` |

C10 is the one that is *not* a height problem — it is a horizontal gutter problem with the same
root (no shared control sizing). It is fixed by reserving the chevron's width on non-container
cards.

---

## 5. Testing

**Pure logic (vitest, node env).** `autoGrowHeight` (grow, cap, overflow flip), `scrollEdges`
(both edges, start, end, non-overflowing), `shouldDismiss` (inside/outside/Escape), and
expression newline-stripping. These four are the increment's real logic; everything else is
class strings.

**A probe rule for cause C-A.** The audit probe had no rule for "sibling controls disagree about
height," which is why it missed all twelve C-sites. Add one: within a flex row, flag controls
whose rendered heights differ by more than 1px. **This rule must be mutation-verified** — it is
planted against a known-bad row before the fixes land, per the audit spec's rule that a probe
which has never gone red proves nothing.

**Regression guard for #5b.** The committed torture fixture
(`webapp/fixtures/ui-audit-torture.json`) exists for exactly this. F11's check is mechanical —
`scrollWidth > clientWidth` under `overflow: hidden` means content is unreachable — so removing
nested scrollers is verified by fact, not judgment.

**Gates.** `npm run lint && npm test && npm run build` in `webapp/frontend`.

---

## 6. Verification

### 6.1 Evidence

Re-shoot the eight states behind the user's screenshots at 1024/1440/1920, plus the audit's
existing drivers, and commit before/after pairs to `docs/ui-improvements/after/`. A finding is
closed when its after-shot shows the fix at all three widths — not when the diff looks right.

### 6.2 The capture harness becomes a committed tool

The audit's `probe.mjs` / `capture.mjs` lived in scratchpad and were lost. The user audits this
UI by hand and will do so again; a throwaway harness makes that manual every time. Move both
under `webapp/frontend/tools/` with the self-test, so the next hand-audit starts from a working
probe rather than rebuilding one.

### 6.3 Preprod

The user has authorised real-world testing on lab-bridge preprod (`ssh khamit@111.88.145.138`,
`windows_arm64_test_client` reserved for this work). Deploy path: build and push the Studio
image, bump `studio_image` in `lab_devices_server`'s `compose/pins.yaml` (currently pinned
`0.8.0`), then `task deploy`.

Preprod is where #5b and #4 must be confirmed, because both depend on real content: a real
morbidostat doc has the deep nesting that made content unreachable, and the long prompts that
made a one-line field unusable. A synthetic fixture can be made to pass either fix by accident.

---

## 7. Risks

**F11 regression (#5b) — the one that matters.** Nested `overflow-x-auto` was added in W10 *to
fix* cards painting over a sibling's action icons. Removing it re-opens that door. The
mitigation is that F11's condition is mechanically checkable against the committed torture
fixture, so the regression cannot pass silently — but this is the change most likely to need a
second pass, and it is why §6.3 requires preprod confirmation on a real doc.

**Auto-grow and the Inspector's fixed width.** `AutoGrowTextArea` in a `w-80` panel makes long
values *tall*. The cap plus internal scroll bounds this, but the cap is a judgment call and may
need tuning against a real morbidostat doc rather than a fixture.

**Breadth.** Twelve bonus sites across six files is a wide diff for a "fix six things"
increment. It is justified because they share one cause and one fix, but each C-site needs its
own assertion in the plan — a shared token that silently misses four sites leaves the app
*more* inconsistent than before, not less.

---

## 8. Deliverables

- `webapp/frontend/src/ui/`: `controls.ts`, `autoGrow.ts`, `AutoGrowTextArea.tsx`,
  `useDismissable.ts`, `scrollEdges.ts`, `ScrollX.tsx` + tests for the four pure modules
- Changed: `index.css` (utility deleted), `builder/{Canvas,Inspector,Toolbar,fields,Palette,
  RolesPanel,StreamsPanel,StreamIntoPicker}.tsx`, `records/RecordsTable.tsx`
- `webapp/frontend/tools/`: capture + probe harness with self-test, incl. the new height rule
- `docs/ui-improvements/after/`: before/after evidence at three widths
- Frontend `CLAUDE.md`: the control-height token documented as a project rule, alongside the
  existing icon and text-colour rules
