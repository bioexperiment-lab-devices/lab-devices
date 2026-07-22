# UI Improvements 4 — design

Fixes for eleven UI issues found in Experiment Studio (webapp/frontend),
catalogued in `docs/ui-improvements-4/improvements.md` with screenshots. All
work happens on the `feat/ui-improvements-4` worktree.

Each fix below names its root cause (file:line) and the concrete change. Two
design decisions were confirmed with the user up front:

- **Separators (#10):** plain neutral slate hairlines (`bg-slate-200`, no
  rounded corners), matching the Toolbar/file-menu reference — not the current
  per-construct tint.
- **Constants form (#8/#9):** a shared **stacked** layout (name row, then a
  full-width expression editor + unit + delete) for both create and edit.

The frontend's standing rules apply throughout (`webapp/frontend/CLAUDE.md`):
control height lives only in `controls.ts`; helper classes *select* one class
per property and are never overridden by concatenation; colours stay in the
state / construct-tint / role-swatch languages; dark theme is a palette remap
(no `dark:` variants); component DOM wiring is verified by the capture probe,
not vitest. Run `npm run capture` after touching any control class.

---

## #1 — Parallel lane controls missing on imported workflows

**Root cause.** `Lane` (`src/builder/Canvas.tsx:451`) renders two structurally
different trees. The `serial` branch (477–542) carries selection, drag,
duplicate, empty-only delete, the fault marker and the diagnostics badge; the
non-`serial` branch (462–474) renders only a static `lane N` label plus
`<BlockView>`. Imported/round-tripped parallels keep their lanes as whatever
kind the JSON declared (`convert.ts:179`), and `wrapAsLane` (`tree.ts:248`) is
only called on in-app inserts — so an imported bare-block lane never becomes
`serial` and lands in the stripped branch. App-added lanes are always `serial`,
which is why the asymmetry only shows on import.

**Fix.** Extract a single `LaneShell` that always renders the lane header
(`LANE N`, label, fault marker, diagnostics badge, **duplicate**, empty-only
**delete**), the selection ring, the drag handle, and the `index > 0`
separator. Both branches use it; only the *body* differs:

- `serial` → `<BlockList parentUid={lane.uid} slot="children" items={lane.children}>`
- any other kind → `<BlockView node={lane}>` (the block keeps its own card + controls)

Delete rule stays "empty-only" (a bare-block lane is never empty, so its `×` is
hidden — it is removed via its inner card's `×` or via select + Delete, exactly
like a populated serial lane). Result: every lane is selectable, draggable and
duplicable regardless of kind. Data model and round-trip fidelity are untouched
(no wrapping on import).

**Verify.** Load `examples/morbidostat.json` (three bare-block lanes) and a
mixed parallel; every lane header shows the duplicate control, selects on click,
and drags. Capture states cover both.

---

## #2 — Left-menu scrollbar renders bold and won't auto-hide

