# Experiment Studio — export / import experiment setups

- **Date:** 2026-07-16
- **Status:** Design (approved forks settled below).
- **Implements:** the studio spec's §13 deferred backlog item *"YAML/DSL import-export"*, narrowed
  to **JSON file export/import** — the doc format that already exists on disk. It also makes
  `examples/README.md:3` true for the first time: that file has told users to upload examples via
  *"Experiments → Import"* since the examples landed, and no such UI was ever built.
- **Depends on:** `docs/superpowers/specs/2026-07-11-experiment-studio-webapp-design.md`
  (increments W1–W6, all on main). Nothing in the engine (`lab_devices`) changes.
- **This is Increment W7.**

## 1. The problem

An experiment setup cannot leave the studio, and it cannot enter one. The only way to reach a doc
is the studio's own saved list (`LoadDialog.tsx` over `GET /api/experiments`) — a list that can only
ever be filled by authoring in the Builder, in that browser, against that database.

Three things follow, and all three are already biting:

- **The examples are unreachable.** `examples/morbidostat.json` and
  `examples/morbidostat-demo-speed.json` are the repo's most carefully documented artifacts — a
  600-line walkthrough in `examples/README.md` — and there is no way to get either one into a
  running studio short of `curl`-ing `POST /api/experiments` by hand. The README tells the user to
  use "Experiments → Import". There is no Experiments tab and no import.
- **Setups cannot be shared or reviewed.** A doc that encodes a scientific protocol — the
  morbidostat's two pace-coupled constants, its freshness windows, its tolerance table — lives in a
  SQLite blob. It cannot be committed, diffed, code-reviewed, or sent to a collaborator.
- **A studio is a silo.** Preprod and production hold unrelated sets of experiments, with no path
  between them.

## 2. What we are building (settled fork: export/import only)

Two file operations over the doc format that **already exists on disk**:

- **Export** — write the open doc, or any stored doc, to a `.json` file.
- **Import** — read such a file back into the studio.

That is the whole feature. The "library" remains what it is today: your saved experiments. The
examples are reached by importing them, which is precisely what `examples/README.md` already
instructs — the instruction starts working rather than the concept changing.

### 2.1 Rejected: bundling the examples as a built-in starter library

Considered and dropped. `docToTree` (`convert.ts:45-52`) rejects `groups`, `group_ref`, `for_each`,
`compute`, and `abort`; both examples use all five. They are valid, runnable docs that **cannot open
in the Builder**. A "Browse examples" list whose flagship entry throws `DocConvertError` on click is
a worse first touch than no list at all. Making them Builder-openable is spec §13's *"Reusable
groups (GroupRef) editing"* — a whole increment, and a prerequisite for the library, not a detail of
it. Export/import is orthogonal and lands now; the library can follow once the Builder can hold
them.

## 3. Format — the file *is* the `ExperimentDoc`

```json
{ "doc_version": 1, "name": "...", "description": "...", "roles": {...}, "workflow": {...} }
```

2-space indent, trailing newline. Nothing else.

This is not a new format. It is byte-compatible with `examples/*.json`, whose top-level key order —
verified — is already exactly the Pydantic field order of `ExperimentDoc` (`docs_store.py:32`). So:

- every existing example imports unchanged, and
- every export drops into `examples/` and runs identically.

**One caveat, measured during the W7 browser proof.** A browser export normalizes float-valued
integers: `"speed_ml_min": 6.0` comes back out as `"speed_ml_min": 6` (11 such literals in
`morbidostat.json`). This is JavaScript's number model, not a defect we can engineer away —
`JSON.parse` collapses `6.0` and `6` onto the same double, and *any* client-side export inherits it.
It is semantically nil: JSON has one number type, the engine's Pydantic coerces `6` to `6.0` for a
float param, and `validate_doc` returns **0 diagnostics on both forms** (verified against the real
`morbidostat.json`). So an export re-imports, validates, and runs identically — but committing one
back over its source example would show a numeric-formatting diff. The **stored** round-trip is
byte-exact (§8, verified: zero repr-level differences through Pydantic); this is a property of the
browser, not of the store.

**No envelope.** No `exported_at`, no studio version, no id, no timestamps. `id`/`created_at`/
`updated_at` are row state grafted on at serialization (`_summary()`, `docs_store.py:54`) — they
describe a database row, not an experiment, and re-importing must mint fresh ones.

