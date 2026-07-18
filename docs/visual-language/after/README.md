# Canvas visual language — probe evidence

Measured against the running app (this worktree's Vite dev server on `:5174`, proxying `/api`
to the FakeLab devserver on `:8000`) with:

```
cd webapp/frontend && npm run probe:selftest && npm run capture -- --url http://localhost:5174 --out ../../docs/visual-language/after
```

Raw data: `probe.json` (one record per state/viewport, every violation verbatim).
Screenshots: 21 PNGs, `<state>@<viewport>.png`.

## Coverage

**Viewports (3):** 1024x720, 1440x900, 1920x1080.

**States (7):** `builder-morbidostat`, `branch-selected`, `inspector-operator-input`,
`expression-popover`, `builder-torture`, `group-scope-deep` *(added by this task)*,
`scope-switcher-long-group`.

21 state/viewport combinations, **0 setup failures**.

### Why `group-scope-deep` was added

The harness must not report a rule clean on a surface that never mounted — W12 shipped
exactly that defect. So coverage was **measured on the running app**, not argued:

| State | Rendered container depth | Zebra classes present | `bg-hatch` |
|---|---|---|---|
| `builder-torture` (main scope) | **11** | slate-50 x19, slate-100 x16 | 0 |
| `branch-selected` (`service` scope) | 5 | slate-50 x4, slate-100 x13 | **1** |
| `group-scope-deep` (`deep_group` scope) | **7** | slate-50 x7, slate-100 x14 | **1** |

The pre-existing states already satisfied the two requirements *individually* — `builder-torture`
renders 11 levels (≥3), and `branch-selected` mounts the group-scope hatch. The gap was that no
state exercised **deep nesting and group scope together**, so the depth zebra was never observed
inside a hatched scope. `group-scope-deep` loads `ui-audit-torture.json` and switches to
`deep_group`, whose body nests `serial > branch > parallel > loop > serial`.

## Per-rule violation counts

| Rule | Count (21 combinations) | Distinct findings |
|---|---|---|
| R1 `clipped-overflow` | **0** | 0 |
| R2 `truncate-without-title` | **0** | 0 |
| R3 `tiny-target` | **0** | 0 |
| R4 `sibling-height-mismatch` | **0** | 0 |
| R5 `text-contrast` | **78** | 5 |

`sibling-height-mismatch` is 0, as required. `probe:selftest` passes:
`PASS — probe found exactly the planted set: {"clipped-overflow":1,"sibling-height-mismatch":3,"text-contrast":2,"tiny-target":1,"truncate-without-title":1}`

Also measured, not a rule: `pageOverflowsViewport` is false in all 21 combinations.

## R5 `text-contrast` — first run, every violation

R5 was added in `b460ac0` and had **never been run against the real app** before this task, so
there is no "before" count to compare against; 78 is the first measurement. The 78 occurrences
are 5 distinct findings repeated across states and viewports.

**All 5 are pre-existing. 0 were caused by this increment.** Blame is against the branch base
`c1f8ed0` (`chore(main): release 0.9.0`).

### Pre-existing (not fixed in this increment)

| # | Measured | Element | Origin | States |
|---|---|---|---|---|
| 1–3 | **2.88:1** < 4.5:1 | `TabShell.tsx:35` — `<span className="mr-1.5 font-mono text-xs opacity-60">` tab numerals "1", "3", "4" | `55887a6` (2026-07-11, frontend shell) | all 7 |
| 4 | **3.20:1** < 4.5:1 | `Toolbar.tsx:166` — `<span className="text-amber-600">●</span>` unsaved-changes dot | `3f32ab1` (2026-07-17, W10 #35) | `scope-switcher-long-group` |
| 5 | **3.64:1** < 4.5:1 | `fields.tsx:29` — `<span className="text-red-500"> *</span>` required-field marker | `e8d6998` (2026-07-12, inspector) | 3 inspector states |

Findings 1–3 are one code site (three tab numerals). The `opacity-60` is folded into the text
alpha, which is what drags slate-600 from 7.58:1 down to 2.88:1.

Note on the brief's predictions: the `TabShell.tsx:35` hit was predicted and is confirmed at
2.88:1. The predicted `ProblemsPanel.tsx:32` hit **did not occur**; the amber finding is
`Toolbar.tsx:166` instead. Recorded as measured, not as predicted.

None of these three are touched by this increment (no construct tint, zebra stripe, role swatch
or hatch is involved — all three sit on plain white or the pre-existing slate-100 backdrop), so
per the task's triage rule they are recorded here and **not** fixed.

### Caused by this increment

**None.** No fix was required, and none was made.

## Proof the new surfaces were actually measured

Zero increment-caused violations is only meaningful if R5 saw the new surfaces. Each was
measured directly on the running app; every value clears the 4.5:1 AA floor:

| Surface | Construct | Header text (`text-slate-700`/`900`) | Caption text (`text-caption`) |
|---|---|---|---|
| `bg-slate-50` | serial + odd zebra | 9.90:1 | 7.25:1 (min row 4.55:1) |
| `bg-teal-50` | parallel | 9.93:1 | 7.27:1 |
| `bg-violet-50` | branch | 9.44:1 | 6.91:1 |
| `bg-fuchsia-50` | loop | 9.65:1 | 7.06:1 |
| `bg-lime-50` | for_each | 17.22:1 | — |
| `bg-slate-100` | even zebra | 17.83:1 | 6.92–7.58:1 |
| `edge-hatch` | `group_ref` | 12.00:1 | 5.10:1 |

51 distinct (surface, text-class, ratio) rows were measured across the three richest states.

**`bg-lime-50` and `bg-teal-50` did not need darkening.** The plan flagged them as the likeliest
to need a step darker for header text to clear AA; measured, they are 17.22:1 and 9.93:1. The
concern was real but the measurement does not support the change, so no change was made.

**`bg-hatch` (group scope) carries no unbacked text — by design.** The group-scope hatch mounts
(1 host) and contains 10 text nodes; **0** of them sit directly on the hatch — each has an opaque
`bg-white` backing between it and the stripes. This is why the predicted
`text-hint`-over-hatch finding (~3.86:1) does **not** appear: commit `3f38779` earlier in this
increment gave the empty-tree and drop-slot hints a conditional `bg-white shadow-sm` backing,
establishing the invariant "text must never sit on the hatch". R5's silence on the hatch is
earned, not vacuous.
