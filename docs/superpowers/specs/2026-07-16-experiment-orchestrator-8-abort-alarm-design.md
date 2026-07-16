# Experiment engine — self-failing blocks (`abort` + `alarm`)

- **Date:** 2026-07-16
- **Status:** Design (approved forks settled below).
- **Implements:** `docs/experiment-engine-limitations.md` **#7** ("No abort or assert block"). The
  doc's own recommendation, verbatim: *"An `assert`/`abort` block: `{abort: {if: "<expr>",
  message: "..."}}`, raising a run failure through the existing finalizer (which already sweeps
  devices to a safe state). A softer `alarm` variant that logs an event and notifies without
  ending the run would suit multi-vial experiments better, where one bad vial should not kill the
  other fourteen."* We ship **both**, unified under one condition-evaluation path.
- **Depends on:** Increments 1–7 (`lab_devices.experiment`), the fault-tolerance increment
  (`retry`/`on_error`/finalizer), the computed-values increment (`compute`/`record`), and the
  parametrized-repetition increment (`for_each`/parametrized groups) — all on main.
- **This is Increment 8.**

## 1. The problem

The block vocabulary can *read* state richly (`branch`, the stat sublanguage) and now *hold*
derived state (`compute`/`record`), but **a workflow cannot fail itself on a condition.** A
three-week morbidostat run's most likely ending is contamination or biofilm — an OD that climbs
and never comes down no matter how much drug is injected. The workflow can *detect* this (the
expression is easy) but it cannot *act* on it: it cannot stop, and it cannot flag. It keeps
cheerfully pumping drug into a contaminated vial for a fortnight, and the run reports
`"completed"`.

This is the **direct sequel to fault tolerance (#0).** Retry + `on_error` made a run *survive* a
dead sensor; they also created the exact failure this increment closes — a run that carries on
through a fault it recorded in `tolerated_errors` but that nothing ever *acts on*. As the
limitations doc puts it: *"the failure mode above ('completed', with a sterilized vial) is
precisely what an `alarm` block is for."*

## 2. What we are building (settled fork: both blocks, one condition path)

Two leaf blocks. Both evaluate a boolean condition **exactly** as `branch` does — same parser,
same `_condition` runtime helper, same static type-check and freshness/read-before-write path
analysis (§6). They differ only in what they do when the condition is **true**:

### 2.1 `abort` — hard stop

```json
{ "abort": { "if": "<boolean-expr>", "message": "..." } }
```

When `if` is true: emit an `abort_raised` event, then raise a new `AbortSignalError`. The error
is **never retried** and **never tolerated** (§4.2); it unwinds the block tree, the existing
finalizer sweeps every touched device to a safe state, and the run ends with status
**`"aborted"`** (§4.3). When `if` is false: a no-op; execution continues.

For **whole-run invariants**: "all vials are contaminated — nothing left to run", "the operator
asked to stop", a hard OD ceiling breach that means the rig is compromised.

### 2.2 `alarm` — flag and continue

```json
{ "alarm": { "if": "<boolean-expr>", "message": "..." } }
```

When `if` is true: emit an `alarm_raised` event and append an `AlarmRecord` to `RunReport.alarms`
(§4.4), then **return normally** — the run keeps going. When `if` is false: a no-op.

For **per-vial conditions** in a multi-vial run, where one bad vial must not kill the other
fourteen. Combined with a `compute`-latched boolean and a `branch`, `alarm` lets the author flag
a contaminated vial *and* drop it from service while the rest run on (§8, §2.4).

### 2.3 Why two block types, not one block with a `severity` field

An `abort` in the JSON *screams* "this stops the run"; an `alarm` reads as "this only flags." A
single `{stop: {if, message, severity: "fatal"|"warn"}}` would hide the single most important
fact about the block — whether it ends the run — behind an enum value. Two distinct top-level
keys make the grammar a set of leaves (each self-describing) and make a document auditable at a
glance. Rejected: the unified-severity block.

### 2.4 They compose with existing primitives (settled fork: stateless `alarm`)

`alarm` is deliberately **stateless** — it fires every cycle its condition holds. This is the
right default because the engine already has a primitive that owns "holding state across cycles":
`compute`. Fire-once (rising-edge) is expressible by composition — alarm on the edge, then latch:

```json
{ "alarm":   { "if": "contaminated_1 and not alarmed_1", "message": "tube 1 contaminated" } },
{ "compute": { "into": "alarmed_1", "value": "alarmed_1 or contaminated_1" } }
```

The `alarm` fires the first cycle `contaminated_1` becomes true (while `alarmed_1` is still
false); the following `compute` latches `alarmed_1`, so it never fires again. A built-in
`once`/latch knob on `alarm` would just re-implement this `compute`. Rejected: a stateful `alarm`
with a `once` flag. (The example's drop-from-service shape is in §8.)

## 3. Schema & serialization (`blocks.py`, `serialize.py`)

### 3.1 `blocks.py`

Two dataclasses, both `BlockBase` leaves (no children, no device):

```python
@dataclass(kw_only=True)
class Abort(BlockBase):
    if_: str
    message: str

