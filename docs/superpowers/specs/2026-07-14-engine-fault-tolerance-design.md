# Experiment engine — fault tolerance (retry + `on_error`)

- **Date:** 2026-07-14
- **Status:** Approved at brainstorm; not yet implemented
- **Implements:** `docs/experiment-engine-limitations.md` §0 — "No retry, and no tolerance for a
  transient device fault", all three suggested features.
- **Depends on:** Increments 1–5 (`lab_devices.experiment`), Experiment Studio W1–W6. All on main.

## 1. The problem

A block that fails, fails the run. There is no retry, no back-off, no "tolerate this and carry
on". A live morbidostat run died at **cycle 17 of 25, 23 minutes in**, on one flaky densitometer
read — a block that had already succeeded ~170 times. The faithful experiment takes 3,600
measurements over 24 h and the published one runs three weeks; at a 1-in-1000 per-read fault
probability, a 24 h run has a ~97% chance of dying. **The morbidostat cannot be run to completion
on this stack today**, and the author has no lever at all.

## 2. What we are building

Two orthogonal block-level modifiers. Together they deliver all three features §0 asks for —
the third falls out of the second for free (§2.3).

### 2.1 `retry` — survive a transient fault

```json
{ "measure": {"device": "od_meter_1", "into": "od_1"},
  "retry": {"attempts": 3, "backoff": "2s"} }
```

Legal on `command` and `measure` only. `attempts` is the **total** number of tries, not
retries-after-the-first. (§0 sketches `times: 3`, which is ambiguous; on a `pump.dispense` that
ambiguity is a dosing hazard, so we name it unambiguously.) `backoff` is a constant delay
between attempts, default `"1s"`. Exponential back-off can be added later as an optional
`factor` without a schema break.

### 2.2 `on_error` — tolerate a persistent fault

```json
{ "serial": {"children": [...]}, "on_error": "continue" }
```

Legal on **any** block. `"fail"` (default) is today's behaviour. `"continue"` absorbs a failure
at this block: the rest of this block's subtree is skipped and the parent proceeds to the next
sibling. It is a *catch*, placed on the block that should absorb the fault — put it on a tube's
service subtree and a fault costs that tube one cycle, not the experiment.

### 2.3 Per-device fault isolation — free

`_run_parallel` (`execute.py:261`) uses an `asyncio.TaskGroup`, so a lane only cancels its
siblings when it **raises**. `on_error: "continue"` on a parallel child absorbs the failure
*inside* that child's task, the TaskGroup never sees an exception, and the siblings run on.
That is §0's feature 3 — one bad vial no longer kills the other fourteen — with no separate
mechanism.

### 2.4 `defaults.retry` — apply a policy once

```json
{ "schema_version": 1,
  "defaults": {"retry": {"attempts": 3, "backoff": "2s"}},
  "blocks": [...] }
```

Applies to every `command`/`measure` that does not carry its own `retry`. Resolved at load.
Two deliberate restrictions:

- **`defaults` carries `retry` only, never `on_error`.** A blanket "tolerate everything" would
  silently make a missed *injection* survivable. Where tolerance sits is a semantic choice per
  subtree; §0 names exactly that distinction as what the morbidostat needs.
- **A default never retries a non-idempotent verb** (§4). It cannot carry `allow_repeat`
  (validation error), and it silently does not apply to verbs whose trait is not `retry_safe`.
  A blanket policy must never start retrying `pump.dispense`.

With limitation #4 (groups are not parametrized) still open, a 15-vial workflow would otherwise
need ~60 hand-copied `retry` clauses. This is what makes the feature usable at the scale §0
says it needs.

## 3. Runtime semantics

### 3.1 Which errors are retryable

Retry exists for faults the hardware or transport can recover from. Everything else fails fast —
retrying an error that will fail identically only delays the failure and muddies the log.

**Never retried, never tolerated by `on_error`** (these escape both mechanisms):

| Error | Why |
|---|---|
| `asyncio.CancelledError`, `RunAbortedError` | An operator abort must never be swallowed or delayed. |
| `InvariantViolationError` | A proven-impossible occupancy state. The static proof was violated; the safety model is broken. `errors.py:63` already says "never retried". |
| `FinalizeError` | Raised after the walk; outside any block's scope. |

