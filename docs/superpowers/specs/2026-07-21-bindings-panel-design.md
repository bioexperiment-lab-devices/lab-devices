# Bindings panel — design

- **Date:** 2026-07-21
- **Status:** Approved (brainstorm), ready for implementation planning
- **Area:** Experiment Studio (`webapp/frontend` + `webapp/backend`) and the engine (`src/lab_devices/experiment`)

## Motivation

A *binding* is the DSL's named-scalar namespace: a value in `RunState.bindings`, written
by an `operator_input` block ("Binding name") or a `compute` block ("Into"), and read by
expressions. Unlike the DSL's other two data namespaces, bindings are **never declared**.
Streams (`streams: {…}`) and roles (`roles: {…}`) are top-level declarations and each already
has its own Builder-palette panel (`StreamsPanel`, `RolesSection`). Bindings have no such
surface — they spring into existence as the write-targets of blocks and are visible only
piecemeal: in individual block inspectors, in group "Locals", and as an autocomplete category
in the expression editor's ƒ-help.

The result: in a non-trivial experiment (e.g. `examples/morbidostat.json`) bindings are spread
across dozens of blocks with **no single place** to answer:

- What named scalars exist in the scope I'm editing?
- What type and unit does each have?
- Which block writes each one?
- Which blocks read each one?

This spec adds a read-only **Bindings** section to the Builder's left palette that answers
exactly those questions, mirroring the existing Roles/Streams panels.

## Goals

- A collapsible **"Bindings"** section in the Builder palette (`Palette.tsx`), below Groups,
  `defaultOpen={false}`.
- **Read-only.** It never mutates the document. Its only interaction is navigation.
- **Scope-aware**, exactly like Roles/Streams: it lists the bindings in scope for expressions
  at the current editing scope.
- For each binding, show: **name**, **inferred type + unit**, **writer(s)** (with block kind),
  and **reader(s)**.
- **Click a row → select + scroll to its writer block** on the canvas (read-only navigation).
- Surface the engine's already-computed type inference to the frontend **additively** — no
  `schema_version` bump, no document-shape change, no migration.

## Non-goals (out of scope for this increment)

- Editing bindings from the panel (rename, retype, delete, change `as` cast). This was
  explicitly deferred; the panel is read-only.
- Declaring bindings up front (a top-level `bindings:` schema section). Not pursued.
- Inferred type/unit for **template-hole** bindings at authoring scope (see the type-column
  rule below). Deferred to a possible follow-up.
- Any change to the Run tab, Records, or the top-level tab bar.

## User experience

### Placement & scope

The panel is a new `<Section title="Bindings" defaultOpen={false}>` in `Palette.tsx`, rendered
after the existing Groups section. Like Roles/Streams it is **scope-aware**: the set of names
it lists is exactly

```
collectBindings(activeTree) ∪ scopeBindingNames(activeGroup)
```

— the same set the expression editor's ƒ-help "Bindings" category already shows
(`ExpressionEditor.tsx`). At **root** scope that is the root-tree bindings; scope into a group
and it becomes that group's binding params + binding locals + body-written bindings. This keeps
the panel consistent with how the rest of the Builder treats scope (you edit one scope at a
time) and reuses helpers that already exist.

### Row anatomy

The palette aside is `w-64` (256px), so rows must be compact and names must truncate (with a
`title`), never widen the column.

```
BINDINGS                                    ⌄
──────────────────────────────────────────────
 od_min                 int              ⌨
 working_volume_ml      number           ƒ
 r_dil                  number           ⌨
▸ dilute_now            bool         ƒ  ×2
    ↳ compute · "decide dilute"      → jump
    ↳ compute · "reset flag"         → jump
    ↳ read by branch · "if dilute"   → jump
──────────────────────────────────────────────
```

Each **primary row** shows:

- **Name** — `min-w-0 flex-1 truncate font-mono text-caption`, with `title={name}` for the full
  value (mirrors the read-only stream-refs row template in `StreamsPanel.tsx`).
- **Type badge** — the inferred type rendered like the engine's diagnostics:
  `int` / `number` / `bool` / `string`, with the unit appended when present
  (`number<AU/s>`). Base and unit are styled distinctly (unit muted). Shown as an unobtrusive
  `—` when the type is unavailable (see the type-column rule). `shrink-0`.
