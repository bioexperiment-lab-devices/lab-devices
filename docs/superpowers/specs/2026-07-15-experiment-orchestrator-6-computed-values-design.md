# Experiment engine — computed bindings & computed streams (`compute` + `record`)

- **Date:** 2026-07-15
- **Status:** Design. Approved forks settled in §3.1 (value types), §4 (seeding), §6
  (disjointness), §8 (example + preprod scope).
- **Implements:** `docs/experiment-engine-limitations.md` **#1** ("No computed bindings — no
  accumulator") and **#3** ("Streams cannot hold computed values"). The limitations doc's own
  summary: these two together "turn the engine from a sequencer that reacts into a controller
  that reasons — and they make #2's `slope` optional rather than essential."
- **Depends on:** Increments 1–5 (`lab_devices.experiment`) and the fault-tolerance increment
  (retry / `on_error`), all on main.
- **This is Increment 6** — the first item pulled off the v2 backlog.

## 1. The problem

The engine can *read* state richly and *act* on it, but it cannot *hold* derived state.

- **Bindings are written only by `operator_input`; streams only by a `measure` on a real
  device.** No block computes a value and names it (`state.py::RunState` — `bindings` written
  by `bind`, `streams` by `record`, both only from the executor's `operator_input` /
  `measure` arms). Nothing in a workflow can carry a derived number from one cycle to the next.
- **Consequence for the morbidostat.** Its drug concentration obeys a recursion:

  ```
  INJECT_DRUG :   c_k = c_{k-1}·V/(V+ΔV) + C·ΔV/(V+ΔV)
  INJECT_MEDIUM:  c_k = c_{k-1}·V/(V+ΔV)
  ```

  This cannot run inside the workflow, so the example **does not know the drug concentration it
  is administering** — it is reconstructed offline from the run log. That rules out the whole
  class of controllers that need `c`: any integral term, any dose ramp, any "stop when `c`
  exceeds X". It also means no counters ("how many drug injections in a row?" — the exact
  predicate the Stock A → Stock B escalation needs).

- **And the two most scientifically interesting quantities cannot be recorded.** Growth rate
  and drug concentration cannot be appended to a stream, so they cannot be charted, CSV-exported,
  or read by later expressions. A morbidostat's characteristic plot is the drug-concentration
  sawtooth, and this example cannot draw it. Studio's live chart shows raw OD and nothing else:
  the operator watches the *input* to the controller and never sees the controller's own state.

## 2. What we are building

Two new **leaf** blocks (§5.1 of the parent taxonomy — alongside `command`, `measure`,
`operator_input`). They are **siblings**: each evaluates one value expression and stores the
result. Neither touches hardware, so both are entirely free of occupancy, the wire lock, jobs,
retry, and the finalizer.

### 2.1 `compute` — name a derived scalar

```json
{ "compute": {"into": "c_1", "value": "c_1 * V/(V+dV) + C * dV/(V+dV)"} }
```

Evaluates `value` and binds the result to `into` in `RunState.bindings` — the **same** namespace
`operator_input` writes and `BindingRef` reads. Assignment overwrites, which is the whole point:
the same `compute` block, run each loop iteration, is the accumulator. Cross-iteration
persistence is free — `bindings` is run-scoped and never reset per iteration.

### 2.2 `record` — append a derived sample to a stream

```json
{ "record": {"into": "c_series_1", "value": "c_1"} }
```

Evaluates `value` and appends `(clock.now(), value)` to the declared stream `into` in
`RunState.streams` **and** to that stream's disk sink if one is configured — byte-identical to
how `_run_measure` publishes a measured sample (`execute.py::_run_measure`). That is what makes a
computed quantity first-class: it lands in the same stream data path a `measure` uses, so it is
charted, CSV-exported, and readable by later expressions with **no** new machinery.

### 2.3 Why two blocks, not one

They differ in target namespace and storage semantics: `compute` writes a **scalar** into
`bindings` (overwrite, may be number or boolean), `record` **appends** a **sample** to a stream
(monotonic timestamp, number only). They share one evaluation helper (§3) and split cleanly on
those two axes. The limitations doc names them separately (`compute`/`let` and `record`) for the
same reason. We use the names **`compute`** and **`record`** (not `let`).

## 3. Runtime semantics (`execute.py`)

Both dispatch through `_execute_inner` as two new arms, and both go through `execute_block`'s
existing envelope, so `block_started` / `block_finished`, the abort gate, and `on_error`
tolerance all apply unchanged.

**Shared evaluation core.** A single helper resolves the value slot exactly as an action's params
are resolved today (`resolve(value, state, now)` — `evaluate.py`):