**Never retried, but tolerable by `on_error`:**

| Error | Why not retried |
|---|---|
| `EvaluationError` | Empty window, unbound binding, divide-by-zero. Nothing changes in 2s — the block that would write the stream is the one failing. |
| `InvalidParamsError`, `InvalidRequestError`, `UnknownCommandError`, `UnknownDeviceError`, `NotCalibratedError`, `NotHomedError` | Author/setup errors. Will fail identically forever. |
| `BusyError` | Already mapped to `InvariantViolationError` at `execute.py:120`. |

**Retryable — everything else from the device or transport**, including `HardwareError`,
`InternalDeviceError`, `DeviceUnreachableError`, `JobFailedError`, `JobTimeoutError`,
`LabProtocolError`, and any unmapped `LabError`. This is an allow-by-default with a deny-list,
erring toward resilience: an unknown error code is more likely a transient hardware oddity than
a permanent one, and §0's whole thesis is that a transient fault must not kill a three-week run.
The fault that killed the live run — `"intensity array: record header/index mismatch"` — lands
here.

### 3.2 Retry mechanics

Retry wraps the whole `_run_action` dispatch pipeline (`execute.py:99`), not just the HTTP call:

1. `await ctx.gate.wait()` — a pause during a retry storm quiesces at the next attempt.
2. Run the pipeline: resolve → classify → occupy → invoke → complete. Params are **re-resolved
   each attempt** against fresh state — a retry is a fresh dispatch, and this is what a fresh
   dispatch does. Occupancy is acquired and released per attempt by the existing `finally`, so a
   retry re-acquires cleanly; `register_open` only fires on success, so a failed open leaves no
   phantom mode.
3. On a retryable error with attempts remaining: emit `block_retried`, `await
   ctx.clock.sleep(backoff)`, loop. The sleep is on `ctx.clock`, so `FakeClock` tests stay free
   of wall-clock.
4. On exhaustion or a non-retryable error: raise, as today.

### 3.3 `on_error: continue` mechanics

Applied in `execute_block` (`execute.py:160`). On a caught, tolerable failure it emits
`block_error_tolerated`, appends to `ctx.tolerated`, and **returns normally**.

- `gap_after` is still honored after a tolerated block — `execute_blocks` (`execute.py:152`)
  honors it unconditionally today and that stays true.
- A tolerated block may leave a device mid-operation (a pump that failed part-way through a
  dispense). The finalizer still sweeps every `touched` device at run end. Within the run, the
  next cycle simply proceeds — the author accepted this by writing `on_error: continue`. This is
  documented in the authoring reference, not enforced.
- Inside a `parallel`, tolerance is per-lane (§2.3). On the `parallel` block itself, the whole
  container is abandoned (the TaskGroup cancels the surviving lanes) and the parent continues.

### 3.4 Reporting

A run that dropped 40 samples must not look identical to a clean one.

- New run-log events: `block_retried` (`{attempt, of, error}`) and `block_error_tolerated`
  (`{error}`).
- New `RunReport.tolerated_errors: tuple[ToleratedError, ...]` where `ToleratedError` is a frozen
  `(block_id: str, error: str)`. It must be declared **after** `persistence_errors` with a
  default — `run.py:137` constructs `RunReport` positionally.
- `status` stays `"completed"`. Adding a fifth status would churn the status union in
  `types/runs.ts`, `STATUS_STYLES`, `_TERMINAL_STATUSES`, and the DB for no information the new
  field does not already carry.

## 4. Retrying a non-idempotent verb

`pump.dispense` takes a **relative** `volume_ml`. If the job fails mid-dispense and we retry, the
culture gets a double dose — silent scientific corruption, worse than a failed run. Pure reads
and absolute setters (`measure`, `measure_blank`, `valve.set_position`, `home`, `stop`, `set_*`,
`configure`) are safely idempotent. The split does not line up with `completion` or
`state_effect`, so it must be declared per trait.

