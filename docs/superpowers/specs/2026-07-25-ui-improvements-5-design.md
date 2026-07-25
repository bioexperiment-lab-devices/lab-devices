# UI Improvements 5 — design

Three follow-up fixes on the eleven that shipped in PR #80, raised in
`docs/ui-improvements-4/comments.md` (screenshots 16, 17, 18), plus one
regression guard. All work happens on the `fix/ui-improvements-5` worktree.

The comments are follow-ups, not new issues: #5 (container indentation) and #12
(expression-input height) were fixed *partially* — each fix left a second-order
defect the first pass did not measure — and #13 (`{binding}` handling) was fixed
for validation but not for autocomplete.

Four decisions were confirmed with the user before this spec:

- **Lane spacing (#5):** "8px of air around every lane." The drop targets
  *become* the gutters; a lane's content starts exactly 8px inside its card
  border, the same as a loop's body.
- **Separator extent (#5):** the hairline spans the **cards region only** — it
  starts below the `LANE N` label row, not at the tinted header — and branch
  arms match.
- **`+ lane` (#5):** the button is separated from the last lane by a hairline
  too, so it reads as its own compartment.
- **Autocomplete depth (#13):** hole context *and* bare-prefix matching — typing
  `{`, `{p`, or plain `o` all reach `{od}`.

The frontend's standing rules apply throughout (`webapp/frontend/CLAUDE.md`):
control metrics live only in `controls.ts`; helper classes *select* one class per
property and are never overridden by concatenation; the expression tokenizer and
parser stay engine-pinned; DOM wiring is verified by the capture probe, not
vitest. Run `npm run capture` (both themes) after touching any control class.

---

## #5 — Parallel lane spacers, indentation and separators

**Root cause.** Three independent contributors, all in `src/builder/Canvas.tsx`:

1. `ContainerBody` (line 393) wraps *every* construct body in `px-2 pb-2` (8px).
2. `ParallelLanes` (409–423) lays the row out as
   `[DropSlot][Lane 0][DropSlot][hairline][Lane 1][DropSlot][+ lane]`, and the
   horizontal `DropSlot` (`DropSlot.tsx:42`) is `mx-0.5 w-2 self-stretch` — **12px
   of real layout width**, including one on each *outer* edge.
3. `Lane` (477) and both branch arms (561, 566) add `p-1` (4px).

So the left inset of the first card differs per construct:

| construct | body padding | gutter | wrapper | inset |
|---|---|---|---|---|
| loop / for_each / serial | 8 | — | — | **8px** |
| branch arm | 8 | — | 4 | **12px** |
| parallel lane | 8 | 12 | 4 | **24px** |

That is screenshot 5's broken indentation. The same drop slot explains
screenshot 16: the inter-lane order is `[12px slot][1px hairline]`, so the line
sits 17px from the left lane's cards and 4px from the right lane's — evenly
spaced only by accident of which side you measure. And the hairline is
`w-px self-stretch` inside an `items-stretch` row, so it runs the full row
height and butts into the tinted header above it.

**Fix — one spacing rule.** *Every lane and arm is surrounded by 8px of air.
Where two of them meet, the two 8px margins form a 16px gutter with the hairline
centred in it. A container's inner content therefore always starts 8px inside
its card border, whatever the construct.*

| change | file | from | to |
|---|---|---|---|
| parallel body padding | Canvas.tsx `ContainerBody` | `px-2 pb-2` | `pb-2` (parallel only; the lane row supplies its own edge air) |
| edge drop slot | DropSlot.tsx | `mx-0.5 w-2` | `w-2` (8px) |
| gutter drop slot | DropSlot.tsx | — | new `divider` prop → `w-4` (16px) with a centred hairline child |
| row order | Canvas.tsx `ParallelLanes` | slot, lane, slot, hairline, lane | `[slot]{lane, [divider slot]}…[divider slot][+ lane]` |
| `+ lane` button | Canvas.tsx | `m-1` | `my-1 mr-2` (left air from the divider slot; `mr-2` gives the row the same 8px right edge as its left) |
| lane wrapper | Canvas.tsx `Lane` | `p-1` | `py-1` |
| branch arms | Canvas.tsx `BranchLanes` | `p-1` | `py-1` |

Resulting geometry, identical on both sides of every lane:

```
parallel card border
│8│ lane 1 cards │8 ┊ 8│ lane 2 cards │8 ┊ 8│ + lane │8│
loop card border
│8│ body cards
```

Branch arms need no gutter change: the row's existing `gap-2` already puts 8px
on each side of their hairline (16px total, centred) — they only lose their
horizontal padding and gain the vertical inset below.

**Separator extent.** The hairline no longer stretches the full row. It starts
below the label row and ends level with the lane content:

```
LANE_DIVIDER_INSET = 'mt-7 mb-1'   // 28px top = lane py-1 (4) + label row h-6 (24); 4px bottom
```

One exported constant in `Canvas.tsx`, used by both the parallel gutter divider
and the branch-arm hairline, so "they match" holds by construction rather than
by two hand-tuned numbers. The 28px is derived from `CONTROL_H` — the label rows
are `h-6` — and carries a comment saying so, because a change to the control
token must move this with it.

**Edge case — empty parallel.** With the body's horizontal padding gone, the
`hint` drop slot (the dashed "drop here" box) would touch the card edges. Its
horizontal variant gains `mx-2` so the empty state keeps the same 8px air. The
vertical hint (empty `BlockList`) is unchanged — its padding still comes from the
parent body.

**Not changed.** Vertical rhythm (the body's `pb-2`, `BlockList`'s `my-0.5 h-2`
slots, the lane label row's height) — nothing in the comment points at it, and
touching it would move every capture baseline for no stated defect.

**Verify.** `npm run capture` both themes: parallel, branch and loop at the same
depth show equal left insets; the hairline is centred in each gutter and clears
the header. Measure the three constructs' first-card offsets in the probe run
(all 8px). Load `examples/morbidostat.json` (bare-block lanes) and
`examples/adaptive-bioreactor-tour.json` (nested parallels) for the drag targets:
dropping at the head, between lanes, and after the last lane must all still work.

---

## #12 — Expression input: visible box larger than the active box

**Root cause.** Tailwind v4's preflight does not blockify form controls — it sets
only `resize: vertical` on `textarea` (`node_modules/tailwindcss/preflight.css:302`),
so a textarea stays `display: inline-block`. In `ExpressionEditor` (line 168) the
textarea is the only in-flow child of `<div className="relative min-w-0 flex-1">`;
a block container puts an inline-level child on a **line box**, which adds the
parent font's descender space below it. The wrapper is therefore ~4px taller than
the textarea, and the highlight overlay — `absolute inset-0` (line 172) — paints
the *wrapper*, not the input. The overlay is the box you see; the textarea is the
box you type in.

This also explains why #12's first pass looked correct in the source: before it,
the textarea measured 20px and the wrapper ~24px, which matched the sibling
controls, so the painted box was right and only the active area was short.
Raising the textarea to `CONTROL_H_PX` (24px) moved the wrapper to ~28px and
turned a hidden mismatch into a visible one. Screenshot 17 is the wrapper's
bottom edge showing below the focused input's border.

**Fix.** Add `block` to `textAreaClass()` (`src/ui/controls.ts`). A block-level
textarea generates no line box in its parent, so the wrapper collapses to exactly
the textarea's height: **visible box == active box == 24px**, and the 24px already
chosen in #80 stands unchanged. Metrics belong to `controls.ts` and nowhere else,
so this is one edit at the single home, not a patch at the call site.

`align-top` was considered and rejected: it fixes the same gap but leaves the
control inline-level, so the wrapper's height stays whitespace-sensitive.

Blast radius is every textarea — `AutoGrowTextArea` (Inspector ×2) and
`fields.tsx:78` also lose ~4px of phantom space under them, which is the correct
rendering in all three cases. `controlClass` (inputs/selects) is deliberately
left alone: those never carry an overlay, and blockifying them would change rows
where an input sits inline beside text.

**Verify.** `controls.test.ts` asserts `block` is present in `textAreaClass()` and
absent from `controlClass()`. The new probe rule below is the real gate: it fails
on today's build and passes after this change.

---

## #13 — Autocomplete for bindings in expressions

**Root cause.** `expr/complete.ts`'s `context()` (line 26) calls the
parity-pinned `tokenize` on the **raw** draft. `{` is not in the grammar, so it
lexes as an error and `completionsAt` returns `null`. Two symptoms follow:

- typing `{` — or `{bud`, as in screenshot 18 — never opens the popup;
- once a *completed* `{od}` exists earlier in the line, `error.pos < caret` holds
  for every later caret position, so autocomplete is dead for the rest of the
  expression. This one is unreported but is the same defect.

Everything else is already in place: `scopeRefs.ts` puts a group's params and
locals into scope in `{hole}` form (`scopeBindingNames`, `scopeStreamNames`), and
the help popover already inserts them. Only the completion path can't see them.

**Fix.** Four changes, all in `expr/complete.ts` except the last:

1. **Mask before lexing.** `context()` runs `maskHoles(text)` (from `expr/holes.ts`,
   added in #80) and tokenizes the masked string. The mask is equal-length by
   construction, so every `pos` and every `replace` span stays valid against the
   original text. Second symptom gone. `tokenize.ts`/`parse.ts` stay untouched —
   the golden parity corpus is the reason `holes.ts` exists at all.
2. **Hole context.** New pure `holeContextAt(text, caret)`: scan back over
   `[A-Za-z0-9_]*` from the caret; if the run is preceded by `{` with no `}` in
   between, return `{ start, prefix, end }`, where `end` swallows a following `}`
   when the caret sits inside an already-complete hole (so accepting replaces
   `{od}` rather than nesting braces). When it matches, the pool is every
   hole-form name in scope, filtered on the **inner** name, inserting the full
   `{name}`. An empty prefix (the user just typed `{`) returns the whole list —
   `{` is an explicit trigger, no Ctrl+Space needed. At the workflow scope no
   hole-form names exist, so it returns `null` and `{` offers nothing, which is
   correct: holes are group-body syntax.
3. **Bare-prefix matching.** `Completion` gains a `match` field — the inner name
   for hole-form entries, the label otherwise — and the atom-position and
   stat-argument pools filter on `match` instead of `label`. Typing `o` in a group
   body then offers `{od}`, and accepting it replaces the partial name token with
   the braced form. A user never has to know the brace syntax to reach a group
   param.
4. **Message polish** (`expr/analyze.ts`): when a parse error lands on a `{`,
   report `unfinished {binding} — add the closing '}'` instead of the lexer's
   `unexpected character '{'`. `{` has no other role in the grammar, so the
   rewrite cannot mislabel anything else, and it is what the user sees for the
   300ms between typing `{od` and typing `}`.

**Verify.** `complete.test.ts` gains cases for: `{` at an atom position (full hole
list), `{p` (filtered), caret inside a complete `{od}` (replace spans the whole
hole), a caret *after* a completed hole earlier in the line (completions alive),
bare `o` matching `{od}`, and the workflow scope returning `null` for `{`.
`analyze.test.ts` covers the reworded message. Manually: open a group body in the
Builder, type `{` in a Value field, accept `{od}`, confirm no amber problem
remains.

---

## Guard — a probe rule for the wrapper/control gap

#12 is the second time a control's *painted* box and its *layout* box have
disagreed without any check noticing, and R4 could not have caught it: its
`rowControls` walker collects `BUTTON`, `INPUT` and `SELECT` only
(`tools/probe.mjs:108`) — textareas are invisible to it. Adding `TEXTAREA` there
is the wrong fix: a legitimately multi-line expression editor beside its 24px ƒ
button would flag on every run.

**New rule R6 — `control-wrapper-gap`.** For every `textarea`, compare its
rendered height with its parent's **content-box** height. Flag when the parent
exceeds it by more than 1px *and* the textarea is the parent's only in-flow child
(every other child is absolutely positioned, or there are none). That is exactly
the #12 shape — a wrapper that paints, or is painted over, at a size its control
does not have — and it cannot fire on an auto-grown textarea, because the wrapper
grows with it.

The rule is written **before** the `block` fix and observed failing on the
current build (the expression editors report a ~4px gap); the fix turns it green.
The probe's standing baseline is zero violations in both themes.

---

## Out of scope

- Vertical rhythm inside containers (no reported defect).
- Blockifying `controlClass` inputs/selects.
- Any change to `tokenize.ts` / `parse.ts` — engine parity is pinned by the
  golden corpus.
- Type-aware completion ranking (offering only `bool`-typed bindings in a guard
  slot, say). The scope lists are untyped here by design; types stay server-side.
