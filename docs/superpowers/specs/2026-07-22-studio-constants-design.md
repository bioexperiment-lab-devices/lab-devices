# Workflow Constants — Design

**Date:** 2026-07-22
**Status:** Approved (forks settled 2026-07-22)
**Feature branch:** `feat/studio-constants`

## 1. Motivation

Experiment authors sprinkle the same magic numbers across a workflow — a target
temperature, a feed rate, a dosing volume — in guards, durations, loop counts,
compute expressions, and device parameters. There is no single place to declare
such a value, so changing it means hunting every use. **Constants** give authors
one editable place to declare a named, typed value and reuse it everywhere, with
unit-checking, so a single edit propagates.

## 2. Concept

A **constant** is a named, typed, **write-once** value declared at the workflow
level. Under the hood it is a value **seeded into `RunState.bindings` before any
block runs**. Because the engine already evaluates expression strings against
`RunState.bindings` at nearly every slot (`execute.py::_resolve_params`,
`evaluate.py::resolve`), a seeded constant is resolved by every existing
expression site for free. Constants are **workflow-global** (visible everywhere,
including inside groups and group-refs) and **immutable**.

This is the "trivial compute under the hood" the feature was conceived as — but
as a first-class, pre-run, write-once value rather than a runtime step.

## 3. Settled decisions (forks)

| Fork | Decision |
| --- | --- |
| Value model | **Literals + derived.** A constant is a literal (number/string/bool) or an expression over *other constants* (`TOTAL = DOSE * COUNT`), evaluated once before the run. Fully static. |
| Representation | **First-class schema key.** New top-level `constants` map on the workflow; engine seeds bindings before blocks. `schema_version → 4`. |
| Units | **Typed with optional unit.** Base type inferred; optional unit annotation via compute's `as` mechanism; unit-checked wherever used. |
| Usage reach | **Also parameter fields.** Value-kind device/measure params and group-call args gain the existing literal↔expression toggle; a constant reference is one kind of expression. |
| Mutability | **Immutable / write-once.** A `compute` / `operator_input` / group-local writing a constant's name is a validation error. |
| Scope | **Workflow-global.** Group-locals remain for group-scoped values; constants are the global registry. |

## 4. Schema

New top-level map on `Workflow` (engine `workflow.py`, FE `types/doc.ts`):

```
constants: dict[str, ConstantDecl]

ConstantDecl:
  value: ValueExpr          # ParamValue: bare literal, or expression string over other constants
  as:    str | None = None  # optional unit annotation (compute's unit-cast mechanism)
```

- `value` mirrors `ComputeBody.value` exactly (`number | string | boolean`). A
  bare number/bool is a literal; a string is an expression in the existing expr
  grammar (bare identifier = reference, quoted = string literal). No new value
  semantics are introduced.
- `constants` serializes as an ordered map. Insertion order is preserved for
  display; evaluation order is topological, independent of map order.
- `schema_version` bumps from 3 to **4**. The loader accepts v3 docs and treats
  a missing `constants` key as `{}` (backward compatible). *Known cost:* every
  fixture/example re-saves at v4 — the same churn the v3 bump incurred
  (webapp/examples-fixtures coupling; see the type-system increment note).

## 5. Evaluation & validation rules

Evaluation:

- All constants are evaluated **once, before the first block executes**, in
  **topological (dependency) order**.
- A constant expression may reference **only other constants** — not streams,
  stream-window functions (`mean`, `count`, `latest`, …), nor runtime bindings
  produced by `compute`/`operator_input`. This is what keeps constants static and
  pre-run.

Validation (surfaced through `/api/validate` as `Diagnostic`s):

1. **Identifier** — each constant name is a valid identifier, unique among
   constants.
2. **No cycles** — a dependency cycle among constants is an error.
3. **Static-only references** — a constant expression referencing a non-constant
   name (stream, runtime binding, window func) is an error.
