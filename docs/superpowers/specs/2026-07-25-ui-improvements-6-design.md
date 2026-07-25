# Experiment Studio UI improvements 6 — design

**Date:** 2026-07-25
**Status:** approved
**Scope:** seven Builder UI defects reported after PR #81 (UI improvements 5), plus a
demo fixture that makes the canvas-geometry ones reproducible.

Predecessors: `2026-07-22-ui-improvements-4-design.md`, `2026-07-25-ui-improvements-5-design.md`.
This round continues the lane-geometry work #81 started: #81 fixed the *horizontal*
rule (every construct indents its content by exactly 8px); this one fixes the
*vertical* one.

## 1. The reported defects

1. **Leaf cards carry a 24px empty box.** `Canvas.tsx` renders
   `<span aria-hidden className="h-6 w-6 shrink-0" />` on every leaf so its icon sits in
   the same column as a container's collapse chevron. It buys alignment nobody asked for
   and costs 24px of horizontal space on every leaf card.
2. **The Constants add form puts `Add` in the wrong row.** It sits beside `name` on row 1,
   before the value and unit have been typed. It should be the last control the user
   reaches: name / expression / unit + Add.
3. **"drop here" is not sized or placed like a chip.** Measured on the real app: a leaf
   card is 34px and a vertical `DropSlot` occupies 12px, so a lane's first card starts
   40px below the lane's top edge (4px lane padding + 24px label row + 12px slot). The
   empty-lane hint is 42px tall and starts at 28px — 12px too high and 8px too tall — and
   it does not grow when a sibling lane is taller.
4. **"+ lane" and "+ add else" are not placed like "drop here" either.** "+ lane" spans
   the parallel's whole interior including the `LANE N` label row; "+ add else" is
   full-arm-width and sits at the top of the else arm.
5. **Role controls are detached from the role.** Rename/delete/colour live in a
   right-aligned cluster below the badge row and act on whichever badge is selected — the
   connection is invisible. The colour swatch inside a badge is decorative.
6. **Roles and verb chips run together.** Within a device-type card there is no visual
   break between the role badges and the verbs you can drag.
7. **A long stream name makes the palette scroll horizontally.** Measured: adding
   `optical_density_channel_three_normalised_long` takes the palette aside from
   `scrollWidth` 254 → 437 against a `clientWidth` of 254.

## 2. Non-goals

- No change to the Constants *edit* rows (already stacked; only the create form was
  reported).
- No change to drag-and-drop semantics. Slot indices, droppable ids and `canDrop` are
  untouched; only the geometry of the boxes moves.
- No new colours. Every class this design adds is a spacing or layout utility.

## 3. Canvas geometry — one band, three tenants

### 3.1 The rule

A lane, a branch arm, and the column that holds `+ lane` all expose the same **chip
band**: the vertical region a lane's cards occupy, from the first card's top edge to the
last card's bottom edge. It excludes the `LANE N` / `then` / `else` label row and the
12px drop-slot gaps that bracket the cards.

Everything that stands in for cards — the "drop here" hint, `+ lane`, `+ add else` —
fills exactly that band. Because a parallel's lane row is `items-stretch`, the tallest
lane sets the row's height, so an empty sibling's hint spans the full band by
construction rather than by measurement.

### 3.2 Tokens

`src/builder/laneLayout.ts` already owns the lane-spacing arithmetic and has a test
pinning it to `CONTROL_H_PX`. The new tokens go there, as literals (Tailwind 4 scans
source text — a computed class compiles to no CSS).

| Token | Value | Stands for |
|---|---|---|
| `CHIP_H_PX` | `34` | `CONTROL_H_PX` (24) + header `py-1` (8) + 1px border ×2 |
| `CHIP_MIN_H` | `min-h-8.5` | a band is never shorter than one chip |
| `CHIP_GAP` | `my-3` | the 12px a vertical `DropSlot` occupies above and below a chip |
| `CHIP_GAP_PX` | `12` | `DropSlot`'s `h-2` box (8) + `my-0.5` margins (2 × 2) |
| `LANE_LABEL_H` | `h-6` | the `LANE N` / `then` / `else` row, one `CONTROL_H` tall |

