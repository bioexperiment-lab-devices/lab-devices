# Experiment Studio — canvas visual language (W14)

**Date:** 2026-07-18
**Status:** approved (forks user-settled 2026-07-18)
**Scope:** frontend-only. No document-format change, no backend change, no engine change.
**Predecessors:** W10 (UI-audit fixes), W11 (UI improvements), W12 (element-library taxonomy), W13 (UI improvements round 2, v0.9.0).

## 1. Problem

A workflow that is complex enough becomes hard to read. The user named three failures, all of which the current canvas earns:

1. **Can't see structure** — what contains what, how deep, where a construct ends.
2. **Can't identify blocks** — every card looks like every other card, so finding a specific device action means reading label text one card at a time.
3. **Can't find my place** — orientation is lost after scrolling or switching scope.

Volume as such ("too much on screen") was explicitly *not* the pain, which is why this increment adds no folding, focus mode, minimap or breadcrumb. It is a visual-language increment only.

## 2. What the canvas looks like today (audit)

Established by reading `src/builder/Canvas.tsx`, `src/ui/icons.tsx`, `src/builder/tree.ts`, `src/builder/summary.ts`, `src/ui/controls.ts`, `src/index.css`.

- **The canvas is 100% slate and white.** `bg-slate-100` canvas, `bg-white` cards, `border-slate-300` card borders, `text-slate-500` icons.
- **Every one of the 14 block kinds renders the identical card**: `'min-w-0 rounded border bg-white text-sm shadow-sm'`, plus `border-blue-500 ring-1 ring-blue-300` when selected. Selection is the only state that changes a card's appearance.
- **There is no kind-keyed color**, with one exception: `KIND_COLOR` in `icons.tsx` tints the `abort` icon `text-red-600` and the `alarm` icon `text-amber-600`. The other twelve kinds render `text-slate-500`.
- **Depth is encoded nowhere.** There is no depth counter in the codebase. Nesting reads only as accumulated box geometry — 1px of border plus 8px of padding per level.
- **`loop` and `for_each` container bodies are byte-identical**: `'ml-2 border-l-2 border-slate-200 px-2 pb-2'` for both.
- **`branch` arms have no container at all** — no border, no background, just a 10px uppercase `then`/`else` caption and an 8px gap.
- **`parallel` lanes are the only construct with a real container**: a dashed `border-slate-200` box with transparent fill.
- **Editing a group body is pixel-identical to editing the main workflow.** The sole cue that you have descended into a subroutine is the value shown in the `ScopeSwitcher` select.
- **Leaf card text is one undifferentiated run.** `blockSummary()` returns a single string — `pump1 · dispense (volume=5)` — rendered at one weight and one color.

### 2.1 The constraint that shapes everything: hue is already spoken for

Every drop of color reaching the canvas today means **state**, not identity:

| Color | Meaning | Where |
|---|---|---|
| Blue | selection, legal drop target, focus | `border-blue-500 ring-1 ring-blue-300`, `bg-blue-400`, `border-blue-400 bg-blue-50`, `focus:border-blue-400`, `bg-blue-100 text-blue-700` |
| Red | error, illegal drop, destructive | `bg-red-600` diagnostic badge, `text-red-600`, `bg-red-200`, `border-red-400` |
| Amber | warning | hazard box `border-amber-300 bg-amber-50 text-amber-800`, unsaved `●`, unresolved-stream pill |
| Emerald | valid | Toolbar pill only, never on canvas |

A Scratch-style "one hue per block family" scheme would therefore put category color in direct competition with error color, and a red-tinted Safety block adjacent to a red-bordered broken block is a system that can no longer say *something is wrong here*. **Hue stays reserved for state.** Structure and identity are carried on other channels, and state reads louder because the field around it stays quiet.

### 2.2 The rejected first proposal, and why

Two earlier candidates were rejected during the brainstorm and are recorded so they are not revisited:

- **Left rails per container, textured by kind.** Rejected: every container is already a card with a 1px border, so a rail draws a second vertical line 8px inside the first. It adds a stroke without adding a fact, and per-kind textures multiply that noise. The only construct a rail would genuinely help is `branch`, whose arms have no box — which is an argument for giving branch arms a box, not for rails everywhere.
- **Tinting by the Flow/Data/Pause/Safety taxonomy.** Rejected: four of the five constructs the user most needs to tell apart (`serial`, `parallel`, `branch`, `loop`, `for_each`) all live in **Flow**. Coloring them identically spends the color channel and returns nothing. The W12 taxonomy is the right way to *organize the palette* and the wrong axis to *color the canvas*; those are different jobs.