**No device mappings.** Deliberate, and load-bearing. Role→device mapping lives in the `mappings`
table keyed `experiment+lab`, and is meaningless on another rig with different device ids. The doc
naming *roles only* is exactly what makes it portable — that is settled fork **S2** of the parent
spec (symbolic roles, role→device mapping each run). Exporting mappings would smuggle one lab's
hardware into another lab's file.

## 4. Architecture (settled fork: import route on the backend, export on the frontend)

One new endpoint; export needs none.

**Why export is client-side.** The Toolbar exports the doc **as open, including unsaved edits**.
That doc exists only in the browser — no server route can reach it. A `GET /{id}/export` route
(mirroring the records download's `Content-Disposition` + `<a href>` pattern) would still need the
Blob path alongside it for the dirty case, leaving two export mechanisms for one feature.

**Why import is server-side.** Import's only behavioral difference from `create` is auto-renaming on
conflict, and the conflict is created by the `name TEXT NOT NULL UNIQUE` constraint in
`db.py:12`. The policy belongs next to the constraint that forces it. Doing it client-side would
mean a retry-on-409 loop duplicating `docs_store.duplicate()`'s `itertools.count` walk — two
implementations of one rule, free to drift, and racing other tabs between attempts.

## 5. Backend — one route, one refactor

### 5.1 `docs_store.py` — extract `create_renaming`

`duplicate()` (`docs_store.py:133`) already owns the suffix walk, inlined. Lift it:

```python
async def create_renaming(self, doc: ExperimentDoc) -> dict[str, Any]:
    """create(), but walk '(copy)', '(copy 2)'… until the unique name lands."""
```

It tries `doc.name` first, then `f"{name} (copy)"`, `f"{name} (copy 2)"`… — reusing the existing
`itertools.count` loop verbatim. `duplicate()` becomes a caller: it passes the source doc under its
**original** name, whose first attempt necessarily conflicts (the source itself holds it) and falls
through to `(copy)`. Identical observable behavior, one implementation.

**Settled behavior note (deliberate, approved):** in the one edge case where a row's name is
concurrently deleted between `get()` and the insert, the refactored `duplicate()` keeps the original
name instead of forcing `(copy)`. Arguably more correct — the name is free — and unreachable in the
single-user deployment this studio targets (parent spec §13 defers multi-user). Recorded so a
reviewer does not read it as a regression.

### 5.2 `api/experiments.py` — `POST /api/experiments/import`

Body `ExperimentDoc`; 201 with the full resource (`{id, name, description, created_at, updated_at,
doc}`), the same shape `POST /api/experiments` returns.

- Malformed / wrong shape → FastAPI's Pydantic 422, free.
- Name taken → auto-suffixed via `create_renaming`. **Never 409.** The caller learns the assigned
  name from `res.doc.name`.
- **No `validate_doc` gate.** Parent spec §4.3 settled it: *"Validation failures never block saving
  — only running."* Import is a save, and matches Save exactly. A doc from a newer engine, or one
  with a broken workflow, imports, then reports its problems in the Builder's diagnostics and
  refuses at run — the same path an authored doc takes.

No route-ordering hazard, verified: the only existing `POST` routes are `""` and
`/{experiment_id}/duplicate`. There is no `POST /{experiment_id}` for `/import` to be shadowed by,
so it can be declared anywhere in the module.

## 6. Frontend — pure core, thin glue

**The constraint that shapes this.** `vite.config.ts` pins `environment: 'node'`; there is no
jsdom, happy-dom, or testing-library in `package.json`; and **all 19 existing test files are pure
logic modules extracted out of components** (`convert`, `tree`, `paths`, `reducer`, `format`,
`preflight`…). Zero component tests exist. That convention is deliberate — the parent spec's final
review accepted "no component-level PreflightPanel test" as a known gap rather than pull in a DOM
harness. This increment does not break that. Instead, every decision goes in a pure module, and the
browser glue is reduced to a branchless stub.

### 6.1 `builder/files.ts` — new module

| Export | Purity | Tested |
|---|---|---|
| `exportFilename(name: string): string` | pure | ✅ node vitest |
| `serializeDoc(doc: ExperimentDocJson): string` | pure | ✅ node vitest |
| `parseDocFile(text: string): ExperimentDocJson` | pure | ✅ node vitest |
| `triggerDownload(filename: string, text: string): void` | DOM side effect | ❌ (see below) |

- `exportFilename` mirrors the backend's proven sanitizer from the records download
  (`records.py:78`): `name.replace(/[^A-Za-z0-9._-]+/g, '_')` + `.json`. Empty or all-symbol names
  fall back to `experiment.json`.
- `serializeDoc` = `JSON.stringify(doc, null, 2) + '\n'`. Returning a **string**, not triggering a
  download, is what makes the round-trip testable in node with no DOM at all.
- `parseDocFile` = `JSON.parse` + throw a typed `DocFileError` on bad JSON. It deliberately does
  **not** shape-check: the server's Pydantic model is the single source of truth, and duplicating it
  in TypeScript would create a second spec to keep in sync.
- `triggerDownload` is ~6 lines, no branching: `Blob` → `URL.createObjectURL` → anchor `click()` →
  `revokeObjectURL`. Untested, exactly like every component in this app. This is the first
  Blob/object-URL code in the frontend (there is currently no `FileReader`, `Blob`,
  `createObjectURL`, or `download=` anywhere).

### 6.2 `api/studio.ts`

```ts
importExperiment(doc: ExperimentDocJson): Promise<ExperimentResource>  // POST /api/experiments/import
```

Goes through the existing `request()` JSON funnel — inherits `apiPath()`'s relative-URL scheme (so
it survives the lab-bridge `/studio/` prefix-stripping proxy, W6's settled contract) and the 30 s
timeout policy.

### 6.3 `Toolbar.tsx` — Export + Import

Two buttons after `Duplicate`.

**Export** — `triggerDownload(exportFilename(name), serializeDoc(selectDoc(useDocStore.getState())))`.
`selectDoc` (`docStore.ts:103`) already produces exactly the `ExperimentDocJson` that Save POSTs.
Never disabled: it works dirty, and works before a first save (no `serverId` needed).

**Import** — a hidden `<input type="file" accept="application/json">`:

1. Dirty guard — `if (selectDirty(...) && !window.confirm('Discard unsaved changes?')) return`,
   identical to `New` / `Load` / `Duplicate`.
2. `parseDocFile(await file.text())` → `importExperiment(doc)` → `res`.
3. `loadDoc(docToTree(res.doc), res.id)` — you are now editing the imported doc.
4. On `DocConvertError` → **it is still saved.** Report it as such (§7).
5. Reset `input.value` so re-importing the same file re-fires `change`.

**A neutral note slot.** `Toolbar` currently renders one `error` state in red (`Toolbar.tsx:128`).
Import needs to say non-alarming things ("imported as 'Morbidostat (copy)'"), so a sibling `note`
state renders in slate/emerald. Errors stay red.

### 6.4 `LoadDialog.tsx` — per-row `⭳`

Beside the existing `✕`: `getExperiment(id)` → `triggerDownload(exportFilename(res.doc.name),
serializeDoc(res.doc))`.

This exports the **stored** doc with no convert round-trip — so it works for docs the Builder cannot
open. That is what closes the loop: without it, an imported `morbidostat.json` can never leave
again, because the only other export path requires opening it in the Builder first.

## 7. The morbidostat path is the one that matters

The single most likely first use of this feature is importing `examples/morbidostat.json`, and it is
the case that looks most like a bug while being a complete success:

```
import morbidostat.json
  → POST /api/experiments/import → 201, saved, id minted
  → docToTree(res.doc) → DocConvertError: groups are not supported
  → note: "imported as 'Morbidostat' — saved, but can't open in the Builder: groups
           are not supported"
```

The doc **is** in the studio. It is in the Load dialog. It can be picked on the Run tab's preflight,
mapped to devices, and run — the full experiment, exactly as designed. The only thing it cannot do
is render as a block tree. So this is a **note, not an error**: never red, never phrased as a
failure, and the message leads with what succeeded. `LoadDialog.open()` already has this exact
`DocConvertError` branch (`LoadDialog.tsx:28-30`, *"cannot open in the builder: …"*); the wording
stays consistent with it.

## 8. Data flow — the two round-trips

**Store round-trip — exact, and the load-bearing guarantee.**

```
examples/morbidostat.json → import → POST → SQLite (model_dump_json) → GET → ⭳ → file
```

Pydantic re-serializes with the same field order; `workflow` is an opaque `dict[str, Any]`
(`docs_store.py:39`), never parsed, so it survives verbatim. Pinned in pytest against the real
example file (§9) — server-side, where it needs no DOM and costs nothing.

**Builder round-trip — lossy by design, and already owned elsewhere.**

```
file → import → docToTree → edit → Export → treeToDoc
```

Defined only for Builder-compatible docs. `convert.ts` already owns this contract and pins it
byte-for-byte against `fixtures/valid-od-growth.json` (its `treeToDoc(docToTree(doc))` golden test).
Export introduces nothing new here — it serializes `selectDoc()`, the same value Save already sends.
`DocContent` carries `persistence`/`defaults` opaquely for exactly this reason, and that keeps
holding.

## 9. Error handling

| Case | Where | Result |
|---|---|---|
| Not JSON | client, `parseDocFile` | `"not a JSON file: <parse error>"` — never reaches the server |
| JSON, wrong shape (no `doc_version`, bad `roles`) | server, Pydantic | 422 → `ApiError` → red error |
| Name already taken | server, `create_renaming` | auto-suffixed; **note** "imported as 'X (copy)'" |
| Valid doc, Builder can't open it | client, `docToTree` | saved; **note**, not an error (§7) |
| Workflow invalid for this engine | neither — saves | surfaces in diagnostics / at run, like Save |
| Unsaved edits open at import | client | `window.confirm('Discard unsaved changes?')` |

No file size limit. The largest real doc — the faithful morbidostat, description and all — is ~30 KB.

## 10. Testing

**Backend (pytest, `test_experiments_api.py` + `test_docs_store.py`):**

- import → 201 + full resource; row is retrievable via `GET`.
- import the same name twice → second lands `(copy)`, third `(copy 2)`.
- import malformed body → 422.
- import a doc with an invalid workflow → **still 201** (pins the Save-precedent decision of §5.2).
- **the round-trip: import `examples/morbidostat.json` → `GET` → deep-equal the file on disk.** Uses
  the real example, not a fixture, so it also pins that the shipped examples stay importable — and
  it would have caught the `examples/README.md` claim being false.
- `duplicate()`'s existing tests stay green unchanged through the `create_renaming` refactor. That
  is the refactor's proof.

**Frontend (vitest, node env, `builder/files.test.ts`):**

- `exportFilename`: spaces → `_`, slashes/unicode stripped, empty and all-symbol → `experiment.json`.
- `serializeDoc`: 2-space indent, trailing newline, key order preserved.
- `parseDocFile`: valid → object; garbage → `DocFileError`.
- **`parseDocFile(serializeDoc(doc))` deep-equals `doc`** — the client round-trip, no DOM required.

Not tested, consistent with the existing convention: `triggerDownload`, and the `Toolbar` /
`LoadDialog` wiring. All decision logic they contain is delegated to the pure module above; what
remains is the DOM call itself.

**Gates** (unchanged, from the parent spec):
`cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
(mypy takes no path arg) and
`cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
(oxlint, 2 known fast-refresh warnings, exit 0).

## 11. Docs

`examples/README.md:3` becomes true as written — "Experiments → Import" resolves to the Toolbar's
Import button. Reword to name the actual control ("**Builder → Import**"), and state plainly that
these two examples save and run but do not open in the Builder, since that is what a user doing this
will immediately observe.

## 12. Settled decisions

| # | Fork | Settled |
|---|---|---|
| 1 | Scope | Export/import only. No bundled example library (§2.1). |
| 2 | Name conflict on import | Auto-suffix `(copy)`, reusing `duplicate()`'s walk. Never 409, never overwrite. |
| 3 | Export surface | Toolbar (open doc, incl. unsaved) **and** Load-dialog row (stored doc). Both — the second is what makes Builder-incompatible docs exportable. |
| 4 | Architecture | Import route server-side; export client-side (§4). |
| 5 | File format | Bare `ExperimentDoc`, byte-compatible with `examples/*.json`. No envelope, no mappings (§3). |
| 6 | Validation on import | None. Matches Save; parent spec §4.3. |
| 7 | Test strategy | Pure core in node vitest; DOM glue untested; round-trip pinned in pytest against the real example (§10). |
| 8 | `duplicate()` refactor | Routes through `create_renaming`; the concurrent-delete edge keeps the original name. Deliberate (§5.1). |

## 13. Out of scope

Bundled example library and Builder support for `groups`/`for_each`/`compute`/`abort` (spec §13,
"Reusable groups (GroupRef) editing" — the prerequisite). YAML or a text DSL (§13's original
framing; JSON is the format that exists). Bulk / multi-file import. Export of run records — that
already exists as the record zip download. Import of records. Cross-studio sync. Device mappings in
the file (§3).
