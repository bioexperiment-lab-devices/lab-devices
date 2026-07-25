# Adaptive canvas chips — design

Date: 2026-07-25
Branch: `fix/ui-improvements-7`
Predecessor: [`2026-07-25-ui-improvements-6-design.md`](2026-07-25-ui-improvements-6-design.md)

## 1. The problem

A canvas card renders every fact about a block on ONE line: role swatch, kind icon,
`device · verb (params)`, label, diagnostics count, duplicate, delete. That is tolerable for a
card in a top-level list, which has the whole canvas to itself. It is not tolerable inside a
`parallel` lane or a `branch` arm, where N cards sit side by side and each one's width is
multiplied by N into the canvas's width.

The canvas's only real degree of freedom is VERTICAL scroll. An experiment may be long; it must
not be wide. Horizontal scroll is for exceptional documents, not for three ordinary action
blocks running in parallel.

Measured (`docs/ui-improvements-3/after/probe.json`, canvas client width 798px at 1440×900):

| state | canvas `scrollWidth` |
| --- | --- |
| `builder-morbidostat` | 2057px (2.6× the viewport) |
| `branch-selected` (the `service` group) | 1770px |
| `builder-torture` | 3934px |

### 1.1 Cause A — the canvas is sized by `max-content`, so nothing CAN wrap

`Canvas.tsx` wraps the whole tree in `w-max min-w-full` (`width: max-content`). Under
max-content sizing "available width" is defined as whatever the content wants, so a flex row
never runs out of room and `flex-wrap` can never fire. The card header is single-line because it
has no choice.

The `max-w-80 truncate` on the summary span and `max-w-40` on the label are damage control for
exactly this — their own comments say so. They cap the blow-up; they do not fix it.

### 1.2 Cause B — fixed chrome eats the width a narrow card has

Per leaf card, on `main` at `e549c8c`:

| piece | width |
| --- | --- |
| `px-2` | 16px |
| role swatch (`h-2.5 w-2.5`) + `gap-1` | 14px |
| `KindIcon` (14px) + `gap-1` | 18px |
| Duplicate + Delete (2 × `IconButton` 24px) + gaps | 56px |
| **fixed chrome** | **104px** |

A lane's floor is `min-w-48` = 192px, so at the floor a card has 88px for its text. On a
1440×900 screen a 3-lane parallel leaves each lane ~223px → ~119px of text, about 20 characters.
Wrapping alone would not rescue that; the chrome has to come down too.

(PR #83 already removed the 24px phantom chevron a leaf used to reserve for alignment with
container cards. That was the third of the three reclaims considered here; it is done.)

### 1.3 Cause C — lane and arm floors MULTIPLY with nesting

`min-w-48` (192px) is the floor on every parallel lane and every branch arm, and nesting
multiplies it. morbidostat's main tree tops out at a 3-lane parallel, but its `service` group
nests `branch → branch → branch` = **8 columns** = 1536px of floor before a single character of
content. No amount of text wrapping touches that number.

**Settled: the 192px floor stays.** Deep nesting is the exceptional case horizontal scroll
exists for. This design does not lower the floor and does not stack lanes or arms vertically.

## 2. Goals and non-goals

**Goals**

1. A card whose width is not otherwise constrained keeps its single-line layout, unchanged.
2. A card squeezed by a lane or arm reorganises onto multiple lines instead of forcing the
   canvas wide.
