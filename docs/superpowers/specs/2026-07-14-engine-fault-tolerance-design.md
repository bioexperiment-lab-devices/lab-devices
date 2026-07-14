# Experiment engine — fault tolerance (retry + `on_error`)

- **Date:** 2026-07-14
- **Status:** **Implemented** (2026-07-14). Two sections carry post-implementation amendments
  where the draft was wrong: **§5.3** (a bare `count(S) > 0` guard does *not* skip a dead
  tube's cycle — it latches an open-loop drug injector) and **§5.4** (the decision is *not* a
  sign test). Both are marked in place. §1 below is the problem statement as it stood before
  the feature; it is history, not current behaviour.
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
did. Two facts about the evaluator set the shape of that check:

- **`_window_values` slices two different ways** (`evaluate.py:161-166`). A `SampleWindow` is
  `samples[-n:]`, so a *short* window is fine — `mean(od_1, last=10)` over 3 samples returns the
  mean of 3, and the slice of a non-empty stream is never empty (the parser rejects `n <= 0`). A
  `DurationWindow` is sliced by **timestamp cutoff** (`now - seconds`), so it can be empty *while
  the stream is not*. Only a **truly empty** window raises (`evaluate.py:139`).
- **`ExprRefs` already splits `streams_windowed` from `streams_counted`** (`analyze.py:30-31`):
  `count()` needs declaration only, never a definite prior writer, and it returns `0` rather than
  raising. So the guard expression itself validates cleanly with no change, whatever its window.

> **A guard is a claim about a *window*, not about a stream.** An earlier draft of this section
> claimed that "proving `count(S) > 0` is sufficient to make *any* windowed stat on `S` safe —
> nothing needs to track counts." **That is false, and it was the origin of a real bug.** It holds
> for sample windows; it fails for duration windows, and it fails in exactly the scenario this
> feature exists to serve. A sensor that stays down for six minutes is precisely what
> `on_error: continue` lets a run survive — and precisely what ages the newest sample out of a
> five-minute window. `count(od_1) > 0` stays true on the stale samples while
> `mean(od_1, last=5min)` goes empty, so
> `count(od_1) > 0 and mean(od_1, last=5min) > 0.4` would have validated clean and then killed the
> run with `EvaluationError: empty stream window` — the very error the feature exists to prevent.

**The sound lattice.** A guard `count(S, W_guard) > 0` proves that **`W_guard`** holds a sample.
That discharges a read `stat(S, W_read)` only when non-emptiness of `W_guard` *implies*
non-emptiness of `W_read`:

| guard | discharges no-window read | discharges `last=N` (samples) | discharges `last=D_read` (duration) |
| --- | --- | --- | --- |
| none (`count(S) > 0`) | yes | yes | **no** |
| `last=N` (samples) | yes | yes | **no** |
| `last=D_guard` (duration) | yes | yes | **only if `D_read >= D_guard`** |

Every guard form implies the stream holds ≥ 1 sample, which is what makes the first two columns
free. A duration guard proves strictly more — a sample landed within `D_guard` of `now` — and a
read over a **wider** window contains the guard's window, so it inherits that sample. One
`evaluate` call threads a single `now` (`evaluate.py:30`), so the two windows are measured from the
same instant. A sample-count guard proves nothing a bare `count(S) > 0` does not, so it collapses
into the first row and the lattice stays two-level: *non-empty stream* < *sample within D*.

Add two primitives to `analyze.py`:

```python
ProvenWindows = Mapping[str, Window]          # stream -> the window proven non-empty

def proven_nonempty(expr: Expr) -> dict[str, Window]:
    """Streams this expression proves non-empty when it evaluates True, with the window."""

def proof_covers(proven: Window, read: Window) -> bool:
    """Does "`proven` holds a sample" imply "`read` holds a sample"?  (the table above)"""
```

- `count(S, W) > k` for k ≥ 0, `count(S, W) >= k` for k ≥ 1, `count(S, W) != 0`, and the mirrored
  forms (`k < count(S, W)`, `k <= count(S, W)`, `0 != count(S, W)`) → `{S: W}`, with a sample
  window normalised to `AllWindow`
- `A and B` → union, keeping the **strongest** proof per stream (a narrower duration wins)
- `A or B` → intersection, keeping the **weakest** proof per stream (a wider duration wins)
- anything else → `{}`