**`Trait` gains one field:**

```python
retry_safe: bool = field(default=False, kw_only=True)
```

Every field after `teardown` is already `kw_only` with a default, so all 16 existing declarations
keep compiling. Annotate the idempotent verbs `retry_safe=True`; `pump.dispense` stays `False`.
Default `False` — opt in per verb, so a verb added later is conservative until someone thinks
about it.

**`retry` on a verb that is not `retry_safe` is a validation error**, unless the block opts in
explicitly:

```json
{ "command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}},
  "retry": {"attempts": 3, "backoff": "2s", "allow_repeat": true} }
```

The escape hatch keeps this un-strict — the author *can* always do it. But the opt-in lives **in
the document**, where a reviewer reading the workflow sees it. A validator warning would be seen
once at load and forgotten; "this block may double-dose a culture" deserves to be durable and
greppable.

`retry_safe` is also projected into `catalog.py`'s `VerbEntry` so the Studio verb picker can mark
which verbs are safe to retry.

## 5. Static analysis — the may-written stream

This is the one place `on_error` genuinely perturbs the engine's guarantees, and it needs care.

### 5.1 The problem

The phase-2 path analyzer treats a `measure` as **definitely** writing its stream
(`validate.py:407`). `_expr_reads` (`validate.py:372`) then hard-errors on a windowed stat
(`mean`/`last`/`min`/`max`) over a stream it cannot prove was written — that proof is what stops
a run dying at runtime on `EvaluationError: empty stream window`.

A `measure` with `on_error: continue` only *maybe* writes. If we say nothing, we would be
tolerating a fault to avoid a dead run while opening a **new** way for the run to die — 23
minutes in, exactly the failure mode §0 exists to eliminate.

### 5.2 The fix: guard refinement (and it closes a pre-existing gap)

**A tolerant block joins like a branch with an empty else.** In `_visit`, a block with
`on_error: "continue"` yields `_merge(entry_state, exit_state)` — the existing `_merge`
(`validate.py:337`) already computes exactly the right join (streams intersect, modes → `maybe`).
So after a tolerant `measure`, `od_1` is not provably written, and a later `mean(od_1, last=10)`
is diagnosed. **This is correct and honest**: if all ten reads in a growth loop fail, the stream
*is* empty.

The author's obligation is therefore to guard the read, and the validator's job is to check they
did. Two facts make this cheap and exact:

- **`_window_values` slices `samples[-n:]`** (`evaluate.py:162`). A *short* window is fine —
  `mean(od_1, last=10)` over 3 samples returns the mean of 3. Only a **truly empty** window
  raises (`evaluate.py:138`). So proving `count(S) > 0` is sufficient to make *any* windowed stat
  on `S` safe. Nothing needs to track counts.
- **`ExprRefs` already splits `streams_windowed` from `streams_counted`** (`analyze.py:30-31`):
  `count()` needs declaration only, never a definite prior writer. So the guard expression itself
  validates cleanly with no change.

Add one primitive to `analyze.py`:

```python
def proven_nonempty(expr: Expr) -> frozenset[str]:
    """Streams this expression proves non-empty when it evaluates True."""
```

- `count(S) > k` for k ≥ 0, `count(S) >= k` for k ≥ 1, `count(S) != 0`, and the mirrored forms
  (`k < count(S)`, `k <= count(S)`, `0 != count(S)`) → `{S}`
- `A and B` → `proven(A) | proven(B)`
- `A or B` → `proven(A) & proven(B)`
- anything else → `{}`

Apply it in exactly two places:

1. **Inside an `and`.** `_expr_reads` currently flattens the whole tree via `references()`, with
   no short-circuit awareness. Walk `and` chains left-to-right instead, letting the left operand's
   `proven_nonempty` set extend the writable-stream set available to the right operand.
2. **Inside `branch.then`.** In `_visit`'s `Branch` arm, seed `then_state.streams` with
   `proven_nonempty(b.if_)`. The `else` arm is not refined — the negation proves emptiness, which
   is not useful.

**This is not a new concession.** `evaluate.py:85` already reads:

> `# Short-circuit enables guard conditions: count(S) > 0 and mean(S) > x (§6).`

The evaluator was *designed* for this idiom and the analyzer never learned it. Guard refinement
closes that gap. It also fixes a pre-existing over-strictness — "measure inside a `branch`, read
it later" is banned today with no way to express the guard — and it does so **soundly**, with no
loosening of the no-runtime-`EvaluationError` proof.

### 5.3 What this means for an author

Tolerate the read, guard the decision:

```json
{ "measure": {"device": "od_meter_1", "into": "od_1"},
  "retry": {"attempts": 3, "backoff": "2s"},
  "on_error": "continue" },
...
{ "branch": {"if": "count(od_1) > 0", "then": [ ...the whole decision tree... ]} }
```

Scientifically this is the right shape anyway: **you must not decide on injections without a
reading.** A tube whose sensor is dead skips its cycle; its neighbours are untouched.

### 5.4 Sharp edge to document

The morbidostat's slope estimator `m = 2·(mean(last=n) − mean(last=2n)) / (n·dt)` assumes evenly
spaced samples. A dropped sample perturbs it slightly. Retry makes drops rare; a single drop in
ten biases the slope marginally and the decision is a sign test, so it is tolerable — but it is
a real caveat and belongs in the example's prose, not buried here.

## 6. Schema and the three mirrors

Both fields are **top-level block keys**, siblings of `label`/`gap_after`/`start_offset` —
consistent with each other and with how block-level modifiers already work.

The rule "a block dict = exactly one type key + a known set of block keys" is **hard-coded in
three places**. All three must learn `retry` and `on_error`, and two of them fail *silently*:

| Mirror | File | Failure if missed |
|---|---|---|
| Engine (canonical) | `serialize.py:17` `_TIMING_KEYS` | Loud: `WorkflowLoadError: block must have exactly one type key`. |
| Studio backend | `webapp/backend/experiment_studio/roles.py:11` | **Silent**: `roles.py:78` `continue`s past the block, so its `device` is never substituted from the role map and the run fails later with a confusing "unknown device". |
| Studio frontend | `webapp/frontend/src/builder/convert.ts:32` `TIMING_KEYS` | Loud in the builder (`DocConvertError`), and it also kills the read-only `records/WorkflowSnapshot.tsx`. |

`_TIMING_KEYS` is no longer only about timing — rename it `_BLOCK_KEYS` (and `BLOCK_KEYS` in the
frontend) in all three.

Round-trip is **not optional**: `block_to_dict` (`serialize.py:226`) and the frontend's
`nodeToBlock` (`convert.ts:155`) both rebuild block dicts field-by-field, so without plumbing
they would **silently drop** `retry`/`on_error` on any save. The frontend needs `retry`/`onError`
on `NodeBase` (`builder/tree.ts:9`), in `blockToNode`/`nodeToBlock`, in `BlockJson`
(`types/doc.ts:59`), and a golden round-trip case in `convert.test.ts`.

Studio UI, minimal but real: the `retry` / `on_error` controls belong in the Inspector's existing
"Timing & label" section (`builder/Inspector.tsx:83`); `retry` is disabled for verbs the catalog
reports as not `retry_safe` unless `allow_repeat` is set. `describeEvent.ts` and `EventLog.tsx`
gain arms for the two new event kinds (both already have a fallback, so this is polish, not a
break), and `_write_report` (`runner.py:143`) must add `tolerated_errors` or it is dropped from
`report.json`.

## 7. Validator restructuring

`_check_block` (`validate.py:305`) is an `isinstance` chain in which **`Serial`, `Parallel`,
`Wait`, and `GroupRef` reach no checker at all**. `on_error` is legal on all of them, so the
chain must be restructured into a real dispatch with an unconditional per-block check:

- `_check_on_error` — value is `"fail"` or `"continue"`. Runs for every block type.
- `_check_retry` — `retry` only on `command`/`measure` (`Diagnostic("block", path, ...)`);
  `attempts` an int ≥ 1; `backoff` a valid duration; `allow_repeat` a bool. On a `command`/
  `measure`, look up the trait (`_check_action`, `validate.py:155`, already does the lookup) and
  error if `not trait.retry_safe and not retry.allow_repeat`.

