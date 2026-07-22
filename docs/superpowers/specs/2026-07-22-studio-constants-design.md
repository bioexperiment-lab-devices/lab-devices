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
| Value model | **Literals + derived.** A constant is a literal (number/string/bool) or an expression over *other constants declared earlier* (`TOTAL = DOSE * COUNT`), evaluated in declaration order before the run. Fully static. |
| Representation | **First-class schema key.** New top-level `constants` map on the workflow; engine seeds bindings before blocks. `schema_version` **stays 3** (additive optional key — see §4). |
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
- `schema_version` **stays 3**. `constants` is an additive, optional top-level
  key: a doc without it is unchanged, and `workflow_to_dict` emits it only when
  non-empty, so every existing fixture round-trips byte-for-byte. The exact-match
  parse gate (`version != SCHEMA_VERSION`, serialize.py:519) makes a bump
  expensive — it would invalidate all ~10 JSON fixtures, both fixture generators,
  `docs/workflow-schema.md`, and dozens of `schema_version=3` test fixtures — for
  a change that is not breaking. *(This reverses the initial v4 decision, after
  mapping the churn.)* **Forward-skew note:** an older engine predating constants
  ignores the key and fails loudly at the first unbound reference — acceptable; a
  `>=` feature-detecting gate is a possible future enhancement.

## 5. Evaluation & validation rules

Evaluation:

- All constants are evaluated **before the first block executes**, in
  **declaration order** (one forward pass). A constant expression may reference
  **only other constants declared earlier** in the map. This single ordering
  constraint gives cycle-freedom, a well-defined runtime seed order, AND a
  well-defined single-pass type-inference order for free — no separate
  topological sort, matching the engine's existing document-order binding
  inference (`_collect_binding_types`) and the group-local `init` precedent.
- A constant expression may **not** reference streams, stream-window functions
  (`mean`, `count`, `latest`, …), nor runtime bindings produced by
  `compute`/`operator_input`. This is what keeps constants static and pre-run.

Validation (surfaced through `/api/validate` as `Diagnostic`s):

1. **Identifier** — each constant name is a valid identifier, unique among
   constants.
2. **Earlier-only references** — a constant may reference only constants declared
   *before* it; forward, self, and cyclic references are all rejected by this one
   rule.
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
- **Device/measure numeric params and group-call args** — *no new field
  machinery.* Value-kind (`int`/`number`/`bool`) param inputs and group-call args
  **already** persist expression strings and already expose the ƒ ("use an
  expression") toggle (`ParamInput`, `ArgField`), and the engine already resolves
  them (`_resolve_params`). This reach is delivered by adding constant names to
  the expression **scope** so they autocomplete and type-check there.

Out of scope: **string-kind device params** stay opaque/literal — the engine
treats them as literal strings, never expressions (`_resolve_params` returns the
value verbatim for `kind == "string"`), so a constant reference could not resolve
there even if typed.

## 7. UI — editable "Constants" section

Placement: a new palette section **after Groups** (order becomes
Flow / Data / Pause / Safety, Roles, Streams, Groups, **Constants**, Bindings).
It is a management/editor panel (like `RolesSection` / `StreamsPanel`), **not**
draggable block chips — a constant is a declaration, not a block.

Each row:

- **Name** (mono, **fixed after creation** — no rename in v1; a constant is cited
  by bare name inside expression *strings*, not a structural node field, so
  renaming would require rewriting every citing expression. Deferred — the
  GroupsPanel sets the same no-rename precedent. To change a name, delete and
  re-add.)
- **Value** (the `ExpressionEditor` — literal or const-expression, with
  autocomplete over earlier constants)
- **Unit** (optional text field → the `as` annotation)
- **Type badge** (inferred `{base}<unit>`, reusing `BindingsPanel`'s `TypeBadge`)
- **Delete** (`IconButton`), **refused while referenced** with a reason — the
  same delete-with-refusal pattern as Groups/Roles, but the reference scan is the
  *expression*-aware one (`bindings.ts`), not the structural `refs.ts`.

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
- `builder/Inspector` fields — **no new toggle**; value-kind params/group-args
  already accept expression strings via the existing ƒ toggle, and light up once
  constants join the scope (below).
- `builder/ExpressionEditor` scope — add constant names to every
  `ExprScope.bindings` construction site so autocomplete, expression-help, and
  the instant "unknown binding" check all recognize them.
- `builder/bindings.ts` — a `countConstantRefs(tree, name)` reusing
  `bindingReferences` (the expression-aware scan) for the delete-refusal check.

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
- Renaming a constant, and reordering constants in the panel (add in dependency
  order; delete-and-re-add to change a name). Both deferred.
- A topological sort over constant dependencies (declaration order is the v1
  contract).
- Bumping `schema_version` (constants are additive within schema 3).
- Dragging a constant chip onto the canvas (insertion is via autocomplete in
  expression fields).