## 3. Design

Four layers, each on a channel that does not compete with the others.

### 3.1 Layer 1 — construct identity on the container's own border and header

The container card's **existing** border and header row take a construct-keyed color. Nothing new is drawn; an existing stroke is recolored.

| Construct | Border | Header fill | Rationale |
|---|---|---|---|
| `serial` | `border-slate-300` | `bg-slate-50` | Neutral. Sequential is the baseline construct and deserves the quietest treatment. |
| `parallel` | `border-teal-200` | `bg-teal-50` | |
| `branch` | `border-violet-200` | `bg-violet-50` | |
| `loop` | `border-fuchsia-200` | `bg-fuchsia-50` | |
| `for_each` | `border-lime-200` | `bg-lime-50` | Maximally distant from `loop`, which is the pair most confused today. |

Hue families are chosen to avoid the four reserved state colors and their near neighbours: no blue or indigo (selection), no red or rose (error), no amber or orange (warning), no emerald or green (valid).

Leaf cards keep `bg-white` and `border-slate-300`, so structure reads as tinted and content reads as white. The single exception is `group_ref`, whose edge is hatched per §3.5.

**Selection must still win.** Since every container now carries a colored border, selection strengthens from `ring-1 ring-blue-300` to `ring-2 ring-blue-400` while keeping `border-blue-500`. The ring, not the border, becomes the load-bearing selection cue.

### 3.2 Layer 1b — depth as a neutral zebra

The container **interior region** — today pure padding, structurally invisible — gets a neutral fill alternating by depth parity: `bg-slate-50` at odd depths, `bg-slate-100` at even depths, counting the outermost container interior as depth 1. Alternation rather than a monotone ramp, because a ramp runs out of range in four levels, whereas parity never exhausts.

Note the ramp deliberately excludes `bg-white`: leaf cards are white, so a white interior would leave a card visible only by its 1px border at every other level. Alternating between the two slate steps keeps white cards contrasting against their container at *every* depth. `bg-slate-100` matching the canvas backdrop is harmless, because the canvas is depth 0 and can never be adjacent to a depth-2 interior.

Containment therefore becomes visible as *filled areas* rather than counted strokes, at zero horizontal cost — the fill rides on padding that already exists. Depth is pre-attentive instead of tallied.

`branch` arms gain a container box for the first time, on the same rules as every other construct. This closes the audit gap in §2.

### 3.3 Layer 2 — role swatches on leaf cards

`command` and `measure` cards gain a small solid rounded swatch before the role name, colored per role.

**User-settled (2026-07-18, do not re-litigate):** colors are **auto-assigned** from a fixed ramp in role-declaration order; all commands and measures of a role share its color; the assignment **persists**, keyed by **role type + name**; the user can **edit** a role's color or **remove** it entirely, and a role with no color renders exactly as cards do today (white, no swatch).

Swatches render at full saturation (`-500`) against the construct tints' pale `-50`/`-200`. That saturation gap is what keeps the two systems legible as separate languages rather than one muddled one. A small solid swatch also reads conventionally as a *legend key* rather than a status, which is what keeps it from competing with the border-and-background state palette.

The ramp is eight colors, drawn from the same reserved-hue exclusion list as §3.1 and fixed in this order: `teal-500`, `violet-500`, `fuchsia-500`, `lime-600`, `cyan-600`, `purple-500`, `pink-500`, `stone-500`. A ninth role wraps to the start of the ramp; two roles sharing a color is a cosmetic collision the user can resolve by editing one, not an error state. `lime` and `cyan` take the `-600` step because their `-500` steps are too light to read as a solid key at swatch size.

**Open fork — where the assignment is stored (§5).**

### 3.4 Layer 3 — typographic hierarchy inside the summary

`blockSummary()` returns one string, so `pump1 · dispense (volume=5)` renders at one weight and one color. It gains a structured sibling:

- `blockSummaryParts(node)` → ordered segments tagged by role of the text (subject / verb / detail / marker).
- `blockSummary(node)` becomes the join of those parts, so the `title` attribute, the drag overlay and `WorkflowSnapshot` keep byte-identical output and need no change.

The canvas renders the parts with weight and color instead of as one run: role `font-medium text-slate-900`, verb `text-slate-700`, params `text-caption`. This separates three facts at a glance while spending no color at all.