Duration and structural shape are checked at **load** (`serialize.py`, raising
`WorkflowLoadError`, matching how `gap_after` is handled); the semantic constraints above are
checked in `validate()` as collected `Diagnostic`s.

## 8. Testing

**Unit / engine.** A fault-injecting fake `LabClient` is the workhorse: fail the Nth call with a
chosen error class, then succeed.

- Retry: succeeds on attempt 2 of 3; exhausts and fails; never retries a deny-listed error;
  never retries `CancelledError`; back-off sleeps on the `FakeClock` (zero wall-clock);
  pause during back-off quiesces; abort during back-off cancels immediately.
- Occupancy: a retried block re-acquires and releases per attempt; a failed mode-open leaves no
  phantom `OpenMode`; the finalizer still sweeps a device whose block was tolerated.
- `on_error`: tolerated failure continues to the next sibling; `gap_after` still honored;
  tolerance on a parallel child leaves siblings running (**this is the #3 regression test**);
  tolerance on the `parallel` itself abandons the container; `InvariantViolationError` and abort
  are *not* tolerated.
- Validator: `retry` on a non-`command`/`measure` block; `retry` on `pump.dispense` without
  `allow_repeat`; `defaults.retry` carrying `allow_repeat`; a tolerant `measure` followed by an
  unguarded windowed read; the same read *guarded* by `count(S) > 0` (both `branch.then` and
  `and` forms) validating clean.
- Round-trip: `workflow_to_dict(workflow_from_dict(d)) == d` with both fields set.

**Real hardware — `windows_arm64_test_client` on lab-bridge preprod.** We have a *genuine,
reproducible transient fault* to test against, which is rare and valuable: the duplicate-serial
store race documented at the end of `experiment-engine-limitations.md`. A `parallel` block of
`set_thermostat` across the three simulated densitometers (which all alias onto
`densitometer-25-006.json`) fails **23 times in 25**. It is a real, transient, retry-curable
fault — exactly the class §0 is about.

1. Baseline: parallel `set_thermostat` × 3, no retry → reproduce the failure.
2. Same block with `retry: {attempts: 3, backoff: "1s"}` → expect it to pass. `set_thermostat`
   is an absolute setter, so it is `retry_safe` and needs no `allow_repeat`.
3. Same block with `on_error: "continue"` and no retry → expect the run to *complete*, with the
   failures in `tolerated_errors` rather than killing it.
4. Full `morbidostat-demo-speed.json` (25 cycles), updated per §9, run to completion.

## 9. The example

`examples/morbidostat.json` and `morbidostat-demo-speed.json` gain `retry` on the six
densitometer reads (three `measure_blank`, three `measure`) and `on_error: "continue"` on the
three OD reads, with each tube's decision tree guarded by `count(od_N) > 0` per §5.3. The
one-time thermostat setup can go back to being `parallel` (retry now covers the duplicate-serial
race), which reverses a workaround the example was forced into.

That makes the example the proof: the workflow §0 says "cannot actually be run to completion on
this stack today" becomes one that can.

## 10. Documentation

- `docs/experiment-engine-limitations.md` §0 — rewritten from "here is what is missing" to "here
  is what shipped", keeping the incident as the motivation. The summary table's row for §0 and
  the closing paragraph both need updating.
- `examples/README.md:165-171` — "**A single flaky sensor read will destroy your run.**" is no
  longer true. Replace with the retry/`on_error` authoring guidance, including the double-dose
  caveat and the guard idiom.
- `2026-07-07-experiment-orchestrator-design.md` §5 (block taxonomy) and §15 (serialization) —
  the closest thing to an authoring reference; both need the two new block keys and the
  `defaults` section.

## 11. Out of scope

`abort`/`alarm` blocks (§7 of the limitations doc), a validator warning-severity tier, `slope`/
`median`/`stddev` stat functions, and fixing the duplicate-serial collision itself (a lab-bridge
defect — retry papers over it here, but the state file should be keyed by device id, not serial).