```python
def _eval_value(value: B.ValueExpr, ctx: RunContext) -> Value:
    return resolve(value, ctx.state, ctx.clock.now())
```

`resolve` passes a literal through and parses+evaluates a string. `clock.now()` is the single
`now` threading the value's duration windows, matching every other dispatch-time evaluation.

### 3.1 `compute` (settled fork: number **or** boolean)

```python
async def _run_compute(block: B.Compute, ctx: RunContext) -> None:
    result = _eval_value(block.value, ctx)          # int | float | bool
    # number or boolean, finite; strings/non-finite already rejected by evaluate()
    ctx.state.bind(block.into, result)
    ctx.emit("binding_computed", block.id, name=block.into, value=result)
```

- **Value type: number OR boolean.** `RunState.bindings` already holds `int | float | bool`
  (`state.py::BindingValue`), and the evaluator already produces and consumes both. So booleans
  are nearly free and unlock **sticky-flag / latch accumulators** —
  `contaminated = contaminated or last(od_1) > kill_threshold` — a running boolean that, once
  true, stays true. That is exactly the shape the future `abort`/`alarm` block (limitations #7)
  will want to trigger on, so `compute` is designed to feed it.
- **What is rejected:** a string result (the evaluator already raises on a string binding ref —
  `evaluate.py::_binding`) and a non-finite number (`evaluate.py::_number`). `compute` adds no
  new rejection; it inherits the evaluator's.

### 3.2 `record` (number only)

```python
async def _run_record(block: B.Record, ctx: RunContext) -> None:
    result = _eval_value(block.value, ctx)
    value = _record_scalar(result, block.into)      # finite number; boolean REJECTED
    ts = ctx.clock.now()
    ctx.state.record(block.into, ts, value)
    sink = ctx.stream_sinks.get(block.into)
    if sink is not None:
        sink.write(Sample(ts, value))
    ctx.emit("sample_recorded", block.id, stream=block.into, value=value)
```

- **Value type: number only.** A `Stream` sample is a `float` (`state.py::Sample`). A boolean
  result is a **runtime `EvaluationError`**, not a silent `float(True) == 1.0` coercion — a
  boolean in a numeric stream is an author mistake, and streams have no runtime safety net.
- **Timestamp:** `clock.now()`, same instant as the evaluation, and `Stream.append` enforces
  non-decreasing timestamps (`state.py`) — a `record` after a `measure` in the same instant is
  fine (equal timestamps are allowed).
- **A distinct event kind, `sample_recorded`** — *not* `measure_recorded`. The stream **data** is
  deliberately indistinguishable from a measured stream (that is what buys free charting), but the
  run-log **provenance** must not be: a reader of the log must be able to tell a computed sample
  from a sensor read. (Same principle as fault-tolerance §3.4: "a run that dropped 40 samples must
  not look identical to a clean one.")

### 3.3 Error handling and tolerance

A bad value expression — empty window, division by zero, unbound binding, a string ref, a boolean
into `record` — raises `EvaluationError`. It flows through `execute_block` exactly like any other
block failure:

- **Never retried.** `EvaluationError` is on the `_NEVER_RETRY` deny-list (`execute.py`), and
  `retry` is not even legal on these blocks (§7). Nothing changes in 2 s: the inputs are what they
  are at this instant.
- **Tolerable by `on_error: "continue"`.** Legal on every block. A *tolerated* `compute` **does
  not update `into`** — the binding keeps its previous value (or stays unbound if never written).
  That is a real hazard for an accumulator (a stale `c` is an open-loop injector), and the
  validator models it precisely: `_visit` joins a tolerated block like a branch with an empty
  else, so `into` becomes only *maybe*-written and a later read of it is diagnosed (§5). A
  tolerated `record` simply skips that sample. This is honest and needs no special-casing —
  the fault-tolerance machinery already does the right thing.

## 4. The accumulator: seeding and cross-iteration state (settled fork: seed with a plain `compute`)

The recursion `c_k = f(c_{k-1})` reads the binding it writes. On the **first** iteration `c` is
unbound. The initial value is supplied by a **separate `compute` before the loop** — no new
syntax:

```json
{ "compute": {"into": "c_1", "value": "0"} },
{ "loop": { "count": 120, "body": [
    ...,
    { "compute": {"into": "c_1", "value": "c_1 * V/(V+dV) + C * dV/(V+dV)"} },
    ...
]}}
```

- **Two different `compute` blocks may target one binding.** The seed writes `c_1`; the in-loop
  block reassigns it. This is required and explicitly allowed (§6).
- **The validator enforces the seed for free.** An unseeded self-referential accumulator —
  `compute c = c*0.9` with no prior writer — is a **read-before-write** load error. Traced
  through `validate.py`: `_visit_loop` first analyses the body from the raw loop-entry state; if
  `c` is not in `state.bindings` on entry (no seed), the in-loop `compute` reads `c` before it is
  written and `_expr_reads_ast` emits "binding 'c' may be read before it is written". The
  subsequent fixpoint re-analysis (where `c` *is* written) does not clear it, because `_Ctx.emit`
  is monotonic. So a missing seed is caught at load — no new check required.
- **Cross-iteration persistence is free.** `bindings` is never reset between iterations
  (`execute.py::_run_loop` re-enters the body against the same `ctx.state`).

## 5. Static analysis — two leaf cases, reusing every existing machine

This is where the two blocks touch the delicate path-sensitive analyzer, and the whole point of
the design is that **they need no new analysis** — they extend `_visit_body` by two leaf cases and
inherit the read-safety, seeding, and freshness-guard machinery already built for measure/branch.

### 5.1 Path analysis (`validate.py::_visit_body`, `run.py::assign_block_ids`, `_footprint`)

```python
elif isinstance(b, B.Compute):
    _expr_reads(b.value, f"{path} compute value", state, c)
    if isinstance(b.into, str):
        state.bindings.add(b.into)
elif isinstance(b, B.Record):
    _expr_reads(b.value, f"{path} record value", state, c)
    if isinstance(b.into, str):
        state.streams.add(b.into)
```

The order matters: check the value's reads against the state **before** adding the block's own
write, so a self-referential read is only satisfied by a *prior* writer (the seed), never by this
block. Consequences, all inherited:

- **The freshness-guard idiom applies to value expressions exactly as to branch conditions.**
  `_expr_reads` runs the same `proof_covers` lattice, so a `record`/`compute` whose value reads a
  duration window of a *tolerated* stream must be guarded (`count(S, last=D) > 0 and ...`) or it
  is diagnosed. The open-loop-injector hazard from the fault-tolerance doc extends to computed
  values unchanged, and is caught by the same validator.
- **A `record` that reads its own stream before any prior sample** — `record r = mean(r, last=5)`
  with no earlier writer — is an empty-window "no preceding measure on some path" load error.
  Same machinery, no new code.
- **Leaves.** Neither block has children, so `_iter_blocks`, `assign_block_ids`, and `_footprint`
  need no recursion arm — they already fall through for non-container types. `_footprint` returns
  nothing for them (no device channels), so **parallel-affinity analysis is unaffected**: two
  lanes may `compute`/`record` concurrently as long as they target distinct names (§6).

### 5.2 Type and declaration checks (`validate.py::_check_block`)

- **`compute` value** must infer to `number`, `boolean`, or `unknown`. There is no single expected
  type — both scalars are valid — so we run `infer_type` and surface only its `problems` (which
  already flag a string/enum binding ref), *without* imposing a top-level expected type. Plus
  `_check_streams_declared(value)` for any stat calls.
- **`record` value** must infer to `number` — strict, via the existing
  `_check_expr_type(value, "number", ...)` — plus `_check_streams_declared(value)`.
- **`into` shape:** a usable identifier (reuse `_IDENT_RE`, not a reserved name), same rule as
  `operator_input.name`.

## 6. Namespaces & disjointness (settled fork: disjoint)

Four rules, all checked in `validate()` as collected `Diagnostic`s (workflow-global, like
`_collect_binding_types`):

1. **A stream is written by `measure` XOR `record`, never both.** Collect the `into` of every
   `measure` and every `record`; a name in both is an error. Mixing raw sensor data with computed
   values in one stream is almost always a bug, and — unlike a tolerated mode, which the finalizer
   nets — there is **no runtime safety net** to catch it, so strictness is justified here.
2. **`record.into` must be a declared stream** (`w.streams`), exactly like `measure.into`.
   `compute.into` must **not** be a declared stream.
3. **No name is both a scalar binding and a stream.** The set of binding names (`operator_input`
   + `compute` targets) and the set of stream names (`measure` + `record` targets) must be
   disjoint. This keeps `c` unambiguously a `BindingRef` and `mean(c, ...)` unambiguously a stat
   over a stream — never both.
4. **A `compute` target may not also be an `operator_input` name.** A binding has one *kind* of
   writer. Multiple `compute` blocks may share a target (the seed pattern, §4); an `operator_input`
   and a `compute` may not. (An operator-supplied initial dose and a computed running dose simply
   use different names — `c0` vs `c` — and the seed is `compute c = c0`.)

## 7. Schema, serialization, and the three mirrors

Both blocks are ordinary type-keyed block dicts: one type key (`compute` / `record`) plus the
usual optional block-level keys. `value` may be a literal or an expression string (`ValueExpr`).

**`retry` is not legal on either** — they dispatch nothing to retry. The existing `_check_retry`
(`validate.py`) already restricts `retry` to `Command`/`Measure`, so `retry` on a `compute`/
`record` is flagged with no new code. `on_error` is legal (every block).

The "one type key + known block keys" rule lives in **three** parsers. For a new *block-level key*
(the fault-tolerance case) all three had to change. For a new *block type*, the picture is
different and mostly free:

| Mirror | File | What it needs |
|---|---|---|
| **Engine (canonical)** | `serialize.py` | **Required.** Add `_compute` / `_record` builders to `_BUILDERS`, two `_dump_body` cases, and round-trip coverage. `value` strings go through `_checked_expr`. `_no_misplaced_block_keys` works unchanged. |
| **Studio backend** | `webapp/backend/experiment_studio/roles.py` | **Free.** `_walk` substitutes `device` only for `_DEVICE_BLOCKS` and recurses only for `_CHILD_LISTS`; a `compute`/`record` block matches neither, so it is passed through untouched — which is exactly right (no device, no children). Add both to the `_LEAF_BLOCKS` *doc* tuple and a `substitute()` pass-through test. Validation is delegated to the engine, which will know the new types. |
| **Studio frontend** | `webapp/frontend/src/builder/convert.ts` | **Not required; degrades gracefully.** `blockToNode`'s `default:` throws `DocConvertError`, and `records/WorkflowSnapshot.tsx` already **catches** it and renders "cannot render the snapshot: …" — identical to how it already treats group-using workflows. No crash. See §7.1. |

### 7.1 Studio frontend: what is free, and what is deferred

- **The live chart of a computed stream is FREE.** `records/RecordViewer.tsx` charts "from
  `/streams`" (its own header comment), i.e. from the per-stream data path, **not** from
  `measure_recorded` events. Because `record` writes the declared stream through the identical
  `RunState` + `StreamSink` path a `measure` uses, a computed stream appears in `/streams` and
  charts with zero frontend change. **This resolves the Q4 charting checkpoint in the free
  direction.**
- **The event log is FREE-with-polish.** `EventLog.tsx` / `describeEvent.ts` already have a
  fallback for unknown kinds, so `binding_computed` / `sample_recorded` display generically.
  Adding two `describeEvent` arms (`binding_computed → "c_1 = 3.14"`, `sample_recorded → "c_series_1
  = 3.14"`) plus color entries is cheap polish and IS included — it is a two-line change per file
  with a unit test, and the event log is the operator's window onto the controller's new state.
- **Deferred (explicit, matches the approved boundary "no Studio builder authoring UI"):** the
  builder **palette** entry to create a `compute`/`record` node, the **inspector** editing forms,
  and `convert.ts` tree round-trip. Consequence: a doc containing these blocks is **importable,
  runnable, and its run record + live chart viewable** in Studio, but it is **not editable in the
  builder canvas** (the snapshot shows the graceful message) — the same status as a group-using
  workflow today. The example is authored as JSON, which is sufficient this increment.

## 8. The example — the demonstrator (settled fork: rewrite + preprod)

`examples/morbidostat.json` and `morbidostat-demo-speed.json` are rewritten to *be* controllers,
which is the headline payoff of #1+#3. Per tube `i ∈ {1,2,3}` (still 3 tubes — parametrized
groups / #4 stay out of scope):

- **Drug concentration as a genuine cross-cycle accumulator.** Declare a binding `c_i`, seed
  `compute c_i = 0` before the loop, and on each injection arm update it by the §1 recursion —
  `compute c_i = c_i * V/(V+dV) + C * dV/(V+dV)` on `INJECT_DRUG`,
  `compute c_i = c_i * V/(V+dV)` on `INJECT_MEDIUM`. The workflow now **knows the dose it is
  administering.**
- **Growth rate computed once per cycle.** `compute r_i = 24 * (mean(od_i, last=5) - mean(od_i,
  last=10)) / last(od_i)`, then branch on `r_i > r_dil`. Computing it once and referencing the
  binding in the branch **deletes the duplicated magic-unit constant** that limitations #2 warns
  about — without implementing #2. The difference-of-means estimator is unchanged; it is just
  named.
- **Publish controller state to chartable streams.** Declare computed streams (e.g.
  `c_series_i`, `r_series_i`) written by `record c_series_i = c_i` / `record r_series_i = r_i`.
  These are `record`-only streams (disjoint from the measured `od_i` / `blank_i`, §6). The
  **drug-concentration sawtooth is now drawable** in Studio's chart, and both quantities export to
  CSV and are recoverable without offline reconstruction.
- The freshness-guard idiom from the fault-tolerance doc is preserved: `c_i`/`r_i` updates and the
  decision all sit under the existing `count(od_i, last=D) > 0` freshness guard, so a dead sensor
  still skips the cycle rather than latching a stale accumulator.
- `examples/README.md` prose is updated to describe the new computed state and remove the
  "reconstructed offline" caveat for `c`.

## 9. Testing (TDD throughout)

**Unit — parser / serializer.** Round-trip `workflow_to_dict(workflow_from_dict(d)) == d` for both
blocks with literal and expression `value`; misplaced-block-key trap; `_checked_expr` rejects a
bad value string at load.

**Unit — evaluator reuse.** `compute` binds number and boolean; `record` rejects boolean and
non-finite; both propagate `EvaluationError` on div-by-zero / empty window / string ref.

**Validator.**
- Seeded accumulator validates clean; **unseeded** self-referential `compute` is a read-before-
  write error (the load-bearing seed test).
- `record` reading its own stream before any prior sample → empty-window error; guarded → clean.
- Every disjointness violation (§6): a stream written by both `measure` and `record`; a name that
  is both a binding and a stream; `compute.into` equal to a declared stream; `record.into` not
  declared; `compute` onto an `operator_input` name.
- `retry` on a `compute`/`record` → error.
- Freshness: a `compute`/`record` value reading a duration window of a tolerated stream unguarded
  → diagnosed; guarded → clean.

**Executor (FakeClock / FakeLab, zero wall-clock).**
- An accumulator across loop iterations produces the exact recursion values (seed then N updates).
- A tolerated `compute` keeps its **stale** value; a later read of it is available but unchanged.
- `record` appends chartable samples to the stream data path and its sink; timestamps monotone.
- `binding_computed` / `sample_recorded` events emitted with the right payloads.
- A `compute`/`record` inside a `parallel` targeting distinct names runs; affinity unaffected.

**Integration.** A small morbidostat-shaped workflow: measure → compute `r` → branch → compute
`c` → record `c`/`r`, over a few cycles, asserting the recorded series.

**Studio backend.** `substitute()` passes `compute`/`record` through untouched; a role-mapped
workflow containing them round-trips and validates.

**Gates (every task):** `.venv/bin/python -m pytest`, `mypy`, `ruff check .`, and
`awk 'length>100'` over experiment src + tests.

## 10. Preprod validation — `windows_arm64_test_client` on lab-bridge

Run the rewritten `morbidostat-demo-speed.json` (25 cycles) against `windows_arm64_test_client`
**through the engine directly** (SSH `khamit@111.88.145.138` → docker exec into the jupyter
container → Python driving `ExperimentRun`, per the established preprod recipe — the run path is
engine + agent protocol, not the Studio web UI). Confirm:

1. `compute` and `record` execute on real hardware without error.
2. The computed streams (`c_series_i`, `r_series_i`) are populated and match the recursion
   computed from the OD trace.
3. The run completes end to end, with `binding_computed` / `sample_recorded` in the run log.

The test rig reads absorbance 0.0 (its densitometer simulator), so — as in the fault-tolerance
run — the dosing arms may not fire and `c` may stay 0; the honest coverage is the **control-flow,
accumulator, and recording machinery on real hardware**, not the pump/valve dosing arms. Record
what was actually exercised.

## 11. Documentation

- `docs/experiment-engine-limitations.md` — **#1** and **#3** rewritten from "what is missing" to
  "what shipped", keeping the motivation; the summary table's rows for #1 and #3 and the closing
  paragraph updated. The note that #1+#3 make #2 optional is now realized in the example.
- `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md` — §5.1 (action-leaf
  taxonomy) gains `compute`/`record`; §6 (data plane — "bindings produced by `operator_input`")
  amended to "…and `compute`"; §15 (serialization) gains the two block forms.

## 12. Out of scope

- **#2 math functions** (`slope`, `ln`, `median`, `stddev`, `abs`) — the difference-of-means
  estimator stays; #1+#3 make `slope` optional, which is the point.
- **#4 parametrized groups** — the example remains 3 tubes.
- **Studio builder authoring UI** for the two blocks — palette entry, inspector forms, and
  `convert.ts` tree round-trip (§7.1). Deferred; the JSON-authored example is sufficient.
- **A `compute` that writes into a stream, or a `record` into a binding** — the split is
  deliberate (§2.3); there is one way to do each.
