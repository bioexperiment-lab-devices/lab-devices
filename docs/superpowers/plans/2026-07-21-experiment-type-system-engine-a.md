# Experiment type system — Engine A (the lattice) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the DSL expression type system's *scalar lattice* — `int`/`number`/`bool`/`string` with `int <: number`, typed `compute` bindings, string comparison, and strict `unknown` — so type mismatches that flow through computed bindings become load-time diagnostics instead of runtime `EvaluationError`s. No document-shape change; `schema_version` stays 2.

**Architecture:** Unify the two type spellings (`analyze.BindingType`/`ExprType`) into one `Type` vocabulary with an `assignable()` subtyping relation; extend `infer_type`'s node rules for `int`/`string`; make `_collect_binding_types` a document-order pass that also infers `compute.into` types; localize strictness in `_check_expr_type`; add single-quoted string literals to the expression grammar and string equality to the evaluator.

**Tech Stack:** Python 3.11+, `pytest`/`pytest-asyncio`, `mypy`, `ruff`. Package under `src/lab_devices/experiment/`. Design: [`../specs/2026-07-21-experiment-type-system-design.md`](../specs/2026-07-21-experiment-type-system-design.md).

## Global Constraints

- **No schema change.** Engine A adds no serialized fields; `schema_version` stays `2`. `serialize.py`, `blocks.py`, `workflow.py` are untouched.
- **Type vocabulary is spelled `int | number | bool | string`** (design §3) — never `float`, never `boolean`. The one exception left alone is the legacy `OperatorInput.type: "float"` field value.
- **Keep the runtime guards.** `evaluate.py`/`execute.py` type checks stay as the fail-safe backstop; the static checker is additive.
- **Fail-safe leniency is preserved for `unknown` *operands*.** Strictness applies only at *slot* level (an expression whose top type is `unknown` used where a concrete type is required).
- **Every check is mutation-verified** (design §12): each new static check gets a test proving a deliberately ill-typed doc is *rejected*, not merely that a good one passes.
- Gate commands (run from repo root): `pytest -q`, `mypy src/lab_devices`, `ruff check src tests`.

---

### Task 1: Unify the type vocabulary and add `assignable`

Collapse `BindingType` and `ExprType` into one `Type` (adds `int`, `string`; renames `boolean`→`bool`), and add the subtyping relation the lattice needs. Behaviour of `infer_type` is otherwise unchanged in this task — only the spelling and the comparison helper.

**Files:**
- Modify: `src/lab_devices/experiment/analyze.py` (`BindingType`, `ExprType`, `infer_type` internals that spell `"boolean"`)
- Modify: `src/lab_devices/experiment/validate.py` (`_INPUT_TYPES`, `_check_expr_type`, `_check_param_value`, `_check_condition`, the `ExprType`/`BindingType` imports/annotations)
- Test: `tests/experiment/test_analyze_types.py` (new)

**Interfaces:**
- Produces: `analyze.Type = Literal["int", "number", "bool", "string", "unknown"]` (single alias; `BindingType` and `ExprType` become aliases of `Type` for back-compat of imports). `analyze.assignable(got: Type, expected: Type) -> bool`.

- [ ] **Step 1: Write failing tests for `assignable`**

```python
# tests/experiment/test_analyze_types.py
from lab_devices.experiment.analyze import assignable

def test_assignable_reflexive():
    for t in ("int", "number", "bool", "string"):
        assert assignable(t, t)

def test_int_is_a_number_but_not_the_reverse():
    assert assignable("int", "number")
    assert not assignable("number", "int")

def test_bool_and_string_are_invariant():
    assert not assignable("bool", "number")
    assert not assignable("string", "number")
    assert not assignable("number", "bool")

def test_unknown_is_leniently_assignable_either_way():
    # unknown is the transient inference state; operand-level checks stay lenient.
    assert assignable("unknown", "number")
    assert assignable("number", "unknown")
```

- [ ] **Step 2: Run — expect ImportError / fail.** `pytest tests/experiment/test_analyze_types.py -q`

- [ ] **Step 3: Implement the vocabulary and `assignable` in `analyze.py`**

Replace the two `Literal` aliases (analyze.py:21-22) with:

```python
Type = Literal["int", "number", "bool", "string", "unknown"]
BindingType = Type  # back-compat alias; a binding's inferred scalar type
ExprType = Type     # back-compat alias; an expression's inferred type

_NUMERIC: frozenset[str] = frozenset({"int", "number"})


def assignable(got: Type, expected: Type) -> bool:
    """Is a value of type `got` acceptable where `expected` is wanted?
    `int <: number` at the base; `unknown` is leniently assignable either way (the
    transient inference state — strictness is enforced at slot level, not here)."""
    if got == "unknown" or expected == "unknown":
        return True
    if got == expected:
        return True
    return got == "int" and expected == "number"
```

Then rename every `"boolean"` **type token** inside `infer_type` to `"bool"` (analyze.py:78, 87, 95, 99-101, 113 and the `expect(..., "boolean", ...)` calls). Leave user-facing message *prose* ("requires a boolean operand") as-is.

- [ ] **Step 4: Update `validate.py` call sites for the `bool` spelling**

- `_INPUT_TYPES` (validate.py:601-606): `"bool": "boolean"` → `"bool": "bool"`.
- `_check_param_value` (validate.py:660): `expected: ExprType = "boolean" if spec.kind == "bool" else "number"` → `"bool"`.
- `_check_condition` (validate.py, the `_check_expr_type(text, "boolean", ...)` call): `"boolean"` → `"bool"`.
- Any other literal `"boolean"`/`"number"` passed as an `expected` type token: leave `"number"` alone, change `"boolean"`→`"bool"`.

- [ ] **Step 5: Run tests + gates.** `pytest tests/experiment/test_analyze_types.py tests/experiment/ -q && mypy src/lab_devices && ruff check src tests`. Fix any existing test that asserted the literal token `"boolean"` in a diagnostic message (message prose is unchanged, so only tests that asserted the raw type token need updating).

- [ ] **Step 6: Commit.** `git add -A && git commit -m "refactor(experiment): unify expr type vocabulary + assignable (int<:number)"`

---

### Task 2: Extend `infer_type` node rules for `int` and `string`

Teach the inferencer that integer literals and `count()` are `int`, that arithmetic preserves `int` only when both operands are `int`, that a `string` binding *flows* as `string` (a problem only when used in a non-string position), and that `string == string` is legal.

**Files:**
- Modify: `src/lab_devices/experiment/analyze.py` (`infer_type`)
- Test: `tests/experiment/test_analyze_types.py`

**Interfaces:**
- Consumes: `Type`, `assignable` (Task 1).
- Produces: `infer_type(expr, binding_types)` returning richer `Type`s. `StatCall count → "int"`, other stats → `"number"`. Signature unchanged (units arrive in Engine B).

- [ ] **Step 1: Write failing tests** (mutation-verified: assert both the pass and the reject case)

```python
from lab_devices.experiment.analyze import infer_type
from lab_devices.experiment.expr import parse_expression

def _t(text, binds=None):
    return infer_type(parse_expression(text), binds or {})

def test_integer_literal_and_count_are_int():
    assert _t("5").type == "int"
    assert _t("count(s)").type == "int"
    assert _t("5.0").type == "number"

def test_int_arithmetic_stays_int_but_division_and_float_widen():
    assert _t("2 + 3").type == "int"
    assert _t("2 * 3").type == "int"
    assert _t("2 / 3").type == "number"      # real division always widens
    assert _t("2 + 3.0").type == "number"

def test_string_binding_flows_as_string_without_a_problem():
    r = _t("mode", {"mode": "string"})
    assert r.type == "string"
    assert r.problems == ()

def test_string_equality_is_allowed():
    r = _t("mode == mode", {"mode": "string"})
    assert r.type == "bool"
    assert r.problems == ()

def test_string_in_arithmetic_is_a_problem():
    r = _t("mode + 1", {"mode": "string"})
    assert r.problems  # non-empty: string is not a number

def test_comparing_string_with_number_is_a_problem():
    r = _t("mode == 1", {"mode": "string"})
    assert r.problems
```

- [ ] **Step 2: Run — expect failures** (`count` currently `number`; string binding currently returns `unknown` + a problem at the ref; `2+3` currently `number`).

- [ ] **Step 3: Rewrite `infer_type`'s `infer` body** (analyze.py:76-113). Key rules:

```python
def infer(e: Expr) -> Type:
    if isinstance(e, Const):
        if isinstance(e.value, bool):
            return "bool"
        return "int" if isinstance(e.value, int) else "number"
    if isinstance(e, BindingRef):
        return binding_types.get(e.name, "unknown")   # string flows; problems come from ops
    if isinstance(e, StatCall):
        return "int" if e.fn == "count" else "number"
    if isinstance(e, UnaryOp):
        if e.op == "not":
            expect(e.operand, "bool", "'not'")
            return "bool"
        return _numeric(e.operand, "unary '-'")        # preserves int/number
    if e.op in ("and", "or"):
        expect(e.left, "bool", f"{e.op!r}"); expect(e.right, "bool", f"{e.op!r}")
        return "bool"
    if e.op in _ARITH_OPS:
        lt = _numeric(e.left, f"operator {e.op!r}"); rt = _numeric(e.right, f"operator {e.op!r}")
        if e.op == "/":
            return "number"
        return "int" if lt == "int" and rt == "int" else "number"
    if e.op in _ORDER_OPS:
        _numeric(e.left, f"operator {e.op!r}"); _numeric(e.right, f"operator {e.op!r}")
        return "bool"
    return _equality(e)   # == / !=
```

with two helpers inside `infer_type`:

```python
def _numeric(e: Expr, ctx: str) -> Type:
    got = infer(e)
    if got not in _NUMERIC and got != "unknown":
        problems.append(f"{ctx} requires a number operand, got {got}")
        return "number"
    return got  # int stays int, number stays number, unknown stays unknown-ish -> caller widens

def _equality(e: BinaryOp) -> Type:
    left, right = infer(e.left), infer(e.right)
    if "unknown" not in (left, right):
        lnum, rnum = left in _NUMERIC, right in _NUMERIC
        ok = (lnum and rnum) or (left == right)   # both numeric, or same non-numeric class
        if not ok:
            problems.append(f"operator {e.op!r} cannot compare {left} with {right}")
    return "bool"
```

Note `_numeric` returns `"number"` on a bad operand so a downstream int-vs-number decision does not further mis-fire; and `expect` (kept from the original) is still used for the boolean operand cases.

- [ ] **Step 4: Run the new tests + the full analyze suite.** `pytest tests/experiment/test_analyze_types.py tests/experiment/ -q`. Existing `infer_type` tests that asserted `count(...) == "number"` at the type level must be updated to `"int"` (verify each is a spelling update, not a real regression).

- [ ] **Step 5: mypy + ruff, then commit.** `git commit -m "feat(experiment): int and string in expression type inference"`

---

### Task 3: Infer `compute` binding types (document-order)

Make `_collect_binding_types` a document-order pass that infers each `compute.into`'s type from its `value` expression (using the types accumulated so far), in addition to the `operator_input` types it already collects. This is the linchpin: it is what makes references to a computed binding statically typed.

**Files:**
- Modify: `src/lab_devices/experiment/validate.py` (`_collect_binding_types`)
- Test: `tests/experiment/test_validate_binding_types.py` (new)

**Interfaces:**
- Consumes: `infer_type`, `Type` (Tasks 1-2); `_iter_all_blocks` (existing, document-order depth-first).
- Produces: `_collect_binding_types(w) -> dict[str, Type]` now covering `compute` bindings. Conflicting definitions of one name degrade to `"unknown"` (matching the existing operator-input rule).

- [ ] **Step 1: Write failing tests** (whole-document, through `validate`)

```python
# tests/experiment/test_validate_binding_types.py
import pytest
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from lab_devices.experiment.errors import ValidationError

def _doc(blocks, **extra):
    return {"schema_version": 2, "blocks": blocks, **extra}

def _validate(doc):
    validate(workflow_from_dict(doc))  # raises ValidationError on failure

def test_computed_number_binding_used_as_guard_is_rejected():
    doc = _doc([
        {"compute": {"into": "x", "value": "1"}},                 # x : int
        {"branch": {"if": "x", "then": []}},                      # guard wants bool
    ])
    with pytest.raises(ValidationError) as ei:
        _validate(doc)
    assert any("bool" in d.message and "into" not in d.message for d in ei.value.diagnostics)

def test_computed_boolean_binding_used_in_arithmetic_is_rejected():
    doc = _doc([
        {"compute": {"into": "flag", "value": "count(s) > 0"}},   # flag : bool
        {"record": {"into": "s2", "value": "flag + 1"}},          # arithmetic on a bool
    ], streams={"s": {}, "s2": {}})
    with pytest.raises(ValidationError):
        _validate(doc)

def test_consistent_computed_binding_use_passes():
    doc = _doc([
        {"compute": {"into": "flag", "value": "count(s) > 0"}},   # flag : bool
        {"branch": {"if": "flag", "then": []}},                   # guard : bool  OK
    ], streams={"s": {}})
    _validate(doc)  # must not raise
```

