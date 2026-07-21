# Experiment type system — Engine B (opaque units) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Add opaque symbolic units to the type lattice: numerics carry a unit, streams are `stream<unit>`, expression units combine under ×/÷ and must be *compatible* (equal, or one side unitless) under +/−/compare, and assignment is exact with an `as` cast to bridge. This is the `schema_version` 2→3 hard break.

**Architecture:** Units are **static-only** — erased at runtime, so `evaluate.py`/`execute.py` are untouched. A new `units.py` holds the `Unit` type (canonical sorted tuple), parsing, rendering, and ×/÷. `analyze` gains a `ScalarType(base, unit)` that `infer_type` produces and checks; `validate` threads stream units, checks unit compatibility at each slot, and applies the `as` cast. `serialize` bumps to v3, requires stream units, and (de)serializes `compute.as`/`record.as`.

**Tech Stack:** Python 3.11+, pytest, mypy, ruff. Design: [`../specs/2026-07-21-experiment-type-system-design.md`](../specs/2026-07-21-experiment-type-system-design.md) §3.1, §3.2, §5, §8.

## Global Constraints

- **Units are static-only.** No change to `evaluate.py`/`execute.py`; the runtime value of an expression is independent of its unit. An `as` cast affects only static inference.
- **Opaque symbolic (design §5):** no ontology. `per_hour` and `x_MIC` are single opaque symbols; `AU/s` is `AU · s⁻¹`. The checker never knows `per_hour ≡ 1/s`.
- **Unitless adapts in operators (design §3.2); assignment is exact (design §3.1).** A bare literal / unitless operand takes its sibling's unit; two differently-dimensioned operands are an error. Assignment (record→stream, compute-as, param-with-unit) requires an exact match, bridged only by `as`.
- **`schema_version` → 3, hard break.** Stream `units` become required; `compute.as`/`record.as` are the new fields. A v2 document does not load.
- **Numeric unit-carrying only.** `bool`/`string` carry no unit. `duration` unit handling is Engine C — not here.
- Gate: `pytest -q`, `mypy src/lab_devices`, `ruff check src tests`.

---

### Task 1: The `Unit` type and algebra (`units.py`)

**Files:** Create `src/lab_devices/experiment/units.py`; Test `tests/test_experiment_units.py`.

**Interfaces — Produces:**
- `Unit = tuple[tuple[str, int], ...]` (canonical: sorted by symbol, no zero exponents). `UNITLESS: Unit = ()`.
- `parse_unit(text: str | None) -> Unit` — raises `UnitError` (new, subclass of `WorkflowLoadError`) on a malformed unit. `""`/`None`/`"unitless"`/`"1"` → `UNITLESS`.
- `unit_str(u: Unit) -> str` — render for messages / round-trip (`()`→`"unitless"`, `{AU:1,s:-1}`→`"AU/s"`).
- `unit_mul(a, b) -> Unit`, `unit_div(a, b) -> Unit`.

- [ ] **Step 1: Tests.** `parse_unit("AU") == (("AU",1),)`; `parse_unit("AU/s") == (("AU",1),("s",-1))`; `parse_unit("per_hour") == (("per_hour",1),)`; `parse_unit("") == ()`; `parse_unit("unitless") == ()`; `unit_mul(parse_unit("AU"), parse_unit("s")) == parse_unit("AU*s")`; `unit_div(parse_unit("AU"), parse_unit("s")) == parse_unit("AU/s")`; `unit_div(parse_unit("AU"), parse_unit("AU")) == ()`; `unit_str(parse_unit("AU/s")) == "AU/s"`; a bad unit (`"AU//"`, `"2AU"`) raises `UnitError`.
- [ ] **Step 2:** Run — fail (no module).
- [ ] **Step 3:** Implement. Parse: strip; empties→`UNITLESS`; split on `/` (first group numerator sign +1, every later group sign −1 so `a/b/c == a/(b·c)`); within a group split on `*`; each term matches `([A-Za-z_][A-Za-z0-9_]*)(?:\^(-?\d+))?`; accumulate `sym→sign*exp` in a dict; canonicalise (drop zeros, sort). `unit_mul`/`unit_div` add/subtract exponents. `unit_str`: numerator terms (exp>0) joined by `*`, then `/` denominator terms (exp<0, rendered positive); pure-denominator like `s^-1` renders `1/s`; `()`→`"unitless"`. Add `UnitError(WorkflowLoadError)` in `errors.py`.
- [ ] **Step 4:** Run — pass. **Step 5:** mypy+ruff, commit `feat(experiment): opaque unit type, parser, and algebra`.

---

### Task 2: `ScalarType` and unit-aware `infer_type`

Promote the inferencer to carry a unit alongside the base. `infer_type` gains `stream_units`; binding types become `ScalarType`.

**Files:** Modify `src/lab_devices/experiment/analyze.py`; Test `tests/test_experiment_type_lattice.py` (extend).