@dataclass(kw_only=True)
class Alarm(BlockBase):
    if_: str
    message: str
```

Added to the `Block` union. `if_` mirrors `Branch.if_` (the trailing underscore avoids the Python
keyword; JSON key is `if`).

### 3.2 `serialize.py`

- `_abort` / `_alarm` builders: `if` via `_checked_expr` (parses after substitution; allows
  `{holes}`), `message` via `_str` (required; a `{hole}` in it is a plain string, interpolated on
  expansion). Both added to `_BUILDERS` under keys `"abort"` / `"alarm"`.
- `_dump_body` arms: `("abort", {"if": b.if_, "message": b.message})` and likewise `alarm`.
- `_no_misplaced_block_keys` is unchanged — neither body uses `retry`/`on_error` as a field name.

Round-trip (`workflow_to_dict ∘ workflow_from_dict == identity`) is a required test (§7).

### 3.3 `expand.py` — nothing to do

`abort`/`alarm` are **not** container blocks, so they never enter `_CHILD_LISTS`. Their two string
fields (`if`, `message`) are interpolated by `_substitute`'s uniform "every string" rule for free,
exactly like `branch.if`. A `for_each tube in [...]` over a body containing an `abort`/`alarm`
substitutes `{tube}` into both fields with **zero** expander changes. (Confirmed against
`expand.py`: `_substitute` deep-walks all strings; leaves are returned as-is by `_expand_block`.)

## 4. Semantics & execution (`execute.py`, `run.py`, `context.py`, `errors.py`)

### 4.1 The two executor arms

`_execute_inner` gains two branches:

```python
elif isinstance(block, B.Abort):
    await _run_abort(block, ctx)
elif isinstance(block, B.Alarm):
    await _run_alarm(block, ctx)
```

```python
async def _run_abort(block: B.Abort, ctx: RunContext) -> None:
    if _condition(block.if_, ctx):
        _emit(ctx, "abort_raised", block.id, message=block.message)
        raise AbortSignalError(str(block.id), block.message)

async def _run_alarm(block: B.Alarm, ctx: RunContext) -> None:
    if _condition(block.if_, ctx):
        ctx.alarms.append(AlarmRecord(str(block.id), block.message))
        ctx.emit("alarm_raised", block.id, message=block.message)
