# Adaptive Bioreactor — Studio Grand Tour (design)

**Status:** approved brainstorm, ready to plan.
**Date:** 2026-07-21.
**Author:** lab-devices.

## 1. Why this exists

Two goals, one artifact:

1. **End-to-end test in battle conditions.** A single experiment that exercises *every*
   schema-3 engine feature and *every* device verb, run to green completion at demo speed
   against a simulated lab — so the hard runtime edges (retry absorbing a fault, per-lane
   fault isolation, mode teardown, unit casts, an alarm that actually raises, an abort that
   actually aborts) are proven, not merely present.
2. **A showcase that pushes Experiment Studio to its limit.** The same document, imported into
   Studio, demonstrates the canvas visual language, the Inspector forms, the expression editor
   (autocomplete / clickable help / instant validation), typed group-parameter editing, the
   read-only Bindings panel, draft + URL persistence, export/import round-trip, the multi-stream
   live chart, and in-run operator-input prompts.

The existing `examples/morbidostat.json` is the closest prior art and covers a lot, but it is a
single fixed control law. This document is a **superset**: an operator picks one of three control
*regimes* at run start, and the same blocks become three different experiments. That is the
narrative spine; the feature coverage rides on it.

### 1.1 Relationship to the morbidostat example

We deliberately **reuse the morbidostat's 9-role device topology** — `medium_pump`,
`drug_pump`, `waste_pump`, `medium_valve`, `drug_valve`, `waste_valve`, `od_meter_1..3` — and
its `MAPPING` onto the preprod `windows_arm64_test_client` (`pump_1..3`, `valve_1..3`,
`densitometer_1..3`). Two payoffs:

- The showcase runs on the *same* virtual lab the morbidostat already runs on, unchanged.
- The committed E2E test **extends the morbidostat's `CultureLab`** simulator (exponential
  growth, dilution on injection, drug inhibition, valve-routed pumps, noisy OD reads) rather
  than reinventing device physics.

Distinctness is carried by *what the blocks do*, not by the hardware list: regime selection,
continuous-perfusion mode, an until-loop, the full operator-input palette, and the verbs and
group-parameter kinds the morbidostat never touches (§4.2).

## 2. The science spine — a regime-switching bioreactor

Three vials, held under continuous culture. At setup the operator chooses a **regime**:

- **`turbidostat`** — hold optical density at a target. When a tube reads above `target_od`,
  inject 1 ml of fresh medium to dilute it; otherwise do nothing. Drug is never used.
- **`chemostat`** — hold a *constant dilution rate*. Medium is delivered continuously by running
  `medium_pump` in **`rotate` mode** (a continuous mode, not a discrete dose) for a settling
  window, governed by an `until`-loop, then stopped. OD is measured for the record but does not
  drive dosing.
- **`morbidostat`** — the evolution experiment: a tube out-growing its dilution above `od_thr`
  gets 1 ml of **drug**; otherwise 1 ml of medium. The believed drug concentration is tracked
  with the same recursion as `examples/morbidostat.json`.

The regime is a single `string` binding from an `enum` operator input, and the per-tube service
group branches on it with **string equality** (`regime == 'morbidostat'`). One document, three
behaviours — this is the headline the whole tour hangs on.

Every regime shares: a warm-up/calibration phase, a paced control loop over three tubes read in
parallel, a per-cycle dose-budget accounting with an alarm, and a wrap-up that returns the rig to
safe state.

## 3. Timeline (~20–25 min at demo speed)

`pace: 60s`; the main loop's `count` is the operator's `cycles` input (default 20). Structure:

- **Phase 0 — Operator setup** (`serial`): the full operator-input palette drives everything
  downstream.
  - `regime` — **enum** (`choices: ["turbidostat","chemostat","morbidostat"]`).
  - `target_od` — **float** (`min`/`max`).
  - `cycles` — **int** (`min`/`max`), feeds `loop.count` as an expression.
  - `warm_start` — **bool**, gates the warm-up phase.
  - `emergency_stop` — **bool**, feeds the whole-run abort guard (§4.4).
  Then a `compute` seeds a `dose_budget_ml` accumulator, and a `wait` whose `duration` is an
  **expression** (`settle_min * 1min`) lets the rig equilibrate.