(`streams` with `{}` units is legal in v2; Engine A does not touch stream units.)

- [ ] **Step 2: Run — expect the two `raises` tests to FAIL** (today a compute binding is `unknown`, so nothing is flagged).

- [ ] **Step 3: Rewrite `_collect_binding_types`** (validate.py:609-621):

```python
def _collect_binding_types(w: Workflow) -> dict[str, Type]:
    """Inferred scalar type of every binding, in document order: operator inputs from their
    declared `type`, compute bindings from their `value` expression (design 2026-07-21 §4.1).
    Conflicting definitions of one name degrade to 'unknown'."""
    types: dict[str, Type] = {}

    def record(name: str, t: Type) -> None:
        if name in types and types[name] != t:
            types[name] = "unknown"
        else:
            types.setdefault(name, t)

    for _, b in _iter_all_blocks(w):
        if isinstance(b, B.OperatorInput) and isinstance(b.name, str):
            t = _INPUT_TYPES.get(b.type, "unknown") if isinstance(b.type, str) else "unknown"
            record(b.name, t)
        elif isinstance(b, B.Compute) and isinstance(b.into, str) and isinstance(b.value, str):
            try:
                expr = parse_expression(b.value)
            except ExpressionError:
                record(b.into, "unknown")   # holes / bad syntax: unparseable here, checked
                continue                     # post-expansion (macro path) or diagnosed globally
            record(b.into, infer_type(expr, types).type)
    return types
```

The `types` map passed into `infer_type` is the types-so-far, so a compute may reference an earlier binding. A forward reference is `unknown` here and is separately the `data-flow` "read before written" diagnostic.

- [ ] **Step 4: Run the tests.** The first two now raise; the third passes. `pytest tests/experiment/test_validate_binding_types.py -q`

- [ ] **Step 5: Run the whole suite** to catch documents that had latent, now-detected type bugs: `pytest tests/experiment -q`. Investigate each new failure — a *test fixture* with a genuine type bug gets fixed; a real regression gets fixed in code.

- [ ] **Step 6: mypy + ruff, then commit.** `git commit -m "feat(experiment): infer compute binding types in document order"`

---

### Task 4: Strict `unknown` at slots, and `int`-precise param checks

Turn on the strictness: an expression whose top type is `unknown` used where a concrete type is required is now a diagnostic (previously silent). Make param checks distinguish `int` from `number`, and route every slot check through `assignable`.

**Files:**
- Modify: `src/lab_devices/experiment/validate.py` (`_check_expr_type`, `_check_param_value`, `_check_compute_value`, `_check_record_value`)
- Test: `tests/experiment/test_validate_strict_types.py` (new)

**Interfaces:**
- Consumes: `assignable`, `infer_type`, `_collect_binding_types` (Tasks 1-3).
- Produces: `_check_expr_type` gains a `strict: bool = True` behaviour — see below.

- [ ] **Step 1: Write failing tests**

```python
# tests/experiment/test_validate_strict_types.py — same _doc/_validate helpers as Task 3
def test_int_param_given_a_float_expression_is_rejected():
    # valve.set_position.position is kind "int"; a number expression must not satisfy it.
    doc = {"schema_version": 2,
           "roles": {"v": {"type": "valve"}},
           "blocks": [{"compute": {"into": "p", "value": "1.5"}},
                      {"command": {"device": "v", "verb": "set_position",
                                   "params": {"position": "p"}}}]}
    with pytest.raises(ValidationError):
        _validate(doc)

def test_int_param_given_an_int_expression_passes():
    doc = {"schema_version": 2,
           "roles": {"v": {"type": "valve"}},
           "blocks": [{"compute": {"into": "p", "value": "1 + 1"}},   # int
                      {"command": {"device": "v", "verb": "set_position",
                                   "params": {"position": "p"}}}]}
    _validate(doc)  # must not raise

def test_branch_conflicting_binding_types_is_rejected_at_use():
    doc = _doc([
        {"branch": {"if": "count(s) > 0",
                    "then": [{"compute": {"into": "x", "value": "1"}}],       # int
                    "else": [{"compute": {"into": "x", "value": "count(s) > 0"}}]}},  # bool
        {"record": {"into": "s2", "value": "x"}},   # x is 'unknown' (conflict) -> strict reject
    ], streams={"s": {}, "s2": {}})
    with pytest.raises(ValidationError):
        _validate(doc)
```

