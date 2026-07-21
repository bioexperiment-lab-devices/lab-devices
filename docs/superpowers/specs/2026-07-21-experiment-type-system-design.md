# A unified type system for the experiment DSL

**Status:** design settled 2026-07-21. Implemented as a staged sequence (Increment 10).
**Predecessor:** Increment 9, "typed group parameters" (`2026-07-20-typed-group-parameters-design.md`).

This spec turns the experiment DSL from a *dynamically* typed language — where a type
mismatch surfaces as a run-time `EvaluationError` — into a *statically* typed one, where the
same mismatch is a load-time `Diagnostic`. It unifies the two ad-hoc type systems the engine
already carries into a single lattice and applies that lattice to every value-bearing slot.

---

## 1. Where we are starting from

The module is **not** untyped. Two independent, partial type systems already exist, and they
meet only at macro-expansion time:

- **System A — value/reference *kinds* (Increment 9).** `ParamKind = int | number | bool |
  string | role | stream | binding` (`workflow.py:11`), split into `VALUE_KINDS` and
  `REFERENCE_KINDS`. It checks JSON-literal *shape* and reference *resolution* for group
  params, `for_each` vars, and `group_ref`/`for_each` args. Load-time `WorkflowLoadError`.

- **System B — expression *types* (`analyze.infer_type`).** Only three types: `number |
  boolean | unknown`. It already statically checks that guards (`branch.if`, `abort.if`,
  `alarm.if`, `loop.until`) are boolean, that `record.value` is numeric, that verb params match
  their registry `Kind`, and that operand mismatches (string/bool in arithmetic, bool-vs-number
  compare) are caught — **but only when the operand types are known.**

### 1.1 The structural gap

System B's leniency is load-bearing: `unknown` never produces a diagnostic. And the *only*
bindings it types are `operator_input` ones (`_collect_binding_types`, `validate.py`). Every
reference to a `compute.into` binding therefore infers as `unknown`, which silently defers to
run time **every** type error that flows through a computed binding:

- a computed boolean (`compute into=x value="a>b"`) used in arithmetic (`record value="x+1"`);
- a computed number (`compute into=x value="mean(S)"`) used as a boolean guard (`branch if:"x"`);
- a computed binding of the wrong type handed to a `bool`/`int`/`number` verb param;
- a computed binding compared with a literal of the other type (`x == 5`).

Each raises an `EvaluationError` mid-run today (catalogued against `evaluate.py`/`execute.py`).
On a three-week morbidostat run that is a fortnight lost to a bug a compiler should have caught.

### 1.2 Adjacent unchecked slots

- **Units are declarative only.** `streams.units` is a free-form string that *nothing* reads
  for checking; `blank_1` (AU/s) and `od_1` (AU) mix freely in one expression
  (engine-limitations "smaller sharp edges").
