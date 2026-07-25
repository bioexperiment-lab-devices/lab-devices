# Adaptive canvas chips — implementation plan

Spec: [`../specs/2026-07-25-adaptive-canvas-chips-design.md`](../specs/2026-07-25-adaptive-canvas-chips-design.md)
Branch: `fix/ui-improvements-7`, from `origin/main` at `e549c8c`.

Five tasks. Task 1 is pure and test-first; tasks 2–4 are the DOM change, which vitest cannot
reach (node env, no jsdom — `webapp/frontend/CLAUDE.md`), so the capture harness in task 5 is
their verification, not an afterthought.

---

## Task 1 — `splitSummary` in `summary.ts`

**Write the tests first** (`summary.test.ts`), then the function.

```ts
export function splitSummary(parts: SummarySegment[]): {
  head: SummarySegment[]
  tail: SummarySegment[]
}
```

Head is every segment up to and including the last one whose `role` is `'subject'` or `'verb'`;
tail is the rest. No segment text changes — it is a partition of the input array.

Tests:

1. One case per block kind (all 14), asserting the exact `head`/`tail` texts from the spec's §5.1
   table. Build the nodes the way `summary.test.ts` already does.
2. **Totality:** for every kind, `[...head, ...tail]` deep-equals `blockSummaryParts(node)`. This
   is what guarantees `blockSummary` stays byte-identical, so run it over the same node set the
   existing byte-identity test uses.
3. **Non-empty head for every kind** — the property §5.1 claims is unreachable-by-construction.
   If a future kind breaks it the fallback is still total, but the test should say so out loud.
4. Degenerate input: `splitSummary([])` → `{head: [], tail: []}`; an all-`detail` array → head
   empty, tail everything.

**Verify:** `npm test -- summary`

---

## Task 2 — sizing model

`Canvas.tsx`, the tree wrapper: `w-max min-w-full` → `w-fit min-w-full`. Replace the comment with
the three-regime table's reasoning from spec §3 — specifically that `fit-content` keeps the
"wide subtree scrolls the canvas rather than clipping in a nested box" property that `w-max` was
chosen for, because when min-content exceeds the viewport the wrapper takes min-content and is
by construction wide enough for every descendant.

**Verify:** `npm run build` then grep the emitted CSS in `dist/assets/*.css` for `width:fit-content`.
A class that compiles to nothing is the standing Tailwind-4 trap.

---

## Task 3 — the card header (`BlockView`)

Order matters; do it as one edit, but the pieces are:

1. Card root: add `relative group/card`. Keep `min-w-0`, `cardBorderClass`, the `group_ref`
   hatch, the selection ring.
2. **Rail** — when `swatch` is non-null, render
   `<span aria-hidden className={`absolute inset-y-0 left-0 w-1 rounded-l ${swatch}`} />` as the
   card's first child, and delete the inline 10px swatch span.
3. Header row: `items-center` → `items-start`; padding `px-2` → `(swatch ? 'pl-3 pr-2 ' : 'px-2 ')`
   — SELECTED, not appended.
4. Chevron and `KindIcon` each wrapped in `flex h-6 shrink-0 items-center` so they centre against
   the text cluster's first line. (`IconButton` is already 24px; the wrapper is what aligns the
   14px icon.)
5. Diagnostics badge moves here, right after `KindIcon`, wrapped the same way. Keep its `title`.
6. Text cluster per spec §5.2 — `flex min-w-0 flex-1 flex-wrap items-center gap-x-1 py-0.5`, with
   head (`min-w-0 shrink truncate`), tail (`min-w-0 wrap-anywhere`) and the label
   (`min-w-0 shrink truncate text-xs italic text-caption`). Keep `title={blockSummary(node)}` on
   the cluster and `title={node.label}` on the label. Per-segment role weights stay as nested
   spans — extract a local `segmentSpans(segs)` helper so head and tail share it.
7. Action cluster → `absolute right-2 top-1 items-center gap-1 rounded ...` with
   `headerFillClass(node.kind) || 'bg-white'` as backing, `shadow-sm`, and display selected by
   `selected ? 'flex ' : 'hidden '` plus `group-hover/card:flex group-focus-within/card:flex`.
   Delete the old `ml-auto` wrapper.
8. Delete the `max-w-80` / `max-w-40` comments and classes.

**Traps to respect**

- Backing and padding are SELECTIONS (`a ? x : y`), never `helper() + ' extra'` — CLAUDE.md's
  cascade rule.
- Named group `group/card`, not bare `group`: bare `group-hover:` matches ANY `.group` ancestor.
- The header keeps the drag `{...listeners}`; the overlay lives inside it and its buttons already
  `stopPropagation`, and `PointerSensor` has a 4px activation distance, so a click cannot start a
  drag.
- `items-center` on the text cluster, not `items-baseline` (spec §5.2).

---

## Task 4 — the lane header (`Lane`)

Same overlay treatment: lane root gets `relative group/lane`; the Duplicate/Delete cluster becomes
`absolute right-1 top-1` (matching the header's `px-1` and `LANE_PAD`), backed by
`interiorFillClass(useContext(DepthContext))` since a lane has no background of its own. Display
selected by `selected ? 'flex ' : 'hidden '` plus `group-hover/lane:flex group-focus-within/lane:flex`.

The diagnostics badge stays in flow, moving to just after the `lane N` label. The lane's
`max-w-40 truncate` on its label becomes `min-w-0 truncate` for the same reason as the card's.

Do NOT touch the branch arms' "remove else" button.

Leave `LANE_LABEL_H`, `CHIP_GAP`, `CHIP_H_PX` and the rest of `laneLayout.ts` alone — the lane
header stays `h-6` and the geometry PR #83 established is unchanged.

---

## Task 5 — verification

1. `npm test` (full suite — `summary.ts` is imported by `convert`/`tree` tests).
2. `npm run lint` and `tsc --noEmit` via whatever `package.json` wires up.
3. `npm run build`, then grep `dist/assets/*.css` for `fit-content` AND `overflow-wrap:anywhere`.
4. **Capture, both themes, against a build of THIS branch.** Per the worktree recipe: build the
   frontend, point the backend at it with a single-origin `STUDIO_STATIC_DIR`, run the backend
   from the repo venv, then `npm run capture -- --theme both`. Capturing against a stale build
   reports clean states about code that is not there — `capture.mjs` has a guard for exactly this.
5. Record in `docs/ui-improvements-7/`: `probe.json`, the screenshots, and a `README.md` with the
   before/after `canvasScrollerOverflow` table per state at each viewport. The acceptance number
   is `builder-morbidostat` at 1440×900 going from a 2057px scroller to none.
6. If a probe rule fires, fix the cause and re-capture — 0 violations is the bar PR #83 set.

---

## Task 6 — ship

Push, open the PR against `main` with the before/after table in the body, wait for CI green,
merge, remove the worktree.

## Rollback

Every change is confined to `Canvas.tsx` plus an additive export in `summary.ts`. Reverting the
commit restores `w-max` and the single-line header; nothing in the document schema, the store or
the backend is touched.