**Interfaces:**
- `ScalarType = dataclass(frozen=True)(base: Base, unit: Unit = UNITLESS)` where `Base = Literal["int","number","bool","string","unknown"]` (the old `Type` string becomes `Base`). Convenience: `BOOL = ScalarType("bool")`, `UNKNOWN = ScalarType("unknown")`, etc.
- `TypeReport.type: ScalarType` (was a `Base` string).
- `infer_type(expr, binding_types: Mapping[str, ScalarType], stream_units: Mapping[str, Unit] = {}) -> TypeReport`.
- `assignable(got: ScalarType, expected: ScalarType) -> bool` — `base` via `int<:number`; `unit` **exact** (equal), unless either base is `unknown`. (Operator-level unitless-adaptation is handled inside `infer`, not here — `assignable` is the assignment/slot relation.)
- `join_types(a: ScalarType, b: ScalarType) -> ScalarType` — base join as before; unit: equal→that unit, else if bases numeric and units differ→`unknown` base (a real conflict), unitless+dimensioned→the dimensioned one? No: **join keeps the unit only if equal, else degrades base to unknown** (a binding written AU here and AU/s there is ambiguous).

- [ ] **Step 1: Tests** (extend `test_experiment_type_lattice.py`): `mean(s)` with `stream_units={"s": parse_unit("AU")}` → `ScalarType("number", ("AU",1))`; `count(s)` → `int`, unitless; `mean(s) + mean(s)` → `number<AU>`; `mean(s) + 1` → `number<AU>` (literal adapts); `mean(a) + mean(b)` with a=AU, b=`AU/s` → a problem (incompatible units); `mean(s) / last(t)` (t: `s`) → `number<AU/s>`; `mean(s) > 0.15` → `bool` no problem (literal adapts); `mean(a) > mean(b)` (AU vs AU/s) → problem.
- [ ] **Step 2:** Run — fail. **Step 3:** Implement:
  - `infer` returns `ScalarType`. `Const`: int/number/bool/string, unit `UNITLESS`. `BindingRef`: `binding_types.get(name, UNKNOWN)`. `StatCall`: `count`→`int` unitless; else `number` with `stream_units.get(stream, UNITLESS)`.
  - `numeric(e, ctx)` returns the operand's `ScalarType` (or `number`/unitless on error).
  - Arithmetic `+`/`-`: bases combine as before; **units: `_combine_add(lu, ru)`** = if one is `UNITLESS` return the other; if equal return it; else append a problem and return `UNITLESS`. `*`: `unit_mul`. `/`: `unit_div`, base `number`. Comparison `<` etc. and `==`/`!=` numeric: check units with `_combine_add` (same compatibility), result `bool` unitless.
  - `_describe` renders `base<unit>` (e.g. `number<AU/s>`), naming a bare binding.
- [ ] **Step 4:** Run — pass; fix Engine-A tests that compared `report.type == "int"` (now `report.type.base == "int"` or `report.type == ScalarType("int")`). **Step 5:** mypy+ruff, commit `feat(experiment): units in expression type inference`.

---

### Task 3: Unit checking, `as` casts, and binding units in `validate.py`

**Files:** Modify `src/lab_devices/experiment/validate.py`; Test `tests/test_experiment_units_validate.py` (new).

**Interfaces / behaviour:**
- `_collect_binding_types(w) -> dict[str, ScalarType]`: operator inputs → base from `_INPUT_TYPES`, unit `UNITLESS`; compute → `infer_type(value, types, stream_units).type`, **overridden by `compute.as`** (parse the asserted unit, keep the inferred base). Join across writers with `join_types`.
- `_stream_units(w) -> dict[str, Unit]`: parse `w.streams[name].units` for every declared stream (top-level; group-local streams enter post-expansion).
- `_check_expr_type(text, expected: ScalarType, ...)`: infer with `stream_units`; problems; ambiguous refs; then `assignable(report.type, expected)` (base+unit exact). For guards, `expected = BOOL`; for `record`, `expected = number<stream unit>` **unless `record.as` is set**, in which case the asserted unit replaces the derived one before the stream-unit check.
- `record.as` / `compute.as`: `as` overrides the value's unit (trusted, no compatibility check with the derived unit — that is the point of a cast). For `record`, the asserted unit must equal the target stream's unit. For `compute`, the binding takes the asserted unit.
- Registry param units (Task 5) plug into `_check_param_value`.

- [ ] **Step 1: Tests** (mutation-verified): recording a `number<AU>` expression into an `AU/s` stream → rejected; recording it into an `AU` stream → clean; `mean(a_AU) + mean(b_AU_s)` in a guard → rejected; a bare-literal threshold `last(od) > 0.15` (od AU) → clean; `record ... as: per_hour` where the target stream is `per_hour` → clean even though the value derives unitless; `record ... as: AU` into a `per_hour` stream → rejected (cast disagrees with target).
- [ ] **Step 2:** Run — fail. **Step 3:** Implement per above. **Step 4:** Run — pass. **Step 5:** mypy+ruff, commit `feat(experiment): unit checking and the as cast`.