- **Writer indicator** — a `KindIcon` for the writer kind (`operator_input` / `compute`), with
  `×N` when the binding has more than one writer. `shrink-0`.
- Declared-but-unwritten group params/locals (e.g. a group `binding` param, or a `binding` local
  whose only value is its constant `init`) show a small `param` / `local` tag instead of a
  writer icon, and are not click-navigable (they have no canvas block).

**Interaction:**

- Clicking a primary row **navigates to its (first) writer**, reusing the store sequence
  `setScope(scope) → select(uid) → scrollToBlock(uid)` — the exact pattern `ProblemsPanel.tsx`
  uses. Read-only: it selects and scrolls, never mutates.
- A disclosure chevron (present when a binding has >1 writer or any readers) expands the row into
  one **child row per writer** and per **reader**, each individually clickable to jump to that
  block. Each child row shows the block kind + its label (or a fallback). This is how
  multi-writer bindings and the "where is it read" answer are surfaced, mirroring how
  `ProblemsPanel` renders N `uid`-anchored rows.

**Empty state:** an em-dash hint in the established idiom —
`No bindings in this scope yet — created by operator_input and compute blocks.`
(`px-1 text-xs text-hint`).

### The type-column rule (concrete vs template-hole) — an intentional, honest limitation

The engine infers a binding's type+unit only on the **expanded** workflow. Concretely:

- **Root-scope, non-templated bindings** (operator inputs, top-level computes such as
  `working_volume_ml`) keep their names through expansion, so their inferred type is available
  and shown in full.
- **Template-hole bindings** — group-local bindings referenced as `{c}`/`{r}` in a group body,
  and bindings written inside a `for_each` with a loop-variable in the name — do **not** have a
  single concrete type at authoring scope. After expansion they become one qualified instance
  per iteration (e.g. `service`'s `c` under `as: "tube_{tube}"` becomes `tube_A_c`,
  `tube_B_c`, …). There is genuinely one type *per instance*, not one type for the authored hole.

The panel therefore shows the inferred type only for names that match an inferred (expanded)
binding name directly; template-hole bindings show `—`. This is presented as the correct mental
model ("template holes are typed per instance"), not a bug. A follow-up could use the expansion
trace to reverse-map a *representative* instance type for template holes; that is deliberately
deferred.

**Graceful degradation:** names, writers, and readers are all derived from the frontend document
tree, independent of the backend. So when the document is invalid (validation returns no binding
types) or the network is down, the panel still lists every binding with its writers/readers and
click-to-navigate — only the type badges fall back to `—`.

## Architecture

### Backend — surface the existing inference (additive)

The engine already computes `dict[str, BindingType]` via the private
`_collect_binding_types(w, stream_units)` (`src/lab_devices/experiment/validate.py`), where
`BindingType = ScalarType(base, unit)`. `unit` is a canonical `tuple[(symbol, exponent), …]`
and there is already a renderer, `unit_str` (`src/lab_devices/experiment/units.py`), producing
`"AU/s"`, `"1/s"`, `"unitless"`, etc.

1. **Add a public engine wrapper** in the experiment package, e.g.

   ```python
   def binding_types(w: Workflow) -> dict[str, BindingType]:
       """Inferred (base, unit) of every binding in the workflow, in document order."""
       return _collect_binding_types(w, _stream_units(w))
   ```

   Export `binding_types` and `unit_str` from `src/lab_devices/experiment/__init__.py`
   (`__all__`). This keeps `_collect_binding_types` / `_stream_units` private and mirrors the
   existing public-analysis pattern (`verb_catalog`, `expression_functions` in `catalog.py`).

2. **Serialize in the web layer.** `webapp/backend/experiment_studio/docs_store.py::validate_doc`
   already expands + parses the document and holds the expanded `Workflow` before validating.
   **Do not change `validate_doc`'s signature** — it returns `list[dict[str, str]]` and is
   asserted by 11 existing tests in `test_docs_store.py` plus the endpoint. Instead add a sibling
   `binding_types_for_doc(doc) -> dict[str, dict[str, str]]` that expands + parses the document
   the same way and serializes each inferred type as `{"base": t.base, "unit": unit_str(t.unit)}`
   (mirroring the diagnostics dict serialization), returning `{}` on any `WorkflowLoadError`. The
   two functions share the small expand+parse cost; validation is debounced and documents are
   small, so the duplicate parse is acceptable and keeps the change strictly additive.