```

`_condition` is the **existing** helper (evaluates fail-safe, raises `EvaluationError` on a
non-boolean). No new evaluation code.

### 4.2 `abort` is never tolerated, never retried, never wrapped

`AbortSignalError` is a new `ExperimentRunError`. Three edits make it behave like the other
non-negotiable errors (`InvariantViolationError`):

1. **Never tolerated.** Add `AbortSignalError` to `_tolerable`'s never-absorb tuple. `_tolerable`
   already recurses into `BaseExceptionGroup`, so a lane-abort inside a tolerated `parallel`
   container is caught too. **This is the load-bearing invariant of the whole feature** and the
   one that goes vacuous silently (see the abort-tests memory) — it is mutation-verified (§7).
2. **Never wrapped.** In `execute_block`, add `AbortSignalError` to the *first* `except` tuple
   (`except (BlockFailedError, InvariantViolationError, AbortSignalError) as exc:`) so it
   re-raises **unwrapped** and is *not* re-emitted as `block_failed` (it emitted its own
   `abort_raised`; an abort is a deliberate stop, not a block failure). Without this, the
   `except Exception` arm would wrap it in `BlockFailedError`, destroying the type `run.py` needs.
3. **Never retried.** `retry` is already rejected by `_check_retry` on any non-`command`/`measure`
   block, so an `abort` can carry no retry policy and `_run_action`'s retry envelope is never in
   its path. Nothing to add.

**The `parallel`-lane subtlety (opposite of the CancelledError trap).** When an `abort` fires in
a `parallel` lane, `asyncio.TaskGroup` gives the *error* priority and **preserves** it in the
`ExceptionGroup` (it only *drops* a racing `CancelledError`). So unlike operator-abort detection,
the `AbortSignalError` **is** present in the group and is found by flattening — `_tolerable`'s
recursion refuses to absorb it, and `run.py`'s `_contains_abort` (§4.3) finds it for the status.
The sibling lanes are cancelled by the TaskGroup; a sibling's live job may strand, but the run is
ending and the finalizer stops every device, so the strand is moot at end-of-run.

### 4.3 Run status (`run.py`) — reuse `"aborted"`, distinguish by error/event

Settled fork: **no new status.** A workflow abort and an operator abort are both "the run was
deliberately stopped"; the *cause* lives in the error type and the `abort_raised` event, not in a
fifth status string (the same principle the fault-tolerance increment applied to
`tolerated_errors`: "the information is in the field, not in a fifth status").

`run.py`'s status computation gains one clause:

```python
cancelled = isinstance(error, asyncio.CancelledError)
operator_aborted = cancelled and ctx.abort_requested
workflow_aborted = error is not None and _contains_abort(error)
status = (
    "aborted" if operator_aborted or workflow_aborted
    else "cancelled" if cancelled
    else "failed" if error is not None
    else "completed"
)
```

`_contains_abort(exc)` flattens `BaseExceptionGroup`s (reusing the `_leaves` shape) and returns
True iff any leaf is an `AbortSignalError`. A workflow abort is **not** a `CancelledError`, so it
falls straight through the existing operator-abort branch; `if error is not None: raise error`
re-raises the `AbortSignalError` (or the group carrying it) after the finalizer has run. The
report carries `status="aborted"`, `error=<AbortSignalError | group>`; `str(AbortSignalError)`
is the author's `message`, so the report is self-describing.

Distinctions preserved:
- **operator abort** → status `"aborted"`, `error` is a `RunAbortedError`, event `abort_requested`.
- **workflow abort** → status `"aborted"`, `error` is (or contains) an `AbortSignalError`, event
  `abort_raised` (with the message + block id).
- **device/hardware fault** → status `"failed"` (unchanged).

### 4.4 `RunReport.alarms` and `RunContext.alarms`

- `errors.py`: an `AlarmRecord` frozen dataclass (`block_id: str`, `message: str`), mirroring
  `ToleratedError`. Not an exception — the record that an alarm fired.
- `context.py`: `RunContext.alarms: list[AlarmRecord] = field(default_factory=list)`.
- `run.py`: `RunReport.alarms: tuple[AlarmRecord, ...] = ()` (declared last with a default, like
  `tolerated_errors`, so the failure-path positional construction is unaffected). Populated from
  `ctx.alarms` on every terminal path (built alongside `tolerated_errors`).

A run that fired alarms stays `"completed"` but is distinguishable post-hoc — the same design as
`tolerated_errors`.

## 5. Validation (`validate.py`) — reuse `branch`'s machinery

### 5.1 Per-block checks (`_check_block`)

Two arms, both leaning on existing helpers:

```python
elif isinstance(block, B.Abort):
    _check_condition(block.if_, f"{path} abort if", w, binding_types, out)
    _check_message(block.message, path, "abort", out)
    if block.on_error == "continue":
        out.append(Diagnostic("block", path,
            "abort may not carry on_error: 'continue'; a safety stop cannot be tolerated"))
elif isinstance(block, B.Alarm):
    _check_condition(block.if_, f"{path} alarm if", w, binding_types, out)
    _check_message(block.message, path, "alarm", out)
```

- `_check_condition` is the **existing** helper (type-checks the expression as boolean and checks
  every stat references a declared stream). Zero new expression logic.
- `_check_message`: `message` must be a non-empty `str` (a hard stop / a notification with no text
  is a defect). A `{hole}` is legal (it is a string until expansion).
- **`abort` forbids `on_error: "continue"`** — tolerating a safety stop is a contradiction, and
  it would also silently swallow a condition-eval failure (`EvaluationError` from an unguarded
  window), defeating the guard. `alarm` allows `on_error` (least-strict lean): tolerating a flaky
  alarm-condition eval is benign because the alarm does not end the run. `_check_on_error` and
  `_check_retry` still run unconditionally on both (via `_check_block`'s unconditional head), so
  `retry` on either is already the standard "command/measure only" error.

### 5.2 Path analysis (`analyze.py` / `validate.py` `_visit_body`)

Two arms; both are **read-only** with respect to abstract path state (neither writes a binding,
a stream, or a mode):

```python
elif isinstance(b, (B.Abort, B.Alarm)):
    _expr_reads(b.if_, f"{path} {kind} if", state, c)
    # state unchanged: abort/alarm write nothing