Apply them in exactly two places:

1. **Inside an `and`.** `_expr_reads` currently flattens the whole tree via `references()`, with
   no short-circuit awareness. Walk `and` chains left-to-right instead, letting the left operand's
   `proven_nonempty` map extend the proofs available to the right operand, and discharge each read
   through `proof_covers`. The whole expression shares one `now`, so a duration proof is valid
   across it.
2. **Inside `branch.then`.** In `_visit`'s `Branch` arm, seed the `then` state with the streams
   `proven_nonempty(b.if_)` names. **Only the stream-level fact crosses the boundary**, as the
   *durable* part of the proof: `Stream` is append-only, so "holds ≥ 1 sample" can never be
   invalidated, whereas a duration proof **decays** — `now` advances while the body runs, and a
   `wait: 10min` inside `then` would age the guard's sample straight back out of the read's window.
   So a duration-windowed read inside the body needs its own guard, in its own expression. The
   `else` arm is not refined at all — the negation proves emptiness, which is not useful.

> **A pre-existing gap, deliberately left open.** A *definite* (untolerated) `measure` proves
> `len(samples) >= 1` and nothing more — so by the table above it does not prove a duration window
> non-empty either, yet `_PathState.streams` discharges every window including duration. A plain
> `measure`, a `wait: 10min`, then `mean(od_1, last=5min)` therefore validates clean today and can
> raise at runtime. This predates guard refinement, and closing it is a **separate strictness
> change**: it would newly reject workflows that validate today. It is scoped out on purpose —
> guard refinement's job is only to stop a *guard* from over-promising. The two are not
> symmetric in practice: a definite measure fails the run outright when the sensor dies, so it
> never reaches the stale-window state that `on_error: continue` is built to survive.

**This is not a new concession.** `evaluate.py:85` already reads:

> `# Short-circuit enables guard conditions: count(S) > 0 and mean(S) > x (§6).`

The evaluator was *designed* for this idiom and the analyzer never learned it. Guard refinement
closes that gap. It also fixes a pre-existing over-strictness — "measure inside a `branch`, read
it later" is banned today with no way to express the guard — and it does so **soundly**, with no
loosening of the no-runtime-`EvaluationError` proof.

### 5.3 What this means for an author

