# Experiment type system — Engine C (durations & slot expressions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Unify `duration` into the lattice as `number<s>`, so a duration literal (`5min`) is an expression value and the duration/count slots (`wait.duration`, `loop.pace`, `loop.count`, `gap_after`, `start_offset`, `retry.backoff`) accept **expressions** resolved at entry — closing engine-limitation #6 (cycle time as an operator input, adaptive timing).

**Architecture:** A duration literal parses to a new `DurationConst` AST node inferring `number<s>` and evaluating to its seconds. The duration slots become expressions type-checked `number<s>` (a bare unitless number is rejected — free safety) and the count slot `int`; the executor resolves each via `evaluate(...)` instead of `parse_duration(...)`. Backward compatible: every existing literal (`5min`) parses and evaluates identically, so no document changes and `schema_version` stays 3.

**Tech Stack:** Python 3.11+, pytest, mypy, ruff. Design: `../specs/2026-07-21-experiment-type-system-design.md` §6.

## Global Constraints

- **Backward compatible — no schema bump.** A duration literal is a *superset* expression; `schema_version` stays 3. Every v3 document keeps loading.
- **`duration` is `number<s>`** — the seconds unit; `5min` → `300` at unit `s`. A duration slot expects `number<s>`; a bare unitless number is a unit error.
- **Resolved at entry.** `wait.duration`/`gap_after`/`start_offset`/`backoff`/`loop.count` at block entry; `loop.pace` per iteration (as today).
- Gate: `pytest -q`, `mypy src/lab_devices`, `ruff check src tests`.

---

### Task 1: `DurationConst` — duration literals as expression values

**Files:** Modify `src/lab_devices/experiment/expr.py` (`DurationConst`, `_atom`, `Expr` union), `analyze.py` (`infer_type`, `references`/walkers), `evaluate.py` (`evaluate`); Test `tests/test_experiment_expr.py`, `tests/test_experiment_type_lattice.py`, `tests/test_experiment_evaluate.py`.

**Interfaces:**
- `expr.DurationConst(seconds: float)` — frozen; added to the `Expr` union.
- `infer_type(DurationConst)` → `ScalarType("number", parse_unit("s"))`.
- `evaluate(DurationConst)` → `seconds` (float).

- [ ] **Step 1: Tests.** `parse_expression("5min")` → `DurationConst(300.0)` (not the old `ExpressionError`); `infer_type(parse_expression("30s")).type == ScalarType("number", parse_unit("s"))`; `parse_expression("cycle_min * 1min")` infers `number<s>` given `cycle_min: number`; a bare `"cycle_min"` (unitless) checked against a duration slot is a unit error (Task 3); `evaluate(parse_expression("5min"), state, 0) == 300.0`; `evaluate(parse_expression("2 * 30s"), …) == 60.0`. A duration literal is STILL usable as a stat window (`count(s, last=5min)`) — that path is unchanged.
- [ ] **Step 2:** Run — fail.
- [ ] **Step 3:** Implement. `expr.py`: add `@dataclass(frozen=True) class DurationConst: seconds: float`; add to `Expr`; in `_atom`, replace the `DURATION` → raise with `return DurationConst(parse_duration(tok.text))`. `analyze.py`: `infer` returns `ScalarType("number", _SECONDS)` for `DurationConst` (`_SECONDS = parse_unit("s")` module const); ensure `references`/`windowed_reads`/`proven_nonempty` walkers ignore it (no bindings/streams). `evaluate.py`: add `if isinstance(expr, DurationConst): return expr.seconds`.
- [ ] **Step 4:** Run — pass. Confirm the window path (`_window` in expr.py) still parses `last=5min` (it consumes the DURATION token directly, not via `_atom`, so it is unaffected — add a regression test asserting `count(s, last=5min)` still parses).
- [ ] **Step 5:** mypy+ruff, commit `feat(experiment): duration literals as number<s> expression values`.

---

### Task 2: Evaluate duration/count slots as expressions in the executor

**Files:** Modify `src/lab_devices/experiment/execute.py`; Test `tests/test_experiment_loop_branch.py`, a new `tests/test_experiment_slot_expressions.py`.

