# Experiment Studio Export/Import (W7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an experiment setup leave the studio as a `.json` file and come back into any studio — making `examples/README.md`'s long-standing "Experiments → Import" instruction true for the first time.

**Architecture:** One new backend route (`POST /api/experiments/import`) owns auto-rename-on-conflict, sitting next to the `name … UNIQUE` constraint that forces it; it reuses a `create_renaming` helper lifted out of the existing `duplicate()`. Export is client-side, because the Toolbar exports the *open, possibly-dirty* doc that exists only in the browser. All frontend decisions live in a new pure module (`builder/files.ts`) tested in node; the DOM call is a branchless stub.

**Tech Stack:** FastAPI + Pydantic + aiosqlite (backend, pytest/mypy/ruff); React 19 + Vite 8 + Zustand + Tailwind 4 (frontend, vitest node-env + oxlint).

**Spec:** `docs/superpowers/specs/2026-07-16-experiment-studio-export-import-design.md`. Section refs below (§N) point at it.

**Branch:** `feat/experiment-studio-7-export-import` (already exists, spec committed at `700bda9`).

## Global Constraints

- **Line length ≤ 100** everywhere (backend ruff, frontend oxlint).
- **Backend gates:** `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` — **mypy takes NO path argument.**
- **Frontend gates:** `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build` — 2 known oxlint fast-refresh warnings are expected, exit 0.
- **Frontend tests run in `environment: 'node'`.** There is no jsdom, happy-dom, or testing-library, and there are **zero component tests**. Do not add a DOM test harness. Pure logic goes in modules with tests; DOM glue stays untested (§6).
- **tsconfig is strict**, with `erasableSyntaxOnly` + `verbatimModuleSyntax` — type-only imports must use `import type`.
- **The exported file is the bare `ExperimentDoc`** — `{doc_version, name, description, roles, workflow}`, 2-space indent, trailing newline. No envelope, no id/timestamps, no device mappings (§3).
- **Import never returns 409** and never runs `validate_doc` (§5.2).
- **Commit after every task.** Conventional-commit prefixes (`feat:`, `refactor:`, `test:`, `docs:`).

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `webapp/backend/experiment_studio/docs_store.py` | Modify: add `create_renaming`, route `duplicate()` through it | 1 |
| `webapp/backend/tests/test_docs_store.py` | Modify: cover `create_renaming`; existing duplicate tests are the refactor's proof | 1 |
| `webapp/backend/experiment_studio/api/experiments.py` | Modify: add `POST /import` | 2 |
| `webapp/backend/tests/test_experiments_api.py` | Modify: import endpoint + real-example round-trip | 2 |
| `webapp/frontend/src/builder/files.ts` | **Create**: pure export/import core + one DOM stub | 3 |
| `webapp/frontend/src/builder/files.test.ts` | **Create**: node-env tests for the pure core | 3 |
| `webapp/frontend/src/api/studio.ts` | Modify: `importExperiment` | 4 |
| `webapp/frontend/src/builder/Toolbar.tsx` | Modify: Export + Import buttons, note slot | 4 |
| `webapp/frontend/src/builder/LoadDialog.tsx` | Modify: per-row `⭳` export | 5 |
| `examples/README.md` | Modify: name the real control; state the Builder limitation | 6 |

---

### Task 1: `create_renaming` — one implementation of the suffix walk

**Files:**
- Modify: `webapp/backend/experiment_studio/docs_store.py:133-142` (`duplicate`)
- Test: `webapp/backend/tests/test_docs_store.py`

**Interfaces:**
- Consumes: existing `ExperimentsStore.create`, `NameConflictError`, `ExperimentDoc`.
- Produces: `async ExperimentsStore.create_renaming(doc: ExperimentDoc) -> dict[str, Any]` — used by Task 2.

**Context:** `duplicate()` today inlines an `itertools.count` walk over `"{name} (copy)"`, `"{name} (copy 2)"`… Import needs the same walk but must try the *original* name first. Lifting it gives both callers one implementation (§5.1).