> **Amendment, 2026-07-14 (post-implementation).** As drafted, this section said *"a tube whose
> sensor is dead skips its cycle"* of a bare `count(od_1) > 0` guard. **That is false, and it is
> the most dangerous sentence in this document.** `count(S) > 0` with no window is a predicate
> over the **whole** stream, and `Stream` is **append-only** — so once a tube has read even once
> it is true *forever*. A sensor that dies mid-run leaves the guard **standing**, while
> `last(od)` and both trailing means freeze on the last successful trace. The condition becomes
> a **constant**: the same arm fires every remaining cycle with no feedback at all, and since a
> healthy vial is above `OD_THR` and out-growing its dilution by construction, the arm that
> latches is frequently **drug**. Each latched cycle walks the §1 concentration recursion toward
> its fixed point, `C` — the undiluted stock. That is an open-loop drug injector on a dead
> sensor: it **sterilizes the vial while the run reports `status: "completed"`.** Measured (tube
> 3's sensor killed after cycle 1 of 120): 120/120 injections were drug, `c` → 9.999 = Stock A,
> OD → 0.0003, a **1,600× collapse**.
>
> A bare `count(S) > 0` detects a sensor that **never worked**. It cannot detect one that has
> **newly died**, which is the only failure this feature is exposed to. Only a **duration**
> window can — it proves a sample landed *recently*, which no whole-stream predicate can.
>
> **The corrected rule: if you tolerate a `measure`, guard the read with a duration window,
> `count(S, last=D) > 0`, sized to the control loop** — long enough to span one cycle's
> sampling, short enough to expire within one cycle. The shipped example uses `last=11min`
> (growth phase 10 × 1 min = 10 min < **11 min** < 12 min cycle pace); the demo-speed doc scales
> it to `last=45s` (30 s < 45 s < 60 s). Note that this constant is coupled to the loop's pace
> and **the engine cannot check it** — there is no freshness primitive and no way to derive one
> from a loop's own `pace`. It is a sharp edge, and it is the price of tolerance.
>
> The lattice in §5.2 is unaffected and was right: it is this section's *application* of it that
> was wrong. Regression test: `test_a_dead_sensor_does_not_latch_an_open_loop_injector`.

Tolerate the read, guard the decision — with a **freshness** guard:

```json
{ "measure": {"device": "od_meter_1", "into": "od_1"},
  "retry": {"attempts": 3, "backoff": "2s"},
  "on_error": "continue" },
...
{ "branch": {"if": "count(od_1, last=11min) > 0", "then": [ ...the whole decision tree... ]} }
```

Scientifically this is the right shape anyway: **you must not decide on injections without a
reading.** A tube that produced no reading *this cycle* skips its cycle entirely — no injection
of either kind — and its neighbours are untouched.

~~That bare `count(od_1) > 0` covers a decision tree built from sample windows (`last=5`,
`last=10`) and whole-stream stats — which is what the morbidostat uses.~~ *(Struck by the
amendment above: it is sound as a static proof and unsound as a freshness check.)*
**If the tree reads a *duration* window, the guard must name that window and sit in the same
expression as the read:**

```json
{ "branch": {"if": "count(od_1, last=5min) > 0 and mean(od_1, last=5min) > od_thr",
             "then": [ ... ]} }
```

A bare `count(od_1) > 0` does not prove the last five minutes hold anything (§5.2), and a duration
guard in an enclosing `branch.if` does not survive into a body that can `wait`.

### 5.4 Sharp edge to document

The morbidostat's slope estimator `m = 2·(mean(last=n) − mean(last=2n)) / (n·dt)` assumes evenly
spaced samples. A dropped sample perturbs it. Retry makes drops rare, and it is tolerable — but
it is a real caveat and belongs in the example's prose, not buried here.

> **Amendment, 2026-07-14 (post-implementation).** As drafted, this section justified that with
> *"the decision is a sign test"*. **That is false.** The *published* rule (ΔOD > 0) is a sign
> test; the example does not implement that rule. It re-expresses the decision as
> `24 * (mean(last=5) - mean(last=10)) / last(od) > r_dil` — a **threshold test at `r_dil`**, a
> positive setpoint. Worse, by the controller's own design invariant (`r_dil = r₀/2`) the
> culture is **pinned at that threshold in steady state**, so its decisions are *habitually
> marginal* — precisely the regime in which a small bias flips one. "Sign test" was exactly the
> wrong reassurance.
>
> Two things the drafted section also got quantitatively wrong. The perturbation is not small,
> and it is not what you would guess: `mean(od, last=10)` is a **sample** window
> (`samples[-10:]` over an append-only stream), so on a lossy cycle it always still returns ten
> values and therefore reaches **back across the cycle boundary**, pulling in the previous
> cycle's pre-injection samples — ~6–8% higher in OD, and a full cycle older. The window is
> *wider* than intended, not narrower, and it straddles a dilution discontinuity. Simulated on
> the faithful doc against a true `r` of 0.8/h: one dropped sample biases `r_est` by −11.5% to
> +3.9% (worst case **−15.5%**); three drops in one cycle, −12.6%.
>
> **The correct justification is the cost of a flip, not its rarity.** The bias is bounded and
> **downward** — toward *withholding* drug, the conservative direction. A flipped decision costs
> **one wrong 1 ml injection**; **ΔV is identical in both arms**, so the dilution rate — the
> quantity the whole controller rests on — is untouched either way; and the bang-bang loop
> self-corrects on the next clean cycle. (Simulated: a tube riding out ~40 transient faults
> still lands at drug ≈ 1.24 ≈ IC₅₀, the same place as the fault-free control.) The conclusion
> ("tolerable") stands; the reasoning that produced it did not.

### 5.5 The same join applies to modes, not just streams

`_merge(entry, exit)` (§5.2) is the whole `_PathState` join, not a streams-only special case — it
also intersects `modes` (`validate.py`'s `_merge`, used by every tolerant block via `_visit`). So a
tolerated **mode-closing** command (its `close` dispatch is on the `on_error: "continue"` block)
leaves that mode `"maybe"` open rather than closed: the entry state still has it `"open"`, the exit
state has it popped/closed, and the join of `"open"` with absent is `"maybe"`, exactly as an
unresolved tolerated *open* is today. A later command on the same channel then draws the existing
"possibly open interval" diagnostic. This is honest — the close may genuinely not have happened —
and nothing spuriously breaks, because there is no end-of-workflow unclosed-mode check to trip. It
is a behaviour change beyond streams that the rest of §5 does not otherwise scope to, recorded here
for completeness.

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
`densitometer-25-006.json`) fails **8 times in 25 (32%)** — re-measured through the engine's
executor on 2026-07-14, and **29/75 (38.7%)** across all thermostat trials that day. (This
section was drafted against an earlier figure of 23/25 = 92%, taken with raw parallel client
calls; the fault is the same fault — same file, same two sharing-violation variants — but it is
roughly a third as frequent as first recorded. **32% is the current number.**) It is a real,
transient, retry-curable fault — exactly the class §0 is about, and frequent enough to test
against.

1. Baseline: parallel `set_thermostat` × 3, no retry → reproduce the failure.
2. Same block with `retry: {attempts: 3, backoff: "1s"}` → expect it to pass. `set_thermostat`
   is an absolute setter, so it is `retry_safe` and needs no `allow_repeat`.
3. Same block with `on_error: "continue"` and no retry → expect the run to *complete*, with the
   failures in `tolerated_errors` rather than killing it.
4. Full `morbidostat-demo-speed.json` (25 cycles), updated per §9, run to completion.

## 9. The example

`examples/morbidostat.json` and `morbidostat-demo-speed.json` gain `retry` on the six
densitometer reads (three `measure_blank`, three `measure`) and `on_error: "continue"` on the
three OD reads, with each tube's decision tree guarded by a **duration-windowed freshness guard**
per §5.3's amendment: `count(od_N, last=11min) > 0` in the faithful doc (growth phase 10 × 1 min
= 10 min < **11 min** < 12 min cycle pace) and `count(od_N, last=45s) > 0` in the demo-speed doc
(30 s < **45 s** < 60 s).