- **Phase 1 — Warm-up & calibration** (guarded by `warm_start`): a `parallel` of a typed
  `for_each` over the three meters (`role<densitometer>` column). Per lane, with lanes staggered
  by `start_offset`/`gap_after` **duration expressions**:
  - `set_thermostat(enabled=true, target_c=30)` — thermal **mode** (retry 6, like the morbidostat).
  - `set_led(level=...)` — optics **mode**.
  - `measure_blank` — baseline (not tolerated: a failed blank stops the run).
  - `set_tube_correction` and `calibrate_tube` — calibration verbs.
  - `valve home` + `valve configure` + `pump set_calibration` — one-time rig configuration.
- **Phase 2 — Adaptive control loop** (`loop`, `count = cycles`, `pace = 60s`): each cycle
  - a whole-run `abort` on `emergency_stop` (guarded off in the happy path),
  - a whole-run `abort` on all-three-contaminated (morbidostat regime only; guarded off),
  - a `parallel` of a typed `for_each` reading all three tubes (`on_error: continue`, per-lane
    isolation), then
  - a `for_each` calling the `service` group once per tube (§4.3), then
  - a `serial` aggregate: `record` the cycle's total dose, an `alarm` when the cumulative
    `dose_budget_ml` is exceeded (fires deterministically — §4.4), and `min`/`max` stats on OD.
- **Phase 3 — Chemostat settling** (inside `regime == 'chemostat'`, per tube): open
  `medium_pump.rotate`, run an **`until`-loop** (`until: last(od) < target_od`, `check: after`,
  bounded by a max-iteration guard) polling OD, then `medium_pump.stop` (explicit **mode
  teardown**). This is where the second loop variant and the continuous mode live.
- **Phase 4 — Wrap-up** (`serial`): explicit teardown of the LED and thermostat modes we want to
  show closing; the finalizer sweeps anything left open; a final `record` of totals.

## 4. Feature coverage

### 4.1 Structural / control-flow (every block type)

`serial`, `parallel`, `loop`(count), `loop`(until+check), `branch`(with `else`), `for_each`
(typed table with `int`/`role`/`stream` columns), `group_ref` + `groups`, `command`, `measure`,
`compute`, `record`(+`as`), `operator_input`, `wait`, `abort`, `alarm`. Block-level keys on
real blocks: `label`, `gap_after`, `start_offset`, `retry`, `on_error`.

### 4.2 Device verbs (full registry sweep)

- **pump:** `dispense` (never retried), `rotate` (mode) + `stop` (teardown), `set_calibration`.
- **valve:** `set_position`, `home`, `configure`, `stop`.
- **densitometer:** `measure`, `measure_blank`, `set_led` (mode), `set_thermostat` (mode),
  `set_tube_correction`, `calibrate_tube`, `stop`.

Modes with teardown exercised: `pump.rotate → stop`, `densitometer.set_led → level 0`,
`densitometer.set_thermostat → enabled false`.

### 4.3 The `service` group — all seven parameter kinds, both local kinds

The per-tube controller is one group, called once per tube by a typed `for_each`. It is the
single place that exercises the whole kind system:

- **params:** `tube` (`int`), `target` (`number`), `regime` (`string`), `is_control` (`bool` — a
  tube measured but never dosed), `meter` (`role<densitometer>`), `od` (`stream`),
  `budget_latch` (`binding`, a shared alarm latch passed in).
- **locals:** `c` (`binding`, `init:"0"` — believed drug concentration), `contaminated`
  (`binding`, `init:"false"`), `r` (`binding`, no init — growth rate), `c_series` (`stream`,
  `units:"x_MIC"`, `persistence:"disk"`), `r_series` (`stream`, `units:"per_hour"`).
- **body:** valve → tube; `measure`; `compute r` and `record ... as "per_hour"`; a nested
  `branch` on `regime` selecting the dosing law; the morbidostat arm updates `c` and
  `record ... as "x_MIC"`; `is_control` gates whether any dose is delivered; expressions use
  `last`/`mean`/`min`/`max`/`count` with both **sample** (`last=5`) and **duration**
  (`last=45s`) windows. Holes `{name}` appear in device/into/args names, in `as`, in `label`
  interpolation, and inside expression strings; `position: "{tube}"` substitutes as a typed
  JSON integer.

### 4.4 The hard edges, made to fire deterministically in CI

- **Retry absorbs a transient fault** — a `FlakyLab`-style densitometer hiccups on a schedule;
  `defaults.retry` re-dispatches and the sample survives; it shows in `report.tolerated_errors`.
- **Per-lane fault isolation** — one lane's read fails past its retries under `on_error:continue`;
  the other two lanes of the same `parallel` keep reading.