**Root cause.** No scrollbar CSS exists anywhere (`index.css` has none), so every
`overflow-*` container falls back to the thick classic native scrollbar. The
Palette is `overflow-y-auto` (`Palette.tsx:126`), which per spec promotes
`overflow-x` to `auto`; the group-card overflow (#3) then forces a *second*
horizontal bar, compounding the effect.

**Fix.** Add global thin scrollbar styling to `index.css`, applied to the app's
scroll surfaces (Firefox `scrollbar-width: thin` + `scrollbar-color`; WebKit
`::-webkit-scrollbar` thin track/thumb using existing slate tokens so it remaps
in dark mode). Fixing #3 removes the horizontal-overflow trigger. The thin
styled bar addresses the "very bold" complaint on every scroller (Palette,
Inspector, Canvas, dialogs). Note: OS overlay-vs-classic *auto-hide* is OS
controlled and out of our reach; the thin style makes a persistent bar
unobtrusive rather than heavy.

**Verify.** Capture the Palette scrolled; bar is thin in both themes and no
horizontal bar appears.

---

## #3 — Group card content overflows the card

**Root cause.** In `GroupsPanel` (`Palette.tsx:79–113`) the params-signature span
is `ml-1 shrink-0 text-caption` with no `truncate`/`min-w-0`, and the `Chip`
container (`Chip.tsx:24`) has no `overflow-hidden`. A multi-param signature
renders at full intrinsic width and spills past the rounded border, under the
Pencil/X icons.

**Fix.** Make the name + signature share one `min-w-0 truncate` region inside the
chip (full text in `title`), add `overflow-hidden` to the chip so nothing paints
past its rounded box, and keep the Pencil/X icons `shrink-0` outside the chip.
The signature now ellipsizes instead of overflowing.

**Verify.** Capture a group with a long signature (the scope-switcher-long-group
state); text ellipsizes within the card, icons don't overlap, palette gains no
horizontal scrollbar.

---

## #5 — Inconsistent left indentation between block types

**Root cause.** `ContainerBody` gives every interior a uniform `px-2` (8px), but
per-kind bodies add different extra left inset: serial/loop/for_each add none
(8px); branch arms add `px-1` (12px, `Canvas.tsx:571/575`); parallel lanes add a
leading horizontal `DropSlot` (`mx-0.5 w-2`) plus lane `p-1` (~24px). Nested
blocks therefore step in by unequal amounts.

**Fix.** Define one indent unit and make every container's first-child content
start at the same left offset. Concretely: keep `ContainerBody`'s `px-2` as the
single unit; normalize branch arms and parallel lanes so their inner content
aligns to that 8px rather than adding their own extra left inset (the lane/arm
horizontal padding becomes symmetric and the leading drop-slot no longer pushes
lane 0's content deeper than a serial child). Horizontal containers still lay
children side by side — the goal is equal *left inset per nesting level*, so the
visible stepping becomes even. This is done together with #10 (separators as
standalone elements remove the border-needs-padding coupling that caused part of
the divergence).

**Verify.** Capture the nested Loop→Parallel→For-each doc from screenshot 5; each
nesting level steps in by the same amount.

---

## #7 — Expression help / autocomplete popup is clipped

**Root cause.** `CompletionPopup` (`ExpressionEditor.tsx:290`) and `HelpPopover`
(`:332`) are plain `absolute … z-20` children of the editor's `relative`
wrapper. `z-20` cannot escape an ancestor `overflow` clip, so both are clipped by
the narrow `overflow-y-auto` side panels (`w-64` Palette, `w-80` Inspector) and,
at the edge, by the viewport.

**Fix.** Render both popups through `createPortal` to `document.body` with
`position: fixed`, anchored to the editor's measured rect and viewport-clamped —
the exact pattern already used by `RolesSection`'s colour picker
(`RolesSection.tsx:270–311`): measure the trigger/panel rects, flip above when
there's no room below, clamp horizontally to keep both edges ≥ 8px inside the
viewport. Reuse that logic so the two dropdowns float above everything.

**Verify.** Open the help popover from a Constants expression editor in the
`w-64` palette; the `w-72` panel renders fully on-screen, not clipped.

---

## #8 / #9 — Constants create/edit forms inconsistent and edit form broken

**Root cause.** The edit row (`ConstantsPanel.tsx:70–95`) packs name (`shrink-0`)
+ `flex-1` ExpressionEditor + fixed `w-14` unit + `shrink-0` TypeBadge + delete
onto one line inside the 256px palette. The non-shrinking siblings consume the
row, so the `flex-1 min-w-0` editor gets ≈0 width and collapses to its
one-character min-content (the editor's overlay wraps `break-words`), stacking
"3.14" vertically (#9). The create form (`:98–116`) is a different shape entirely
— a plain `<input>` for the value (not an expression editor) and no unit field
(#8).

**Fix.** Give both forms one shared **stacked** layout:

```
name (mono, truncates)                         [× delete]
[ full-width ExpressionEditor (value/expression) ]
[ unit input ]   TypeBadge
```

The ExpressionEditor spans the full panel width (no horizontal competition, so it
no longer collapses), the create form uses the same ExpressionEditor + unit field
as edit, and both commit through the existing `coerceConstantValue`. Create adds
its unit at creation time. Name stays a fixed label (no rename action exists).

**Verify.** Capture the Constants panel with an existing constant and the create
form open; the value editor renders full width (no vertical char-stacking), both
forms have a unit field, and they look identical.

---

## #10 — PR #70 line separators look bad

**Root cause.** Lane/arm separators are a `border-l` drawn on a `rounded` padded
box in construct tint (`Canvas.tsx:465–466, 490–491, 575`). `border-radius`
rounds the stroke's corners, the padding around it differs between lanes
(`p-1` + `DropSlot`) and branch arms (`px-1 pb-1` + `gap-2`), and only one side
of a branch pair carries the border. The clean reference is the Toolbar's
`h-4 w-px bg-slate-200` (`Toolbar.tsx:216, 239`).

**Fix (confirmed: plain slate).** Replace the border-on-box separators with
standalone neutral hairline elements — a full-height `w-px self-stretch
bg-slate-200` between lanes (and between branch arms) so there are no rounded
corners, no tint, and uniform spacing. Remove the leftover `rounded` from the
lane boxes' separator role. Sweep the other section dividers for consistency
where they share this pattern (`Palette.tsx:17`, `InspectorSection.tsx:28`,
`StreamsPanel.tsx:148` already use plain `border-slate-200` full-width rules and
are acceptable as-is; the fix targets the canvas lane/arm dividers that regressed
in #70). Done together with #5.

**Verify.** Capture a Parallel and a Branch; dividers are clean 1px slate lines,
evenly spaced, no rounded corners, both arms symmetric.

---

## #12 — Expression inputs are 20px tall instead of 24px

**Root cause.** The editor's textarea/overlay use `textAreaClass()` (no height
class by design) and the height is set by auto-grow to content: a single line is
`16px` line-height + `4px` py = **20px** (`ExpressionEditor.tsx:89–102`,
`autoGrow.ts:13`). Every other control is `24px` via `controlClass()`'s
`CONTROL_H` (`h-6`), so the editor sits 4px short and trips the probe's
sibling-height rule.

**Fix.** Floor the auto-grow height at the 24px control height. Add an optional
`minHeight` parameter to `autoGrowHeight` (default `lineHeight`, preserving
`AutoGrowTextArea`'s behaviour) and pass `CONTROL_H`'s pixel value (24) from the
ExpressionEditor. Height stays owned by the controls module per CLAUDE.md; a
single-line expression now renders at 24px, multi-line still grows.

**Verify.** `npm run capture`; probe R4 (`sibling-height-mismatch`) passes for
every expression field beside a sibling control.

---

## #13 — Expression validation rejects `{binding}` references

**Root cause.** The client-side live validator runs the parity-pinned tokenizer
(`expr/tokenize.ts`) directly on raw draft text (`analyze.ts:54` →
`parse.ts:51`). That tokenizer has no `{` token (it mirrors the engine's
`expr.py`, which also has none), so `{od}`/`{tube}` produce
`unexpected character '{'`. The `{name}` "hole" form is legal only because a
*separate* backend layer (`expand.py` `_HOLE_RE`) substitutes holes before the
expression parser runs (`docs_store.validate_doc`). The frontend never ports that
pre-pass, so holes the editor itself offers (as `{hole}` chips in group scope)
are then flagged invalid. Highlighting has the same gap: `classify` paints
everything after the first `{` as an error span.

**Fix.** Add a hole-masking pre-pass in the expr layer (a new pure helper,
node-testable). `maskHoles(text)` replaces each `{ident}` with an equal-length
valid identifier (`{od}` → `_od_`, braces → underscores) and returns the hole
spans + names, preserving every downstream position exactly. Then:

- `analyzeExpression` tokenizes/parses the **masked** text (no false
  `unexpected character '{'`), checks each hole name against the active scope
  (accepting either `{name}` or bare `name` membership), and reports
  `unknown binding/stream '{name}'` only when genuinely absent — with the message
  cosmetically restored to `{name}` form via the recorded span.
- `highlightSpans`/`classify` tokenize the masked text so a hole colours as a
  name reference (positions map back to the original `{od}` via equal-length
  masking); no more error span after `{`.

The parity-pinned `tokenize.ts`/`parse.ts` are **not** touched (masking is a new
layer above them, so the golden corpus stays valid and the engine port stays in
lockstep). Server-side validation remains authoritative.

**Verify.** Unit-test `maskHoles` (positions preserved, keyword holes like
`{not}`→`_not_` don't become keywords, incomplete `{od` left alone). In a group
scope, `mean({od}, last=5)` and a `{tube}` param value validate clean and
highlight correctly; an unknown `{bogus}` reports `unknown binding '{bogus}'`.

---

## Testing strategy

- **Pure-function units (vitest, node):** `maskHoles` (#13), the auto-grow
  `minHeight` floor (#12). No DOM/component tests here per repo rules.
- **Capture probe (`npm run capture`, both themes):** the DOM/visual fixes —
  lane controls (#1), scrollbar (#2), group-card truncation (#3), indentation
  (#5), portal popups (#7), constants stacked layout (#8/#9), separators (#10),
  expression height (#12, probe R4), and binding highlight/validation (#13).
  Add/adjust capture states where an existing one doesn't already exercise the
  fixed surface.
- **Full suite + typecheck + lint** green before PR.

## Out of scope

- Changing the engine expression grammar or the `{name}` hole mechanism.
- Round-trip/data-model changes (imported lanes stay their original kind).
- OS-level scrollbar auto-hide behaviour (#2) — only the thin styling is ours.
- Constant rename UI (no `renameConstant` exists; not requested).
