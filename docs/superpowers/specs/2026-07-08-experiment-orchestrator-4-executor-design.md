# Experiment Orchestrator — Increment 4: Async Executor Design

- **Date:** 2026-07-08
- **Status:** Approved; implemented (plans 4a/4b, Increment 4)
- **Parent spec:** `2026-07-07-experiment-orchestrator-design.md` (as amended) — this doc
  elaborates §4, §6–9, §11–14 into a concrete runtime design. Where the parent spec speaks,
  it wins; this doc adds executor-level decisions the parent leaves open.
- **Depends on:** Increments 1–3 (`lab_devices.experiment` foundation, expressions,
  validator), all merged to main.

## 1. Scope

Execute a validated workflow end-to-end against a `LabClient`: recursive async execution of
the block tree, trait-driven command dispatch, live open-mode registry + non-blocking
busy-tracker, expression evaluation at dispatch time (fail-safe), the safe-shutdown
finalizer, pause/resume (quiesce) and abort, engine-assigned block ids, and an in-memory
run log behind a sink interface.

Out of scope (Increment 5): control-plane introspection tier (list_devices/status/ping
queries), recovery tier (rediscover, guarded disconnect), disk persistence sinks
(jsonl/csv).

## 2. Settled decisions

User-settled at brainstorm (2026-07-08):

