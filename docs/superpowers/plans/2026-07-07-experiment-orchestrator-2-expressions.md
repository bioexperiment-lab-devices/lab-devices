# Experiment Orchestrator — Increment 2: Expression Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data-plane expression engine (design §6-8, §15): tokenizer + parser for the infix expression strings stored in the AST, a runtime state model (streams + bindings), and a fail-safe evaluator — standalone, synchronous, hardware-free.

**Architecture:** Four new modules in `lab_devices.experiment`: `durations.py` (shared `"5min"`/`"30s"` → seconds parser, also used by interval fields), `expr.py` (typed expression AST + tokenizer + recursive-descent parser), `state.py` (append-only timestamped `Stream`s + scalar bindings in a `RunState`), `evaluate.py` (expression AST × state × now → value, with the §6 fail-safe missing-data rule). `serialize.py` gains eager parse-at-load so syntax errors fail at load time; expression strings stay stored verbatim in the block AST, so Increment 1 round-trip is untouched.

**Tech Stack:** Python 3.11, standard library only (`re`, `dataclasses`, `bisect`), pytest. No async, no hardware, no new dependencies.

## Global Constraints

- Interpreter: run ALL tooling as `.venv/bin/python -m <tool>` — bare `python`/`python3` lacks the deps.
- Gate after every task (all must be clean before commit):
  - `.venv/bin/python -m pytest` (whole suite, not just the new file)
  - `.venv/bin/python -m mypy` (strict; config checks `src/lab_devices` only — tests are not type-checked)
  - `.venv/bin/python -m ruff check .`
  - `awk 'length > 100 {print FILENAME ":" FNR ": " length}' src/lab_devices/experiment/*.py tests/test_experiment_*.py` — must print nothing (ruff's default select does not include E501).
- Source modules start with `from __future__ import annotations` and a one-line docstring citing the design section. Dataclasses throughout. Python ≥3.11.
- Tests live flat in `tests/` as `test_experiment_*.py` and do NOT use the future-import (repo convention).
- Expressions remain verbatim `str` in the block AST (`blocks.py` is not modified); load-time parsing is validation only, and JSON round-trip must stay lossless. All existing Increment 1 tests must stay green (their fixture strings were checked during planning: every `gap_after`/`pace`/`duration` and every `if`/`until` in them is valid under this grammar).
- Branch: `feat/experiment-orchestrator-2-expressions` off `main` (PR #1 is merged into main). Never commit to `main`.

## Settled design sub-decisions (rationale recorded; do not re-litigate in-task)

1. **Eager parse at load.** `serialize.py` parses every expression/duration string while building blocks (like the existing `lookup()` verb check) and fails the load on syntax errors. Parse results are discarded — strings stay verbatim in the AST; the Increment 4 executor re-parses (parsing is cheap; no caching machinery).
2. **Every string param is parsed as an expression at load.** Enum-ish string params like `"direction": "forward"` are bare names, which are *syntactically* valid (they parse as binding refs), so they pass load. Distinguishing enum params from expression params semantically is Increment 3's registry param-typing job. Consequence: a string param that is not a grammatical expression (e.g. `"fast forward"`) is a load error — acceptable, since the §3 registry's real string params are all identifier-like.
3. **Shared duration parser** in `durations.py`: `parse_duration("30s"|"5min"|"250ms"|"1.5h") -> float` seconds. Raises `ValueError`; callers wrap into their own taxonomy (`ExpressionError` in the parser, `WorkflowLoadError` in the loader). Also wired into load validation for `gap_after`, `start_offset`, `pace`, `wait.duration` (same fail-fast principle).
4. **Duration literals exist only inside stat windows** (`last=5min`), exactly per the §6 grammar. Interval fields are plain duration strings, not expressions, in this increment.
5. **Errors:** `ExpressionError(WorkflowLoadError)` for syntax (mirrors the `UnknownVerbError` precedent — a bad expression makes the document unloadable); `EvaluationError(ExperimentError)` for every runtime can't-produce-a-value case: empty window, unbound binding, divide-by-zero, unknown stream, type mismatch.
6. **`last=N` is a cap ("up to the N most recent samples"), not a minimum.** The design's own flagship example (§15.2) evaluates `mean(OD, last=100)` on loop iteration 1 with a single sample; a strict "insufficient window" reading would break it. The only missing-data case for `last/mean/min/max` is a genuinely *empty* window; `count` over an empty window is `0` (§6, explicitly not missing data).
7. **`and`/`or` short-circuit (Python semantics, left-to-right).** This is what makes `count`'s special empty-window behavior useful: `count(OD) > 0 and mean(OD) > x` is the sanctioned guard idiom for pre-test loops (§6 cold-start). Operands are still type-checked as booleans when evaluated.
8. **Comparison chaining (`a < b < c`) is a parse error** — clearer than silently evaluating `(a < b) < c` into a type error.
9. **Bindings may hold `str`** in state (enum `OperatorInput` produces them), but *referencing* a string binding in an expression raises `EvaluationError` — the grammar has no string literals, so no expression can meaningfully consume one.
10. **Numbers:** literals without a decimal point parse as `int`, with one as `float`; `bool` is NOT a number (`1 + true` is an `EvaluationError`, despite Python's `bool ⊂ int`); `/` is true division; division by zero (int or float) raises `EvaluationError`, never `inf`.

## Setup (before Task 1)

```bash
cd /Users/khamit/lab-devices
git checkout main && git pull
git checkout -b feat/experiment-orchestrator-2-expressions
git add docs/superpowers/plans/2026-07-07-experiment-orchestrator-2-expressions.md
git commit -m "docs: increment 2 (expression engine) implementation plan"
```

---

### Task 1: Error taxonomy additions + shared duration parser

**Files:**
- Modify: `src/lab_devices/experiment/errors.py`
- Create: `src/lab_devices/experiment/durations.py`
- Test: `tests/test_experiment_durations.py` (create)

**Interfaces:**
- Consumes: `ExperimentError`, `WorkflowLoadError` from `errors.py` (Increment 1).
- Produces:
  - `ExpressionError(WorkflowLoadError)`, `EvaluationError(ExperimentError)`.
  - `parse_duration(text: str) -> float` (seconds; raises `ValueError`).
  - `DURATION_PATTERN: str` — an anchorless, group-free regex fragment matching a duration literal (`\b`-terminated), for embedding in the expression tokenizer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_durations.py
import pytest

from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import (
    EvaluationError,
    ExperimentError,
    ExpressionError,
    WorkflowLoadError,
)


def test_new_error_taxonomy():
    assert issubclass(ExpressionError, WorkflowLoadError)
    assert issubclass(EvaluationError, ExperimentError)
    assert not issubclass(EvaluationError, WorkflowLoadError)


def test_basic_units():
    assert parse_duration("30s") == 30.0
    assert parse_duration("5min") == 300.0
    assert parse_duration("1h") == 3600.0
    assert parse_duration("250ms") == 0.25


def test_fractional_values():
    assert parse_duration("1.5min") == 90.0
    assert parse_duration("0.5s") == 0.5


def test_surrounding_whitespace_is_tolerated():
    assert parse_duration(" 30s ") == 30.0


def test_result_is_float():
    assert isinstance(parse_duration("30s"), float)


@pytest.mark.parametrize(
    "bad", ["", "30", "s", "5 min", "5m", "-30s", "30sec", "min5", "1h30min", "5MIN"]
)
def test_invalid_durations_raise_value_error(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_durations.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment.durations'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/lab_devices/experiment/errors.py`:

```python
class ExpressionError(WorkflowLoadError):
    """An expression string is syntactically invalid (design §6, §15)."""


class EvaluationError(ExperimentError):
    """An expression could not produce a value at runtime (fail-safe rule, design §6):
    empty stream window, unbound binding, divide-by-zero, or a type mismatch."""
```

Create `src/lab_devices/experiment/durations.py`:

```python
"""Shared duration-literal parser for stat windows and interval fields. See design §6, §9."""

from __future__ import annotations

import re

_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0}
# Longest first so "min" is not half-matched as "m"; \b stops e.g. "5s2"/"5min_x".
_UNITS_ALT = "|".join(sorted(_UNIT_SECONDS, key=len, reverse=True))

# Anchorless, group-free fragment for embedding in the expression tokenizer.
DURATION_PATTERN = rf"\d+(?:\.\d+)?(?:{_UNITS_ALT})\b"

_DURATION_RE = re.compile(rf"(?P<number>\d+(?:\.\d+)?)(?P<unit>{_UNITS_ALT})")


def parse_duration(text: str) -> float:
    """Parse "30s" / "5min" / "250ms" / "1.5h" into seconds.

    Raises ValueError on anything else; callers wrap it into their own taxonomy.
    """
    match = _DURATION_RE.fullmatch(text.strip())
    if match is None:
        raise ValueError(
            f"invalid duration {text!r}: expected <number><unit> with unit ms|s|min|h"
        )
    return float(match.group("number")) * _UNIT_SECONDS[match.group("unit")]
```

- [ ] **Step 4: Run test to verify it passes, then the full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_durations.py -v`
Expected: PASS (all)

Run the full gate (see Global Constraints): whole pytest suite, mypy, ruff, awk length check.
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/errors.py src/lab_devices/experiment/durations.py tests/test_experiment_durations.py
git commit -m "feat(experiment): expression/evaluation errors + shared duration parser"
```

---

### Task 2: Expression AST + tokenizer

**Files:**
- Create: `src/lab_devices/experiment/expr.py`
- Test: `tests/test_experiment_expr.py` (create)

**Interfaces:**
- Consumes: `DURATION_PATTERN` from Task 1; `ExpressionError` from Task 1.
- Produces (all frozen dataclasses unless noted):
  - AST nodes: `Const(value: int | float | bool)`, `BindingRef(name: str)`, `AllWindow()`, `SampleWindow(n: int)`, `DurationWindow(seconds: float)`, `StatCall(fn: str, stream: str, window: Window)`, `UnaryOp(op: str, operand: Expr)`, `BinaryOp(op: str, left: Expr, right: Expr)`.
  - Type aliases: `Window = AllWindow | SampleWindow | DurationWindow`, `Expr = Const | BindingRef | StatCall | UnaryOp | BinaryOp`.
  - `STAT_FNS: frozenset[str]` = `{"last", "mean", "min", "max", "count"}`.
  - `Token(kind: str, text: str, pos: int)` with kinds `NUMBER | DURATION | NAME | OP | END`; `tokenize(text: str) -> list[Token]` (raises `ExpressionError` on an unexpected character; keywords lex as plain `NAME`s).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_expr.py
import pytest

from lab_devices.experiment.errors import ExpressionError
from lab_devices.experiment.expr import (
    BinaryOp,
    BindingRef,
    SampleWindow,
    StatCall,
    tokenize,
)


def test_tokenize_arithmetic():
    kinds = [(t.kind, t.text) for t in tokenize("2.0 * (a_1 - b)")]
    assert kinds == [
        ("NUMBER", "2.0"), ("OP", "*"), ("OP", "("), ("NAME", "a_1"),
        ("OP", "-"), ("NAME", "b"), ("OP", ")"), ("END", ""),
    ]


def test_tokenize_duration_and_comparison():
    kinds = [(t.kind, t.text) for t in tokenize("mean(OD, last=5min) >= x")]
    assert ("DURATION", "5min") in kinds
    assert ("OP", ">=") in kinds
    assert ("OP", "=") in kinds  # the 'last=' equals sign
    assert ("OP", ",") in kinds


def test_number_then_name_when_not_a_duration():
    kinds = [(t.kind, t.text) for t in tokenize("5msx")]
    assert kinds[0] == ("NUMBER", "5")
    assert kinds[1] == ("NAME", "msx")


def test_two_char_operators_lex_whole():
    ops = [t.text for t in tokenize("a <= b == c != d >= e") if t.kind == "OP"]
    assert ops == ["<=", "==", "!=", ">="]


def test_keywords_lex_as_plain_names():
    kinds = {(t.kind, t.text) for t in tokenize("true and not false or x")}
    assert ("NAME", "and") in kinds
    assert ("NAME", "not") in kinds
    assert ("NAME", "true") in kinds


def test_positions_recorded():
    assert [t.pos for t in tokenize("a + b")] == [0, 2, 4, 5]


def test_unexpected_character_raises():
    with pytest.raises(ExpressionError, match="unexpected character"):
        tokenize("a $ b")


def test_ast_node_equality():
    expr = BinaryOp("-", BindingRef("target_OD"), StatCall("mean", "OD", SampleWindow(100)))
    assert expr == BinaryOp(
        "-", BindingRef("target_OD"), StatCall("mean", "OD", SampleWindow(100))
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_expr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment.expr'`

- [ ] **Step 3: Write minimal implementation**

Create `src/lab_devices/experiment/expr.py`:

```python
"""Expression sublanguage: typed AST and tokenizer. See design §6 and §15."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lab_devices.experiment.durations import DURATION_PATTERN
from lab_devices.experiment.errors import ExpressionError

STAT_FNS = frozenset({"last", "mean", "min", "max", "count"})


@dataclass(frozen=True)
class Const:
    value: int | float | bool


@dataclass(frozen=True)
class BindingRef:
    name: str


@dataclass(frozen=True)
class AllWindow:
    pass


@dataclass(frozen=True)
class SampleWindow:
    n: int


@dataclass(frozen=True)
class DurationWindow:
    seconds: float


Window = AllWindow | SampleWindow | DurationWindow


@dataclass(frozen=True)
class StatCall:
    fn: str  # one of STAT_FNS
    stream: str
    window: Window


@dataclass(frozen=True)
class UnaryOp:
    op: str  # "-" | "not"
    operand: Expr


@dataclass(frozen=True)
class BinaryOp:
    op: str  # "+" "-" "*" "/" "<" "<=" ">" ">=" "==" "!=" "and" "or"
    left: Expr
    right: Expr


Expr = Const | BindingRef | StatCall | UnaryOp | BinaryOp


@dataclass(frozen=True)
class Token:
    kind: str  # "NUMBER" | "DURATION" | "NAME" | "OP" | "END"
    text: str
    pos: int


_TOKEN_RE = re.compile(
    rf"\s+|(?P<DURATION>{DURATION_PATTERN})"
    r"|(?P<NUMBER>\d+(?:\.\d+)?)"
    r"|(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<OP><=|>=|==|!=|[-+*/(),<>=])"
)


def tokenize(text: str) -> list[Token]:
    """Lex an expression string; raises ExpressionError on an unexpected character."""
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise ExpressionError(f"unexpected character {text[pos]!r} at position {pos}")
        if match.lastgroup is not None:  # None == whitespace
            tokens.append(Token(match.lastgroup, match.group(), pos))
        pos = match.end()
    tokens.append(Token("END", "", len(text)))
    return tokens
```

- [ ] **Step 4: Run test to verify it passes, then the full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_expr.py -v`
Expected: PASS (all)

Run the full gate. Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/expr.py tests/test_experiment_expr.py
git commit -m "feat(experiment): expression AST + tokenizer"
```

---

### Task 3: Recursive-descent expression parser

**Files:**
- Modify: `src/lab_devices/experiment/expr.py` (append parser; extend one import)
- Test: `tests/test_experiment_expr.py` (append)

**Interfaces:**
- Consumes: everything from Task 2; `parse_duration` from Task 1.
- Produces: `parse_expression(text: str) -> Expr` (raises `ExpressionError` with position info). Precedence, loosest → tightest: `or` → `and` → `not` → comparisons (non-chaining) → `+ -` → `* /` → unary `-` → atom. `NAME(` opens a stat call; bare `NAME` is a binding ref; `true`/`false` are `Const`; duration literals are only legal as `last=<duration>` windows.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_expr.py` (extend the existing `expr` import to also name `AllWindow, Const, DurationWindow, UnaryOp, parse_expression`):

```python
def test_number_literals():
    assert parse_expression("42") == Const(42)
    assert parse_expression("2.5") == Const(2.5)


def test_bool_literals():
    assert parse_expression("true") == Const(True)
    assert parse_expression("false") == Const(False)


def test_binding_reference():
    assert parse_expression("target_OD") == BindingRef("target_OD")


def test_stat_fn_name_usable_as_binding():
    assert parse_expression("min") == BindingRef("min")


def test_arithmetic_precedence():
    assert parse_expression("1 + 2 * 3") == BinaryOp(
        "+", Const(1), BinaryOp("*", Const(2), Const(3))
    )


def test_parentheses_override_precedence():
    assert parse_expression("(1 + 2) * 3") == BinaryOp(
        "*", BinaryOp("+", Const(1), Const(2)), Const(3)
    )


def test_left_associativity():
    assert parse_expression("8 - 2 - 1") == BinaryOp(
        "-", BinaryOp("-", Const(8), Const(2)), Const(1)
    )


def test_unary_minus():
    assert parse_expression("-x") == UnaryOp("-", BindingRef("x"))
    assert parse_expression("2 * -3") == BinaryOp("*", Const(2), UnaryOp("-", Const(3)))


def test_stat_call_default_window():
    assert parse_expression("count(OD)") == StatCall("count", "OD", AllWindow())


def test_stat_call_sample_window():
    assert parse_expression("mean(OD, last=100)") == StatCall("mean", "OD", SampleWindow(100))


def test_stat_call_duration_window():
    assert parse_expression("mean(OD, last=5min)") == StatCall(
        "mean", "OD", DurationWindow(300.0)
    )


def test_design_feedback_expression():
    assert parse_expression("2.0 * (target_OD - mean(OD, last=100))") == BinaryOp(
        "*",
        Const(2.0),
        BinaryOp("-", BindingRef("target_OD"), StatCall("mean", "OD", SampleWindow(100))),
    )


def test_design_until_condition():
    assert parse_expression("mean(OD, last=5min) >= target_OD") == BinaryOp(
        ">=", StatCall("mean", "OD", DurationWindow(300.0)), BindingRef("target_OD")
    )


def test_boolean_precedence_or_over_and():
    assert parse_expression("a and b or c") == BinaryOp(
        "or", BinaryOp("and", BindingRef("a"), BindingRef("b")), BindingRef("c")
    )


def test_not_binds_looser_than_comparison():
    assert parse_expression("not count(OD) > 0") == UnaryOp(
        "not", BinaryOp(">", StatCall("count", "OD", AllWindow()), Const(0))
    )


def test_comparison_of_arithmetic():
    assert parse_expression("a + 1 < b * 2") == BinaryOp(
        "<",
        BinaryOp("+", BindingRef("a"), Const(1)),
        BinaryOp("*", BindingRef("b"), Const(2)),
    )


@pytest.mark.parametrize("bad,fragment", [
    ("", "empty expression"),
    ("   ", "empty expression"),
    ("2 +", "expected a literal"),
    ("2 + * 3", "expected a literal"),
    ("(2", "expected"),
    ("2 2", "trailing input"),
    ("foo(OD)", "unknown function"),
    ("mean()", "stream name"),
    ("mean(OD, first=3)", "window must be"),
    ("mean(OD, last=2.5)", "must be an integer"),
    ("mean(OD, last=0)", "must be positive"),
    ("mean(OD, last=5 min)", "expected"),
    ("a < b < c", "cannot be chained"),
    ("5min + 3", "stat window"),
    ("2 + and", "unexpected keyword"),
])
def test_parse_errors(bad, fragment):
    with pytest.raises(ExpressionError, match=fragment):
        parse_expression(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_expr.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_expression'`

- [ ] **Step 3: Write minimal implementation**

In `src/lab_devices/experiment/expr.py`, change the durations import to:

```python
from lab_devices.experiment.durations import DURATION_PATTERN, parse_duration
```

and update the module docstring to `"""Expression sublanguage: typed AST, tokenizer, parser. See design §6 and §15."""`. Then append after `tokenize`:

```python
_KEYWORDS = frozenset({"and", "or", "not", "true", "false"})
_COMPARE_OPS = frozenset({"<", "<=", ">", ">=", "==", "!="})


class _Parser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._tokens = tokenize(text)
        self._pos = 0

    def parse(self) -> Expr:
        expr = self._or_expr()
        tok = self._peek()
        if tok.kind != "END":
            raise self._fail(tok, "unexpected trailing input")
        return expr

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _fail(self, tok: Token, msg: str) -> ExpressionError:
        where = f"at position {tok.pos}" if tok.kind != "END" else "at end of input"
        shown = f" (got {tok.text!r})" if tok.text else ""
        return ExpressionError(f"{msg}{shown} {where} in {self._text!r}")

    def _match_op(self, *ops: str) -> Token | None:
        tok = self._peek()
        if tok.kind == "OP" and tok.text in ops:
            return self._advance()
        return None

    def _expect_op(self, op: str) -> None:
        if self._match_op(op) is None:
            raise self._fail(self._peek(), f"expected {op!r}")

    def _match_name(self, name: str) -> bool:
        tok = self._peek()
        if tok.kind == "NAME" and tok.text == name:
            self._advance()
            return True
        return False

    def _or_expr(self) -> Expr:
        expr = self._and_expr()
        while self._match_name("or"):
            expr = BinaryOp("or", expr, self._and_expr())
        return expr

    def _and_expr(self) -> Expr:
        expr = self._not_expr()
        while self._match_name("and"):
            expr = BinaryOp("and", expr, self._not_expr())
        return expr

    def _not_expr(self) -> Expr:
        if self._match_name("not"):
            return UnaryOp("not", self._not_expr())
        return self._comparison()

    def _comparison(self) -> Expr:
        expr = self._additive()
        op_tok = self._match_op(*_COMPARE_OPS)
        if op_tok is None:
            return expr
        right = self._additive()
        trailing = self._peek()
        if trailing.kind == "OP" and trailing.text in _COMPARE_OPS:
            raise self._fail(trailing, "comparisons cannot be chained")
        return BinaryOp(op_tok.text, expr, right)

    def _additive(self) -> Expr:
        expr = self._multiplicative()
        while (tok := self._match_op("+", "-")) is not None:
            expr = BinaryOp(tok.text, expr, self._multiplicative())
        return expr

    def _multiplicative(self) -> Expr:
        expr = self._unary()
        while (tok := self._match_op("*", "/")) is not None:
            expr = BinaryOp(tok.text, expr, self._unary())
        return expr

    def _unary(self) -> Expr:
        if self._match_op("-") is not None:
            return UnaryOp("-", self._unary())
        return self._atom()

    def _atom(self) -> Expr:
        tok = self._advance()
        if tok.kind == "NUMBER":
            return Const(float(tok.text) if "." in tok.text else int(tok.text))
        if tok.kind == "DURATION":
            raise self._fail(tok, "duration literals are only valid as a stat window")
        if tok.kind == "NAME":
            if tok.text == "true":
                return Const(True)
            if tok.text == "false":
                return Const(False)
            if tok.text in _KEYWORDS:
                raise self._fail(tok, f"unexpected keyword {tok.text!r}")
            nxt = self._peek()
            if nxt.kind == "OP" and nxt.text == "(":
                return self._stat_call(tok)
            return BindingRef(tok.text)
        if tok.kind == "OP" and tok.text == "(":
            expr = self._or_expr()
            self._expect_op(")")
            return expr
        raise self._fail(tok, "expected a literal, name, stat call, or '('")

    def _stat_call(self, fn_tok: Token) -> Expr:
        if fn_tok.text not in STAT_FNS:
            raise self._fail(
                fn_tok,
                f"unknown function {fn_tok.text!r}; expected one of count, last, max, mean, min",
            )
        self._expect_op("(")
        stream_tok = self._advance()
        if stream_tok.kind != "NAME" or stream_tok.text in _KEYWORDS:
            raise self._fail(stream_tok, "expected a stream name")
        window: Window = AllWindow()
        if self._match_op(",") is not None:
            window = self._window()
        self._expect_op(")")
        return StatCall(fn=fn_tok.text, stream=stream_tok.text, window=window)

    def _window(self) -> Window:
        key = self._advance()
        if key.kind != "NAME" or key.text != "last":
            raise self._fail(key, "window must be last=<N> or last=<duration>")
        self._expect_op("=")
        val = self._advance()
        if val.kind == "NUMBER":
            if "." in val.text:
                raise self._fail(val, "window sample count must be an integer")
            n = int(val.text)
            if n <= 0:
                raise self._fail(val, "window sample count must be positive")
            return SampleWindow(n)
        if val.kind == "DURATION":
            return DurationWindow(parse_duration(val.text))
        raise self._fail(val, "window must be last=<N> or last=<duration>")


def parse_expression(text: str) -> Expr:
    """Parse an infix expression string into a typed AST; raises ExpressionError."""
    if not text.strip():
        raise ExpressionError("empty expression")
    return _Parser(text).parse()
```

- [ ] **Step 4: Run test to verify it passes, then the full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_expr.py -v`
Expected: PASS (all)

Run the full gate. Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/expr.py tests/test_experiment_expr.py
git commit -m "feat(experiment): recursive-descent expression parser"
```

---

### Task 4: Runtime data-plane state (streams + bindings)

**Files:**
- Create: `src/lab_devices/experiment/state.py`
- Test: `tests/test_experiment_state.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks (deliberately independent of `expr.py`).
- Produces:
  - `Sample(timestamp: float, value: float)` — frozen dataclass; timestamp shares the clock later used for the evaluator's `now`.
  - `Stream` — append-only: `append(timestamp: float, value: float) -> None` (raises `ValueError` if timestamps would decrease; equal allowed), `samples: Sequence[Sample]` property (read-only view), `__len__`.
  - `BindingValue = int | float | bool | str`.
  - `RunState(streams: dict[str, Stream], bindings: dict[str, BindingValue])` with helpers `record(stream, timestamp, value)` (creates the stream on first write) and `bind(name, value)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_state.py
import pytest

from lab_devices.experiment.state import RunState, Sample, Stream


def test_stream_appends_in_order():
    s = Stream()
    s.append(1.0, 0.5)
    s.append(2.0, 0.6)
    assert len(s) == 2
    assert list(s.samples) == [Sample(1.0, 0.5), Sample(2.0, 0.6)]


def test_equal_timestamps_allowed():
    s = Stream()
    s.append(1.0, 0.5)
    s.append(1.0, 0.6)
    assert len(s) == 2


def test_decreasing_timestamp_rejected():
    s = Stream()
    s.append(2.0, 0.5)
    with pytest.raises(ValueError, match="non-decreasing"):
        s.append(1.0, 0.6)


def test_sample_is_frozen():
    sample = Sample(1.0, 0.5)
    with pytest.raises(AttributeError):
        sample.value = 0.7


def test_run_state_record_creates_stream():
    state = RunState()
    state.record("OD", 1.0, 0.5)
    state.record("OD", 2.0, 0.6)
    assert len(state.streams["OD"]) == 2
    assert state.streams["OD"].samples[-1] == Sample(2.0, 0.6)


def test_run_state_bind():
    state = RunState()
    state.bind("target_OD", 0.8)
    state.bind("mode", "fast")
    assert state.bindings == {"target_OD": 0.8, "mode": "fast"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment.state'`

- [ ] **Step 3: Write minimal implementation**

Create `src/lab_devices/experiment/state.py`:

```python
"""Runtime data-plane state: streams and operator-input bindings. See design §6."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sample:
    """One stream point; timestamp shares the clock used for the evaluator's `now`."""

    timestamp: float
    value: float


class Stream:
    """Append-only, timestamp-ordered series produced by Measure blocks (design §6)."""

    def __init__(self) -> None:
        self._samples: list[Sample] = []

    def append(self, timestamp: float, value: float) -> None:
        if self._samples and timestamp < self._samples[-1].timestamp:
            raise ValueError(
                f"stream timestamps must be non-decreasing: "
                f"{timestamp} < {self._samples[-1].timestamp}"
            )
        self._samples.append(Sample(timestamp, value))

    @property
    def samples(self) -> Sequence[Sample]:
        """Read-only, oldest-first view of the series."""
        return self._samples

    def __len__(self) -> int:
        return len(self._samples)


BindingValue = int | float | bool | str


@dataclass
class RunState:
    """Shared workflow state: named streams plus scalar bindings (design §6)."""

    streams: dict[str, Stream] = field(default_factory=dict)
    bindings: dict[str, BindingValue] = field(default_factory=dict)

    def record(self, stream: str, timestamp: float, value: float) -> None:
        """Append a measurement, creating the stream on first write."""
        self.streams.setdefault(stream, Stream()).append(timestamp, value)

    def bind(self, name: str, value: BindingValue) -> None:
        """Bind an operator-input scalar for later reference by name."""
        self.bindings[name] = value
```

- [ ] **Step 4: Run test to verify it passes, then the full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_state.py -v`
Expected: PASS (all)

Run the full gate. Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/state.py tests/test_experiment_state.py
git commit -m "feat(experiment): runtime data-plane state (streams + bindings)"
```

---

### Task 5: Fail-safe evaluator + `resolve` entry point

**Files:**
- Create: `src/lab_devices/experiment/evaluate.py`
- Test: `tests/test_experiment_evaluate.py` (create)

**Interfaces:**
- Consumes: `Expr` + node types + `parse_expression` (Tasks 2-3), `RunState`/`Sample` (Task 4), `EvaluationError` (Task 1), `ValueExpr` from `blocks.py` (Increment 1: `str | int | float | bool`).
- Produces:
  - `Value = int | float | bool`.
  - `evaluate(expr: Expr, state: RunState, now: float) -> Value` — raises `EvaluationError` for: unbound binding, string-valued binding, unknown stream, empty window for `last/mean/min/max`, division by zero, any type mismatch. `count` over an empty (but existing) stream returns `0`. `and`/`or` short-circuit left-to-right.
  - `resolve(value: ValueExpr, state: RunState, now: float) -> Value` — literals pass through; strings are parsed then evaluated (the entry point Increment 4's executor will call per block dispatch).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_evaluate.py
import pytest

from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.evaluate import evaluate, resolve
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.state import RunState, Stream


def ev(text, state=None, now=0.0):
    return evaluate(parse_expression(text), state if state is not None else RunState(), now)


def _od_state():
    state = RunState()
    for t, v in [(0.0, 0.4), (10.0, 0.5), (20.0, 0.6), (30.0, 0.7)]:
        state.record("OD", t, v)
    return state


def test_arithmetic():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("7 / 2") == 3.5
    assert ev("-4 + 1") == -3


def test_int_and_float_results():
    assert ev("2 + 3") == 5
    assert isinstance(ev("2 + 3"), int)
    assert isinstance(ev("2.0 + 3"), float)


def test_division_by_zero_raises():
    with pytest.raises(EvaluationError, match="division by zero"):
        ev("1 / 0")
    with pytest.raises(EvaluationError, match="division by zero"):
        ev("1 / (2 - 2)")


def test_comparisons():
    assert ev("1 < 2") is True
    assert ev("2 <= 2") is True
    assert ev("3 > 4") is False
    assert ev("4 >= 5") is False
    assert ev("1 == 1.0") is True
    assert ev("1 != 2") is True


def test_boolean_operators():
    assert ev("true and false") is False
    assert ev("true or false") is True
    assert ev("not true") is False
    assert ev("not 1 > 2") is True


def test_bool_equality():
    assert ev("true == true") is True
    assert ev("true != false") is True


def test_bindings():
    state = RunState()
    state.bind("target_OD", 0.8)
    assert ev("target_OD * 2", state) == pytest.approx(1.6)


def test_unbound_binding_raises():
    with pytest.raises(EvaluationError, match="unbound binding 'target_OD'"):
        ev("target_OD + 1")


def test_string_binding_rejected_in_expression():
    state = RunState()
    state.bind("mode", "fast")
    with pytest.raises(EvaluationError, match="holds a string"):
        ev("mode == 1", state)


@pytest.mark.parametrize("bad", ["1 + true", "true < false", "not 3", "1 and true", "1 == true"])
def test_type_mismatches_raise(bad):
    with pytest.raises(EvaluationError):
        ev(bad)


def test_stats_over_all():
    state = _od_state()
    assert ev("last(OD)", state, now=30.0) == 0.7
    assert ev("mean(OD)", state, now=30.0) == pytest.approx(0.55)
    assert ev("min(OD)", state, now=30.0) == 0.4
    assert ev("max(OD)", state, now=30.0) == 0.7
    assert ev("count(OD)", state, now=30.0) == 4


def test_sample_window_takes_most_recent():
    state = _od_state()
    assert ev("mean(OD, last=2)", state, now=30.0) == pytest.approx(0.65)


def test_sample_window_is_a_cap_not_a_minimum():
    # Design §15.2 evaluates mean(OD, last=100) right after the first measurement:
    # last=N means "up to the N most recent samples", so 4 samples is fine.
    state = _od_state()
    assert ev("mean(OD, last=100)", state, now=30.0) == pytest.approx(0.55)


def test_duration_window_is_relative_to_now():
    state = _od_state()
    assert ev("mean(OD, last=15s)", state, now=30.0) == pytest.approx(0.65)
    assert ev("count(OD, last=1min)", state, now=30.0) == 4


def test_duration_window_boundary_is_inclusive():
    state = _od_state()
    assert ev("count(OD, last=10s)", state, now=30.0) == 2


def test_stale_stream_fails_fresh_window():
    state = _od_state()
    with pytest.raises(EvaluationError, match="empty stream window"):
        ev("last(OD, last=5s)", state, now=120.0)


@pytest.mark.parametrize("fn", ["last", "mean", "min", "max"])
def test_empty_window_raises_for_value_stats(fn):
    state = RunState()
    state.streams["OD"] = Stream()
    with pytest.raises(EvaluationError, match="empty stream window"):
        ev(f"{fn}(OD)", state)


def test_count_over_empty_window_is_zero_not_missing():
    state = RunState()
    state.streams["OD"] = Stream()
    assert ev("count(OD)", state) == 0


def test_unknown_stream_raises():
    with pytest.raises(EvaluationError, match="unknown stream 'OD'"):
        ev("count(OD)")


def test_short_circuit_and_enables_count_guard():
    state = RunState()
    state.streams["OD"] = Stream()
    assert ev("count(OD) >= 1 and mean(OD) > 0.5", state) is False


def test_short_circuit_or():
    state = RunState()
    state.streams["OD"] = Stream()
    assert ev("count(OD) == 0 or mean(OD) > 0.5", state) is True


def test_left_operand_of_and_still_fails_on_missing_data():
    state = RunState()
    state.streams["OD"] = Stream()
    with pytest.raises(EvaluationError):
        ev("mean(OD) > 0.5 and count(OD) >= 1", state)


def test_resolve_passes_literals_through():
    state = RunState()
    assert resolve(3.5, state, now=0.0) == 3.5
    assert resolve(7, state, now=0.0) == 7
    assert resolve(True, state, now=0.0) is True


def test_resolve_parses_and_evaluates_strings():
    state = _od_state()
    state.bind("target_OD", 0.8)
    volume = resolve("2.0 * (target_OD - mean(OD, last=100))", state, now=30.0)
    assert volume == pytest.approx(2.0 * (0.8 - 0.55))
    assert resolve("mean(OD, last=5min) >= target_OD", state, now=30.0) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_evaluate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lab_devices.experiment.evaluate'`

- [ ] **Step 3: Write minimal implementation**

Create `src/lab_devices/experiment/evaluate.py`:

```python
"""Expression evaluator with fail-safe missing-data semantics. See design §6-8."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence

from lab_devices.experiment.blocks import ValueExpr
from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.expr import (
    BinaryOp,
    BindingRef,
    Const,
    DurationWindow,
    Expr,
    SampleWindow,
    StatCall,
    UnaryOp,
    parse_expression,
)
from lab_devices.experiment.state import RunState, Sample

Value = int | float | bool

_ARITH_OPS = frozenset({"+", "-", "*", "/"})
_ORDER_OPS = frozenset({"<", "<=", ">", ">="})


def evaluate(expr: Expr, state: RunState, now: float) -> Value:
    """Evaluate a parsed expression; raises EvaluationError if no value can be produced."""
    if isinstance(expr, Const):
        return expr.value
    if isinstance(expr, BindingRef):
        return _binding(expr, state)
    if isinstance(expr, StatCall):
        return _stat(expr, state, now)
    if isinstance(expr, UnaryOp):
        return _unary(expr, state, now)
    return _binary(expr, state, now)


def resolve(value: ValueExpr, state: RunState, now: float) -> Value:
    """Resolve a block scalar slot: literals pass through, strings parse and evaluate."""
    if isinstance(value, str):
        return evaluate(parse_expression(value), state, now)
    return value


def _binding(ref: BindingRef, state: RunState) -> Value:
    if ref.name not in state.bindings:
        raise EvaluationError(f"unbound binding {ref.name!r}")
    bound = state.bindings[ref.name]
    if isinstance(bound, str):
        raise EvaluationError(
            f"binding {ref.name!r} holds a string; expressions evaluate numbers and booleans"
        )
    return bound


def _number(value: Value, ctx: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{ctx} requires a number, got {value!r}")
    return value


def _boolean(value: Value, ctx: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationError(f"{ctx} requires a boolean, got {value!r}")
    return value


def _unary(expr: UnaryOp, state: RunState, now: float) -> Value:
    if expr.op == "not":
        return not _boolean(evaluate(expr.operand, state, now), "'not'")
    return -_number(evaluate(expr.operand, state, now), "unary '-'")


def _binary(expr: BinaryOp, state: RunState, now: float) -> Value:
    if expr.op == "and":
        # Short-circuit enables guard conditions: count(S) > 0 and mean(S) > x (§6).
        if not _boolean(evaluate(expr.left, state, now), "'and'"):
            return False
        return _boolean(evaluate(expr.right, state, now), "'and'")
    if expr.op == "or":
        if _boolean(evaluate(expr.left, state, now), "'or'"):
            return True
        return _boolean(evaluate(expr.right, state, now), "'or'")
    left = evaluate(expr.left, state, now)
    right = evaluate(expr.right, state, now)
    ctx = f"operator {expr.op!r}"
    if expr.op in _ARITH_OPS:
        return _arith(expr.op, _number(left, ctx), _number(right, ctx))
    if expr.op in _ORDER_OPS:
        return _compare(expr.op, _number(left, ctx), _number(right, ctx))
    if isinstance(left, bool) != isinstance(right, bool):
        raise EvaluationError(f"{ctx} cannot compare a boolean with a number")
    return (left == right) if expr.op == "==" else (left != right)


def _arith(op: str, left: int | float, right: int | float) -> int | float:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if right == 0:
        raise EvaluationError("division by zero")
    return left / right


def _compare(op: str, left: int | float, right: int | float) -> bool:
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def _stat(call: StatCall, state: RunState, now: float) -> Value:
    values = _window_values(call, state, now)
    if call.fn == "count":
        return len(values)
    if not values:
        raise EvaluationError(f"{call.fn}({call.stream}): empty stream window")
    if call.fn == "last":
        return values[-1]
    if call.fn == "mean":
        return sum(values) / len(values)
    if call.fn == "min":
        return min(values)
    return max(values)


def _window_values(call: StatCall, state: RunState, now: float) -> list[float]:
    stream = state.streams.get(call.stream)
    if stream is None:
        raise EvaluationError(f"unknown stream {call.stream!r}")
    samples: Sequence[Sample] = stream.samples
    if isinstance(call.window, SampleWindow):
        samples = samples[-call.window.n:]
    elif isinstance(call.window, DurationWindow):
        cutoff = now - call.window.seconds  # inclusive: sample at the cutoff counts
        start = bisect_left(samples, cutoff, key=lambda s: s.timestamp)
        samples = samples[start:]
    return [s.value for s in samples]
```

- [ ] **Step 4: Run test to verify it passes, then the full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_evaluate.py -v`
Expected: PASS (all)

Run the full gate. Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/evaluate.py tests/test_experiment_evaluate.py
git commit -m "feat(experiment): fail-safe expression evaluator"
```

---

### Task 6: Eager expression + duration validation at workflow load

**Files:**
- Modify: `src/lab_devices/experiment/serialize.py`
- Test: `tests/test_experiment_load_validation.py` (create)

**Interfaces:**
- Consumes: `parse_expression`/`ExpressionError` (Tasks 1-3), `parse_duration` (Task 1), everything already in `serialize.py`.
- Produces: no new public names. Behavior change: `block_from_dict`/`workflow_from_dict` now raise `ExpressionError` (a `WorkflowLoadError`) for malformed expression strings in `params`/`if`/`until`, and `WorkflowLoadError` for malformed duration strings in `gap_after`/`start_offset`/`pace`/`wait.duration`, and for non-string `if`/`until`. Loaded blocks still store the original strings verbatim (round-trip unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_load_validation.py
import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import ExpressionError, WorkflowLoadError
from lab_devices.experiment.serialize import block_from_dict, workflow_from_dict


def test_bad_param_expression_fails_at_load():
    with pytest.raises(ExpressionError, match="param 'volume_ml'"):
        block_from_dict({"command": {"device": "pump_1", "verb": "dispense",
                                     "params": {"volume_ml": "2.0 * ("}}})


def test_bad_measure_param_fails_at_load():
    with pytest.raises(ExpressionError):
        block_from_dict({"measure": {"device": "densitometer_1", "verb": "measure",
                                     "into": "OD", "params": {"x": "1 +"}}})


def test_bad_branch_condition_fails_at_load():
    with pytest.raises(ExpressionError, match="branch if"):
        block_from_dict({"branch": {"if": "last(OD >", "then": []}})


def test_bad_loop_until_fails_at_load():
    with pytest.raises(ExpressionError, match="loop until"):
        block_from_dict({"loop": {"until": "mean(", "body": []}})


def test_non_string_conditions_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"branch": {"if": 5, "then": []}})
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"until": True, "body": []}})


def test_bad_durations_fail_at_load():
    stop = {"device": "pump_1", "verb": "stop"}
    with pytest.raises(WorkflowLoadError, match="gap_after"):
        block_from_dict({"command": stop, "gap_after": "30 sec"})
    with pytest.raises(WorkflowLoadError, match="start_offset"):
        block_from_dict({"command": stop, "start_offset": "later"})
    with pytest.raises(WorkflowLoadError, match="wait duration"):
        block_from_dict({"wait": {"duration": "5"}})
    with pytest.raises(WorkflowLoadError, match="loop pace"):
        block_from_dict({"loop": {"count": 3, "pace": "1 minute", "body": []}})


def test_enum_like_string_params_still_load():
    b = block_from_dict({"command": {"device": "pump_2", "verb": "rotate",
                                     "params": {"direction": "forward",
                                                "speed_ml_min": 2.0}}})
    assert isinstance(b, B.Command)
    assert b.params["direction"] == "forward"


def test_feedback_expression_param_loads_verbatim():
    text = "2.0 * (target_OD - mean(OD, last=100))"
    b = block_from_dict({"command": {"device": "pump_1", "verb": "dispense",
                                     "params": {"volume_ml": text}}})
    assert isinstance(b, B.Command)
    assert b.params["volume_ml"] == text


def test_valid_durations_load_verbatim():
    b = block_from_dict({"command": {"device": "pump_1", "verb": "stop"},
                         "gap_after": "30s"})
    assert b.gap_after == "30s"


def test_bad_expression_inside_group_body_fails_at_load():
    doc = {"schema_version": 1,
           "groups": {"g": {"body": [{"branch": {"if": "((", "then": []}}]}},
           "blocks": []}
    with pytest.raises(ExpressionError):
        workflow_from_dict(doc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_load_validation.py -v`
Expected: FAIL — the "bad" cases load without raising (e.g. `Failed: DID NOT RAISE`); the "still load" cases already pass.

- [ ] **Step 3: Write minimal implementation**

In `src/lab_devices/experiment/serialize.py`:

1. Extend the imports:

```python
from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import ExpressionError, WorkflowLoadError
from lab_devices.experiment.expr import parse_expression
```

2. Add three helpers after `_str`:

```python
def _checked_expr(value: Any, ctx: str) -> str:
    text = _str(value, ctx)
    try:
        parse_expression(text)
    except ExpressionError as exc:
        raise ExpressionError(f"{ctx}: {exc}") from exc
    return text


def _checked_duration(value: Any, ctx: str) -> str:
    text = _str(value, ctx)
    try:
        parse_duration(text)
    except ValueError as exc:
        raise WorkflowLoadError(f"{ctx}: {exc}") from exc
    return text


def _checked_params(body: Any, ctx: str) -> dict[str, Any]:
    params = _params(body, ctx)
    for name, value in params.items():
        if isinstance(value, str):
            _checked_expr(value, f"{ctx} param {name!r}")
    return params
```

3. In `_command`, replace `params=_params(body, "command")` with `params=_checked_params(body, "command")`. In `_measure`, replace `params=_params(body, "measure")` with `params=_checked_params(body, "measure")`.

4. Replace `_wait` with:

```python
def _wait(body: Any, timing: dict[str, Any]) -> B.Block:
    duration = _checked_duration(_req(body, "duration", "wait"), "wait duration")
    return B.Wait(duration=duration, **timing)
```

5. Replace `_loop` with:

```python
def _loop(body: Any, timing: dict[str, Any]) -> B.Block:
    if not isinstance(body, dict):
        raise WorkflowLoadError("loop requires an object body")
    has_count = body.get("count") is not None
    has_until = body.get("until") is not None
    if has_count == has_until:
        raise WorkflowLoadError("loop requires exactly one of 'count' or 'until'")
    check = body.get("check", "after")
    if check not in ("before", "after"):
        raise WorkflowLoadError(f"loop check must be 'before' or 'after', got {check!r}")
    until = _checked_expr(body["until"], "loop until") if has_until else None
    pace = body.get("pace")
    if pace is not None:
        pace = _checked_duration(pace, "loop pace")
    return B.Loop(
        body=_children(_req(body, "body", "loop"), "loop.body"),
        count=body.get("count"), pace=pace,
        until=until, check=check, **timing,
    )
```

6. In `_branch`, replace the `if_` line with:

```python
    if_ = _checked_expr(_req(body, "if", "branch"), "branch if")
```

7. In `block_from_dict`, after the `timing = ...` line, add:

```python
    if "gap_after" in timing:
        timing["gap_after"] = _checked_duration(timing["gap_after"], "gap_after")
    if "start_offset" in timing:
        timing["start_offset"] = _checked_duration(timing["start_offset"], "start_offset")
```

- [ ] **Step 4: Run test to verify it passes, then the full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_load_validation.py -v`
Expected: PASS (all)

Run the full gate — pay attention to `tests/test_experiment_serialize.py` and `tests/test_experiment_workflow.py`: every fixture string in them is valid under the grammar, so they must still pass unchanged. If one fails, the bug is in this task's code, not the fixture.
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/serialize.py tests/test_experiment_load_validation.py
git commit -m "feat(experiment): eager expression/duration validation at workflow load"
```

---

### Task 7: Public API exports + end-to-end smoke

**Files:**
- Modify: `src/lab_devices/experiment/__init__.py`
- Test: `tests/test_experiment_smoke.py` (append)

**Interfaces:**
- Consumes: everything above.
- Produces: package-level re-exports: `ExpressionError`, `EvaluationError`, `parse_duration`, `parse_expression`, `Expr`, `Const`, `BindingRef`, `StatCall`, `UnaryOp`, `BinaryOp`, `Window`, `AllWindow`, `SampleWindow`, `DurationWindow`, `Sample`, `Stream`, `BindingValue`, `RunState`, `Value`, `evaluate`, `resolve` (added to the existing `__all__`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_smoke.py` (add `import pytest` and `import lab_devices.experiment as exp` to its imports):

```python
def test_expression_engine_end_to_end():
    state = exp.RunState()
    state.bind("target_OD", 0.8)
    state.record("OD", 0.0, 0.5)
    state.record("OD", 10.0, 0.6)
    volume = exp.resolve("2.0 * (target_OD - mean(OD, last=100))", state, now=10.0)
    assert volume == pytest.approx(0.5)
    assert exp.resolve("mean(OD, last=5min) >= target_OD", state, now=10.0) is False
    assert exp.resolve("count(OD) >= 2 and last(OD) > 0.55", state, now=10.0) is True


def test_expression_engine_error_types_exported():
    with pytest.raises(exp.ExpressionError):
        exp.parse_expression("2 *")
    with pytest.raises(exp.EvaluationError):
        exp.evaluate(exp.parse_expression("nope + 1"), exp.RunState(), now=0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_smoke.py -v`
Expected: FAIL with `AttributeError: module 'lab_devices.experiment' has no attribute 'RunState'`

- [ ] **Step 3: Write minimal implementation**

Replace `src/lab_devices/experiment/__init__.py` with:

```python
"""Declarative experiment-orchestration layer on top of lab_devices. See design §1."""

from __future__ import annotations

from lab_devices.experiment.blocks import (
    Block,
    Branch,
    Command,
    GroupRef,
    Loop,
    Measure,
    OperatorInput,
    Parallel,
    Serial,
    Wait,
)
from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import (
    EvaluationError,
    ExperimentError,
    ExpressionError,
    UnknownVerbError,
    WorkflowLoadError,
)
from lab_devices.experiment.evaluate import Value, evaluate, resolve
from lab_devices.experiment.expr import (
    AllWindow,
    BinaryOp,
    BindingRef,
    Const,
    DurationWindow,
    Expr,
    SampleWindow,
    StatCall,
    UnaryOp,
    Window,
    parse_expression,
)
from lab_devices.experiment.serialize import (
    block_from_dict,
    block_to_dict,
    load_workflow,
    save_workflow,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.state import BindingValue, RunState, Sample, Stream
from lab_devices.experiment.workflow import (
    Group,
    Metadata,
    Persistence,
    StreamDecl,
    Workflow,
)

__all__ = [
    "Block", "Branch", "Command", "GroupRef", "Loop", "Measure", "OperatorInput",
    "Parallel", "Serial", "Wait",
    "EvaluationError", "ExperimentError", "ExpressionError", "UnknownVerbError",
    "WorkflowLoadError",
    "block_from_dict", "block_to_dict", "load_workflow", "save_workflow",
    "workflow_from_dict", "workflow_to_dict",
    "Group", "Metadata", "Persistence", "StreamDecl", "Workflow",
    "AllWindow", "BinaryOp", "BindingRef", "Const", "DurationWindow", "Expr",
    "SampleWindow", "StatCall", "UnaryOp", "Window", "parse_expression", "parse_duration",
    "BindingValue", "RunState", "Sample", "Stream",
    "Value", "evaluate", "resolve",
]
```

(Note: `ExperimentError` was already exported in Increment 1; the errors import simply gains the two new classes.)

- [ ] **Step 4: Run test to verify it passes, then the full gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_smoke.py -v`
Expected: PASS (all)

Run the full gate. Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/__init__.py tests/test_experiment_smoke.py
git commit -m "feat(experiment): export expression engine public API"
```

---

## Out of scope (do NOT build in this increment)

- Wiring `resolve()` into block execution — Increment 4 (`resolve` is provided as the entry point, unused by any block code here).
- The static validator (device-affinity, mode-lifetime, data-flow) — Increment 3.
- The async executor/scheduler/finalizer, block `id` assignment — Increment 4.
- String literals in the grammar (enum-binding comparisons), `all` as an explicit window keyword, scientific notation, compound durations (`1h30min`) — deferred until a design revision asks for them.