- **`enum` inputs are un-branchable.** The evaluator rejects string bindings outright, so an
  `enum` choice can be collected and logged but never branched on (limitation #5).
- **Durations/counts are literals.** `wait.duration`, `loop.pace/count`, `gap_after`,
  `start_offset` cannot be expressions, so cycle time can never be an operator input
  (limitation #6).

---

## 2. Settled decisions

Seven candidates were surveyed; the user chose to address **all** of them, unified as one type
system rather than seven patches. The forks were settled as:

| Fork | Decision |
|---|---|
| Scope | The full lattice: compute-binding typing, `int` vs `number`, string comparison, strict `unknown`, explicit binding declarations, expressions in duration/count slots, and units. |
| Units depth | **Opaque symbolic.** Units are opaque tags; equal under `+ − < <= > >= == !=`, combined structurally under `× ÷`. No unit ontology (the checker does not know `per_hour ≡ 1/s`). `unitless` is a first-class unit. A bare literal is unitless. |
| Binding types | **Infer-first, declare when ambiguous.** A binding's type is inferred from its writer(s) via the existing data-flow order; an explicit declaration is required only when inference cannot resolve it (conflicting types across branches, or a use that outruns every writer). |
| Migration | **Strict, `schema_version` 3, hard break.** Existing documents must be re-annotated (stream units, and any binding type inference cannot pin) before they load, exactly as v2 hard-broke v1. |
| Duration | **Unified as `number<s>`.** A duration is a number carrying the seconds unit; `"5min"` normalises to `300`. Duration slots expect `number<s>`, so any expression producing one works and a bare unitless number is *rejected*. |
| Unit cast | **A structured per-writer-block field**, not an in-expression operator. Studio edits expressions as plain text with no structured surface, so a cast belongs on the block (`compute`/`record`) as a `<select>`-editable field, reviewable in JSON. |

---

## 3. The type lattice

```
Scalar   = Base × Unit
  Base   ∈ { int, number, bool, string }        with  int <: number   (same unit)
  Unit   = a canonical map {symbol: exponent}   {} = unitless; carried only by int / number
duration = number<s>                            ("5min" → 300 ; window last=30s → number<s>)

Reference constructors (declared entities, not expression results):
  stream<Unit>        an append-only series of number<Unit>
  binding<Scalar>     a named scalar
  role<device_type>   an instrument slot
```

- `bool` and `string` carry **no** unit (unit is `{}` and unit operations are inapplicable).
- `Unknown` is retained **only** as a transient inference state. Under strict v3, an `Unknown`
  reaching a *checked* slot is a diagnostic ("cannot determine the type of …; annotate it"),
  not silence. This is the tightening the increment turns on.
- System A collapses into the lattice: `int/number/bool/string` are `Base`; `role/stream/binding`
  are the reference constructors. One vocabulary, spelled `number` (never `float` — the legacy
  `operator_input.type: "float"` is the one exception and is left as-is for its own field).

### 3.1 Subtyping and assignability

`int <: number` at equal units. An expression of type `T` is assignable to a slot expecting `S`
iff `base(T) <: base(S)` **and** `unit(T) == unit(S)`, where **assignment requires an *exact*
unit match** — a unitless value does **not** silently adapt to a dimensioned target, and vice
versa; a mismatch is bridged only by an explicit `as` cast (§6). That exactness is what keeps
`as` meaningful: it is the visible assertion that stands in for the ontology the checker lacks.
`bool` and `string` are invariant. This mirrors the runtime, which already accepts an int where
a number is wanted and coerces an integral float into an `int` slot, and which rejects `bool` as
a number (Python's `bool ⊆ int` is deliberately overridden — that override is preserved).

### 3.2 Unitless operands adapt (the rule that keeps strictness usable)

Inside an operator, **a unitless operand adapts to its sibling's unit; only two operands that
both carry a *non-empty* unit and disagree are an error.** So `last(od) > 0.15` type-checks
(the bare `0.15` adapts to `AU`), `24 * slope` stays `number<AU/s>` (the `24` adapts), and an
unannotated threshold — `last(od) > od_min` where `od_min` is a unitless `operator_input` —
just works. What the checker still catches is two genuinely-dimensioned quantities that
disagree: `mean(od) + mean(blank)` (`AU` vs `AU/s`), or a threshold *mis*-annotated
`od_min: per_hour` compared against `AU`. This is the sweet spot: unannotated documents are not
punished, but real dimensional mistakes are caught. Without this rule, strict units would reject
every threshold comparison in the corpus and the system would be unusable.

---

## 4. Where types come from

| Site | Type source | Change |
|---|---|---|
| `streams.<name>` | `units` becomes a **required** unit annotation (`unitless` allowed) → `stream<unit>` | units existed as free text; now a typed, required field |
| `operator_input` | `type` → base; new optional `unit` → `binding<number<unit>>` | + `unit` |
| `compute.into` | **inferred** from `value`, threaded through data-flow order; optional `as: {type?, unit?}` declares an ambiguous binding and/or asserts a cast | the linchpin |
| `record.into` | the target stream's unit is authoritative; `value`'s derived unit must equal it, or optional `as: <unit>` asserts it | + `as` |
| group `binding` locals | inferred from `init` / body writers; `as` where ambiguous | binding-type inference |
| group `stream` locals | `units` (already present on `LocalDecl`) → `stream<unit>` | now typed |
| verb params (registry) | **unit-unchecked** (base only) — deferred, see §13 | none this increment |

**One `as` field, two jobs.** On `compute` it (a) declares the scalar type of a binding whose
inference is ambiguous — the "declare when ambiguous" escape — and (b) asserts a unit the opaque
algebra could not derive (a magic conversion constant). On `record` it asserts the value's unit
against the target stream. It is a structured field a Studio `<select>` edits; there is no
in-expression cast operator.

### 4.1 Binding-type inference (infer-first)

`_collect_binding_types` grows from a flat pre-pass into part of the existing path-sensitive
walk (`_visit_blocks` / `_expr_reads_ast` in `validate.py`), which already threads a
`state.bindings` written-set through the block sequence:

- `operator_input` binds `binding<number<unit>>` / `binding<bool>` / `binding<string>` from its
  `type` (+ optional `unit`), as today but unit-aware.
- `compute.into` binds the inferred type of its `value` expression **at the point of
  assignment**; that type is available to every later use. An explicit `as` overrides it.
- At a `branch` merge, a binding assigned incompatible types on the two arms is a diagnostic
  ("binding `x` is assigned a number in one arm and a boolean in the other; annotate with
  `as`"). A binding assigned on one arm only keeps its pre-branch type where it had one.
- A use that reaches no writer is already the existing `data-flow` "may be read before written"
  diagnostic; a use whose type is still `Unknown` (writer exists but type unresolved) is the new
  strict diagnostic.

Group bodies are unit/type-checked **post-expansion** on concrete streams, reusing the existing
macro-expansion validation path (`_validate_macro_workflow` expands, then re-runs every concrete
check). Holes are unparseable until expansion — the established deferral — so no `ParamDecl`
change is needed and group-param typing (Increment 9) is untouched.

---

## 5. The unit algebra (opaque symbolic)

A `Unit` is a canonical mapping from opaque symbol to integer exponent; `{}` is `unitless`.
`"AU"` → `{AU:1}`, `"AU/s"` parses to `{AU:1, s:-1}`, `"per_hour"` → `{per_hour:1}` (an opaque
symbol — **not** `{h:-1}`; the algebra has no ontology). Rules, applied inside `infer_type`:

- `Const` int → `int<>`, float → `number<>`, bool → `bool`. A **duration literal** → `number<s>`.
- `BindingRef` → the binding's inferred/declared scalar (or `Unknown`).
- `StatCall`: `count(S) → int<>` (unitless); `last/mean/min/max(S) → number<unit(S)>`.
- unary `-`: numeric operand; base and unit preserved. `not`: bool operand → `bool`.
- `+`, `-`: numeric operands, units **compatible** (equal, or one side unitless — §3.2); base =
  `number` if either is `number` else `int`; result unit = the non-empty one.
- `*`: numeric operands; base combine (int·int = int, else number); unit = componentwise sum of
  exponents (a unitless factor leaves the other's unit unchanged).
- `/`: numeric operands; base = `number` (always — real division); unit = componentwise
  difference of exponents.
- `< <= > >=`: numeric operands, units **compatible** (§3.2) → `bool`.
- `== !=`: operands the same class — both numeric with compatible units (§3.2), or both `bool`,
  or both `string` → `bool`. **string == string is the new capability** (limitation #5): the
  evaluator stops rejecting string bindings in equality.
- `and`, `or`: bool operands → `bool`.

Within an operator a unitless operand adapts (§3.2), so `24 * (…AU/AU…)` derives `unitless`;
**assignment**, by contrast, is exact (§3.1), so recording that unitless result into a `per_hour`
stream needs `as: per_hour` — the one place the author must assert what the algebra cannot
derive.

Unit parsing: a small grammar over the existing free-form strings — a `/`-separated
numerator/denominator of `symbol` or `symbol^n` terms, plus the literal `unitless`. The strings
already in the corpus (`AU`, `per_hour`, `x_MIC`, `AU/s`) all parse. Anything unparseable is a
load-time `units` diagnostic under v3.

---

## 6. Expression grammar & runtime

- **`expr.py`** — duration literals become **values** (`number<s>`), not only window arguments.
  This is what lets duration/count slots take expressions (limitation #6). The tokenizer already
  lexes `DURATION`; `_atom` stops rejecting it and emits a `Const` of the parsed seconds carrying
  the `s` unit (the unit lives in the type layer, not in `Const`, which stays a plain value; the
  inferencer stamps `number<s>` on a duration-literal `Const` — see §6.1).
- **`evaluate.py`** — string equality: `==`/`!=` accept two string operands; a string binding is
  no longer rejected outright, only in numeric/boolean *positions*. All other runtime type guards
  stay as a belt-and-suspenders backstop behind the now-complete static checker.
- **`execute.py`** — duration and count slots (`wait.duration`, `loop.pace`, `gap_after`,
  `start_offset`, `retry.backoff`, `loop.count`) accept `ValueExpr`; resolved at block entry
  (`pace` per iteration), then unit/`int`-checked. `as` casts are applied when binding/recording.

### 6.1 Distinguishing an int literal, a float literal, and a duration literal

`Const.value` is already `int | float | bool`, so `5` vs `5.0` is preserved. A duration literal
parses to a float count of seconds; to mark it `number<s>` (not a bare `number<>`) the parser
wraps it in a distinct AST node (`DurationConst`) or tags the `Const` — an implementation detail
left to the plan, constrained only by: the inferencer must see `number<s>`, and the evaluator
must see the plain float.

---

## 7. The checker

- **`analyze.py`** — `BindingType`/`ExprType` (plain `Literal`s today) become a small structured
  `Type` (base + unit + an `Unknown` sentinel). `infer_type` gains the rules of §5 and takes
  `stream_units: Mapping[str, Unit]` alongside `binding_types`. The freshness analysis
  (`proven_nonempty`, `proof_covers`, `windowed_reads`, `references`) is **orthogonal and
  untouched**.
- **`validate.py`** — `_check_expr_type` compares against a structured expected `Type` (base +
  unit) rather than a bare `Literal`; `_collect_binding_types` becomes the data-flow inference of
  §4.1; `_check_param_value` checks the optional registry `unit`; the writer blocks apply `as`.
  A new diagnostic category, `units`, joins the existing `type`/`declaration`/`data-flow` set.

---

## 8. Schema v3 & serialization

**The `schema_version` bump lands in Engine B, not Engine A.** Engine A is a pure
checker/runtime strengthening: it changes no document *shape* and *adds* capability (string
equality), so a well-formed v2 document keeps loading — Engine A only rejects documents carrying
a latent type bug that would have crashed the run anyway. The first *shape* change is Engine B's
required stream units and the `as`/`unit` fields; that is where v2 hard-breaks to v3. (Engine C
is additive — a duration/count slot that took only a literal now also takes an expression, a
superset — so it needs no further bump.)

- **`schema_version` → 3** (in Engine B), strict-equality reject with a migration message,
  exactly as v2 rejected v1. New/changed fields, each following the Increment-9 "extension
  quartet" (dataclass field + `_*_KEYS` frozenset + from/to-dict + `docs/workflow-schema.md`):
  - `StreamDecl.units` — required (was optional free text).
  - `Compute.as: {type?, unit?}` ; `Record.as: <unit>`.
  - `OperatorInput.unit` (optional).
  - (Registry param units deferred — see §13.)
  - `LocalDecl` stream `units` reinterpreted as a typed unit.
- The dump side stays the hand-written `isinstance` ladder (`_dump_body`); both directions get
  the new fields. Canonical key order is extended deliberately and asserted by tests.
- **`docs/workflow-schema.md`** → a v3 rewrite; every ` ```json ` fence is executed by
  `test_docs_workflow_schema.py`, so the doc and the loader cannot drift.

---

## 9. Studio (final stage)

Mirrors the Increment-9 engine/Studio split. Backend diagnostics need **no** new UI — they flow
through `/api/validate` → `ProblemsPanel.tsx` automatically once `paths.ts` resolves the path.

- `types/doc.ts` mirror + `builder/convert.ts` `schema_version` guard/emit → 3 (+ fixture bump).
- **Stream unit** free-text inputs → `<select>` over a `/api/catalog` unit vocabulary, in
  `StreamsPanel.tsx`, `StreamIntoPicker.tsx`, and `LocalDeclListEditor`.
- **Binding scalar-type** selector: clone the `ParamDeclListEditor` kind-`<select>` (and its
  kind→dependent-field cascade) into `ValueForm` (compute) and the group param/local editors.
- **`as` cast**: a unit `<select>` beside the value in `ValueForm`, housed in the collapsible
  `InspectorSection` "tail section" idiom.

The `/api/catalog` endpoint gains the unit vocabulary and the scalar-type/kind lists it does not
already expose.

---

## 10. Error handling & backward compatibility

- Every new failure is a load-time `Diagnostic` (`type` / `declaration` / `data-flow` / new
  `units`) or a `WorkflowLoadError`, in the Increment-9 message style: name the offender,
  enumerate the legal set, cite this design's §. No new runtime exception types.
- **Hard break.** A v2 document does not load under v3; the rejection message points at the two
  things v2 never recorded — stream units and unresolved binding types. Stale Studio drafts under
  v2 are discarded by the existing version-guard pattern.
- The runtime type guards in `evaluate.py`/`execute.py` are **kept**, now unreachable for a
  validated document but retained as the fail-safe backstop the engine's safety story depends on.

---

## 11. Delivery sequencing

One unified design, delivered as a stacked sequence that keeps `main` releasable, each stage its
own PR merged before the next begins:

1. **Engine A — the lattice.** Structured `Type`; `int`/`string` completion; compute-binding
   data-flow inference; strict `unknown`; string equality. **No shape change — `schema_version`
   stays 2.** A well-formed v2 document keeps loading; only documents with a latent type bug
   (which would have crashed the run) are newly rejected. A stricter-validation note goes in the
   CHANGELOG; any example that carried such a latent bug is fixed to keep loading.
2. **Engine B — units.** Opaque unit algebra; required stream units; `as` casts on
   `compute`/`record` (registry param units deferred — §13). **The `schema_version` 2→3 hard break
   lands here** — required stream units and the `as`/`unit` fields are the first shape change.
   `examples/` and `docs/workflow-schema.md` re-annotated to load.
3. **Engine C — durations & slots.** Duration literals as `number<s>`; expressions in
   duration/count slots resolved at entry.
4. **Studio.** The `types/doc.ts` mirror, the selectors, and the `/api/catalog` vocabulary.

`writing-plans` produces a detailed plan per stage, just-in-time, so each plan reflects the code
the previous stage actually landed.

---

## 12. Testing

- **Mutation-verified checker tests.** Each new static check gets a test that a *mutated*
  (deliberately ill-typed) document is rejected with the specific diagnostic, not merely that a
  well-typed one passes — the "vacuous abort tests" lesson: a test that never fails proves
  nothing.
- **Round-trip serialization** for every new field; `test_docs_workflow_schema.py` re-pointed to
  v3, so the schema doc's fences stay executable.
- **`examples/morbidostat.json`** re-annotated (stream units + the `r_series` → `as: per_hour`
  cast) and kept loading, expanding, and running — the end-to-end proof, as in Increment 9.
- On completion, mark limitations **#5** (enum in expressions) and **#6** (durations/counts as
  expressions) shipped in `docs/experiment-engine-limitations.md`.

---

## 13. Non-goals (deliberately out of scope)

- **A unit ontology.** Opaque symbolic units by decision: the checker will never know
  `per_hour ≡ 1/3600 s⁻¹`, so it cannot flag a wrong *conversion* constant — only a wrong
  *combination*. Full dimensional analysis is a possible future increment.
- **Units on value-kind group params.** A `number` group-param arg stays a unitless literal;
  units live on streams, bindings, and expressions. Deferrable without reopening this work.
- **Registry param units (deferred in full).** Device params are unit-unchecked. Annotating a
  param's unit (e.g. `volume_ml→ml`) sounds attractive but conflicts with the engine's core use
  case: a feedback control law legitimately computes a dose from a measured stream via an
  implicit-gain conversion (`volume_ml: "2.0 * (target - mean(od))"` derives `AU`, not `ml`), and
  a param slot has no `as` cast to bridge it — unlike a record. Enforcing param units would
  reject the flagship feedback pattern with no escape hatch. Deferred pending a param-level cast
  (or unit literals in the expression grammar). The `_check_expr_type` unit machinery is in place
  and reused by records, so this is a small future add once the escape hatch is designed.
- **Scalar math functions** (`ln`, `slope`, `abs`, …) — limitation #2, unrelated.

---

## 14. Worked example — the morbidostat under v3

The re-annotation that proves the design carries the real workload:

- `streams`: `od_1: {units: "AU"}`, `c_series: {units: "x_MIC"}`,
  `r_series: {units: "per_hour"}`, `blank_1: {units: "AU/s"}` — units now required and typed.
- The drug-concentration recursion `c*12/13 + 10*1/13` derives `x_MIC` (constants unitless),
  matching `c_series` — no cast.
- The growth-rate estimate `24*(mean(od,last=5) - mean(od,last=10))/last(od)` derives
  `unitless` (AU/AU); recording it into `r_series` (per_hour) carries `"as": "per_hour"` — **the
  one required annotation**, the visible assertion that stands in for the ontology the checker
  deliberately lacks. This is the single place the morbidostat must change beyond declaring its
  stream units.
- The contamination latch `count(od,last=90s) > 0 and mean(od,last=90s) > 2.0` type-checks with
  **no** new annotation: `mean(od,…)` is `number<AU>` and the bare `2.0` adapts to it (§3.2), so
  every threshold comparison in the corpus keeps working. Strict units cost the author exactly
  one cast, not a rewrite — which is what makes "strict" acceptable rather than punishing.
