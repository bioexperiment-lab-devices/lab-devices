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
teardown, channel, params}` registry** — the single source of truth for which
verbs exist and how they behave. Beyond the original trait pair:

- **`channel`** — the independent hardware subsystem the verb occupies (pump and
  valve verbs: `motor`; densitometer `measure`/`measure_blank`/`set_led`/
  `set_tube_correction`/`calibrate_tube`: `optics`; `set_thermostat`: `thermal`;
  `stop` touches **all** of its device's channels — it is the blunt safe-state
  primitive). Affinity (§12–13) is per `(device, channel)`, so an open thermostat
  mode does not lock the densitometer's optics.
- **`params`** — per-verb parameter specs (required/optional; kind `number | int |
  bool | string`). Numeric-kind params accept expressions (§6); string-kind params
  are opaque literals, never evaluated (the core leaves e.g. `direction` values
  device-defined, so the registry does not invent enums). Dict-valued driver
  params (`speed_profile`, `job_id`) are not expressible in the AST and are
  rejected.
- **`measurement`** — flags verbs whose job result yields a scalar a `Measure`
  block may capture (`measure`, `measure_blank`).

A `CommandBlock` is one block type; it does not encode traits in its class.

## 5. Block taxonomy (the AST)

One uniform `Block` node: `id`, optional `label`, type-specific fields, and
`children` where the type has them. Three families. (The `id` is engine-assigned
at load for runtime tracking — the authored JSON carries none, per §15.2 — so it
arrives with the executor in Increment 4, not in the serialized AST.)

### 5.1 Action blocks (leaves)

| Block | Fields | Notes |
|---|---|---|
| `Command` | `device`, `verb`, `params: {name → ValueExpr}` | Traits looked up from the registry. Covers job commands, instant config, mode-starts, and mode-stops (e.g. `stop`) alike. |
| `Measure` | `device`, `verb`, `into: <stream>` | A job-`Command` whose `(timestamp, value)` result is appended to a named stream. |
| `OperatorInput` | `name`, `type`, `prompt`, constraints | Binds a scalar the operator enters mid-run. Blocks its own lane until entered; other parallel lanes keep running. |
| `Compute` | `into: <binding>`, `value: ValueExpr` | Evaluates `value` and binds a number **or** boolean into the binding namespace (overwrite → accumulator across loop iterations). No hardware. Added Increment 6 (2026-07-15). |
| `Record` | `into: <stream>`, `value: ValueExpr` | Evaluates `value` and appends the number to a **declared** stream via the same data path `Measure` uses (charted/exported for free). A stream is `Measure`-written XOR `Record`-written. Added Increment 6. |

### 5.2 Container blocks

| Block | Fields |
|---|---|
| `Serial` | ordered `children`, per-child `gap_after` (§9) |
| `Parallel` | concurrent `children` (must be affinity-distinct: no shared `(device, channel)`), per-child `start_offset` (§9) |
| `Loop` | `mode` (§8), `body` |
| `Branch` | `if: <condition>`, `then`, optional `else` |
| `Group` | `name`, `body` — reusable; invoked by `GroupRef` |

### 5.2a Block-level modifiers (amendment 2026-07-14)

Added by [`2026-07-14-engine-fault-tolerance-design.md`](2026-07-14-engine-fault-tolerance-design.md).
Both are **top-level block keys**, siblings of `label` / `gap_after` / `start_offset` — not
fields of any one block type.

| Key | Legal on | Meaning |
|---|---|---|
| `retry` | `Command`, `Measure` only | `{attempts, backoff?, allow_repeat?}`. **`attempts` is the TOTAL number of tries** (not retries-after-the-first); `backoff` is a **constant** delay, default `"1s"`, **no jitter**. Retries only transient device/transport faults — an author error, an operator abort and an `InvariantViolationError` are never retried. |
| `on_error` | **any** block | `"fail"` (default) \| `"continue"`. `"continue"` absorbs a failure *at this block*: the rest of this subtree is skipped and the parent proceeds to the next sibling. On a **child of a `Parallel`** it isolates that lane — the siblings keep running (per-device fault isolation). On the `Parallel` itself the container is abandoned and the surviving lanes cancelled. |

`retry` on a verb the registry does not mark `retry_safe` is a **validation error**;
`allow_repeat: true` is the opt-in. It does not make the verb idempotent — `pump.dispense` takes
a *relative* `volume_ml`, so a retry can **double-dose a culture**. `allow_repeat` is an explicit
acceptance of that, recorded in the document where a reviewer can see it.

A tolerated `Measure` only *maybe* writes its stream, so the path analyzer (§12) will reject a
later windowed read of it unless it is **guarded** — and the guard must use a **duration** window
(`count(S, last=D) > 0`) if the stream can go stale, because `count(S) > 0` is a whole-stream
predicate over an append-only stream and stays true forever once written. See §5.2/§5.3 of the
fault-tolerance design.

### 5.3 Data plane (declarations + expressions, not flow)

- **`Stream`** declarations at top level: `{name, units?, persistence-override?}`.
- **`ValueExpr`** = literal | binding-ref | `stat(fn, window)` | arithmetic.
  Fills any scalar slot: params, thresholds, counts, durations, intervals.
- **`Condition`** = a boolean `ValueExpr` (comparisons + `and`/`or`/`not`). Feeds
  `Branch` and the conditional `Loop`.

## 6. Data plane: streams, expressions, conditions

Two kinds of shared workflow state:

- **Streams** — append-only, timestamped series produced by `Measure` **or `Record`**
  (Increment 6), consumed by statistics. Named, optional units.
- **Bindings** — scalars produced by `OperatorInput` **or `Compute`** (Increment 6),
  referenced by name. A name is either a scalar binding or a stream, never both.

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
no silent fallbacks, no context-specific behavior. (Sole exception: `count`, which
is 0 over an empty window and a never-written stream — every declared stream is
pre-created at run start.) Consequence: a conditional
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

  Conditional loops accept the same optional `pace` (amendment 2026-07-08): each
  turn is paced to at least D — a polling floor. In a pre-test loop the next
  `until` check runs after the pace elapses; a post-test loop checks `until`
  before the pace, so exit skips the trailing sleep.

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
  the verb's param specs (unknown or missing-required params, kind mismatches, and
  expression type errors — a numeric slot fed a boolean expression, a condition
  that is not boolean — are static errors).
- **Affinity** — no two commands occupy the same `(device, channel)` concurrently
  on any reachable path or under any `parallel` interleaving. A `parallel` whose
  branches' `(device, channel)` footprints overlap is a static error; the same
  device on disjoint channels is legal.
- **Mode lifetime** — a command instance is classified *open* / *close* / *neither*
  by comparison against the registry teardown: a `state_effect: mode` verb whose
  params literally equal its teardown's params is a close; anything else
  (including any expression-valued param, conservatively) is an open; a
  `state_effect: none` verb that is some mode's teardown verb (pump `stop`) closes
  that mode. **Closes are optional** — a mode left open at any point (a branch
  arm, a loop exit, the end of the workflow) is legal, because the finalizer
  (§13.2) is the universal close; and a close with no open mode is a legal no-op
  (§15.2's example relies on this). The one hard rule: **no same-`(device,
  channel)` command may execute while a mode is possibly open on any path to it —
  except that mode's matching close** (which closes if open, no-ops if not). This
  holds through branch merges (may-open tracking) and loop back-edges (a body that
  opens without closing re-executes its open inside the still-open interval — an
  error on iteration two).
- **Data-flow** — every binding is written (`operator_input`) before read on all
  paths; every stat-referenced stream and every `Measure.into` target is declared
  in `workflow.streams`; every stat except `count` has a definite prior writer on
  every path to it (a post-test loop body counts for its own `until` check).
  `count` needs only the declaration — it evaluates to 0 on a never-written
  stream, which requires the executor to pre-create every declared stream at run
  start.

The mode-lifetime and affinity checks are a control-flow lifetime analysis
(may-open mode intervals over the CFG). This is the price of the **free
start/stop** mode model (a mode is opened by one block and closed by a later
block or by the finalizer, so it can span arbitrary structure) — accepted in
exchange for that flexibility.

## 13. Scheduler, concurrency, finalizer

### 13.1 Concurrency & mutual exclusion

- **Substrate**: structured concurrency — an `asyncio.TaskGroup` per `Parallel`
  block, giving clean nested cancellation.
- **Affinity mutual exclusion is enforced by the static proof (§12), not by
  runtime locks.** A continuous mode holds its `(device, channel)` affinity
  conceptually for its whole *scope* (open→close, or open→finalizer), spanning the
  blocks in between; a blocking `asyncio.Lock` held across that gap would
  *deadlock* against the very same-channel op the validator already forbids. So
  locks buy nothing and add a failure mode.
- **Runtime safety net**: a live `(device, channel) → {occupant, teardown}`
  registry plus a **non-blocking busy-tracker**. Each dispatch checks "is this
  slot occupied by someone other than me?" A hardware `BusyError` is a
  proven-impossible state, so it is treated as a scheduler-invariant violation →
  finalize, never a silent retry.
- **Channel-level affinity admits concurrent same-device commands on distinct
  channels** (thermostat + measure on one densitometer). The executor must either
  rely on the transport tolerating this, or serialize same-device dispatches
  transparently — without holding any lock across a mode's open scope.

### 13.2 Finalizer

Runs on **normal end, any block error, or operator abort**, in fixed order:

1. Cancel in-flight jobs (`device.stop`).
2. Walk the live-open-mode registry and issue each mode's teardown.
3. Unconditional, idempotent **safe-state sweep** over every device the run ever
   touched: `stop`, `stop_monitoring`, `set_led(0)`, thermostat off — including
   modes this run never started.

The finalizer is the *universal close*: §12 makes explicit mode-closes optional,
so any mode still open at run end — normal or aborted — is torn down here.

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

### 15.1a Workflow defaults (amendment 2026-07-14)

A top-level `defaults` section, sibling of `persistence`, resolved at load:

```json
"defaults": { "retry": { "attempts": 3, "backoff": "2s" } }
```

- Applies to every `command` / `measure` that does **not** carry its own `retry`. A block's own
  `retry` wins outright; there is no merging.
- It carries **`retry` only, never `on_error`.** A blanket "tolerate everything" would silently
  make a missed *injection* survivable, and where tolerance belongs is a semantic choice per
  subtree.
- **A default never retries a non-idempotent verb.** It cannot carry `allow_repeat` (validation
  error), and it silently does not apply to a verb the registry does not mark `retry_safe`. A
  blanket policy must never start retrying `pump.dispense`.

Without this, a 15-vial workflow would need ~60 hand-copied `retry` clauses while parametrized
groups (§16, deferred) remain unbuilt.

### 15.2 Full example

*(Amended 2026-07-14: the document below now shows `defaults`, `retry` and `on_error`, and the
guarded read they oblige.)*

> **Amendment 2, 2026-07-14 (post-review).** The first amendment guarded the `dispense` with a
> bare `count(OD) > 0` and blessed it in prose. **That was wrong, and this is the canonical
> authoring reference, so it was teaching the worst bug on the branch.** Run as it stood, with the
> densitometer dying after one read, this workflow validated clean and then issued **106 dispenses
> — 101 ml — in one simulated hour**, on a frozen `mean`, and never terminated. Every guard below
> is now a **duration** window, and the loop declares the `pace` those windows are sized from. The
> rule, in one line: **a guard in front of an actuator must prove the reading is FRESH, and only
> `count(S, last=D) > 0` does that.**

```json
{
  "schema_version": 1,
  "metadata": {
    "name": "od-feedback-feed",
    "author": "khamitov",
    "description": "Feed pump_1 by live OD until target, stirring throughout."
  },
  "persistence": { "default": "disk", "format": "jsonl" },
  "defaults": { "retry": { "attempts": 3, "backoff": "2s" } },
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
          "pace": "1min",
          "until": "count(OD, last=5min) > 0 and mean(OD, last=5min) >= target_OD",
          "body": [
            { "measure": { "device": "densitometer_1", "verb": "measure", "into": "OD" },
              "on_error": "continue" },
            { "branch": {
                "if": "count(OD, last=30s) > 0",
                "then": [
                  { "command": { "device": "pump_1", "verb": "dispense",
                                 "params": { "volume_ml": "2.0 * (target_OD - mean(OD, last=100))",
                                             "speed_ml_min": 3.0 } },
                    "gap_after": "30s" }
                ]
            } }
          ]
      } },

      { "command": { "device": "pump_2", "verb": "stop" } },

      { "branch": {
          "if": "count(OD, last=5min) > 0 and last(OD) > target_OD",
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

Reading the 2026-07-14 keys in it (amendment):

- **`defaults.retry`** covers every `command`/`measure` here that is `retry_safe` — the
  `measure` and `set_led`. It **does not** reach either `dispense`: `volume_ml` is relative, so a
  retry could double-dose. Feeding twice is a worse outcome than feeding late, and the default
  is built so that you cannot ask for it by accident. (To retry a dispense you must write
  `retry: {..., "allow_repeat": true}` on the block itself, and mean it.)
- **`on_error: "continue"` on the `measure`** buys the loop the right to survive a flaky
  densitometer — at the price of a stream that is now only *maybe* written.
- **Every read of `OD` is therefore guarded, and every guard is a DURATION window.** This is the
  rule, and it has no exceptions: **never write a bare, whole-stream `count(OD) > 0`.** It is a
  sound *static* proof (the stream holds a sample) and a worthless *freshness* check, and a guard
  in front of an actuator is a freshness check. `Stream` is append-only, so `count(OD) > 0` is
  true **forever** after the first successful read: a densitometer that dies mid-run leaves the
  guard standing while `mean` and `last` freeze on the final trace, the condition becomes a
  **constant**, and the pump fires every remaining turn on a value nobody is measuring. That is
  an **open-loop actuator on a dead sensor**, and the validator cannot catch it, because the
  workflow is perfectly well-formed. See the fault-tolerance design §5.3 — on the morbidostat the
  same mistake ran a drug pump to the undiluted stock and sterilized the vial while the run
  reported `completed`.
- **Sizing the two windows.** Both come from the loop's `pace`, which is why the loop now declares
  one (`1min`) instead of leaving its turn length implicit:
  - The `dispense` guard, `count(OD, last=30s) > 0`, must be **wider than the age of this turn's
    sample when the branch is evaluated** (the `measure` is the block immediately before it, so
    that age is one read's latency) and **narrower than the loop's `pace`**, so that the *previous*
    turn's sample — one full pace old — can never satisfy it. `read latency ≪ 30s < 1min`. A body
    that overruns its pace only makes the previous sample *older*, so the guard fails safe under
    overrun.
  - The `until` guard must be a duration `count` **no wider than the read it guards** (here
    `last=5min` guarding a `last=5min` mean), and in the **same expression** (short-circuit
    `and`), because a `wait` between guard and read would let the proof go stale. A *wider*
    window proves nothing about the read's narrower one; a whole-stream `count` proves nothing
    about any duration window at all. Either way the loop dies on an empty window. (The lattice
    runs the other way: a *narrower* duration proof is the stronger one — §5.2 of the
    fault-tolerance design.)
  - The trailing `set_led` branch reads `last(OD)` — a value that can be **stale** even while the
    stream is non-empty — so it carries the same 5-minute freshness guard. The loop's own exit
    condition all but discharges it on a normal exit: exiting *proves* a sample landed within the
    last five minutes, and only the `pump_2 stop` sits in between.
- **What a dead sensor does now.** Measured against the fake lab (densitometer dark after its
  first read): the loop dispenses on the one turn that had a reading and **never again** — 1
  dispense, then nothing, versus **106 dispenses and 101 ml in one simulated hour** under the bare
  `count(OD) > 0` this section used to show. What it does **not** do is stop: the `until` reads the
  same dead stream, so the loop cannot reach its exit condition and spins — paced, with the pump
  idle — until an operator aborts. There is no way to say "exit if the stream went stale" (no
  `elapsed()`, and no `abort` block — limitations #7 and #8 of the limitations doc). **A feedback
  loop cannot outlive the sensor it feeds back from.** The guard's job is not to make it survive;
  it is to make the failure *inert* — the difference between a run you have to kill and a run that
  kills the culture.

### 15.3 Computed values — `compute` / `record` (amendment 2026-07-15, Increment 6)

Two leaf blocks that evaluate a `value` expression and store the result; neither touches hardware.
Full design:
[`superpowers/specs/2026-07-15-experiment-orchestrator-6-computed-values-design.md`](superpowers/specs/2026-07-15-experiment-orchestrator-6-computed-values-design.md).

```json
{ "compute": { "into": "c", "value": "c * V/(V+dV) + C * dV/(V+dV)" } }
{ "record":  { "into": "c_series", "value": "c" } }
```

- `compute` binds a **number or boolean** into the binding namespace (§6). Assignment overwrites,
  so the same `compute` inside a loop is an accumulator; its value persists across iterations. A
  self-referential accumulator must be **seeded** by a prior `compute` — an unseeded one is a
  read-before-write load error.
- `record` appends a **number** to a **declared** stream (§5.3) through the same path a `Measure`
  writes, so the value is charted, CSV-exported, and readable by later stats. A stream is written
  by `Measure` **or** `record`, never both; no name is both a scalar binding and a stream.
- `value` is an infix string (or a literal), evaluated at dispatch on one `clock.now()`. `retry`
  is not legal on either block; `on_error` is (a tolerated `compute` leaves its binding at its
  previous value, which the path analyzer models as a may-write).

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
