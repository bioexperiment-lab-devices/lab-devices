/** The canvas's lane-spacing tokens (comment #5 on PR #80), owned here the way `ui/controls.ts`
 * owns control metrics: one home, so a parallel's lanes and a branch's arms cannot drift apart.
 *
 * The rule: EVERY lane and arm is surrounded by 8px of air, so a container's inner content starts
 * exactly 8px inside its card border whatever the construct. Before this, three contributors
 * stacked up — the body's `px-2`, a 12px horizontal DropSlot that was pure invisible spacer, and
 * the lane's own `p-1` — putting a parallel's first card 24px in, a branch arm's 12px in and a
 * loop's 8px in. The drop slots ARE the gutters now: one edge width at the row's ends, two
 * between neighbouring lanes, with the separator centred in the gap instead of hugging whichever
 * lane happened to follow it.
 *
 * Class names are literals because Tailwind 4 scans source text — a computed `w-${n}` compiles to
 * no CSS at all (CLAUDE.md). `laneLayout.test.ts` checks the arithmetic those literals stand for,
 * including their lockstep with CONTROL_H_PX. */

/** A lane's / arm's vertical padding. Horizontal padding is deliberately absent: the gutters
 * supply the horizontal air, and a second source of it is what broke the indentation. */
export const LANE_PAD = 'py-1'
export const LANE_PAD_PX = 4

/** The air at the outer edge of a lane row — one lane's worth. */
export const LANE_EDGE_W = 'w-2'

/** The gutter where two lanes meet: two edges' worth, separator centred inside it. */
export const LANE_GUTTER_W = 'w-4'

/** How far the separator clears the lane's label row (`LANE 1`, `then`, `else`), which is one
 * CONTROL_H tall inside LANE_PAD: the line covers the lane's CARDS, not its label, so it never
 * runs into the tinted construct header above it. The bottom inset matches the lane's padding. */
export const LANE_DIVIDER_TOP_PX = 28
export const LANE_DIVIDER_INSET = 'mt-7 mb-1'

/** A leaf card's height: the header's one CONTROL_H row inside `py-1`, plus the card's 1px border
 * top and bottom (measured 34px on the real app). Everything that stands in for a card inside a
 * lane is at least this tall, so an empty lane beside a one-card lane reads as the same box
 * rather than as a taller, looser one — the hint used to be 42px against a 34px card. */
export const CHIP_H_PX = 34
export const CHIP_MIN_H = 'min-h-8.5'

/** A vertical DropSlot's own box and margins, owned here so the filler that REPLACES the slots
 * can reproduce them. Before this, BranchLanes carried a hand-copied `my-0.5 h-2` spacer with a
 * comment telling the next reader to keep it in sync by hand. */
export const DROP_SLOT_V = 'my-0.5 h-2'

/** The air a vertical DropSlot occupies above and below a card. The empty-list hint IS the
 * leading slot, so it has no earlier sibling to supply this and must carry it as margin. */
export const CHIP_GAP_PX = 12
export const CHIP_GAP = 'my-3'

/** The `LANE N` / `then` / `else` row above a lane's cards — one CONTROL_H, inside the lane's
 * padding. `ChipBand` (Canvas.tsx) reproduces it invisibly so a control that sits OUTSIDE any
 * lane still starts where the lanes' cards start. */
export const LANE_LABEL_H = 'h-6'