- [ ] **Step 1: Write the failing tests**

Add to `webapp/backend/tests/test_docs_store.py`:

```python
async def test_create_renaming_keeps_a_free_name(store: ExperimentsStore) -> None:
    created = await store.create_renaming(make_doc("Fresh"))
    assert created["name"] == "Fresh"
    assert created["doc"]["name"] == "Fresh"


async def test_create_renaming_walks_suffixes_when_taken(store: ExperimentsStore) -> None:
    await store.create(make_doc("X"))
    first = await store.create_renaming(make_doc("X"))
    second = await store.create_renaming(make_doc("X"))
    assert first["name"] == "X (copy)"
    assert second["name"] == "X (copy 2)"
    assert first["doc"]["name"] == "X (copy)"
    assert first["id"] != second["id"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_docs_store.py -q -k create_renaming`
Expected: FAIL — `AttributeError: 'ExperimentsStore' object has no attribute 'create_renaming'`

- [ ] **Step 3: Implement `create_renaming` and route `duplicate` through it**

In `docs_store.py`, replace the whole `duplicate` method with:

```python
    async def create_renaming(self, doc: ExperimentDoc) -> dict[str, Any]:
        """create(), but walk '(copy)', '(copy 2)'… until a free name lands (design §5.1)."""
        try:
            return await self.create(doc)
        except NameConflictError:
            pass
        for n in itertools.count(1):
            candidate = f"{doc.name} (copy)" if n == 1 else f"{doc.name} (copy {n})"
            try:
                return await self.create(doc.model_copy(update={"name": candidate}))
            except NameConflictError:
                continue
        raise AssertionError("unreachable")

    async def duplicate(self, experiment_id: str) -> dict[str, Any]:
        source = await self.get(experiment_id)
        return await self.create_renaming(ExperimentDoc.model_validate(source["doc"]))
```

Note the behavior this preserves: duplicating `"X"` tries `"X"` (which the source itself holds, so it
conflicts) and falls through to `"X (copy)"` — identical to the old inlined loop.

- [ ] **Step 4: Run the full store suite**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_docs_store.py -q`
Expected: PASS, **including the pre-existing `test_duplicate_suffixes_name` unchanged** — that test passing untouched is the refactor's proof.

- [ ] **Step 5: Run the gates**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/docs_store.py webapp/backend/tests/test_docs_store.py
git commit -m "refactor(studio): lift duplicate()'s suffix walk into create_renaming"
```

---

### Task 2: `POST /api/experiments/import`

**Files:**
- Modify: `webapp/backend/experiment_studio/api/experiments.py`
- Test: `webapp/backend/tests/test_experiments_api.py`

**Interfaces:**
- Consumes: `ExperimentsStore.create_renaming` (Task 1); the `get_store` dependency already in the module.
- Produces: `POST /api/experiments/import` → 201 `{id, name, description, created_at, updated_at, doc}` — consumed by Task 4's `importExperiment`.

**Context:** No route-ordering hazard, verified: the only existing `POST` routes are `""` and `/{experiment_id}/duplicate`, so there is no `POST /{experiment_id}` for `/import` to be shadowed by.

- [ ] **Step 1: Write the failing tests**

Add to `webapp/backend/tests/test_experiments_api.py`. Add `import json` and `from pathlib import Path` at the top if not already present (`Path` already is):