*(As drafted, this section said `count(od_N) > 0` — the whole-stream form. **That is the bug
§5.3's amendment exists to retract**, and it is not what shipped: a bare `count` is true forever
on an append-only stream, so it cannot see a newly dead sensor, and it latches the drug arm open.
The shipped examples use the duration windows above.)*

The one-time thermostat setup can go back to being `parallel` (retry now covers the
duplicate-serial race), which reverses a workaround the example was forced into.

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

### 11.1 Deferred to v2, and named — the warning tier, and `on_error` on an actuation

Carried out of the final review of this increment (2026-07-14). **Not built. Recorded so it is
not re-derived from scratch, and so the reason it matters is not lost.**

**What.** A **warning severity tier** in the validator (today every diagnostic is an error, so
there is nowhere to put a "this is probably wrong" finding), and, on top of it, a check that
**flags `on_error` on an *actuating* command** — a `pump.dispense`, a `valve.set_position`, a
`densitometer.set_thermostat`: any verb whose trait moves the world rather than reading it. The
registry already carries what the check needs (`retry_safe` is the closest existing marker; a
dedicated `actuating` / `read_only` trait flag would be the honest one). The warning would name
the block and say what it costs: *the world is left in an unknown state and every block after
this one inherits it.*

**Why it is worth doing.** The hazard is currently **prose only** — "Tolerance is for reads", in
`docs/experiment-engine-limitations.md`, and the corresponding "What is still not solved" bullet.
A tolerated *read* costs a sample. A tolerated *actuation* costs the integrity of the experiment,
silently: the `set_position` fails, the tolerance absorbs it, the next `dispense` puts the drug in
the wrong tube, and the run reports `"completed"`. Nothing in the run says so.

And prose in these documents is not a control. **This branch proved that twice.** The prose said
an abort is never swallowed; it was — once by a `parallel`'s tolerance (Round 4, C1), once by a
raising log sink displacing the in-flight `CancelledError` in `_dispatch_action`'s `finally`
(Round 5, Fix 1). Both were fixed by putting a *check* where the sentence used to be. The
actuation hazard is the last one still guarded by a sentence alone, and it is the one whose
failure mode is a silently invalidated experiment rather than a crash.

**Why not now.** The tier is a real schema/API change (`Diagnostic.severity`, the validator's
return shape, the `/validate` response, Studio's diagnostics panel and its "can I run this?"
gate — a warning must *not* block a run, which is the whole point of the tier and the whole
difficulty of adding one). That is an increment, not a fix, and this branch is closing.