3. No card content can widen the canvas beyond the lane/arm floors that hold it.
4. `builder-morbidostat` stops scrolling horizontally at 1440×900.
5. `CHIP_H_PX` (34px, PR #83's chip-band unit) still describes an unwrapped leaf card exactly.

**Non-goals**

- Lowering `min-w-48`.
- Stacking branch arms or parallel lanes vertically when narrow.
- Any change to `blockSummary`'s output string, which the drag overlay, the run log and every
  `title` attribute depend on.
- Touch-device support for the canvas (the Studio is a desktop tool; see §7).

## 3. Sizing model — `w-fit`, not `w-max`

`Canvas.tsx`: `w-max min-w-full` → **`w-fit min-w-full`**.

`width: fit-content` resolves to `min(max-content, max(min-content, available))`, giving three
regimes:

| regime | used width | effect |
| --- | --- | --- |
| `max-content ≤ available` | available (via `min-w-full`) | identical to today — nothing wraps |
| `min-content ≤ available < max-content` | available | **new** — lanes shrink, cards wrap, no scroll |
| `available < min-content` | min-content | canvas scrolls, and the wrapper is still as wide as its content so borders and fills paint correctly |

The third row is the property `w-max` was there for ("a wide subtree makes the canvas scroll
instead of clipping inside a nested box"), and `fit-content` keeps it: when min-content exceeds
the viewport the wrapper takes min-content, which is by construction wide enough for every
descendant, so nothing paints outside its box.

Everything in §4 and §5 exists to make regime 2 produce a good-looking card, and to push
regime 3 as far out as possible.

## 4. Card chrome

```
BEFORE  [swatch 10][icon 14][ summary ≤320 truncate ][ label ≤160 truncate ][badge][⧉ 24][✕ 24]
        └──────────────────────── 104px of fixed chrome ──────────────────────────────────────┘

AFTER   ┃[icon 14][badge?] [ head │ tail │ label — wraps ]           (⧉ ✕ float on hover)
        ▲ rail 4px         └────────── 34px of fixed chrome ────────┘
```

### 4.1 Duplicate/Delete float (−56px)

The card root takes `relative group/card`. The action cluster becomes
`absolute right-2 top-1`, `hidden` by default and `flex` when any of: the card is hovered
(`group-hover/card:flex`), focus is inside it (`group-focus-within/card:flex`), or the card is
selected. `right-2 top-1` reproduces exactly where the buttons sit today (the header's `px-2`
and `py-1`).

Its backing is `headerFillClass(kind) || 'bg-white'` — `headerFillClass` returns `''` for leaves,
which are `bg-white`. This is a SELECTION of one background class, never a concatenation onto
another (CLAUDE.md's cascade rule).

Named groups (`group/card`, `group/lane`) rather than bare `group`: `group-hover:` matches any
ancestor carrying `.group`, so an unnamed group would make a lane reveal every card's actions.

Nothing becomes unreachable: the buttons keep their `title`/`aria-label`, appear on keyboard
focus, are permanently visible on the selected card, and `Delete`/`Backspace` on a selected
block already removes it (`BuilderTab.tsx`).

### 4.2 Role swatch → left rail (−14px)

The 10px inline square becomes a 4px stripe on the card's left edge:
`absolute inset-y-0 left-0 w-1 rounded-l` plus the role's existing `bg-*` class from
`assignRoleColors`. It reads better in a vertical stack — a colour column you can scan — and
costs zero inline width.

Deliberately NOT `border-l-4 border-l-<role>`: `cardBorderClass` SELECTS the card's single
border class (and replaces it entirely on selection), so a border-colour override would be the
appended-utility cascade fight CLAUDE.md forbids. An absolutely-positioned child cannot lose
that fight.

The header's left padding becomes `pl-3 pr-2` when a rail is present and stays `px-2` otherwise —
again a selection, not an append.

Only `command` and `measure` carry roles (`useRoleColor` returns `null` for every other kind), so
the rail never appears on a container, and `group_ref`'s `edge-hatch pl-1.5` left edge can never
collide with it (a `group_ref` has no role).

### 4.3 The diagnostics badge moves to the leading cluster

The badge sits today in the same right-hand cluster as the actions. That cluster is becoming a
hover overlay, and an error count that disappears — or hides behind the overlay — on hover is
the wrong trade. The badge moves to immediately after `KindIcon`, staying in flow.

Side effect worth having: error counts line up in a column down the left of a card stack instead
of being scattered at each card's ragged right end.

### 4.4 Lane headers get the same treatment

`Lane`'s header carries the same Duplicate/Delete pair. It is not a width driver (its min-content
is ~100px, well under the 192px floor), but a card that hides its actions sitting inside a lane
that does not would read as a bug, and three lanes' worth of permanently-lit buttons is real
visual noise on a dense canvas.

The lane root takes `relative group/lane`; the overlay is `absolute right-1 top-1` (matching the
header's `px-1` and the lane's `LANE_PAD`). Its backing is `interiorFillClass(depth)` read from
`DepthContext` — a lane has no background of its own, it sits on its parallel's interior fill.

Hovering a card inside a lane also hovers the lane, so the lane's actions appear too. That is
CSS hover propagation and it is the right behaviour: you are in that lane.

The branch arms' "remove else" button is not touched — it only exists while the arm is empty.

## 5. What stays atomic, what wraps

### 5.1 `splitSummary` — a new pure function in `summary.ts`

```ts
export function splitSummary(parts: SummarySegment[]): {
  head: SummarySegment[]
  tail: SummarySegment[]
}
```

It PARTITIONS the array `blockSummaryParts(node)` already returns. No segment's text changes, so
`blockSummary` — the join of those texts — is byte-identical and its pinning test still passes.
The drag overlay, the run log's block names and every `title` attribute are untouched.

**Rule: `head` is every segment up to and including the LAST segment whose role is `subject` or
`verb`; `tail` is the rest.** If no such segment exists, `head` is empty and everything is tail
(unreachable for all 14 kinds — pinned by a test — but the function stays total).

| kind | head (atomic) | tail (wraps) |
| --- | --- | --- |
| `command` | `pump1 · dispense` | `(volume=5.0, rate=2)` |
| `measure` | `od1 · read` | `→ od_1` |
| `wait` | `wait` | `30s` |
| `operator_input` | `input od_min` | `(float)` |
| `serial` | `Serial` | `· 3` |
| `parallel` | `Parallel` | `· 3 lanes` |
| `loop` (count) | `Loop` | `×120` |
| `loop` (until) | `Loop until` | `count(od_1) > 5` |
| `branch` | `If` | `count(od_1, last=11min) > 0` |
| `compute` | `r_est` | `= 24 * (mean(od_1, last=5) - …)` |
| `record` | `od_1` | `← last(od_raw)` |
| `abort` | `Abort if` | `pressure > 3` |
| `alarm` | `Alarm if` | `temp > 40` |
| `for_each` | `For each` | `tube, od × 3` |
| `group_ref` | `service` | `(tube=1)` |

The fault marker (`R×3`, `⤳`) is a `marker` segment and always lands in the tail.

Long expressions gain the most: a branch condition is a 320px nowrap run today.

### 5.2 Rendering

```jsx
<span title={blockSummary(node)} className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1 py-0.5">
  <span className="min-w-0 shrink truncate">{head.map(segment)}</span>
  <span className="min-w-0 wrap-anywhere">{tail.map(segment)}</span>
  {node.label && (
    <span title={node.label} className="min-w-0 shrink truncate text-xs italic text-caption">
      “{node.label}”
    </span>
  )}
</span>
```

`segment` keeps the existing per-role weights (`subject` → `font-medium text-slate-900`,
`verb` → `text-slate-700`, `detail`/`marker` → `text-caption`) as nested spans, so the three-weight
reading of a summary survives the split.

Three load-bearing details:

- **`min-w-0` on the head and label, not `max-w-*`.** A flex item with `min-width: 0` contributes
  ZERO to its flex container's min-content size. So a pathological
  `bioreactor_left_densitometer · read_optical_density` can no longer widen the canvas at all: it
  ellipsizes inside whatever width the lane gives it, with the parent's `title` carrying the full
  text (probe R2 — truncate-without-title — satisfied). This is why `max-w-80` and `max-w-40` are
  DELETED rather than tightened; they were caps on an intrinsic contribution that no longer
  exists.
- **`gap-x-1` stands in for the segments' leading spaces.** Segments carry their own separators
  (`' · '`, `' ('`, `' → '`), and a flex item's leading whitespace collapses at the start of its
  line box. 4px is a space's width at `text-sm`, so this is visually a no-op.
- **`items-center`, never `items-baseline`.** An `overflow: hidden` box's baseline is its bottom
  margin edge, so `truncate` + `items-baseline` misaligns. Every item here is one line-height
  tall, so centring and baseline agree anyway.

`flex-wrap` places the tail on line 2 WHOLE rather than squeezing it onto line 1: items are laid
out at their hypothetical (max-content) size while they fit, and move to the next line when they
do not. That is exactly the "identity on line 1, detail below" behaviour this design wants, with
no breakpoint to tune.

`wrap-anywhere` (`overflow-wrap: anywhere`, Tailwind ≥4.1; the project is on 4.3.2) is what keeps
a single unbreakable token — a long expression with no spaces — from setting a large min-content
size. Unlike `break-word` it DOES reduce the intrinsic minimum.

### 5.3 Vertical metric

The header row becomes `items-start`; `KindIcon` and the collapse chevron get an
`h-6 items-center` wrapper; the text cluster takes `py-0.5` so its 20px first line centres against
the 24px control row.

An unwrapped leaf card is therefore `py-1` (8px) + 24px + 2px border = **34px**, exactly
`CHIP_H_PX`. PR #83's chip band, `CHIP_MIN_H` and `laneLayout.test.ts` all keep holding. A wrapped
card is simply taller than the band's minimum — which container cards already are.

## 6. Expected outcome

At 1440×900, canvas usable width 766px (798px client − 32px `p-4`):

| state | today | predicted | fits? |
| --- | --- | --- | --- |
| `builder-morbidostat` | 2057px | ~720px (3 lanes × 192px floor + gutters + `+ lane` + nesting) | **yes** |
| `branch-selected` | 1770px | ~1350px (8 arms × 192px floor) | no — Cause C, out of scope |
| `builder-torture` | 3934px | floor-driven; long names no longer contribute | partly |

These are predictions from the class arithmetic. `npm run capture` decides, and the
`canvasScrollerOverflow` metric it already records per state/viewport/theme is the acceptance
number.

## 7. Risks

| risk | mitigation |
| --- | --- |
| Hover-only actions have no touch story | `group-focus-within` for keyboard; permanently visible on the selected card; `Delete` on a selection already works. The Studio is a desktop lab tool. |
| Probe R3 (tiny target) stops seeing Duplicate/Delete in states with nothing selected | The `inspector-*` capture states all have a selected block, so the buttons still render for the probe. |
| A hovered overlay covers the end of line 1 | Accepted — that IS the reclaimed space. The full text is in `title`. |
| `w-fit` / `wrap-anywhere` compiling to nothing | Grep the emitted stylesheet for both after building, per the standing Tailwind-4 trap — the same check PR #83 ran on `min-h-8.5`. |
| A wrapped card breaks a chip-band assumption | `CHIP_H_PX` is a MINIMUM (`CHIP_MIN_H`); container cards already exceed it. §5.3 keeps the unwrapped leaf at exactly 34px. |

## 8. Testing

- **vitest** (node env, pure functions only): `splitSummary` over all 14 block kinds; the
  identity `[...head, ...tail]` deep-equals `blockSummaryParts(node)`; every kind yields a
  non-empty head.
- **`npm run capture --theme both`**: 0 violations across every state/viewport/theme combination,
  and a before/after table of `canvasScrollerOverflow` recorded in `docs/ui-improvements-7/`.
- **Built-stylesheet grep** for `w-fit` and `wrap-anywhere`.