| # | Decision | Choice |
|---|---|---|
| D1 | Plan decomposition | Two plans: 4a sequential executor + finalizer; 4b parallel + pause/resume/abort. One branch, one PR. |
| D2 | Same-device wire concurrency (§13.1 carry-forward) | Per-device `asyncio.Lock` held **only across each single HTTP command call** — never across job waits or mode scopes, so it cannot deadlock against the proven affinity model. |
| D3 | Test clock | Manual-advance `FakeClock` (sleeper heap; explicit `advance` / advance-to-next-deadline driver). Zero wall-clock in executor tests. |
| D4 | `persistence: disk` before Increment 5 | Reject at run start with `UnsupportedPersistenceError`, before touching hardware. No silent in-memory downgrade of data the author asked to persist. |
| D5 | Executor core shape | Module-level recursive async functions + `RunContext` (mirrors the validator's style) behind a thin `ExperimentRun` facade. |
| D6 | Validation gate | `ExperimentRun` **validates at construction** (raises `ValidationError`). The runtime's no-locks safety model is the static proof; an unvalidated workflow cannot be run. |
| D7 | Runtime open/close classification | Classified via `mode_action(device, verb, resolved_params)` on the **resolved** values actually sent. `set_led(level=<expr → 0>)` is a close at runtime even though the validator conservatively called it an open. Runtime tracks hardware truth; divergence only ever frees state earlier and the finalizer is idempotent. |
| D8 | Finalizer errors on an otherwise-successful run | `execute()` raises `FinalizeError`. A "completed" run whose hardware may still be rotating is not a success. |

Engine-level decisions settled in this doc (each marked **[settled]** where defined):
executor-owned job polling via the clock (§6); occupancy check-and-mark with no
intervening await (§7); in-flight jobs stay tracked across cancelled waits (§7); operator
input validated by the executor, fail-safe on violation, providers own re-prompting (§8);
`gap_after` honored unconditionally while a trailing loop `pace` is skipped — gap is
end→next-start (defined transitively, e.g. the next loop iteration), pace is a floor
between iteration starts (§9); `pace` honored in both loop
modes (§9); pause gates block dispatch only — job polls, offsets/gaps in progress, and the
finalizer ignore the gate (§10); LIFO teardown order (§11); registry gains `result_field`
(§14); `job_timeout` default `None` (§3).

## 3. Public API & lifecycle

```python
from lab_devices.experiment import ExperimentRun, RunOptions

run = ExperimentRun(client, workflow, options=RunOptions(...))  # validates (D6)
report = await run.execute()   # raises on failure/abort; run.report always set
run.pause(); run.resume()      # sync — flip the dispatch gate
run.abort()                    # sync — set flag + cancel root task; finalizer still runs
```

- `RunOptions` (all optional): `clock` (default `MonotonicClock`), `input_provider`
  (default: unattended provider that raises → fail-safe), `log_sink` (default
  `InMemoryRunLog`), `job_poll_interval=0.25`, `job_poll_max=2.0`, `job_timeout=None`
  **[settled: no timeout by default — jobs are bounded by hardware; abort is the
  operator's escape]**.
- `execute()` prep, in order: assign block ids (§13); **pre-create every declared stream**
  in a fresh `RunState` (Increment-3 carry-forward: `count()` = 0 on a never-written
  stream); reject disk persistence (D4) — workflow default *or any per-stream override*;
  emit `run_started`. Only then does dispatch begin.
- `execute()` is single-shot: a second call raises `ExperimentRunError`. `pause()` /
  `resume()` / `abort()` are idempotent; `abort()` before `execute()` makes `execute()`
  finalize-and-raise immediately (nothing dispatched, sweep over zero touched devices is a
  no-op).
- Lifecycle: Load → Validate (construction) → Run (`execute()`) → Finalize (always, §11).

## 4. Modules

New modules under `src/lab_devices/experiment/` (each: future-import + one-line docstring
citing its design section):

| Module | Contents |
|---|---|
| `clock.py` | `Clock` protocol, `MonotonicClock` |
| `inputs.py` | `InputRequest`, `OperatorInputProvider` protocol, `UnattendedInputProvider` |
| `runlog.py` | `RunEvent`, `RunLogSink` protocol, `InMemoryRunLog` |
| `occupancy.py` | `BusyTracker` + open-mode registry (`Occupancy`) |
| `execute.py` | recursive walker + command dispatch pipeline |
| `finalize.py` | the finalizer (§11) |
| `context.py` | `RunOptions`, `RunContext` (imported by `execute.py`/`finalize.py`; keeping them in `run.py` would be a circular import) |
| `run.py` | `assign_block_ids`, `RunReport`, `ExperimentRun` |

`errors.py` gains the run taxonomy (§15); `registry.py` gains `result_field` (§14);
`blocks.py` gains `BlockBase.id` (§13). The package `__init__` re-exports the new public
surface (`ExperimentRun`, `RunOptions`, `RunReport`, `Clock`, `MonotonicClock`,
`OperatorInputProvider`, `InputRequest`, `RunEvent`, `RunLogSink`, `InMemoryRunLog`, and
the new errors).

## 5. RunContext

One dataclass threaded through the walk (built by `ExperimentRun`, never user-visible):

- `client: LabClient` + a device-handle cache keyed by device id.
- `state: RunState` — streams (pre-created) + bindings.
- `clock: Clock`, `inputs: OperatorInputProvider`, `log: RunLog`.
- `occupancy: Occupancy` — busy slots + open modes (§7).
- `locks: dict[str, asyncio.Lock]` — per-device wire locks (D2), created lazily.
- `touched: dict[str, None]` — insertion-ordered set of devices ever dispatched to
  (marked synchronously at occupancy-mark time, so even a failed call's device is swept).
- `in_flight: dict[str, Job]` — live jobs keyed by job id, with their device ids.
- `gate: asyncio.Event` — set = running; cleared = paused.
- `abort_requested: bool`, `groups`, `options`.

## 6. Clock

```python
class Clock(Protocol):
    def now(self) -> float: ...
    async def sleep(self, seconds: float) -> None: ...
```

`MonotonicClock` = `loop.time()` + `asyncio.sleep`. **One clock feeds everything**: sample
timestamps, the evaluator's `now` (duration windows like `last=5min` are exact under
FakeClock), serial gaps, loop pacing, parallel start offsets, `Wait`, and job polling.

**[settled] Executor-owned job polling.** `Job.result()`'s internal loop calls
`asyncio.sleep` with real time, which would defeat the injectable clock. Instead the
executor polls: `while job.state not terminal: await job.refresh(); await
clock.sleep(backoff)` (backoff: `job_poll_interval` doubling up to `job_poll_max`;
deadline check against `clock.now()` if `job_timeout` is set → `JobTimeoutError`). Once
terminal, it calls `await job.result()`, which returns the payload or raises
`JobFailedError`/`JobCancelledError` **without sleeping** — terminal-state interpretation
stays in the core, unduplicated.

`FakeClock` (tests, §16): sleeper heap keyed by deadline; `advance(dt)` fires due sleepers
in deadline order with bounded settle-rounds (`await asyncio.sleep(0)` × N) between
firings so woken tasks can register new sleeps before later deadlines fire; a
`drive(clock, task)` helper alternates settle / advance-to-next-deadline until the run
task completes, and fails the test on deadlock (no sleepers, task not done) instead of
hanging.

## 7. Command dispatch pipeline (safety-critical)

For a `Command` or `Measure` with registry trait `T`, in order:

1. **Gate**: `await ctx.gate.wait()` (pause point, §10).
2. **Resolve params**: only **non-string-kind** registry slots go through `resolve(value,
   state, clock.now())` (Increment-3 carry-forward); string-kind params pass through as
   opaque literals. Resolved values are kind-checked against the `ParamSpec`: `bool`
   never satisfies a numeric slot; `int` slots accept `int` or an integral `float`
   (coerced to `int` — expression division always yields `float`, so `"8/2"` must be
   able to satisfy an int slot); non-integral values for an `int` slot fail. Any
   `EvaluationError` or kind mismatch →
   `BlockFailedError` → finalize. Fail-safe, uniform (§6 of parent spec).
3. **Classify**: `mode_action(device, verb, resolved_params)` on resolved values (D7) →
   open / close / neither.
4. **Occupancy check-and-mark — synchronous, no `await` between check and mark**, so no
   sibling task can interleave through the window **[settled]**. Slot rules mirror parent
   §12 exactly:
   - slot held by another in-flight command → `InvariantViolationError`;
   - slot held by an open mode → allowed **only** if this command is that mode's matching
     close; anything else (including a second open of the same mode) →
     `InvariantViolationError`;
   - free → mark with this block's id across all of `T.channels`.
   A hardware `BusyError` at step 5 is the same proven-impossible state →
   `InvariantViolationError` → finalize. **Never retried.**
5. **Invoke** the typed device method (`Pump.dispense`, `Densitometer.measure`, … via a
   narrow typed wrapper over `getattr(device, verb)`) — typed methods are required so
   `measure` gets its `result_model` and `dispense` its param filtering — while holding
   that device's wire lock **only across this one HTTP call** (D2). All wire calls to a
   device go through its lock uniformly: dispatches, job polls, finalizer calls (free of
   contention by then, but one rule is reviewable).
6. **Complete**, by trait:
   - `completion=job`: track in `ctx.in_flight`, poll to terminal via the clock (§6), then
     `job.result()`. **[settled]** The in-flight entry is removed only when the job
     reaches a terminal state; a cancelled wait (abort) leaves it tracked so finalizer
     step 1 stops it. Busy slots are freed in a `finally`.
   - `completion=immediate, state_effect=none`: slots freed after the call (`finally`).
   - **mode-open**: on success, register `(device, mode_verb) → (teardown verb + literal
     params, channels, block id)` in the open-mode registry; slots stay mode-held until
     close or finalizer. On failure, roll back the mark.
   - **mode-close**: issue the command; on success deregister the mode and free its
     channels. On failure the mode stays registered (block fails → finalizer retries the
     teardown best-effort; teardowns are idempotent).

Error funnel: any `LabError` from step 5/6 (other than `BusyError`) →
`BlockFailedError(block_id, cause)`. Everything propagates up the tree; a `Parallel`
TaskGroup converts sibling failures into cancellation (§9); all paths reach the finalizer
exactly once (§11).

## 8. Measure and OperatorInput

**Measure** = the job pipeline above, plus: extract the scalar named by
`trait.result_field` (§14) from the job result (typed `RawModel` attribute or raw-dict
key); missing/`None` → fail-safe `BlockFailedError`; stamp `(clock.now(), value)` —
completion-time timestamp — into `state.streams[into]`; emit `measure_recorded`. The
shared clock keeps `Stream.append`'s non-decreasing-timestamp invariant.

**OperatorInput**: `value = await ctx.inputs.request(InputRequest(name, type, prompt,
min, max, choices, block_id))`. Only this lane blocks; parallel siblings keep running.
**[settled]** The executor validates the returned value against type + constraints
(`float` accepts int|float, `int` accepts int only — providers return typed values, no
coercion — `bool` bool, `enum` str ∈ choices; bools never satisfy numeric types; min/max
for numerics) and fails the block on violation — providers own any re-prompt UX
inside `request()`. Valid → `state.bind(name, value)`, emit `input_bound`.
`UnattendedInputProvider` (default) raises immediately → fail-safe.

```python
class OperatorInputProvider(Protocol):
    async def request(self, request: InputRequest) -> BindingValue: ...
```

## 9. Container semantics

- **Serial** — children in order. `gap_after` on a child = `clock.sleep` after that
  child's end; **[settled]** honored unconditionally, including on a container's last
  child — parent §15.2 places `gap_after` on the last loop-body child to pace
  iterations, so the "next start" is defined transitively (next iteration, or whatever
  follows the container); at run end a trailing gap merely delays finalize.
- **Parallel** — `asyncio.TaskGroup`, one task per child: `await
  clock.sleep(start_offset)` (if set) → execute child. Device-distinctness is already
  proven by the validator; the busy-tracker is the safety net. A child failure cancels
  siblings (structured concurrency); the resulting `ExceptionGroup` of
  `BlockFailedError`s propagates as-is — the top-level funnel does not flatten it away.
- **Loop** — per parent §8. Pre-test (`check: before`): evaluate `until` first, zero
  iterations if already true. Post-test (`check: after`): body then check. Condition
  evaluation errors fail the loop block (fail-safe; pre-test cold-start is the documented
  authoring risk). `count` mode: N iterations. **[settled]** `pace` is a floor measured by
  the clock from iteration start, honored in *both* count and until modes, never cancels
  an overrunning body, and there is no trailing pace-sleep after the final iteration. The
  pause gate is re-checked at each iteration top.
- **Branch** — evaluate `if_` (boolean, fail-safe); run `then` or `else_` serially; no
  else → skip.
- **GroupRef** — execute the group's body inline (existence + acyclicity proven by the
  validator).
- **Wait** — gate, then `clock.sleep(duration)`.

## 10. Pause / resume / abort

**Pause = quiesce dispatch** (parent §14). `pause()` clears the gate; every block entry
and every loop-iteration top awaits it, so nothing *new* dispatches. In-flight job polls
continue (they are past the gate); sleeps in progress (gaps, offsets, paces, waits)
elapse, and the *next* block entry blocks on the gate. Open modes keep running — **no
pause path touches the open-mode registry**; modes are torn down only by their explicit
close or the finalizer. `resume()` sets the gate.

**Abort = cancel + finalize.** `abort()` sets `abort_requested` and cancels the root
execution task; cancellation propagates through nested TaskGroups (in-flight job *waits*
are cancelled; the jobs themselves are stopped by finalizer step 1). `execute()` catches
the cancellation, finalizes, and raises `RunAbortedError` if `abort_requested`, else
re-raises `CancelledError` (external cancellation must propagate — asyncio correctness);
the finalizer runs in both cases. Abort works while paused.

## 11. Finalizer — the universal close

One funnel: `execute()`'s `try/finally`. Normal end, block error, `ExceptionGroup` from a
TaskGroup, invariant violation, fail-safe evaluation error, operator abort, external
cancellation — every path reaches the finalizer exactly once, after all execution tasks
have completed or been cancelled. The gate is ignored (a paused run finalizes fully).
Fixed order:

1. **Cancel in-flight jobs**: `device.stop()` once per device holding a tracked live job
   (deduped; entries survive cancelled waits, §7).
2. **Walk the open-mode registry** in LIFO open order **[settled]** and issue each mode's
   teardown with the registry's literal teardown params.
3. **Safe-state sweep** — unconditional, idempotent, over every touched device in
   insertion order: `stop` for every device; densitometers additionally
   `stop_monitoring`, `set_led(level=0)`, `set_thermostat(enabled=False)`. This covers
   modes this run never started (e.g. a monitoring session left by a previous operator).

Best-effort throughout: every individual call is try/excepted (including
`CancelledError`); an error is logged (`finalize_step_failed`), collected, and **never
skips the remaining steps or the sweep**. Collected errors land in
`report.finalize_errors` and as `add_note` annotations on the primary error. If the run
otherwise succeeded but the finalizer collected errors, `execute()` raises
`FinalizeError` (D8); the report keeps `status="completed"` with `finalize_errors`
populated.

## 12. Run log, report, persistence

- `RunEvent(timestamp, kind, block_id, data)` — timestamps from the run clock. Kinds
  (final list in the plan): run_started/run_finished, block_started/block_finished/
  block_failed, measure_recorded, input_requested/input_bound, mode_opened/mode_closed,
  paused/resumed/abort_requested, invariant_violation, finalize_started/job_cancelled/
  teardown_issued/sweep_command/finalize_step_failed/finalize_finished.
- `RunLogSink` protocol with **sync** `emit(event)`; `InMemoryRunLog` appends to a list.
  Increment-5 disk sinks implement the same interface.
- `RunReport`: `status` (`completed | failed | aborted`), `error`, `finalize_errors`,
  `state` (the `RunState`), `log`. Always set on `run.report` before `execute()` raises.
- Persistence: `in_memory` honored (streams live in `RunState`; log in the sink); any
  `disk` default or per-stream override → `UnsupportedPersistenceError` at run start (D4).

## 13. Block ids

`BlockBase` gains `id: str | None = None` — engine-assigned, **never serialized** (parent
§5: authored JSON carries none). `ExperimentRun` assigns structural-path ids at
construction over `workflow.blocks` and every group body, matching the validator's
diagnostic paths (`"blocks[0].children[2]"`, `"groups['prime_line'].body[0]"`).
Group-body blocks are shared objects across `GroupRef` expansions and loop iterations
re-execute the same nodes, so the id is the *static* identity; dynamic occurrence context
(iteration index, expansion path) goes in run-log event `data`, not the id.

## 14. Registry addition: `result_field`

`Trait` gains `result_field: str | None` (only on `measurement=True` verbs):
`("densitometer", "measure") → "absorbance"`, `("densitometer", "measure_blank") →
"slope"`. `Measure` reads the scalar from the typed result model attribute
(`MeasureResult.absorbance`) or the raw payload key (`measure_blank` has no typed model).
Keeps "which scalar does a measurement yield" in the single source of truth.

## 15. Error taxonomy additions

```
ExperimentError
└── ExperimentRunError            # base for the runtime
    ├── BlockFailedError          # block id + path context, __cause__ = original
    ├── InvariantViolationError   # busy-slot conflict or hardware BusyError
    ├── RunAbortedError           # operator abort completed (finalizer ran)
    ├── FinalizeError             # finalizer errors on an otherwise-successful run (D8)
    └── UnsupportedPersistenceError  # disk persistence before Increment 5 (D4)
```

Raise rules: single block failure → `BlockFailedError`; parallel multi-failure → the
TaskGroup's `ExceptionGroup` of them; run failed + finalizer errors → the primary error
with finalize errors as notes; success + finalizer errors → `FinalizeError`.

## 16. Test infrastructure

**FakeLab extensions** (`tests/fakelab.py`, in place; defaults inert so the existing core
suite is untouched):

- `calls: list[tuple[device_id, cmd, params]]` — chronological record of every routed
  device command; polling reads (`get_job`) excluded by default (`record_polls=True` to
  include). This is the observable sequence E2E assertions run against.
- Error injection: `inject_error(device_id, cmd, code, message, times=1)` — a queue
  consumed on match; `code="busy"` exercises the invariant path, `"hardware_error"` the
  block-failure path.
- Job control: per-command `polls_to_complete` overrides; `hold_job(cmd)` /
  `complete_job(job_id, result=..., error=...)` for manual in-flight control (the pause
  test holds a dispense, pauses, releases, and asserts completion with no new dispatch).

**FakeClock + driver** (`tests/fakeclock.py`): as §6. **Workflow builders**
(`tests/experiment_run_helpers.py`): compact constructors for the E2E scenarios.

**Flagship E2E set** (all against FakeLab, asserting the call *sequence*; 4a lands the
sequential ones, 4b the concurrent/control ones):

1. §15.2-shaped rotate + measure-loop + feedback-dispense (in-memory persistence): exact
   dispatch sequence; loop exits on threshold; explicit `pump stop` closes the mode; sweep
   issues `stop` / `stop_monitoring` / `set_led 0` / thermostat-off; zero open modes at
   end.
2. Mid-run job failure (`hardware_error` on dispense) → full finalizer, open rotate torn
   down, `status="failed"`, original error surfaced.
3. Fail-safe expression (empty-window `mean`) → block fails → finalize.
4. `count()` = 0 over a declared never-written stream (pre-creation proof) — a `Branch`
   on `count(S) == 0` runs without any measure.
5. Operator input: scripted provider binds a value consumed by a later param; unattended
   provider → fail-safe finalize.
6. Pause: in-flight dispense completes while paused, nothing new dispatches, modes stay
   open; resume continues exactly where it left off.
7. Abort mid-run → cancel + finalize; in-flight job's device stopped; modes torn down.
8. Injected `BusyError` → `InvariantViolationError` → finalize, **no retry** (call log
   proves single attempt).
9. Parallel: `start_offset` honored (clock-asserted); one branch fails → sibling
   cancelled → exactly one finalizer pass.
10. Same-densitometer thermal+optics parallel overlap (validator-legal) runs through the
    per-device wire lock; operator-input lane blocks while the sibling lane proceeds.

## 17. Plan decomposition (D1)

- **4a — sequential executor + finalizer end-to-end**: errors, block ids, registry
  `result_field`, clock, runlog, inputs, occupancy, FakeLab extensions + FakeClock,
  dispatch pipeline, Serial/Loop/Branch/GroupRef/Wait/Measure/OperatorInput, finalizer,
  `ExperimentRun` facade, sequential flagships (1–5).
- **4b — concurrency + lifecycle control**: Parallel + start_offset, wire lock under real
  overlap, pause/resume, abort, BusyError/invariant paths, ExceptionGroup funneling,
  flagships (6–10).

Branch `feat/experiment-orchestrator-4-executor` off main; 4b stacks on 4a; single PR.

## 18. Deferred

- Increment 5: disk sinks (jsonl/csv) behind `RunLogSink`/stream persistence,
  introspection tier, recovery tier.
- Existing tickets that also bound the executor: resource caps (nesting depth /
  group-DAG expansion — runtime recursion mirrors AST depth, same ticket as the
  validator's), device-id shape check.
- Job-level `PumpJob.pause/resume` remains excluded (parent §3.3) — workflow pause is
  quiesce, never job pause.
