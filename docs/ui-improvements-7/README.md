# Adaptive canvas chips — measured result

Spec: [`../superpowers/specs/2026-07-25-adaptive-canvas-chips-design.md`](../superpowers/specs/2026-07-25-adaptive-canvas-chips-design.md)

Captured with `npm run capture -- --theme both` against a single-origin build of `main`
(`e549c8c`) and of this branch, same backend, same fixtures.
`probe-before.json` / `probe.json` are the two full runs.

## Probe rules

**0 violations across 114 state/viewport/theme combinations, both runs.** The rules were
already clean before this work and stay clean after it — no contrast, hit-area, truncation or
clipping regression.

The after run also had **0 setup failures**, against 2 in the before run (transient navigation
timeouts on `group-scope-roles-streams`).

## The number this work is judged on

`canvasScrollerOverflow` — the canvas's own horizontal scroller, `scrollWidth` vs `clientWidth`.
"fits" means the metric is absent: the canvas does not scroll horizontally at all. Light theme;
dark is identical (layout is a palette remap, not a variant system).

| state | 1024×720 | 1440×900 | 1920×1080 |
| --- | --- | --- | --- |
| `builder-morbidostat` | 1935 → 766 | 1935 → **fits** | 1935 → **fits** |
| `inspector-operator-input` | 1935 → 766 | 1935 → **fits** | 1935 → **fits** |
| `for-each-role-grid` | 1935 → 766 | 1935 → **fits** | 1935 → **fits** |
| `group-ref-kind-aware-args` | 1935 → 766 | 1935 → **fits** | 1935 → **fits** |
| `branch-selected` | 1701 → 905 | 1701 → 905 | 1701 → **fits** |
| `expression-popover` | 1701 → 905 | 1701 → 905 | 1701 → **fits** |
| `inspector-retry-hazard` | 1701 → 905 | 1701 → 905 | 1701 → **fits** |
| `group-scope-typed-properties` | 1701 → 905 | 1701 → 905 | 1701 → **fits** |
| `scope-switcher-long-group` | 871 → 707 | 871 → **fits** | fits |
| `ui-improvements-6` | 1095 → 1027 | 1095 → 1027 | fits |
| `group-scope-deep` | 609 → 559 | fits | fits |
| `group-scope-expression` | 575 → 451 | fits | fits |
| `group-scope-roles-streams` | 575 → 451 | fits | fits |
| `builder-torture` | 3642 → 1770 | 3642 → 1770 | 3642 → 1770 |
| `inspector-tail-*` (4 states) | 3642 → 1770 | 3642 → 1770 | 3642 → 1770 |
| `inspector-bool-param-toggle` | 3642 → 1770 | 3642 → 1770 | 3642 → 1770 |

**13 of 57 measured state/viewport combinations stopped scrolling horizontally. Every single
one narrowed; none got wider.** The canvas client width is 382px at 1024×720, 798px at
1440×900 and 1278px at 1920×1080.

Headline: **`builder-morbidostat` at 1440×900 went from a 1935px scroller to no scroller at
all** — the whole workflow, including its 3-lane parallel and the `+ lane` button, inside the
viewport.

## What is left, and why

The floor states (`builder-torture` and friends at 1770px, `branch-selected` at 905px) are
Cause C in the spec — `min-w-48` (192px) on every parallel lane and branch arm, multiplied by
nesting. `builder-torture` nests to six columns; morbidostat's `service` group nests
`branch → branch → branch` = eight. No amount of text reflow touches that number, and the
192px floor is deliberately kept (spec §1.3): deep nesting is the exceptional document
horizontal scroll exists for.

What DID change for those states is that they are now floor-bound rather than content-bound —
torture halved (−51%) because its long device names no longer vote on the canvas's width at
all. That is the invariant this work buys: **no card's text can widen the canvas; only lane and
arm floors can.**

## Screenshots

`screenshots/` holds before/after pairs at 1440×900 in both themes for the three states that
show the change best. The full 114-shot runs are reproducible with the command above; only
these twelve are committed.

| pair | shows |
| --- | --- |
| `*-builder-morbidostat@1440x900-*` | the headline: 3 lanes + `+ lane` now inside the viewport, cards wrapped to 4 lines inside each lane, top-level cards still on one line |
| `*-branch-selected@1440x900-*` | the 8-column `service` group — still scrolling, but 47% narrower |
| `*-builder-torture@1440x900-*` | long device names no longer contributing; the remaining width is floors |