```python
async def test_import_creates_and_is_retrievable(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/experiments/import", json=doc_payload("Imported"))
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Imported"
    fetched = await client.get(f"/api/experiments/{body['id']}")
    assert fetched.status_code == 200 and fetched.json() == body


async def test_import_auto_renames_instead_of_conflicting(client: httpx.AsyncClient) -> None:
    """§5.2: import never 409s — it walks the suffix like duplicate does."""
    first = await client.post("/api/experiments/import", json=doc_payload("X"))
    second = await client.post("/api/experiments/import", json=doc_payload("X"))
    third = await client.post("/api/experiments/import", json=doc_payload("X"))
    assert [r.status_code for r in (first, second, third)] == [201, 201, 201]
    assert first.json()["name"] == "X"
    assert second.json()["name"] == "X (copy)"
    assert third.json()["name"] == "X (copy 2)"
    assert second.json()["doc"]["name"] == "X (copy)"


async def test_import_malformed_is_422(client: httpx.AsyncClient) -> None:
    for bad in (
        doc_payload(doc_version=2),
        doc_payload(name=""),
        {k: v for k, v in doc_payload().items() if k != "workflow"},
    ):
        resp = await client.post("/api/experiments/import", json=bad)
        assert resp.status_code == 422


async def test_import_does_not_gate_on_workflow_validity(client: httpx.AsyncClient) -> None:
    """§5.2: import is a save. Parent spec §4.3 — validation never blocks saving, only running."""
    broken = doc_payload(
        "Broken",
        workflow={
            "schema_version": 1,
            "blocks": [{"command": {"device": "ghost_role", "verb": "no_such_verb"}}],
        },
    )
    resp = await client.post("/api/experiments/import", json=broken)
    assert resp.status_code == 201
    assert resp.json()["doc"]["workflow"]["blocks"][0]["command"]["verb"] == "no_such_verb"


async def test_import_roundtrips_the_real_morbidostat_example(client: httpx.AsyncClient) -> None:
    """The load-bearing guarantee (§8): the shipped examples import byte-for-byte.

    Uses the real file, not a fixture — so this also pins that examples/*.json stay importable.
    """
    path = Path(__file__).parents[3] / "examples" / "morbidostat.json"
    original = json.loads(path.read_text())
    resp = await client.post("/api/experiments/import", json=original)
    assert resp.status_code == 201
    fetched = await client.get(f"/api/experiments/{resp.json()['id']}")
    assert fetched.json()["doc"] == original
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_experiments_api.py -q -k import`
Expected: FAIL — 405 or 422 (no such route; `/import` currently falls through to no matching POST).

- [ ] **Step 3: Add the route**

In `api/experiments.py`, add after `create_experiment` (anywhere in the module works — see Context):

```python
@router.post("/import", status_code=201)
async def import_experiment(
    doc: ExperimentDoc, store: ExperimentsStore = Depends(get_store)
) -> dict[str, Any]:
    """§5.2: create with auto-rename on conflict. Never 409; no validate_doc gate."""
    return await store.create_renaming(doc)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd webapp/backend && .venv/bin/python -m pytest tests/test_experiments_api.py -q`
Expected: PASS, all tests including the pre-existing `test_name_conflict_is_409` (which covers `POST ""`, whose 409 behavior is unchanged and load-bearing for Save).

- [ ] **Step 5: Run the gates**

Run: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add webapp/backend/experiment_studio/api/experiments.py webapp/backend/tests/test_experiments_api.py
git commit -m "feat(studio): POST /api/experiments/import with auto-rename on conflict"
```

---

### Task 3: `builder/files.ts` — the pure core

**Files:**
- Create: `webapp/frontend/src/builder/files.ts`
- Test: `webapp/frontend/src/builder/files.test.ts`

**Interfaces:**
- Consumes: `ExperimentDocJson` from `../types/doc`.
- Produces, all used by Tasks 4 and 5:
  - `class DocFileError extends Error`
  - `exportFilename(name: string): string`
  - `serializeDoc(doc: ExperimentDocJson): string`
  - `parseDocFile(text: string): ExperimentDocJson`
  - `triggerDownload(filename: string, text: string): void`

**Context:** This is the **first** `Blob` / `createObjectURL` / `type="file"` code in the frontend — verified, there is none today. Tests run in node with no DOM, which is exactly why `serializeDoc` returns a *string* instead of triggering the download itself: it makes the round-trip testable with zero DOM.

- [ ] **Step 1: Write the failing tests**

Create `webapp/frontend/src/builder/files.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import type { ExperimentDocJson } from '../types/doc'
import { DocFileError, exportFilename, parseDocFile, serializeDoc } from './files'