---

### Task 4: Schema v3 — `as` fields, required stream units

**Files:** Modify `serialize.py`, `blocks.py`; Test `tests/test_experiment_serialize.py` (extend) + a version-gate test.

- `blocks.py`: `Compute.as_: str | None = None`, `Record.as_: str | None = None` (Python `as` is a keyword; field `as_`, JSON key `"as"`).
- `serialize.py`: `SCHEMA_VERSION = 3`; the reject message updated (v2→v3, cite this design); stream `units` **required** (a declared stream with no `units` is a `WorkflowLoadError`); `_compute`/`_record` builders read/emit `"as"`; `_dump_body` emits `"as"` when set; `_BLOCK`/compute/record key allowlists include `as`.

- [ ] **Step 1: Tests:** a `schema_version: 2` doc → `WorkflowLoadError` "expected 3"; a v3 doc with `compute.as`/`record.as` round-trips (`workflow_to_dict(workflow_from_dict(d)) == d`); a v3 stream with no `units` → `WorkflowLoadError`.
- [ ] **Step 2:** Run — fail. **Step 3:** Implement (extension quartet: field + allowlist + from-dict + to-dict). **Step 4:** Run — pass. **Step 5:** commit `feat(experiment)!: schema_version 3 — required stream units, compute/record as`.

---

### Task 5: Registry param units (optional, incremental)

**Files:** Modify `registry.py` (`ParamSpec.unit`), `validate.py` (`_check_param_value`); Test extend `tests/test_experiment_units_validate.py`.

- `ParamSpec.unit: str | None = None`. Annotate: `pump.dispense.volume_ml`→`"ml"`, `speed_ml_min`→`"ml/min"`, `drop_suckback_ml`→`"ml"`, `set_calibration.measured_volume_ml`→`"ml"`/`ml_per_step`→`"ml"`; `set_thermostat.target_c`→`"degC"`. Others stay `None` (unit-unchecked).
- `_check_param_value`: when the param has a unit and the value is an expression, `expected = ScalarType(base, parse_unit(spec.unit))`; a unitless expression adapts (so a bare literal `volume_ml: 1.0` is fine), a differently-dimensioned expression is rejected.

- [ ] **Step 1: Tests:** `volume_ml: "mean(od_AU)"` → rejected (AU vs ml); `volume_ml: "1.0"` → clean; `volume_ml: "dose_ml"` where `dose_ml` is a unitless operator input → clean (adapts). **Steps 2-5:** implement, run, commit `feat(experiment): optional per-verb param units`.

---

### Task 6: Re-annotate the morbidostat, docs, and fixtures

**Files:** `examples/morbidostat.json`, `examples/morbidostat-demo-speed.json`, `docs/workflow-schema.md`, `tests/experiment_validate_helpers.py` + inline fixtures, `docs/experiment-engine-limitations.md`.

- Test helpers `wf`/`wf2` etc.: `schema_version: 3`; inject `"units": "unitless"` for streams declared without one; so most tests migrate centrally.
- Sweep every `schema_version: 2` in `tests/` → `3` (26 files) and every executable ` ```json ` fence in `docs/workflow-schema.md` → `3` with stream units; rewrite §7 "schema version" to describe the 2→3 break.
- `morbidostat.json` (+ demo-speed): the growth-rate `compute`/`record` into `r_series` (`per_hour`) and the concentration into `c_series`/`c` (`x_MIC`) get `"as"` casts where the opaque algebra derives unitless (the `24·…` and the stock-concentration constants). Confirm it loads, validates, expands, and runs.
- `docs/experiment-engine-limitations.md`: close the "stream `units` are declarative only" sharp edge under "Smaller sharp edges".

- [ ] **Step 1:** Update helpers + version sweep; run `pytest -q`, fix fallout (a fixture that genuinely mixes units gets a real unit or an `as`). **Step 2:** Re-annotate the morbidostat; `pytest -q -k "morbidostat or docs_workflow_schema"`. **Step 3:** Update the schema doc §6/§7 and limitations doc. **Step 4:** Full gate. **Step 5:** commit `docs(experiment): re-annotate morbidostat and schema for v3 units`.

---

## Self-Review

- **Spec coverage (§11.2):** unit algebra → T1; unit inference → T2; unit checking + `as` → T3; required stream units + `as` fields + v3 → T4; registry param units → T5; re-annotation → T6. Runtime untouched (units static-only) — Global Constraints.
- **Placeholders:** none.
- **Type consistency:** `ScalarType`/`Unit`/`assignable`/`join_types`/`infer_type(stream_units)` used consistently T2→T5; `as_` field name and `"as"` JSON key consistent T3/T4.
- **Mutation-verified:** T2, T3, T5 assert reject cases.