### 3.5 Layer 4 — orientation, and where hatching earns its place

Two places, both about *content that is not what it appears to be*:

- **Group scope.** While `scope !== null` the canvas backdrop takes a diagonal hatch and the scope name renders as a persistent strip above the tree. A group body is a subroutine, and the hatch says "this is not the main workflow" without stealing content space. This is the direct fix for *can't find my place*.
- **`group_ref` cards.** A `group_ref` is structurally a leaf but semantically expands to an entire subtree that is not rendered inline. A hatched card edge marks it as standing for something not shown here.

Hatching is used **only** for these two "stands for something absent" cases and is not a general decoration.

## 4. Implementation constraints

Non-negotiable, drawn from `webapp/frontend/CLAUDE.md` and prior increments' scars:

- **Color classes must be SELECTED by a helper option, never appended to a helper's output.** This is the trap that has now bitten twice: W11 on `width`, W12 on `text` color, where `IconButton`'s appended `text-blue-700` lost silently to a baked-in `text-slate-500` at equal specificity in the same `@layer utilities`. Any construct-tint or swatch helper must emit exactly one class per property. An increment that introduces five new tints via string concatenation will ship a canvas that looks correct in source and renders slate.
- **AA contrast.** `text-hint` already measures under 4.5:1 on `bg-slate-100`; five new tinted surfaces each need re-checking under the committed probe, not by eye.
- **vitest is node-env, pure functions only.** The construct-tint map, the ramp assignment, and `blockSummaryParts` are all pure and must be unit-tested as such. Component rendering is verified by the probe harness, not vitest.
- **No document-format change**, so `docToTree`/`treeToDoc` are untouched and open+save stays a byte no-op (W9-settled).
- **Icons stay lucide-only**; `∀`, `R×N`, `⤳`, `×N`, `●` remain typographic.

## 5. Where role color assignments live

**User-settled 2026-07-18: browser-local `localStorage`, keyed by `type:name`.** Do not re-litigate.

This keeps the increment frontend-only and delivers the stated payoff — `drug_pump` is the same color in every experiment the user opens. The accepted costs, recorded so they are not rediscovered as bugs:

- A colleague opening the same document on the shared stack sees **different colors**. Role color is a per-user reading aid, not document state.
- The assignment does **not** survive a new machine or a cleared browser. It is regenerated from the ramp in declaration order, so the canvas is never broken by its absence — only differently colored.
- Nothing about role color is exported, imported, validated, or sent to the backend.

The rejected alternative was storing colors in the document, which would share them across researchers and survive export, at the cost of a document-format change pulling in the backend, validation and the byte-no-op round-trip contract, and of turning a reading aid into shared state two people can disagree about.

A stale key — a role deleted or renamed since assignment — is inert and must not be garbage-collected eagerly, because a rename followed by an undo must recover the original color.

## 6. Out of scope

- Folding, collapse-to-summary, focus mode, minimap, breadcrumbs — volume was explicitly not the reported pain.
- Full lane-strip redesign for many lanes (carried from the W10 audit's "S1 worth revisiting").
- `ScopeSwitcher` intrinsic-width cosmetic issue (known-open since W11).
- Verb-keyed icons. Every `command` shares `Play` and every `measure` shares `CircleDot` today; §3.4's typographic hierarchy addresses the identification pain without opening the catalog-to-icon mapping question.
- Dark mode.

## 7. Verification

- **Pure logic → vitest:** construct-tint map exhaustive over `FlowKind` (compile-time exhaustiveness, as W12's section test does); ramp assignment (declaration order, persistence key, removal → no swatch); `blockSummaryParts` join equals legacy `blockSummary` output for all 14 kinds.
- **DOM truth → committed W11 probe harness:** `npm run capture` across the standard state/viewport matrix; contrast and `sibling-height-mismatch` rules stay at 0 on all five new tinted surfaces and at every depth parity. **The probe must be confirmed to actually render nested containers at depth ≥ 3 and a group scope** — W12 shipped a rule that passed vacuously because the harness never opened the panel it measured.
- **Fixtures:** `ui-audit-torture.json` (all 14 kinds, 8 lanes, a `wash cycle` group) and `morbidostat.json` must both open and render. Torture is the depth and construct-coverage case; morbidostat is the real-document case.
- **Gates:** full frontend suite; backend run unchanged.
- **Release:** ships as `feat` via release-please.