const doc = (): ExperimentDocJson => ({
  doc_version: 1,
  name: 'OD growth curve',
  description: null,
  roles: { feed_pump: { type: 'pump' } },
  workflow: { schema_version: 1, blocks: [] },
})

describe('exportFilename', () => {
  it('slugs runs of disallowed characters', () => {
    expect(exportFilename('OD growth curve')).toBe('OD_growth_curve.json')
  })

  it('keeps the characters the backend sanitizer keeps', () => {
    expect(exportFilename('morbidostat-demo_speed.v2')).toBe('morbidostat-demo_speed.v2.json')
  })

  it('strips path separators so an export cannot escape the download directory', () => {
    expect(exportFilename('../../etc/passwd')).toBe('etc_passwd.json')
  })

  it('falls back when nothing survives sanitizing', () => {
    expect(exportFilename('')).toBe('experiment.json')
    expect(exportFilename('...')).toBe('experiment.json')
    expect(exportFilename('Морбидостат')).toBe('experiment.json')
  })
})

describe('serializeDoc', () => {
  it('is 2-space indented with a trailing newline', () => {
    const text = serializeDoc(doc())
    expect(text.startsWith('{\n  "doc_version": 1,\n')).toBe(true)
    expect(text.endsWith('}\n')).toBe(true)
  })

  it('preserves the examples/*.json key order', () => {
    expect(Object.keys(JSON.parse(serializeDoc(doc())) as object)).toEqual([
      'doc_version',
      'name',
      'description',
      'roles',
      'workflow',
    ])
  })
})

describe('parseDocFile', () => {
  it('rejects non-JSON with a typed error', () => {
    expect(() => parseDocFile('not json at all')).toThrow(DocFileError)
    expect(() => parseDocFile('')).toThrow(DocFileError)
  })

  it('round-trips a doc through serialize (§8, client half)', () => {
    expect(parseDocFile(serializeDoc(doc()))).toEqual(doc())
  })
})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webapp/frontend && npm test -- --run files`
Expected: FAIL — cannot resolve `./files`.

- [ ] **Step 3: Implement the module**

Create `webapp/frontend/src/builder/files.ts`:

```ts
/**
 * Export/import of experiment docs as files (design 2026-07-16 §6).
 *
 * The file IS the bare ExperimentDoc, byte-compatible with examples/*.json.
 * Everything here except triggerDownload is pure and tested in node — the DOM
 * call is deliberately the only untested line, per this app's test convention.
 */
import type { ExperimentDocJson } from '../types/doc'

/** Bad JSON in an imported file. Shape is the server's job, not ours (§6.1). */
export class DocFileError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DocFileError'
  }
}

/** Mirrors the backend's proven record-download sanitizer (api/records.py:78). */
export function exportFilename(name: string): string {
  const stem = name.replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^[._]+|[._]+$/g, '')
  return `${stem || 'experiment'}.json`
}

/** The exported file body: 2-space indent, trailing newline, key order as given (§3). */
export const serializeDoc = (doc: ExperimentDocJson): string =>
  `${JSON.stringify(doc, null, 2)}\n`

/** Parse only. The server's Pydantic model is the single source of truth for shape. */
export function parseDocFile(text: string): ExperimentDocJson {
  try {
    return JSON.parse(text) as ExperimentDocJson
  } catch (e) {
    throw new DocFileError(`not a JSON file: ${e instanceof Error ? e.message : String(e)}`)
  }
}