3. **Extend the endpoint response.** `webapp/backend/experiment_studio/api/validate.py` calls both
   `validate_doc(doc)` and `binding_types_for_doc(doc)` and returns a new additive key:

   ```json
   { "ok": true, "diagnostics": [...], "binding_types": { "od_min": {"base": "int", "unit": "unitless"}, ... } }
   ```

   Purely additive — no `ExperimentDoc`/schema change, no change to `validate_doc`. When
   expansion or parsing fails, the endpoint returns diagnostics as today and an empty
   `binding_types` map.

Binding-type keys are the expanded/qualified names (root bindings plus `tube_A_c`-style
instances). The frontend matches by name and simply ignores keys it has no authored name for.

### Frontend — read the types reactively and render the panel

The `/api/validate` call is **already reactive**: `builder/useValidation.ts` re-POSTs the doc
500ms after edits settle (mounted once in `BuilderTab.tsx`), and stashes the result in
`useDocStore`. Today its `.then` keeps only `resp.diagnostics`; a new `binding_types` field is
dropped. Wiring it through is ~a dozen lines:

1. **Types** — extend `ValidateResponse` in `types/doc.ts` with
   `binding_types?: Record<string, { base: string; unit: string }>`.
2. **Store** — add `bindingTypes: Record<string, {base, unit}>` + `setBindingTypes` to
   `EditorState` in `stores/docStore.ts` (mirror the `diagnostics`/`setDiagnostics` pair,
   initialize alongside `diagnostics: []`, clear it in `loadDoc`).
3. **Wire** — in `useValidation.ts`, inside the existing `.then((resp) => {…})`, add
   `state.setBindingTypes(resp.binding_types ?? {})`.

**Pure, testable derivation helpers** (node-env vitest can only test pure functions — no DOM).
Add to `builder/refs.ts` (or a new `builder/bindings.ts`), each unit-tested:

- `collectBindingWriters(tree): Record<string, WriterRef[]>` where
  `WriterRef = { kind: 'operator_input' | 'compute'; uid: string; label: string | null; inputType?: InputType }`.
  Walk the tree with the existing `visitNodes`; for each `operator_input`/`compute` record the
  writer (a binding may have several).
- `collectBindingReaders(tree): Record<string, ReaderRef[]>` where
  `ReaderRef = { uid: string; label: string | null; field: string }`. Walk every
  expression-bearing field (`compute.value`, `record.value`, `branch.condition`,
  `loop.count`/`until`/`pace`, `abort.condition`, `alarm.condition`, and `command`/`measure`
  param values), parse each with the existing `parseExpression`, and collect `binding`-typed AST
  nodes. The parser AST already tags binding reads (`expr/parse.ts`), so this is a small walk.
- `bindingIndex(tree, scopeBindingDecls, bindingTypes): BindingRow[]` — merge the name set
  (writers ∪ readers ∪ declared scope bindings), attach type from `bindingTypes[name]`, in
  document order. `BindingRow = { name; type?: {base, unit}; writers: WriterRef[]; readers:
  ReaderRef[]; decl?: 'param' | 'local' }`. This is the single value the component renders.

**Component** — `builder/BindingsPanel.tsx`:

- Subscribe to `useDocStore`: `activeTree` (via `useActiveTree()`), `scope`, `bindingTypes`,
  and the active group (for `scopeBindingNames`), plus `select`, `setScope`, `scrollToBlock`.
- Compute `bindingIndex(...)` with `useMemo`.
- Render `<ul className="space-y-1">` of primary rows + disclosure children, following the
  read-only row template from `StreamsPanel`'s stream-refs list and `GroupsPanel`.
- All icons via `KindIcon` / lucide with `aria-hidden`; the disclosure toggle is an `IconButton`
  (≥24px hit area, `title`/`aria-label`); truncating name spans carry `title`; colors limited to
  neutral surfaces (`bg-slate-100`, `text-caption`, `text-hint`), reserving hue for state.