**Interfaces:**
- `execute._eval_seconds(text: str, ctx, now) -> float` — `evaluate(parse_expression(text), ctx.state, now)`, coerced to a non-negative finite float (a negative/non-finite duration raises `EvaluationError`).
- `execute._eval_count(value: int | str, ctx, now) -> int` — an int literal passes through; a string evaluates to an int (`EvaluationError` if the result is not an integer).

- [ ] **Step 1: Tests** (through a real run): a `wait` whose `duration` is `"pause_s"` (an operator-input/compute binding of seconds) sleeps that long; a `loop` whose `count` is `"cycles"` (a computed int) runs that many times; `loop.pace` as an expression paces per iteration; a `wait.duration` that evaluates negative fails the block.
- [ ] **Step 2:** Run — fail (the slots are still `parse_duration`).
- [ ] **Step 3:** Implement `_eval_seconds`/`_eval_count`; replace the six `parse_duration(...)` slot sites (execute.py:213 backoff, 463 gap_after, 609 wait.duration, 733 loop.pace, 785 start_offset) with `_eval_seconds(...)`, and the `iterations >= block.count` comparison (744) with a `_eval_count`-resolved int computed at loop entry. `backoff` evaluates against `ctx.state` at the retry site.
- [ ] **Step 4:** Run — pass. **Step 5:** commit `feat(experiment): resolve duration/count slots as expressions at entry`.

---

### Task 3: Type-check the slots; relax load-time duration validation

**Files:** Modify `validate.py` (`_check_block`, `_check_loop`, timing checks), `serialize.py` (`_checked_duration`, `_loop`, `Loop.count`), `blocks.py` (`Loop.count` type); Test `tests/test_experiment_slot_expressions.py`, `tests/test_experiment_validate_blocks.py`.

- `blocks.py`: `Loop.count: int | str | None` (a str is an expression).
- `serialize.py`: `_checked_duration` no longer rejects a non-literal — a duration slot is an expression, validated at validate-time; keep it a string field (parse errors surface as a `type` diagnostic). `Loop.count` accepts an int or a string.
- `validate.py`: `_check_duration(text, ctx, env, out)` → `_check_expr_type(text, "number", ctx, env, out, expected_unit=parse_unit("s"))` + `_check_streams_declared`; applied to `wait.duration`, `loop.pace`, `gap_after`, `start_offset`, `retry.backoff`. `_check_count(value, ctx, env, out)` → int literal ok, else `_check_expr_type(value, "int", …)`.

- [ ] **Step 1: Tests** (mutation-verified): `wait.duration: "5"` (bare unitless) → a `units` diagnostic (needs `<s>`); `wait.duration: "5min"` → clean; `loop.count: "1.5"` → a `type` diagnostic (not int); `loop.count: "cycles"` where `cycles` is a computed int → clean; `wait.duration: "cycle_min * 1min"` → clean.
- [ ] **Step 2:** Run — fail. **Step 3:** Implement. **Step 4:** Run — pass; full suite (fix any fixture whose `gap_after`/`start_offset`/`backoff` was a bare non-`<s>` literal — none should exist, they are all `"1s"`-style). **Step 5:** commit `feat(experiment): type-check duration/count slots (number<s> / int)`.

---

### Task 4: Mark limitation #6 shipped; docs

**Files:** `docs/experiment-engine-limitations.md` (#6), `docs/workflow-schema.md` (§6 note on duration expressions).

- [ ] **Step 1:** Mark limitation #6 ("Durations and counts are literals") **SHIPPED**, noting `wait.duration`, `loop.pace`, `loop.count`, `gap_after`, `start_offset`, `retry.backoff` now take expressions typed `number<s>` / `int`, so cycle time can be an operator input. **Step 2:** Add a one-line note to `workflow-schema.md` §6. **Step 3:** full gate. **Step 4:** commit `docs(experiment): mark durations/counts-as-expressions (limitation #6) shipped`.

---

## Self-Review

- **Spec coverage (§11.3):** duration = number<s> → T1; slot expressions resolved at entry → T2; slot typing → T3; #6 shipped → T4. Backward compatible, no schema bump — Global Constraints.
- **Placeholders:** none.
- **Type consistency:** `DurationConst`, `_SECONDS`, `_eval_seconds`/`_eval_count`, `_check_duration`/`_check_count` used consistently.
- **Mutation-verified:** T1, T3 assert reject cases.