/** Browser glue. No branching, no decisions — untested by convention (§6.1). */
export function triggerDownload(filename: string, text: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd webapp/frontend && npm test -- --run files`
Expected: PASS, 9 tests.

- [ ] **Step 5: Run the gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass (2 known oxlint fast-refresh warnings, exit 0).

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/builder/files.ts webapp/frontend/src/builder/files.test.ts
git commit -m "feat(studio): pure export/import core (filename, serialize, parse)"
```

---

### Task 4: Toolbar — Export + Import

**Files:**
- Modify: `webapp/frontend/src/api/studio.ts`
- Modify: `webapp/frontend/src/builder/Toolbar.tsx`

**Interfaces:**
- Consumes: `exportFilename`, `serializeDoc`, `parseDocFile`, `triggerDownload`, `DocFileError` (Task 3); `POST /api/experiments/import` (Task 2); existing `selectDoc`, `selectDirty`, `loadDoc`, `docToTree`, `DocConvertError`.
- Produces: `importExperiment(doc: ExperimentDocJson): Promise<ExperimentResource>` in `api/studio.ts` — also used by nothing else, but exported for symmetry with the other six calls.

**Context — the case that matters (§7):** importing `examples/morbidostat.json` **succeeds** and then throws `DocConvertError` from `docToTree`, because the doc uses `groups`. The doc is saved, listed, runnable. That is a **note, not an error** — never red, and the message must lead with what succeeded.

- [ ] **Step 1: Add the API call**

In `webapp/frontend/src/api/studio.ts`, add after `createExperiment`:

```ts
export const importExperiment = (doc: ExperimentDocJson) =>
  postJson<ExperimentResource>('/api/experiments/import', doc)
```

- [ ] **Step 2: Wire the Toolbar**

In `webapp/frontend/src/builder/Toolbar.tsx`:

Change the React import (line 1) to add `useRef`:

```ts
import { useRef, useState } from 'react'
```

Change the studio-api import (line 3) to add `importExperiment`:

```ts
import {
  createExperiment,
  duplicateExperiment,
  importExperiment,
  replaceExperiment,
} from '../api/studio'
```

Add after the `convert` import (line 18):

```ts
import { DocConvertError, docToTree } from './convert'
import { DocFileError, exportFilename, parseDocFile, serializeDoc, triggerDownload } from './files'
```

(the `convert` line already exists — extend it to also import `DocConvertError`.)

Add state beside the existing `loadOpen` (line 55):

```ts
  const [note, setNote] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
```

Add `setNote(null)` to `run()` so a stale note never outlives the next action. The body becomes:

```ts
  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    setNote(null)
    try {
      await fn()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'name_conflict') {
        setError(`name already taken — rename the experiment or use Save as`)
      } else {
        setError(e instanceof Error ? e.message : String(e))
      }
    } finally {
      setBusy(false)
    }
  }
```

Add the two handlers after `fresh()` (line 119):

```ts
  const exportDoc = () => {
    const state = useDocStore.getState()
    triggerDownload(exportFilename(state.name), serializeDoc(selectDoc(state)))
  }

  const importFile = (file: File) => {
    if (selectDirty(useDocStore.getState()) && !window.confirm('Discard unsaved changes?')) return
    return run(async () => {
      const res = await importExperiment(parseDocFile(await file.text()))
      try {
        loadDoc(docToTree(res.doc), res.id)
        setNote(`imported as '${res.doc.name}'`)
      } catch (e) {
        if (!(e instanceof DocConvertError)) throw e
        // §7: it IS saved and runnable — it just can't render as a block tree.
        setNote(`imported as '${res.doc.name}' — saved, but can't open in the Builder: ${e.message}`)
      }
    })
  }
```

`parseDocFile` throwing `DocFileError` propagates to `run()`'s catch and shows red — which is exactly §9's "not a JSON file" row. `DocFileError` is imported for that contract's clarity even though `run()` handles it structurally; if oxlint flags it as unused, drop it from the import.

Render the note next to the error (line 128):

```tsx
      {error && <span className="truncate text-xs text-red-600">{error}</span>}
      {note && <span className="truncate text-xs text-emerald-700">{note}</span>}