**Mount** — add the `<Section title="Bindings" defaultOpen={false}><BindingsPanel /></Section>`
in `Palette.tsx` after Groups.

### End-to-end data flow

```
edit → docStore(tree/groups/…) changes
     → useValidation debounced POST /api/validate
       backend: expand+parse workflow → binding_types(workflow) → serialize {base, unit_str}
     → resp.binding_types → docStore.bindingTypes
BindingsPanel: bindingIndex(activeTree, scopeDecls, bindingTypes)
             → rows (name + type badge + writers + readers)
row/child click → setScope(scope) → select(uid) → scrollToBlock(uid) → Canvas scrolls
```

## Error handling & edge cases

- **Invalid / unparseable document:** backend returns empty `binding_types`; panel still shows
  names/writers/readers from the tree, type badges show `—`.
- **Multiple writers of one binding:** disclosure lists each writer as its own clickable child
  row; the primary-row click targets the first writer.
- **Re-clicking the same writer:** `Canvas`'s scroll effect keys on `scrollToUid` and does not
  reset it, so navigating to the same `uid` twice is a no-op. Acceptable for v1 (clicking a
  *different* row always works). If "re-scroll on repeat click" is wanted later, reset
  `scrollToUid` to `null` before re-setting — noted, not implemented.
- **Template-hole bindings:** `—` type (per the type-column rule); writers/readers/navigation
  still work within the group scope.
- **Declared-only bindings (param/local, no writer block):** shown with a `param`/`local` tag,
  not click-navigable.

## Testing strategy

Matches the three CI gates the change touches:

- **Engine (`test` job):** unit tests for `binding_types(w)` — a workflow with an int operator
  input, a `number<unit>` compute (with and without an `as` cast), and a multi-writer join —
  asserting the returned base+unit. `mypy --strict` + `ruff` clean. Confirm `unit_str`/
  `binding_types` are exported.
- **webapp-backend (`webapp-backend` job):** a test POSTing a document to `/api/validate` and
  asserting the `binding_types` map (root binding present with expected `{base, unit}`; invalid
  doc yields empty map, diagnostics still present). `mypy` + `ruff` clean.
- **webapp-frontend (`webapp-frontend` job):** vitest (node env, pure functions only) for
  `collectBindingWriters`, `collectBindingReaders`, and `bindingIndex` — covering multi-writer,
  reader extraction across each expression-bearing field, scope declarations, and type
  attachment. `oxlint` clean and `npm run build` (tsc + vite) green. DOM wiring is verified by
  the existing probe/capture harness, not unit tests.

## File-by-file change list

**Engine**
- `src/lab_devices/experiment/validate.py` — add public `binding_types(w)` wrapper.
- `src/lab_devices/experiment/__init__.py` — export `binding_types`, `unit_str`.
- `tests/test_experiment_binding_types.py` (extend) — tests for `binding_types(w)`.

**webapp-backend**
- `webapp/backend/experiment_studio/docs_store.py` — add `binding_types_for_doc(doc)` (leave
  `validate_doc` unchanged).
- `webapp/backend/experiment_studio/api/validate.py` — add `binding_types` to the response.
- `webapp/backend/tests/` — endpoint/`binding_types_for_doc` test asserting the map (and empty on
  invalid docs).

**webapp-frontend**
- `webapp/frontend/src/types/doc.ts` — extend `ValidateResponse`.
- `webapp/frontend/src/stores/docStore.ts` — `bindingTypes` + `setBindingTypes`; init; clear in
  `loadDoc`.
- `webapp/frontend/src/builder/useValidation.ts` — set `bindingTypes` from the response.
- `webapp/frontend/src/builder/refs.ts` (or new `builder/bindings.ts`) — `collectBindingWriters`,
  `collectBindingReaders`, `bindingIndex` (pure).
- `webapp/frontend/src/builder/BindingsPanel.tsx` — the panel component.
- `webapp/frontend/src/builder/Palette.tsx` — mount the `Bindings` section after Groups.
- `webapp/frontend/src/builder/*.test.ts` — unit tests for the pure helpers.

## Follow-ups (explicitly deferred)

- Representative instance type for template-hole bindings via the expansion trace.
- Any editing affordances (rename/retype/`as`-cast) — would graduate the panel from read-only to
  an editing hub, a separate decision.