- [ ] **Step 2: Run — expect all three to behave wrong today** (float→int not caught; conflict→unknown silently accepted).

- [ ] **Step 3: Add strictness to `_check_expr_type`** (validate.py:624-642):

```python
def _check_expr_type(text, expected, ctx, binding_types, out, *, strict=True):
    try:
        expr = parse_expression(text)
    except ExpressionError as exc:
        out.append(Diagnostic("type", ctx, f"invalid expression: {exc}"))
        return
    report = infer_type(expr, binding_types)
    for problem in report.problems:
        out.append(Diagnostic("type", ctx, problem))
    if report.type == "unknown":
        if strict:
            out.append(Diagnostic(
                "type", ctx,
                "cannot determine the type of this expression; it may reference a binding "
                "with no single inferable type — give it a consistent type or annotate it",
            ))
        return
    if not assignable(report.type, expected):
        out.append(Diagnostic("type", ctx, f"expected a {expected} expression, got {report.type}"))
```

- [ ] **Step 4: Make `_check_param_value` int-precise** (validate.py:660): replace the two-way `expected` with three-way, so an `int` param demands an `int`-typed expression:

```python
if isinstance(value, str):
    if spec.kind == "bool":
        expected: ExprType = "bool"
    elif spec.kind == "int":
        expected = "int"
    else:
        expected = "number"
    _check_expr_type(value, expected, ctx, binding_types, out)
    _check_streams_declared(value, ctx, w, out)
    return
```

- [ ] **Step 5: Tighten `_check_compute_value` and `_check_record_value`.** `_check_compute_value` must reject a value whose type is `string` or `unknown` (a compute stores a number or a boolean), so give it an explicit check rather than accepting any top type:

```python
# inside _check_compute_value, after computing `report = infer_type(...)` / its problems:
if report.type == "string":
    out.append(Diagnostic("type", ctx, "compute stores a number or a boolean, not a string"))
elif report.type == "unknown":
    out.append(Diagnostic("type", ctx,
        "cannot determine the type of this compute value; give it a consistent type"))
```

`_check_record_value` already asserts `"number"`; ensure it now calls `_check_expr_type(..., "number", ...)` so an `int` expression is accepted (via `assignable`) but a `bool` is rejected. (If it hand-rolled the number check, switch it to `_check_expr_type` for consistency, keeping its existing boolean-literal guard.)

- [ ] **Step 6: Run all new tests + full suite + gates.** `pytest tests/experiment -q && mypy src/lab_devices && ruff check src tests`. Fix fixtures with genuine now-caught bugs.

- [ ] **Step 7: Commit.** `git commit -m "feat(experiment): strict unknown + int-precise param typing"`

---

### Task 5: String literals in the grammar + string equality at runtime

Add single-quoted string literals to the expression language (`'chemostat'`) and let the evaluator compare strings, so an `enum` operator input becomes branchable (engine-limitation #5).

**Files:**
- Modify: `src/lab_devices/experiment/expr.py` (tokenizer, `Const`, `_atom`)
- Modify: `src/lab_devices/experiment/evaluate.py` (`_binary` equality, `_binding` string handling)
- Test: `tests/experiment/test_expr.py`, `tests/experiment/test_evaluate.py` (existing files)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Const.value` widened to `int | float | bool | str`; a `'...'` literal parses to `Const(str)`. `infer_type` already returns `"string"` for `Const(str)` once Task 2's `isinstance(e.value, bool)`/`int`/`float` chain gets a `str` arm — add it.

- [ ] **Step 1: Write failing tests**

```python
# tests/experiment/test_expr.py
from lab_devices.experiment.expr import parse_expression, Const, BinaryOp
def test_single_quoted_string_literal():
    e = parse_expression("mode == 'chemostat'")
    assert isinstance(e, BinaryOp) and e.op == "=="
    assert isinstance(e.right, Const) and e.right.value == "chemostat"

# tests/experiment/test_evaluate.py
from lab_devices.experiment.evaluate import evaluate
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.state import RunState
def test_string_equality_evaluates():
    st = RunState(); st.bind("mode", "chemostat")
    assert evaluate(parse_expression("mode == 'chemostat'"), st, 0.0) is True
    assert evaluate(parse_expression("mode == 'turbidostat'"), st, 0.0) is False

def test_string_still_rejected_in_arithmetic():
    import pytest
    from lab_devices.experiment.errors import EvaluationError
    st = RunState(); st.bind("mode", "chemostat")
    with pytest.raises(EvaluationError):
        evaluate(parse_expression("mode + 1"), st, 0.0)
```

- [ ] **Step 2: Run — expect parse failure on the quote char.**

- [ ] **Step 3: Add the string token to `expr.py`.** Extend `_TOKEN_RE` (expr.py:74-79) with a `STRING` group matching `'[^']*'` (single-quoted, no escapes — the enum choices are plain identifiers-ish words); widen `Const.value` type (expr.py:18) to `int | float | bool | str`; in `_atom` handle `tok.kind == "STRING"` by returning `Const(tok.text[1:-1])`. Keep the DURATION-in-expression rejection as-is (durations arrive in Engine C).