`laneLayout.test.ts` gains assertions that `CHIP_H_PX` derives from `CONTROL_H_PX` and
that `CHIP_MIN_H` / `CHIP_GAP` carry those pixel values, so the two modules cannot drift.
Its `px()` helper must accept a fractional suffix (`8.5`).

**Verify before relying on it:** `min-h-8.5` must actually emit CSS under Tailwind 4's
dynamic spacing scale. A class that compiles to nothing is this codebase's recurring
trap (frontend/CLAUDE.md). If it does not, use `min-h-[34px]` — arbitrary values are
banned for *colour*, not for spacing, and the token has one home either way.

### 3.3 The stretch chain

For `flex-1` to mean anything the chain from the lane row down to the filler must all
stretch:

- `ParallelLanes` row — `flex items-stretch`, already correct.
- `BranchLanes` row — `flex gap-2`, already `align-items: stretch` by default.
- `Lane` — currently `display: block`. Becomes `flex flex-col`, with the label row fixed
  at `LANE_LABEL_H` and `BlockList` taking the rest.
- Branch arms — same change.
- `BlockList` — gains `min-h-0 flex-1` on its root. This is inert in the block parents it
  also has (a loop's body, the canvas root): `flex-basis` does not apply to a block-level
  child of a block-level box.

When a lane is populated and shorter than its tallest sibling, the leftover space lands
at the bottom of the column (`justify-content: flex-start`), so cards stay top-aligned
and the band still starts at the same y in every lane.

### 3.4 "drop here"

`DropSlot`'s `hint` branch drops `py-3` and `mx-2` and takes `flex-1 ${CHIP_GAP}
${CHIP_MIN_H}` plus the padding needed to centre its text. The 12px gaps come from
`CHIP_GAP` rather than from a preceding sibling, because the hint *is* the leading
`DropSlot` (index 0) — there is no earlier slot to supply them. Adjacent margins do not
collapse inside a flex container, so `12 + 34 + 12` reproduces a one-card lane's
`slot + card + slot` exactly.

The horizontal hint (a parallel whose lanes have all been deleted) uses the `ChipBand`
wrapper from §3.5 so it aligns with `+ lane`, which is the only thing beside it.

### 3.5 `+ lane` and `+ add else`

Both are fit-width, left-aligned, and fill the band top to bottom.

`+ add else` already lives inside an arm, so it needs only the band: a
`${CHIP_GAP} flex min-h-0 flex-1 items-stretch` row wrapper with
`inlineButtonClass({ subtle: true, stretch: true })` inside. In a **row**, `self-stretch`
gives full height and content width; the button must not carry `width: 'w-full'`. This
deletes the `<div className="my-0.5 h-2" />` spacer in `BranchLanes` and the
"if DropSlot's vertical size changes, change this to match" comment above it — the token
replaces the coupling that comment was warning about.

`+ lane` sits outside any lane, so it gets a small `ChipBand` component that reproduces
lane geometry:

```
ChipBand = LANE_PAD ─ invisible LANE_LABEL_H row ─ CHIP_GAP band (flex, min-h-0, flex-1)
```

It loses `self-stretch my-1`. Its horizontal air is unchanged: the divider `DropSlot`
before it, `mr-2` after it.

### 3.6 The leaf spacer

`Canvas.tsx`'s `<span aria-hidden className="h-6 w-6 shrink-0" />` is deleted, together
with the `isContainer` ternary that produced it. Leaf icons stop sharing a column with
container chevrons; that alignment is the cost, and it was accepted deliberately.

## 4. Palette

### 4.1 Constants add form

Row order becomes name / expression + ƒ / unit + Add. The name input goes full-width now
that `Add` has left its row. Enter in either the name or the unit input still commits,
unchanged.

### 4.2 Role badge controls

The active badge stops being a `<button>` — a button cannot contain buttons — and becomes
a container laid out like one (`badgeClass`, minus the click handler, applied to a
`<div>`), holding:

- the colour swatch as a `<button>`, which opens the existing `RoleColorPicker` popover;
- the role name;
- `✎` rename and `✕` delete `IconButton`s.

Inactive badges are unchanged: a plain `<button>` carrying a swatch and a name, whose
click selects. The standalone 🎨 / ✎ / ✕ cluster below the badge row is deleted.

Details that decide the shape:

- A role with **no colour** (an explicit `clearColor`, distinct from an absent override —
  see `roleColorStore.ts`) has no swatch to click. The *active* badge therefore always
  renders a swatch slot: a filled square when the role has a colour, a hollow outlined
  ring when it does not. Inactive colourless badges render nothing, as today.
- Group-param `{hole}` badges are read-only references authored in the group's Params
  panel. They never get controls, matching the current `selectedIsParam` guard.
- The badge must carry `min-w-0` with the name in a `truncate` span that owns the
  `title`, or a long role name pushes the 256px palette into horizontal scroll — the same
  failure §4.4 fixes for streams. `badgeClass` already sets `min-w-0 max-w-full`.
- The rename input still replaces the badge in place, as today.

### 4.3 Device-type hairline

A `border-t border-slate-200` above the verb-chip row inside `RoleTypeBlock`. The verb
row only renders when a role is selected, and a selection implies the type has roles, so
"if any roles exist for this type" and "the chip row is rendering" are the same
condition — no extra guard.

### 4.4 Stream name width

The overflow comes from the name *button*, not from either input: both inputs are already
`w-24`, while `inlineButtonClass()` bakes `shrink-0` and sizes to its content.

`inlineButtonClass` gains a `shrinkable` option that **selects** `min-w-0 max-w-full` in
place of `shrink-0` (selecting, never appending — equal-specificity utilities in one
`@layer utilities` block are decided by compiled order, per frontend/CLAUDE.md). The
caller wraps the name in a `truncate` span carrying the `title`, which is also what the
probe's `truncate-without-title` rule requires.

Capping the input's `maxLength` instead was rejected: names arrive from imported docs
too, so the render is what has to be bounded.

## 5. Demo fixture

`webapp/fixtures/ui-improvements-6.json`, wired into `tools/capture.mjs` as a new state
so every future round re-probes this geometry.

Verified against the running backend that the shapes it needs actually validate: empty
serial lanes, empty loop bodies and `else: []` all pass `/api/validate`; `else: null` is a
Studio-only state expressed by **omitting** the key (the schema rejects a literal null).

Coverage:

| Edge case | Why |
|---|---|
| parallel: 1-chip lane │ empty lane │ tall lane | the core "hint respects the tallest lane" case |
| nested parallel inside the tall lane, with its own empty lane | the band must work at depth |
| branch, `then` populated, `else` absent | `+ add else` band |
| branch, `then` populated, `else` empty | else-arm "drop here" band |
| loop with an empty body | a band with no sibling to stretch to → one chip tall |
| alarm, abort, wait, operator_input, measure, command, compute, record | leaf spacer removal on every leaf kind |
| long stream name | palette horizontal overflow |
| long role name | badge truncation with controls inside |
| a colourless role | the hollow-ring colour trigger |
| a device type with zero roles | the hairline's absent case |
| constants with and without units | the reordered add form beside real rows |

## 6. Verification

- `npm run lint && npm test && npm run build` (frontend gates).
- `npm run capture` in both themes against the new fixture:
  - R4 `sibling-height-mismatch` covers the rebuilt badge row (swatch + name + two icons).
  - R2 `truncate-without-title` covers the stream name and the role name.
  - R5 `text-contrast` and R6 `control-wrapper-gap` should be unaffected; a regression in
    either means something in this design touched paint or textarea metrics, which it
    should not.
- Unit tests are pure-function only (vitest, node env — no jsdom): `laneLayout.test.ts`
  for the new tokens, `controls.test.ts` for `shrinkable`. The badge restructure and the
  band layout are verified by capture, not by unit test.
- Before/after screenshots reviewed locally by the user before merge.

## 7. Risks

- **`min-h-8.5` may not compile.** Mitigated by verifying the emitted CSS before relying
  on it; fallback `min-h-[34px]`. §3.2.
- **The active badge is now the densest row in a 256px column** — swatch, name, two icons.
  A long role name is the case to watch; `min-w-0` + truncate is the guard, and the
  fixture exercises it.
- **Removing the leaf spacer changes every leaf card's left edge**, so any capture-based
  diff will be noisy this round. Expected, not a regression.