```

This gives the freshness/read-before-write guarantees **for free**: an `abort if
mean(od_1, last=30min) > x` whose window is not proven non-empty draws the same "guard it with
`count(...) > 0`" diagnostic that a `branch` or a tolerated `measure` read does. The author is
forced to guard the abort/alarm condition at *load time*, so it almost never raises
`EvaluationError` at *run time*.

**Deliberately out of scope for v1 (documented):** an `abort if <not-fresh>` could, in principle,
*establish* freshness for the blocks after it (if we reach them, the negation held) — abort-as-an
-early-return-guard. Implementing that requires a negation-proof of the condition and is genuine
new analysis; it is **not** built here. Abort/alarm contribute no proof to the continuation; the
author guards subsequent reads explicitly, exactly as today. Noted as a possible future polish.

### 5.3 `_footprint`, `_iter_blocks`, `assign_block_ids`

`abort`/`alarm` command no device and have no children:
- `_footprint` ignores them (they contribute no `(device, channel)`).
- `_iter_blocks` needs **no** recursion arm (leaves).
- `assign_block_ids`'s `walk` assigns each an id from its enclosing list and does not recurse
  (leaves) — no change.

## 6. Everything analysis-related is inherited

Because the condition is validated and evaluated through the *same* path as `branch.if`, and
because macro expansion runs before validation and execution (Increment 7):

- A `for_each tube in [1,2,3]` over a body with `abort if <uses {tube}>` expands to three concrete
  `abort` blocks with `od_1`/`od_2`/`od_3`, each independently freshness-checked.
- A parametrized `service(tube)` group containing an `alarm` inlines per call with `{tube}`
  substituted, and the concrete conditions are type/stream/freshness-checked at their expanded
  positions.
- Not one line of new expression, type, or path-analysis logic — this is the same payoff
  Increment 7 documented for `for_each`.

## 7. Testing (TDD throughout; safety props mutation-verified)

**Serialization (`test_experiment_serialize*`).**
- Round-trip: `workflow_to_dict(workflow_from_dict(d)) == d` for docs with `abort` and `alarm`,
  including `{hole}`s in `if` and `message`.
- Load errors: missing `if`; missing/empty `message`; a bad expression in `if`.

**Validator (`test_experiment_validate*`).**
- `abort`/`alarm` condition type errors (non-boolean → diagnosed as boolean-expected).
- Unguarded windowed read in the condition → the freshness diagnostic; guarded → clean.
- `abort with on_error: "continue"` → the "safety stop cannot be tolerated" diagnostic; the same
  on `alarm` → clean.
- `retry` on `abort`/`alarm` → the "command/measure only" diagnostic.
- Undeclared stream in the condition → the declaration diagnostic.
- `for_each` over an `abort` body → per-tube expansion validates (affinity/freshness at expanded
  positions).

**Executor (FakeClock / FakeLab, zero wall-clock) (`test_experiment_execute*`).**
- `abort` true → status `"aborted"`; `abort_raised` event present with the message; `error` is an
  `AbortSignalError`; the finalizer ran (touched devices swept — assert the sweep commands hit the
  wire). `abort` false → no-op, run completes.
- `alarm` true → `alarm_raised` event; `report.alarms` populated; run completes `"completed"`.
- `alarm` stateless: inside a `loop count=N`, an always-true condition fires N times
  (`len(report.alarms) == N`); a `compute`-latched condition fires once.
- **`abort` inside a `parallel` lane** → siblings cancelled, group flattened, status `"aborted"`
  (**not** `"failed"`), `AbortSignalError` found in the group.
- **`abort` is not tolerated by an enclosing tolerant container** → a `parallel`/`serial` carrying
  `on_error: "continue"` around an aborting lane/child still aborts the whole run.

**Mutation verification (per the abort-tests memory — the four traps).** For every test above that
defends a *safety* property, prove it is non-vacuous by **deleting the feature from the source,
confirming the test FAILS, restoring, and checksumming byte-identical** — and report it:
- Delete `AbortSignalError` from `_tolerable`'s tuple → the "not tolerated" tests must fail.
- Delete the `AbortSignalError` arm from `execute_block`'s first `except` (let it wrap) → the
  status-`"aborted"` tests must fail (status becomes `"failed"`).
- Delete `_contains_abort`'s group recursion → the `parallel`-lane abort test must fail.
- Assert at the **wire** (no hardware command dispatched after the abort fires), not on
  `report.status` alone (a TaskGroup can re-raise a parent cancellation and *look* aborted). Use
  `asyncio.wait({task}, timeout=...)` as the hang-guard, never `asyncio.wait_for` (it cancels on
  timeout, and a displacement bug would hang pytest forever).

**Integration — morbidostat (FakeLab) (`test_examples_morbidostat.py`).**
- The existing IC50 control-loop test still passes unchanged (behavior-preserving).
- A tube driven to the contamination predicate fires its `alarm`, latches `contaminated_{tube}`,
  and is dropped from service (no further injection on that tube); the other tubes continue and
  still pin at IC50.
- All-tubes-contaminated fires the whole-run `abort` → status `"aborted"`, finalizer swept.

**Gates (every task):** `.venv/bin/python -m pytest`, `mypy` (scope `src/lab_devices` only),
`ruff check .`, and `awk 'length>100'` over experiment src + tests.

## 8. The example — the demonstrator (settled fork: full rewrite + preprod)

`examples/morbidostat.json` and `morbidostat-demo-speed.json` gain the contamination story #7 was
filed for, plus an operator-triggerable hard stop that can be exercised on real hardware.

### 8.1 Per-vial: `alarm` + drop-from-service (inside the `service(tube)` group)

- A **latched** `compute contaminated_{tube} = contaminated_{tube} or <contam-predicate>` seeded
  (`for_each`) to `false` before the loop, alongside the existing `c_{tube}` seed.
- The `<contam-predicate>` expresses "OD stays high while drug is maxed out and it still won't
  come down": `c_{tube} >= stock_a * 0.99 and mean(od_{tube}, last=Wc) > od_ceiling`, guarded by
  `count(od_{tube}, last=Wc) > 0` (freshness). Exact constants (`od_ceiling`, `Wc`) pinned in the
  plan against the demo's OD/pace scaling, and cross-checked against the pace-coupled-constant
  discipline already in the doc.
- The service body is wrapped `branch if not contaminated_{tube}` — a contaminated tube is
  **skipped entirely** (no drug, no medium, no dilution), and on the rising edge an `alarm`
  fires: `"tube {tube} contaminated — dropped from service"`. One bad vial no longer receives
  drug for a fortnight, and the other fourteen run on. This is the concrete argument for `alarm`.

### 8.2 Whole-run: `abort`

Two `abort`s at the top of the cycle loop body:
- **Science stop:** `abort if contaminated_1 and contaminated_2 and contaminated_3` — every vial
  is lost, so there is nothing left to run; stop and sweep rather than pump drug into three dead
  cultures for three weeks. (Generalizes to all-of-N via a `compute` fold when scaled.)
- **Operator stop (preprod-exercisable):** a `bool` `operator_input emergency_stop` (collected at
  setup) + `abort if emergency_stop`. This lets the preprod smoke actually **trigger a real
  abort** and watch the finalizer sweep the thermostats/pumps/valves safe on
  `windows_arm64_test_client` — the end-to-end hardware proof that the sim's OD-0.0 reads cannot
  give for the contamination predicate (§8.3).

### 8.3 Honest gap (stated up front, like §0's dosing gap)

The test rig's simulated densitometers read absorbance **0.0** on every read, so the
*contamination* predicate (high sustained OD) **cannot fire on that hardware** — the same rig
property that kept dosing unexercised in #0. Therefore:
- The **contamination → alarm → drop-from-service** and **all-contaminated → abort** paths are
  proven in **FakeLab integration tests** (§7), where OD is scriptable.
- The **operator `abort` → finalizer sweep** path is proven on **real hardware** via
  `emergency_stop` (§8.2), exercising the raise, the non-tolerance, the status, the event, and
  the safe-state sweep end to end.
- The preprod **clean run** (no `emergency_stop`, OD 0.0) must complete **without a spurious
  abort or alarm** — the negative control that the new blocks do not fire when they should not.

### 8.4 Behavior-preservation proof

Same two guarantees Increment 7 used: (a) a golden `expand_dict` fixture for the rewritten doc,
and (b) the existing IC50 integration test passing **unchanged** for a run with no contamination
and no emergency stop (the new blocks are inert on the happy path). `examples/README.md` gains the
contamination-guard and emergency-stop prose and the compute-latch idiom for fire-once alarms.

## 9. Studio — the Increment-6/7 boundary (settled fork)

Runnable and viewable, **not** canvas-editable — identical to how `compute`/`record`/`for_each`
shipped.

- **Backend grammar parity (`webapp/backend/experiment_studio/roles.py`).** Add `"abort"` and
  `"alarm"` to `_LEAF_BLOCKS` (no device, no children). The parity test
  `test_walker_grammar_matches_engine_serializer` (`_DEVICE_BLOCKS ∪ _CHILD_LISTS ∪ _LEAF_BLOCKS
  == set(serialize._BUILDERS)`) stays green with both added on both sides.
- **Report plumbing (`webapp/backend/experiment_studio/runner.py`).** `status` already flows
  through verbatim, so `"aborted"` needs **no** new backend code. Add an `alarms` key to the
  report dict, mirroring `tolerated_errors`:
  `[{"block_id": a.block_id, "message": a.message} for a in report.alarms]`.
- **Frontend event log (`describeEvent.ts`).** Add cases: `abort_raised` →
  `run aborted by workflow: <message>`; `alarm_raised` → `alarm: <message>`. (Both already
  degrade to `kind {json}` — this makes them first-class.) Add matching `describeEvent.test.ts`
  cases.
- **Frontend report summary (`reportSummary.ts`).** Add `alarmSummary(report)` mirroring
  `toleratedSummary` (`N alarm(s): <messages>`), surfaced on the live-run terminal panel and
  `RecordViewer.tsx`. The `"aborted"` status renders through the existing status machinery.
- **Frontend builder (`convert.ts`).** Add `abort`/`alarm` to the explicit
  "known-but-unsupported-in-builder" set so a doc using them imports, runs on hardware, charts its
  streams, and shows in the event log — but is not canvas-editable, with a specific message rather
  than a generic throw. (Docs using `for_each`/groups — like the morbidostat — are already
  non-canvas-editable, so this changes nothing for the example.)
- **Types (`types/records.ts` / `types/runs.ts`).** Add the `alarms` field to the report type.
- **Backend tests:** an `abort`/`alarm` doc validates and runs through the runner; the report
  carries `alarms`; a role-mapped doc with `abort`/`alarm` substitutes and runs.

## 10. Out of scope

- **Full builder authoring UI** for `abort`/`alarm` (and `compute`/`record`/`for_each`/groups) —
  the canvas has no support for any of these; a grammar-parity builder increment is separate and
  larger. JSON-authored is sufficient, matching Increments 6/7.
- **Push/email/SMS notification** on `alarm`. "Notify" for v1 = the `alarm_raised` run-log event,
  surfaced live in Studio (the run log is the engine's notification channel, consistent with its
  existing philosophy). An external notifier (webhook/email) is a separate integration.
- **Abort-as-guard** (an `abort if <not-fresh>` establishing freshness for subsequent reads,
  §5.2) — genuine new negation-proof analysis; deferred.
- **A stateful `alarm` (`once`/latch flag)** — duplicates `compute`; the latch idiom is
  documented instead (§2.4).
- **A fifth run status** — reuse `"aborted"`, distinguished by error type + event (§4.3).
- **`elapsed()`-driven or count-driven auto-abort** — that is limitation #8 (no clock); this
  increment is condition-driven only.

## 11. Documentation

- `docs/experiment-engine-limitations.md` — **#7** rewritten from "what is missing" to "what
  shipped", keeping the motivation; the summary-table row for #7 and the closing paragraphs
  updated (the contamination guard is now expressible; `abort`/`alarm` are the sequel to #0). Note
  the honest gap (§8.3): the contamination *firing* path is proven in FakeLab, the operator abort
  on real hardware.
- `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md` — §5 (block taxonomy)
  gains `abort`/`alarm`; §12 (validation) gains the condition/`on_error` rules; §15
  (serialization) gains the two new forms.
- `examples/README.md` — the contamination guard, the emergency stop, and the fire-once alarm
  idiom.