- [ ] **Step 4: Add the `str` arm to `infer_type`'s `Const` case** (from Task 2): `if isinstance(e.value, str): return "string"` (place before the numeric checks; `bool` is already special-cased first).

- [ ] **Step 5: Evaluate string equality.** In `evaluate.py` `_binary` (evaluate.py:100-102), the `==`/`!=` branch currently rejects a bool-vs-number mix and otherwise compares. Generalise: allow two strings to compare equal/unequal; keep the "cannot compare a boolean with a number" rule; a string-vs-number comparison raises. In `_binding` (evaluate.py:54-57), stop raising for a string binding *unconditionally* — return the string; the numeric coercions (`_number`) still reject it wherever a number is actually required, and `==` now handles the string case. Verify `_number`/`_boolean` still reject strings so `mode + 1` raises.

- [ ] **Step 6: Run the new tests + full suite + gates.** `pytest tests/experiment -q && mypy src/lab_devices && ruff check src tests`

- [ ] **Step 7: Commit.** `git commit -m "feat(experiment): single-quoted string literals and string equality (enum branching)"`

---

### Task 6: Sweep examples, mark limitation #5 shipped, CHANGELOG

**Files:**
- Modify (if needed): `examples/*.json`, any test fixture with a now-caught latent type bug
- Modify: `docs/experiment-engine-limitations.md` (#5)
- Modify: `CHANGELOG.md` note is handled by release-please from commit messages — instead add a short note to the design/limitations docs; do **not** hand-edit `CHANGELOG.md`.

- [ ] **Step 1: Run the full test suite and the examples' own validation tests.** `pytest -q`. Every `examples/*.json` is loaded/validated by the doc/example tests; any that now fails carried a latent type bug — fix the document so it type-checks (and note what the bug was in the commit body).

- [ ] **Step 2: Confirm `examples/morbidostat.json` still loads, validates, expands, and (in its fake-lab test) runs.** `pytest -q -k "morbidostat or docs_workflow_schema"`

- [ ] **Step 3: Mark limitation #5 shipped** in `docs/experiment-engine-limitations.md` (§5 "`enum` operator inputs are unusable in expressions"): add a "**SHIPPED (2026-07-21, Increment 10 Engine A)**" banner mirroring the existing shipped-banner style, noting single-quoted string literals + string equality now make an `enum` branchable, e.g. `branch if: "mode == 'chemostat'"`.

- [ ] **Step 4: Full gate run.** `pytest -q && mypy src/lab_devices && ruff check src tests`

- [ ] **Step 5: Commit.** `git commit -m "docs(experiment): mark enum-in-expressions (limitation #5) shipped; fix latent type bugs in examples"`

---

## Self-Review

- **Spec coverage (Engine A slice of §11.1):** structured lattice → Tasks 1-2; `int`/`number` → Tasks 1,2,4; string comparison → Tasks 2,5; strict `unknown` → Task 4; compute-binding inference → Task 3; string equality/#5 → Tasks 5-6; no shape change → Global Constraints. Units, `as`, durations, schema v3 are explicitly **out** of Engine A (Engine B/C).
- **Placeholders:** none — every code step shows the code.
- **Type consistency:** `Type`/`assignable`/`infer_type` signatures are used identically across tasks; `_collect_binding_types` return type widened to `dict[str, Type]` in Task 3 and consumed by `_check_expr_type` in Task 4; `Const.value` widening (Task 5) is consistent with the `infer_type` `str` arm.
- **Mutation-verified:** Tasks 2-5 each assert a *reject* case, not only a pass case.
