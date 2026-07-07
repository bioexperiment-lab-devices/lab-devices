# Experiment Orchestrator — Design

- **Date:** 2026-07-07
- **Status:** Draft for review
- **Depends on:** `lab_devices` core driver library (this repo)

## 1. Purpose & scope

A declarative workflow-orchestration layer on top of the `lab_devices` core. The
operator describes an experiment as a tree of composable **blocks** — nested and
arranged serially or in parallel — saved as a portable text file, and the engine
executes it against real hardware (pumps, valves, densitometers) with
device-safe scheduling and guaranteed safe shutdown.

Non-goals for v1: a GUI, a bespoke authoring language, closed-loop recovery
(auto-resume after a device drops), and parametrized/macro groups. Each is called
out in §16 as a deferred extension.

## 2. Core principle: everything is blocks, across two planes

The user-facing model is uniform composition: **every unit is a block**, and
blocks nest. But the system has two distinct planes, and keeping them separate is
what makes experiments reproducible:

- **Block plane** — the reproducible experiment definition. Deterministic,
  portable, the thing you save and share. The entire AST lives here.
- **Control plane** — the operator's out-of-band actions on *this run's
  environment* (pause, abort, re-scan the bus). Never part of the saved artifact.

This split is load-bearing: environmental actions must *not* be expressible as
blocks, or a saved workflow would encode "and then I re-scanned the USB bus" and
stop being reproducible.

## 3. The narrow subset of `lab_devices` the orchestrator uses

The orchestrator deliberately uses a small, curated slice of the core API, in
**two tiers**.

### 3.1 Block-plane verbs (used inside the AST)

| Category | Core surface |
|---|---|
| Device selection | `LabClient.pump/valve/densitometer/device(id)` |
| Self-completing jobs | `pump.dispense`, `valve.set_position`, `densitometer.measure`/`measure_blank`; the `Job` handle's `.result(timeout=…)` and `.cancel()` |
| Instant config | `valve.configure`, `valve.home`, `densitometer.set_tube_correction`, `calibrate_tube`, `pump.set_calibration` |
| Continuous modes | `pump.rotate`, `densitometer.set_led`, `set_thermostat` (+ their teardowns) |
| Teardown / safe state | `device.stop`, `densitometer.stop_monitoring` |

### 3.2 Control-plane methods (used out-of-band, §14)

| Tier | Methods | Safety |
|---|---|---|
| Lifecycle | pause, resume, abort→finalize | governs the run |
| Introspection (read-only) | `list_devices`, `agent_info`, device `status`/`ping` | always safe |
| Recovery (mutating, guarded) | `rediscover`, guarded `disconnect`/reconnect | only when target device idle, or forces a finalize of affected work first |

### 3.3 Deliberately excluded

`start_monitoring` **as a measurement mechanism** (the orchestrator drives
discrete `measure()` calls so each read carries its own timestamp and cadence);
`get_readings`; `read_raw`, `rotate_raw` (low-level); `Job.refresh`/`get_job`
(wrapped by `.result()`); `PumpJob.pause/resume` (job-level, distinct from
workflow pause). Note `stop_monitoring` is *not* excluded — it is a defensive
finalizer primitive even though monitoring is never *started* by the orchestrator.

## 4. Command trait model

The three command "categories" (job / instant / continuous) are a projection of
**two orthogonal traits**, because they don't map onto one transport
distinction: `measure()` returns a `Job` (self-completing) yet leaves no state;
`rotate()` returns immediately yet leaves a mode that must be actively stopped.

Every command carries:

- **`completion`**: `job` | `immediate` — how the block knows it is done.
- **`state_effect`**: `none` | `mode` — whether it leaves an ongoing mode needing teardown.

The three named categories are derived views:

| Category | completion | state_effect |
|---|---|---|
| Job command | `job` | `none` |
| Instant read/config | `immediate` | `none` |
| Continuous mode | `immediate` | `mode` |

