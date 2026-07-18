# Canvas visual language — probe evidence

Measured against the running app (this worktree's Vite dev server on `:5179`, proxying `/api`
to the FakeLab devserver on `:8000`) with:

```
cd webapp/frontend && npm run probe:selftest && npm run capture -- --url http://localhost:5179 --out ../../docs/visual-language/after
```

**Always pass `--url` with a port you started yourself.** A Vite left running by a *different
checkout* answers on the default port exactly as convincingly as the right one — during this
work a stale server on `:5173` was serving the main checkout while the code under test sat in
a worktree. `capture.mjs` now refuses to proceed unless the running app renders this
increment's construct tints (see "Staleness guard" below), so that mistake fails loudly
instead of reporting 21 clean states about code that is not there.

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
| R5 `text-contrast` | **0** | 0 |

**All five rules are at 0.** R5 measured 78 occurrences / 5 distinct findings on its first run;
all three code sites behind those findings were fixed in the final review pass (below), and the
re-capture reports 0. R5 has now printed 0 at least once, so it is a rule that can go red
meaningfully rather than one that is red by default and therefore ignored.

`probe:selftest` passes, which is what keeps that 0 from being a broken-rule 0:
`PASS — probe found exactly the planted set: {"clipped-overflow":1,"sibling-height-mismatch":3,"text-contrast":2,"tiny-target":1,"truncate-without-title":1}`

Also measured, not a rule: `pageOverflowsViewport` is false in all 21 combinations, and there
were **0 setup failures**.

## Staleness guard

`capture.mjs` runs one preflight before any screenshot: it loads the torture fixture and
requires the DOM to contain this increment's construct tints (`.bg-teal-50` / `.bg-fuchsia-50`,
emitted by the `parallel` and `loop` containers in that fixture's main scope). A build predating
the canvas visual language renders those containers untinted and fails the preflight with an
explanatory setup error naming the port. Any other preflight failure (no Builder tab, fixture
import never completes) is re-thrown with the same guidance rather than as a bare Playwright
timeout.

Verified by pointing the harness at the stale main-checkout server still listening on `:5173`:

```
$ node tools/capture.mjs --url http://localhost:5173 --out /tmp/stale-check
Error: SETUP ERROR — could not drive the app at http://localhost:5173 far enough to verify it.
Underlying failure: TimeoutError: locator.click: Timeout 30000ms exceeded.
  - waiting for getByRole('button', { name: /^2\s*Builder$/ })
Is something else listening on that port, or is the server not running?
Start the dev server from the checkout you mean to measure, on a port of its own, ...
```

No screenshots were written and the process exited non-zero — a silent pass converted into an
obvious failure.

## R5 `text-contrast` — the three sites fixed

Measured on the running app, before and after:

| Site | Before | After | Change |
|---|---|---|---|
| `TabShell.tsx:35` tab numerals | **2.88:1** | **4.76:1** | `opacity-60` → `text-hint` |
| `Toolbar.tsx:168` unsaved dot | **3.20:1** | **5.03:1** | `text-amber-600` → `text-amber-700` |
| `fields.tsx:31` required marker | **3.64:1** | **4.77:1** | `text-red-500` → `text-red-600` |

The tab numerals keep their hierarchy without opacity: slate-500 at full alpha stays quieter
than both the active (slate-900) and inactive (slate-600) tab label while clearing AA on the
white header. `opacity` is folded into text alpha by R5, which is what dragged slate-600 from
7.58:1 down to 2.88:1 — the reason the rule is right to reject it.

### Four further `text-amber-600` sites, fixed for consistency

`text-amber-600` measures 3.20:1 on white (2.92:1 on `bg-slate-100`) and sat on four other
meaning-carrying text nodes that no captured state currently mounts — `Inspector.tsx:409`,
`Inspector.tsx:827`, `fields.tsx:140`, `RolesSection.tsx:85`, all validation/warning strings.
R5 did not report them only because those states are not in the harness; the defect is
identical to the Toolbar dot's. Fixing the dot alone would also have left the app with two
different warning ambers. All four moved to `text-amber-700`, which was measured clear on every
background they can sit on:

| | `bg-white` | `bg-slate-50` | `bg-slate-100` | `bg-amber-50` |
|---|---|---|---|---|
| `text-amber-600` | 3.20 | 3.06 | 2.92 | 3.09 |
| `text-amber-700` | **5.03** | **4.81** | **4.59** | **4.85** |

`src/ui/icons.tsx:42` keeps `text-amber-600` for the alarm *icon*: that is non-text content
(WCAG 1.4.11, 3:1 floor), which 3.20:1 clears, and recolouring it would change the alarm
block's identity.

## R5 `text-contrast` — the first run, for the record

R5 was added in `b460ac0` and had **never been run against the real app** before this work, so
there is no "before" count to compare against; **78** occurrences / **5** distinct findings was
the first measurement. The 78 are 5 distinct findings repeated across states and viewports.

**All 5 were pre-existing. 0 were caused by this increment.** Blame is against the branch base
`c1f8ed0` (`chore(main): release 0.9.0`).

They were initially recorded and left unfixed, on the triage rule that this increment fixes what
it breaks. The final whole-branch review overturned that: a rule that has *never* printed 0 is
the "permanently red, therefore ignored" failure mode R1's own comments warn about, which makes
R5 worthless as a gate no matter who introduced the findings. All three sites were therefore
fixed, and the counts above are the re-measurement.

### The 5 findings as first measured (all now fixed)

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

None of these three is *caused* by this increment (no construct tint, zebra stripe, role swatch
or hatch is involved — all three sit on plain white or the pre-existing slate-100 backdrop).
They are nonetheless fixed here, so that R5 can print 0. Line numbers above are the pre-fix
ones; see the after-table earlier in this document for the current lines and ratios.

### Caused by this increment

**None.** Every new surface introduced by the canvas visual language cleared AA on first
measurement — see the next section.

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