- **Alarm raises** — the `dose_budget_ml` accumulator crosses its threshold after a fixed number
  of cycles, **independent of sensor values** (so it fires in every regime, deterministically),
  using the fire-once latch idiom (`alarm` on the edge, then a sticky `compute`).
- **Abort aborts** — proven by a **separate test variant** that answers `emergency_stop=true`,
  yielding `status == "aborted"` with the finalizer still sweeping modes off. The **main green
  run** answers `false`, so its aborts are present-but-guarded and the run completes. A second
  abort (all-three-contaminated, morbidostat regime) is likewise guarded off in the happy path.
- **Mode teardown** — thermostat/LED/rotate modes are opened and their teardown observed in the
  run's device calls (extending the morbidostat's thermostat-sweep assertion).

### 4.5 Studio UI surfaces (the showcase)

Documented in the walkthrough, verified by hand on import: canvas visual language rendering the
nested `parallel`/`for_each`/`loop`/`group_ref` tree; Inspector forms; the expression editor over
the rich guards (autocomplete, clickable help, instant validation); typed group-parameter editing;
the read-only Bindings panel (#67); draft + URL persistence; export/import round-trip; the
multi-stream live chart (`od_1..3`, `tube_N_c_series`, `tube_N_r_series`); and in-run
operator-input prompts for the Phase-0 palette.

> **Known Studio limitation (not a blocker).** Like the morbidostat, this document uses `groups`
> and `for_each`, which the block-builder canvas cannot yet *edit* (examples/README.md). It
> imports, saves, validates, runs, and renders read-only; the walkthrough says so and directs
> canvas-editing demonstrations at the non-group phases.

## 5. Deliverables

1. **`examples/adaptive-bioreactor-tour.json`** — the experiment, in the `{doc_version, name,
   description, workflow}` envelope, with a rich embedded `description` in the house style.
2. **`examples/README.md`** — a new row in the table and a walkthrough section that maps each
   feature and Studio surface to where it is seen, plus the "flip `emergency_stop` to see abort"
   and regime-switching notes (the showcase guide). Persistence-as-CSV is mentioned as a
   one-line variant rather than contorting the science for it.
3. **`tests/test_examples_adaptive_bioreactor.py`** — the committed E2E test:
   - loads / validates / expands the document;
   - pins the fault-tolerance and feature shape (as the morbidostat test pins its own);
   - runs the loop green to `completed` against an extended `CultureLab` for **each of the three
     regimes**, asserting the regime-specific dosing behaviour;
   - asserts each hard edge of §4.4 fires (retry tolerated, per-lane isolation, alarm raised,
     modes torn down);
   - a **forced-abort variant** asserting `status == "aborted"` on `emergency_stop=true`.
   The simulator subclasses (`CultureLab` and fault-injecting variants) live in the test module,
   extending the morbidostat harness in `tests/fakelab.py` / `tests/fakeclock.py`.
4. **Wiring** — the example is discoverable in `examples/` (Studio imports it directly); the new
   README row is covered by whatever guards the examples table; the E2E test joins the suite.

## 6. Non-goals / explicit scope limits

- **No engine or Studio code changes.** This is a data + test + docs deliverable. If authoring
  the document surfaces a genuine engine gap, that is a *finding* to report, not silently
  worked around — but the design is built entirely from features that already ship.
- **No biological realism claim.** Demo-speed intervals are biologically meaningless, stated
  loudly in the embedded description, exactly as the demo-speed morbidostat does.
- **CSV persistence** is not exercised in the shipped document (format is document-global; the
  science wants `jsonl`); it is documented as a variant only.
- **The `windows_arm64_test_client` live run** reads flat/near-zero OD, so the *sensor-driven*
  regime behaviour and the contamination abort can only be proven on the `CultureLab` simulator;
  the live run proves it loads, maps, runs to completion, and drives the modes and the live chart
  — the same honest split the morbidostat design documents.

## 7. Risks

- **Determinism of the alarm and fault edges.** Mitigated by driving the alarm off a
  cycle-counted accumulator (not sensor values) and by scheduling faults on fixed read counts, as
  the morbidostat's `FlakyLab` already does.
- **Pace-coupled constants.** The freshness-window / slope constants are tied to `pace` and
  `count` exactly as in the morbidostat; the embedded description must carry the same warning and
  the test must pin the values.
- **Scope creep toward a second engine feature.** Held off by §6: every block is drawn from the
  shipped feature set; the artifact's ambition is *coverage and legibility*, not new capability.