```

Add the buttons after `Duplicate` (line 155), and the hidden input just before the `loadOpen` line (157):

```tsx
        <button
          className={buttonClass}
          disabled={busy}
          title="Download this experiment as a JSON file"
          onClick={exportDoc}
        >
          Export
        </button>
        <button
          className={buttonClass}
          disabled={busy}
          title="Import an experiment from a JSON file"
          onClick={() => fileRef.current?.click()}
        >
          Import
        </button>
```

```tsx
      <input
        ref={fileRef}
        type="file"
        accept="application/json,.json"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = '' // re-importing the same file must re-fire change
          if (file) void importFile(file)
        }}
      />
```

- [ ] **Step 3: Run the gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass. If `typecheck` complains that `DocFileError` is unused, remove it from the import.

- [ ] **Step 4: Commit**

```bash
git add webapp/frontend/src/api/studio.ts webapp/frontend/src/builder/Toolbar.tsx
git commit -m "feat(studio): Export and Import buttons in the builder toolbar"
```

---

### Task 5: LoadDialog — per-row export

**Files:**
- Modify: `webapp/frontend/src/builder/LoadDialog.tsx`

**Interfaces:**
- Consumes: `exportFilename`, `serializeDoc`, `triggerDownload` (Task 3); existing `getExperiment`.
- Produces: nothing.

**Context:** This is what closes the round-trip. The Toolbar's Export can only reach docs the Builder can open — so without this, an imported `morbidostat.json` could **never leave the studio again**. Exporting `res.doc` straight from the server does no `convert` round-trip, so it works for any stored doc.

- [ ] **Step 1: Wire it**

In `webapp/frontend/src/builder/LoadDialog.tsx`:

Extend the api import (line 2) — `getExperiment` is already there, so only the files import is new. Add after the `convert` import (line 5):

```ts
import { exportFilename, serializeDoc, triggerDownload } from './files'
```

Add the handler after `remove()` (line 49):

```ts
  const exportItem = async (item: ExperimentSummary) => {
    setError(null)
    try {
      const res = await getExperiment(item.id)
      // the STORED doc, no convert round-trip — works for docs the builder can't open
      triggerDownload(exportFilename(res.doc.name), serializeDoc(res.doc))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }
```

Add the button immediately before the delete `✕` button (line 91):

```tsx
              <button
                title="Export experiment as JSON"
                onClick={() => void exportItem(item)}
                className="text-xs text-slate-300 hover:text-sky-600"
              >
                ⭳
              </button>
```

- [ ] **Step 2: Run the gates**

Run: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add webapp/frontend/src/builder/LoadDialog.tsx
git commit -m "feat(studio): export any stored experiment from the load dialog"
```

---

### Task 6: Make `examples/README.md` true, and prove the flow in a real browser

**Files:**
- Modify: `examples/README.md:1-5`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: nothing.

**Context:** `examples/README.md:3` has instructed users to import via "**Experiments → Import**" since the examples landed. There is no Experiments tab; the control is in the Builder. Fix the instruction to name the real control, and state the Builder limitation plainly — a user importing the morbidostat *will* hit it immediately, and finding it documented is the difference between a known limitation and a bug.

- [ ] **Step 1: Reword the instruction**

Replace `examples/README.md` lines 1–5 (the heading and the paragraph above the table) with:

```markdown
# Example experiments

Import one of these into Experiment Studio (**Builder → Import**, or
`POST /api/experiments/import` with the file as the body), map its roles to your devices on the
preflight screen, and run it.

Both examples use `groups`, `for_each`, `compute`, and `abort`, which the block builder cannot
render yet (spec §13, "Reusable groups (GroupRef) editing"). So they import, save, validate, and
run — but the Builder canvas will refuse to open them, and Studio will tell you so when you import.
Pick them on the Run tab and edit them as JSON.
```

- [ ] **Step 2: Prove the whole flow in a real browser**

Use the proven W5 recipe — the backend devserver plus a scratchpad Playwright script.

```bash
cd webapp/backend && .venv/bin/python tests/devserver.py &
cd webapp/frontend && npm run dev &
```

Then drive it (scratchpad script, not committed) against `http://localhost:5173`:

1. Builder tab → **Import** → set the file input to `examples/morbidostat.json`.
2. **Assert the §7 contract:** a note appears reading `imported as 'Morbidostat' — saved, but can't open in the Builder: workflow groups are not supported in the builder (v2 backlog)`, and it is **not** red (`text-emerald-700`, not `text-red-600`).
3. **Load** → assert `Morbidostat` is listed → click its `⭳` → capture the download → assert the bytes `JSON.parse`-deep-equal `examples/morbidostat.json`. **This is the full round-trip through the real UI.**
4. Import `examples/morbidostat.json` a second time → assert the note reads `imported as 'Morbidostat (copy)'`.
5. Build any small doc in the Builder → **Export** → assert the file parses and its `name` matches.
6. Import a garbage file (`echo 'not json' > /tmp/x.json`) → assert a **red** error starting `not a JSON file:`.

Playwright sets a file input with `page.setInputFiles('input[type=file]', path)` — it does not need the input to be visible, so the hidden input is fine. Capture downloads with `page.waitForEvent('download')`.

- [ ] **Step 3: Run every gate, both halves**

```bash
cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build
```
Expected: all pass. Kill the devserver and `npm run dev` afterwards.

- [ ] **Step 4: Commit**

```bash
git add examples/README.md
git commit -m "docs: point examples at the real import control and state the builder limit"
```

---

### Task 7: PR

**Files:** none — repository operation.

- [ ] **Step 1: Push and open the PR**

```bash
git push -u origin feat/experiment-studio-7-export-import
gh pr create --title "feat(studio): export/import experiment setups (W7)" --body "$(cat <<'EOF'
Picks up the studio spec's §13 deferred "YAML/DSL import-export", narrowed to JSON file
export/import — the doc format that already exists on disk.

It also makes `examples/README.md` true: that file has told users to import the examples via
"Experiments → Import" since they landed, and no such UI was ever built.

## What's in it

- `POST /api/experiments/import` — create with auto-rename on conflict. Never 409, no validation
  gate (import is a save; parent spec §4.3 settled that validation blocks running, not saving).
- `create_renaming` lifted out of `duplicate()`, so the `(copy N)` walk has one implementation.
- `builder/files.ts` — pure export/import core, tested in node; the DOM call is a branchless stub,
  untested like every component here (this repo has no jsdom and zero component tests, on purpose).
- Toolbar **Export** (the open doc, including unsaved edits) + **Import**.
- Load-dialog per-row **⭳** — exports the *stored* doc with no convert round-trip, which is what
  makes docs the Builder can't open exportable at all.

## The case worth reviewing

Importing `examples/morbidostat.json` succeeds, then `docToTree` throws because the doc uses
`groups`. The doc is saved, listed, and runnable — it just can't render as a block tree. So it
reports as a **note, not an error**. See design §7.

## Proof

- Backend round-trip pinned against the **real** `examples/morbidostat.json` — import → GET →
  deep-equal the file on disk. That test also pins that the shipped examples stay importable.
- `duplicate()`'s pre-existing tests pass untouched — the refactor's proof.
- Full flow driven in a real browser (import → note → export → byte-compare → re-import → rename).

Design: `docs/superpowers/specs/2026-07-16-experiment-studio-export-import-design.md`
Plan: `docs/superpowers/plans/2026-07-16-experiment-studio-7-export-import.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Wait for CI, then merge**

```bash
gh pr checks --watch
gh pr merge --squash
```

---

### Task 8: Preprod live verification (post-merge)

**Files:** none — deployment operation. Depends on release-please cutting the release and CI publishing the image.

**Context:** The studio ships as `ghcr.io/bioexperiment-lab-devices/experiment-studio`, pinned by `studio_image` in `pins.yaml` in the **`lab_devices_server`** repo (`/Users/khamit/lab_devices_server`). The `/studio/*` route and its Authelia rule already exist from W6 — **no `authelia/configuration.yml` change is needed here**, so the known deploy gotcha (CI deploys exclude that file) does not apply and a normal CI stack deploy suffices.

- [ ] **Step 1: Confirm the release published the image**

```bash
gh release list --limit 3
gh api /orgs/bioexperiment-lab-devices/packages/container/experiment-studio/versions --jq '.[0].metadata.container.tags'
```
Expected: a new minor version (feat bump), tag present and public.

- [ ] **Step 2: Pin it on preprod**

In `/Users/khamit/lab_devices_server`, bump `studio_image` in `pins.yaml` to the new tag, commit, push, and let CI deploy. Verify:

```bash
ssh khamit@111.88.145.138 'docker inspect lab-bridge-studio-1 --format "{{.Config.Image}}"'
```
Expected: the new tag.

- [ ] **Step 3: Prove import → run on real hardware**

Per the proven preprod recipe — a single script through the jupyter container, which can reach the studio at `http://studio:8000`:

```bash
ssh khamit@111.88.145.138 docker exec -i lab-bridge-jupyter-1 python - <<'PY'
import json, urllib.request
doc = json.load(open('/tmp/morbidostat-demo-speed.json'))
req = urllib.request.Request(
    'http://studio:8000/api/experiments/import',
    data=json.dumps(doc).encode(),
    headers={'Content-Type': 'application/json'},
)
body = json.load(urllib.request.urlopen(req))
print('imported:', body['id'], body['name'])
assert body['doc'] == doc, 'round-trip mismatch on preprod'
print('round-trip OK')
PY
```

(Copy the example in first with `scp` + `docker cp`, or inline the JSON.)

Then, through the studio UI at `https://<preprod>/studio/`, map the imported experiment's nine roles
onto `windows_arm64_test_client`'s devices and run it. **Known rig behaviors from the preprod
memory, so they are not mistaken for import bugs:** the simulated pump agent requires a positive
`speed_ml_min` on dispense; the densitometer needs a `measure_blank` first; and the rig's OD sensors
read `0.0`, so every cycle takes the "too dilute → no action" branch and the dosing arms never fire.
The claim being proven here is narrow and worth stating exactly: **a doc that entered the studio as a
file runs on real hardware identically to one authored in the Builder.**

- [ ] **Step 4: Report**

Record the imported id, the record id, and the run status. Leave the artifacts on preprod as W6's smoke did.

---

## Self-Review

**Spec coverage:**

| Spec § | Task |
|---|---|
| §2 scope: export/import only | whole plan; §2.1's rejection is why there is no library task |
| §3 format: bare doc, no envelope/mappings | 3 (`serializeDoc`), 2 (round-trip test) |
| §4 architecture: import server-side, export client-side | 2, 3–5 |
| §5.1 `create_renaming` + duplicate refactor | 1 |
| §5.2 import route, no 409, no validate gate | 2 |
| §6.1 pure core / DOM stub | 3 |
| §6.2 `importExperiment` | 4 |
| §6.3 Toolbar, dirty guard, note slot, input reset | 4 |
| §6.4 LoadDialog `⭳` | 5 |
| §7 morbidostat note-not-error | 4 (impl), 6 (browser proof) |
| §8 store round-trip | 2 (pytest, real example), 6 (browser, full UI) |
| §9 error table | 2 (422), 3 (`DocFileError`), 4 (red vs note), 6 (browser proof of both) |
| §10 testing + gates | every task |
| §11 docs | 6 |

No gaps.

**Placeholder scan:** none — every code step carries real code, every command is exact.

**Type consistency:** `create_renaming(doc: ExperimentDoc) -> dict[str, Any]` defined in Task 1, called identically in Task 2. `exportFilename` / `serializeDoc` / `parseDocFile` / `triggerDownload` / `DocFileError` defined in Task 3, imported with those exact names in Tasks 4 and 5. `importExperiment(doc: ExperimentDocJson): Promise<ExperimentResource>` defined in Task 4 Step 1, used in Task 4 Step 2. `DocConvertError` is imported from `./convert`, where it already exists.