4. **Immutability** — a `compute`, `operator_input`, or group-local `init`
   writing a name already declared as a constant is an error ("`X` is a constant;
   cannot be reassigned").
5. **No shadowing** — a constant name that collides with an existing binding
   *writer* is reported (mirror of rule 4 from the other direction).
6. **Units** — the `as` unit is valid and compatible with the inferred base type
   (reuses compute's `as` checks).

Type inference: constants are registered in the type environment **first**, so
downstream binding-type inference and unit-checking see them. Their inferred
`{base, unit}` is included in the `binding_types` map returned by `/api/validate`.

## 6. Usage surface

Because the engine resolves expressions against bindings almost everywhere, a
seeded constant is immediately usable in:

- **Guards / conditions** — `branch.if`, `loop.until`, `abort.if`, `alarm.if`
- **Durations & counts** — `wait` duration, `loop` count (schema-v3 expressions)
- **Data values** — `compute.value`, `record.value`
- **Device/measure numeric params and group-call args** — via extending the
  existing literal↔expression toggle (already used for count/duration slots) to
  value-kind params + group args. The engine already resolves these server-side
  (`_resolve_params` evaluates non-string params); this slice is the frontend
  affordance + validation. A constant reference autocompletes in the editor.

Out of scope: **string-kind device params** stay opaque/literal (engine treats
them as literal strings, not expressions).

## 7. UI — editable "Constants" section

Placement: a new palette section **after Groups** (order becomes
Flow / Data / Pause / Safety, Roles, Streams, Groups, **Constants**, Bindings).
It is a management/editor panel (like `RolesSection` / `StreamsPanel`), **not**
draggable block chips — a constant is a declaration, not a block.

Each row:

- **Name** (mono, editable → `renameConstant`)
- **Value** (the `ExpressionEditor` — literal or const-expression, with
  autocomplete over other constants)
- **Unit** (optional text field → the `as` annotation)
- **Type badge** (inferred `{base}<unit>`, reusing `BindingsPanel`'s `TypeBadge`)
- **Delete** (`IconButton`), **refused while referenced** with a reason — the
  same delete-with-refusal pattern as Groups/Roles

A **"+ Add constant"** control seeds a new row. Validation is live through the
existing `/api/validate` path; constant diagnostics appear in the Problems panel.
Constants surface in `ExpressionEditor` autocomplete via `scopeRefs`/`exprHelp`,
and in the new value-kind param expression toggle.

## 8. Components touched

**Engine (`src/lab_devices/experiment/`)**

- `workflow.py` — `ConstantDecl` dataclass; `Workflow.constants`; loader parse +
  validation (identifier/cycle/static-only/immutability/units); topological sort.
- `state.py` / runner (`execute.py` entry) — seed `RunState.bindings` from
  constants before the first block; evaluate derived constants in topo order.
- Type inference — register constants in the type env first; include in
  `binding_types`.

**Backend (`webapp/backend/experiment_studio/`)**

- Validate path — surface constant diagnostics; extend the returned type env.
- Loader/serializer — round-trip `constants`.

**Frontend (`webapp/frontend/src/`)**

- `types/doc.ts` — `ConstantDeclJson`; `WorkflowJson.constants`.
- `stores/docStore` — `addConstant` / `renameConstant` / `setConstantValue` /
  `setConstantUnit` / `removeConstant` (with refusal reason).
- `builder/ConstantsPanel.tsx` — the editor panel; wired into `Palette.tsx`
  after the Groups section.
- `builder/Inspector` fields — extend the literal↔expression toggle to
  value-kind params and group-call args.
- `builder/scopeRefs` / `builder/exprHelp` — include constants in autocomplete.

**Fixtures / examples**

- A round-trip fixture doc exercising constants (literal, derived, unit,
  used in a guard + a param).
- A constants showcase folded into an example workflow.

## 9. Testing

**Engine**

- Topological ordering (derived constant resolves after its dependency).
- Cycle rejection; static-only reference rejection; immutability rejection.
- Unit inference + unit-checking at a use site.
- Constants seeded before the first block (a guard on step 1 sees them).
- Byte round-trip of a doc with constants.

**Backend**

- `/api/validate` returns constant diagnostics for each rule.
- `binding_types` includes constants with inferred `{base, unit}`.

**Frontend** (vitest, pure functions only — no rendering)

- `docStore` constant actions (add/rename/setValue/setUnit/remove + refusal).
- `scopeRefs`/`exprHelp` include constants in completions.
- Param-field toggle logic. DOM wiring verified by the probe capture harness.

## 10. Non-goals

- Runtime-mutable constants / overridable defaults (constants are write-once).
- Group-scoped constants (group-locals already cover that).
- Constants in opaque string device params.
- Dragging a constant chip onto the canvas (insertion is via autocomplete + the
  param toggle).