Each subsystem reads exactly one trait: the **scheduler** reads `completion` (when
does the device's affinity-lock release?); the **finalizer** reads `state_effect`
(what must I actively stop?).

Traits are looked up from a **`(device-type, verb) → {completion, state_effect,
teardown}` registry** — the single source of truth for which verbs exist and how
they behave. A `CommandBlock` is one block type; it does not encode traits in its
class.

## 5. Block taxonomy (the AST)

One uniform `Block` node: `id`, optional `label`, type-specific fields, and
`children` where the type has them. Three families.

### 5.1 Action blocks (leaves)

| Block | Fields | Notes |
|---|---|---|
| `Command` | `device`, `verb`, `params: {name → ValueExpr}` | Traits looked up from the registry. Covers job commands, instant config, mode-starts, and mode-stops (e.g. `stop`) alike. |
| `Measure` | `device`, `verb`, `into: <stream>` | A job-`Command` whose `(timestamp, value)` result is appended to a named stream. |
| `OperatorInput` | `name`, `type`, `prompt`, constraints | Binds a scalar the operator enters mid-run. Blocks its own lane until entered; other parallel lanes keep running. |

### 5.2 Container blocks

| Block | Fields |
|---|---|
| `Serial` | ordered `children`, per-child `gap_after` (§9) |
| `Parallel` | concurrent `children` (must be device-distinct), per-child `start_offset` (§9) |
| `Loop` | `mode` (§8), `body` |
| `Branch` | `if: <condition>`, `then`, optional `else` |
| `Group` | `name`, `body` — reusable; invoked by `GroupRef` |

### 5.3 Data plane (declarations + expressions, not flow)

- **`Stream`** declarations at top level: `{name, units?, persistence-override?}`.
- **`ValueExpr`** = literal | binding-ref | `stat(fn, window)` | arithmetic.
  Fills any scalar slot: params, thresholds, counts, durations, intervals.
- **`Condition`** = a boolean `ValueExpr` (comparisons + `and`/`or`/`not`). Feeds
  `Branch` and the conditional `Loop`.

## 6. Data plane: streams, expressions, conditions

Two kinds of shared workflow state:

- **Streams** — append-only, timestamped series produced by `Measure`, consumed
  by statistics. Named, optional units.
- **Bindings** — scalars produced by `OperatorInput`, referenced by name.

**One expression sublanguage** serves everything (this is why "condition" and
"parameter" stopped being two concepts): a condition is a *boolean* expression, a
feedback parameter is a *numeric* expression, both built from the same terms and
operators, evaluated at the instant the block dispatches.

Grammar (informal):

```
expr    := term (op term)*                 # + - * /, comparisons, and/or/not
term     := literal | binding | stat | "(" expr ")"
binding  := <name>                          # from OperatorInput
stat     := fn "(" stream ["," window] ")"  # fn ∈ {last,mean,min,max,count}
window   := "last=" N | "last=" T | (default: all)   # N samples or T duration (e.g. 5min)
```

Stat vocabulary is kept small: `last, mean, min, max, count` over windows
`all | last=<N samples> | last=<T duration>`.

**Missing-data rule (fail-safe everywhere).** Any expression that cannot produce a
value at runtime — empty/insufficient stream window, unbound binding,
divide-by-zero — **fails its block and triggers the finalizer**. One uniform rule,
no silent fallbacks, no context-specific behavior. Consequence: a conditional
loop that reads a stream must have data before its first check — which the
post-test loop (§8) provides for free, and the pre-test loop requires the author
to pre-seed.

## 7. Feedback control

Because a parameter can be any numeric expression, closed-loop control is
first-class: `dispense(volume_ml = "2.0 * (target - mean(OD, last=100))")`. The
cost is entirely absorbed by the fail-safe rule (§6) — a feedback param that
resolves to no-data never fires a garbage value; it fails the block and finalizes.

## 8. Loops (three kinds)

`Loop.mode` is one of:

- **`count`** — `{ count: N, pace: D? }`. Repeat N times; if `pace` is set, each
  iteration is paced to duration D. Pacing is a **floor, not a deadline**: a body
  that finishes early waits out the remainder of D; a body that overruns D is
  never cancelled mid-flight (that could interrupt a dispense) — it runs to
  completion and the next iteration starts immediately.
- **conditional** — `{ until: <condition>, check: before | after }`. The
  condition has **one fixed meaning: the loop runs until it becomes true**
  (continues while false). The two timings:
  - **`check: before`** (pre-test / "check then act") — test first; zero
    iterations if already true; otherwise run body, repeat. Cold-start caveat
    (§6): pre-seed data or the first check errors.
  - **`check: after`** (post-test / "act then check") — run body once, then test;
    repeat. Always ≥1 iteration; no cold-start problem. The safe default.

There is **no polarity inversion** between the two timings — the operator writes
one condition and picks *when* it's checked. Genuine zero-iteration "skip if
already satisfied" semantics without the cold-start risk are expressed by wrapping
a post-test loop in a `Branch`.

## 9. Intervals

Timing is a **per-child attribute of the container**, not a block — because a
parallel stagger is a start-offset between concurrently-starting branches, with no
"block" to place there, so intervals cannot uniformly *be* blocks:

- In `Serial`: `gap_after` on a child = delay from that child's **end** to the
  next child's **start**.
- In `Parallel`: `start_offset` on a child = delay from the container's **start**
  to that child's **start** (a stagger).

Optional sugar: a `Wait(duration)` leaf inside serial flow that compiles to a
`gap`.

## 10. Groups, branching, operator input

- **Groups** are non-parametrized in v1: a named `body` invoked by `GroupRef`.
  (Parametrized "macro" groups are deferred — §16.)
- **Branch**: `if <condition> then <block> [else <block>]`. Condition is a boolean
  expression (§6).
- **OperatorInput**: typed (`float`/`int`/`enum`/`bool`), validated against
  constraints, surfaced to the operator as a pending-input request. The block (and
  only its lane) blocks until the value is entered; the value is bound for later
  reference.

## 11. Execution model — lifecycle

1. **Load** — parse the JSON to an AST.
2. **Validate** — all static (§12). A workflow that fails validation never runs.
3. **Schedule / Run** — structured concurrency (§13).
4. **Finalize** — always runs (§13.2).

## 12. Static validation rules

Proven at load, before any hardware is touched:

- **Registry** — every `(device-type, verb)` is known; params type-check against
  the verb.
- **Device-affinity** — no two commands target the same device concurrently on any
  reachable path or under any `parallel` interleaving. A `parallel` with two
  device-overlapping branches is a static error.
- **Mode lifetime** — every mode-open (`state_effect: mode`) reaches a matching
  mode-close on **every** path (both branch arms, loop back-edges); no same-device
  command falls inside a mode's open interval.
- **Data-flow** — every binding is written before read on all paths; every
  referenced stream has a prior writer on the path.

The mode-lifetime and device-affinity checks are a control-flow lifetime analysis
(balanced open/close over the CFG). This is the price of the **free start/stop**
mode model (a mode is opened by one block and closed by a later block, so it can
span arbitrary structure) — accepted in exchange for that flexibility.

## 13. Scheduler, concurrency, finalizer

### 13.1 Concurrency & mutual exclusion

- **Substrate**: structured concurrency — an `asyncio.TaskGroup` per `Parallel`
  block, giving clean nested cancellation.
- **Device-affinity mutual exclusion is enforced by the static proof (§12), not by
  runtime locks.** A continuous mode holds its device's affinity conceptually for
  its whole *scope* (open→close), spanning the blocks in between; a blocking
  `asyncio.Lock` held across that gap would *deadlock* against the very same-device
  op the validator already forbids. So locks buy nothing and add a failure mode.
- **Runtime safety net**: a live `device → {occupant, teardown}` registry plus a
  **non-blocking busy-tracker**. Each dispatch checks "is this device occupied by
  someone other than me?" A hardware `BusyError` is a proven-impossible state, so
  it is treated as a scheduler-invariant violation → finalize, never a silent
  retry.

### 13.2 Finalizer

Runs on **normal end, any block error, or operator abort**, in fixed order:

1. Cancel in-flight jobs (`device.stop`).
2. Walk the live-open-mode registry and issue each mode's teardown.
3. Unconditional, idempotent **safe-state sweep** over every device the run ever
   touched: `stop`, `stop_monitoring`, `set_led(0)`, thermostat off — including
   modes this run never started.

## 14. Pause / resume, and the control plane

**Pause = quiesce dispatch.** Stop starting new blocks; let in-flight jobs finish;
leave open modes running (rotation, thermostat) because they maintain the
experiment's physical state. Resume continues dispatch where it left off. The
invariant holds: modes are torn down only by their explicit close or the
finalizer — never by pause.

The control plane (§3.2) exposes three tiers of out-of-band operator power:
lifecycle (pause/resume/abort), introspection (read-only queries), and guarded
recovery (`rediscover`, guarded `disconnect`). None are blocks.

## 15. Serialization

**Pure JSON, single canonical format.** No second format to translate. A saved
workflow is one self-contained document — metadata + persistence + streams +
groups + blocks — portable across any lab whose device ids match, diffable, and
schema-versioned for forward evolution. Its purpose is **storing and sharing
experiment setups**; because it is pure block-plane (§2), it is reproducible by
construction.

**Expressions are infix strings** inside the JSON, not nested object trees —
because a runtime expression *evaluator* is required regardless, so a string field
is strictly less machinery than serializing an expression AST, and stays readable.

### 15.1 Persistence config

Workflow-level default with per-stream override:

```json
"persistence": { "default": "disk", "format": "jsonl" }
```

- `default`: `in_memory` | `disk`; `format`: `jsonl` | `csv`.
- A per-stream `persistence` key overrides the default for that stream.
- Applies to both measurement streams and the run log.

### 15.2 Full example

```json
{
  "schema_version": 1,
  "metadata": {
    "name": "od-feedback-feed",
    "author": "khamitov",
    "description": "Feed pump_1 by live OD until target, stirring throughout."
  },
  "persistence": { "default": "disk", "format": "jsonl" },
  "streams": {
    "OD":   { "units": "AU" },
    "temp": { "units": "C", "persistence": "in_memory" }
  },
  "groups": {
    "prime_line": {
      "body": [
        { "command": { "device": "pump_1", "verb": "dispense",
                       "params": { "volume_ml": 1.0, "speed_ml_min": 5.0 } } }
      ]
    }
  },
  "blocks": [
    { "serial": { "children": [
      { "operator_input": { "name": "target_OD", "type": "float",
                            "prompt": "Enter target OD", "min": 0.0, "max": 2.0 } },
      { "group_ref": { "name": "prime_line" } },

      { "command": { "device": "pump_2", "verb": "rotate",
                     "params": { "direction": "forward", "speed_ml_min": 2.0 } } },

      { "loop": {
          "check": "after",
          "until": "mean(OD, last=5min) >= target_OD",
          "body": [
            { "measure": { "device": "densitometer_1", "verb": "measure", "into": "OD" } },
            { "command": { "device": "pump_1", "verb": "dispense",
                           "params": { "volume_ml": "2.0 * (target_OD - mean(OD, last=100))",
                                       "speed_ml_min": 3.0 } },
              "gap_after": "30s" }
          ]
      } },

      { "command": { "device": "pump_2", "verb": "stop" } },

      { "branch": {
          "if": "last(OD) > target_OD",
          "then": [ { "command": { "device": "densitometer_1", "verb": "set_led",
                                   "params": { "level": 0 } } } ]
      } }
    ] } }
  ]
}
```

The `pump_2` rotate opens a continuous mode (free start/stop) closed by the later
`pump_2 stop`, with no `pump_2` command in between — valid under §12. The dispense
volume is a feedback expression over a binding and a stream stat.

## 16. Package structure, testing, deferred work

- **Package**: a **`lab_devices.experiment` submodule** within the existing
  package. Keeps the orchestrator shipping with the core it drives, under the same
  build/test/lint toolchain. The submodule imports only the §3 narrow-subset
  surface of the parent package.
- **Conventions**: Python ≥3.11, async, strict mypy, ruff (line length 100),
  hermetic pytest. The existing `tests/fakelab.py` fake makes the engine testable
  end-to-end with no hardware.
- **Deferred to v2**: parametrized/macro groups; closed-loop recovery
  (device-drop → finalize → `rediscover` → resume); a friendlier authoring surface
  (YAML/DSL) that emits the same JSON; validator warnings for pre-test cold-start.
