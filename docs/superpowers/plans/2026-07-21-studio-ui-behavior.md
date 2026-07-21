# Studio Behavior Fixes (PR 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five behavior fixes: blank stream units serialize as `"unitless"`, Save prompts for a name on never-saved documents, device string params with a closed value set become enums end-to-end (engine registry → catalog → Inspector select), the Devices-tab valve rotation options match the real device contract, and no-roles experiments can start.

**Architecture:** The enum change flows one way: `ParamSpec.values` in the engine registry → `verb_catalog()` → `GET /api/catalog` (pass-through, no backend change) → `types/catalog.ts` → `ParamInput`. Engine load-validation rejects out-of-enum literals (holes exempt). Everything else is a local fix in the named file. No new document fields → no `schema_version` bump.

**Tech Stack:** Python 3.11+ engine (dataclasses, TypedDict), FastAPI backend (untouched), React 19.2 + vitest 4 (node env, pure fns only) frontend.

**Spec:** `docs/superpowers/specs/2026-07-21-studio-ui-polish-design.md` (§PR 2)

## Global Constraints

- Worktree: stacked on PR 1 — branch `feat/studio-ui-behavior` created FROM `feat/studio-ui-polish`.
- Frontend gate: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`.
- Webapp backend gate: `cd webapp/backend && .venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` (mypy takes NO path argument; venv built with `-e ../.. -e ".[dev]"` so the LOCAL engine is under test, not PyPI's).
- Engine gate (repo root): `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` plus `awk 'length>100' src/lab_devices/experiment/*.py tests/test_experiment_*.py` must print nothing. Root venv: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.
- Engine test conventions: flat `tests/test_experiment_*.py`, helpers via `from tests.experiment_validate_helpers import cmd, diags, wf`; source modules keep the one-line docstring citing a design §.
- vitest is node-env and imports PURE modules only — never import a `.tsx` component into a test.
- Commit after every task; end every commit body with the two Claude trailers used on this branch (see `git log -1`).

---

### Task 1: Engine — `ParamSpec.values`, registry entries, catalog serialization, load validation

**Files:**
- Modify: `src/lab_devices/experiment/registry.py:16-22` (ParamSpec), `:58-130` (pump/valve entries)
- Modify: `src/lab_devices/experiment/catalog.py:11-37`
- Modify: `src/lab_devices/experiment/validate.py:739-742` (`_check_param_value` string branch)
- Test: `tests/test_experiment_catalog.py`, `tests/test_experiment_validate_params.py`

**Interfaces:**
- Produces: `ParamSpec(name, kind, required=False, values: tuple[str, ...] | None = None)`; `ParamEntry` gains optional `values: list[str]` (key present only when the spec declares values); a `params`-category diagnostic `expected one of [...], got '...'` for out-of-enum literals.

- [ ] **Step 1: Failing validation tests** — append to `tests/test_experiment_validate_params.py`:

```python
def test_enum_string_param_rejects_unknown_literal():
    d = diags(wf([cmd("pump_1", "rotate", {"direction": "backwards", "speed_ml_min": 1.0})]))
    assert any(
        x.category == "params" and "expected one of" in x.message and "backwards" in x.message
        for x in d
    )


def test_enum_string_param_accepts_declared_literal():
    d = diags(wf([cmd("pump_1", "rotate", {"direction": "reverse", "speed_ml_min": 1.0})]))
    assert not any("expected one of" in x.message for x in d)


def test_enum_string_param_defers_holes():
    """A `{hole}` is a for_each/group placeholder — not a literal to check. Same deferral
    rule as _role_type's device holes."""
    d = diags(wf([cmd("pump_1", "rotate", {"direction": "{dir}", "speed_ml_min": 1.0})]))
    assert not any("expected one of" in x.message for x in d)
```

and to `tests/test_experiment_catalog.py`:

```python
def test_catalog_declares_enum_values_for_closed_string_params():
    cat = verb_catalog()
    rotate = {p["name"]: p for p in cat["pump"]["rotate"]["params"]}
    assert rotate["direction"]["values"] == ["forward", "reverse"]
    valve = {p["name"]: p for p in cat["valve"]["set_position"]["params"]}
    assert valve["rotation"]["values"] == ["shortest", "direct", "wrap"]
    configure = {p["name"]: p for p in cat["valve"]["configure"]["params"]}
    assert configure["default_rotation"]["values"] == ["shortest", "direct", "wrap"]
    dispense = {p["name"]: p for p in cat["pump"]["dispense"]["params"]}
    assert dispense["direction"]["values"] == ["forward", "reverse"]


def test_catalog_omits_values_key_for_open_string_params():
    cat = verb_catalog()
    volume = {p["name"]: p for p in cat["pump"]["dispense"]["params"]}["volume_ml"]
    assert "values" not in volume
```

Run: `.venv/bin/python -m pytest -q tests/test_experiment_validate_params.py tests/test_experiment_catalog.py` — the new tests FAIL (`values` unknown / no diagnostic).

- [ ] **Step 2: Implement.** `registry.py` — extend the dataclass:

```python
@dataclass(frozen=True)
class ParamSpec:
    """One verb parameter: its scalar kind and whether the verb requires it (design §4).
    `values` closes a string param over an explicit literal set (an enum): the device
    accepts exactly these spellings, so the validator can reject the rest at load."""

    name: str
    kind: Kind
    required: bool = False
    values: tuple[str, ...] | None = None
```

and the four entries (values per `docs/lab-bridge-api-reference.md:508` for direction, `:581` for rotation modes):

```python
            ParamSpec("direction", "string", values=("forward", "reverse")),      # dispense
            ParamSpec("direction", "string", required=True, values=("forward", "reverse")),  # rotate
            ParamSpec("rotation", "string", values=("shortest", "direct", "wrap")),          # set_position
            ParamSpec("default_rotation", "string", values=("shortest", "direct", "wrap")),  # configure
```

`catalog.py` — `ParamEntry` gains `values: NotRequired[list[str]]` (import `NotRequired` from `typing`); emit it only when declared:

```python
            params=[
                ParamEntry(name=p.name, type=p.kind, required=p.required, values=list(p.values))
                if p.values is not None
                else ParamEntry(name=p.name, type=p.kind, required=p.required)
                for p in trait.params
            ],
```

`validate.py` — the string branch of `_check_param_value` becomes:

```python
    if spec.kind == "string":
        if not isinstance(value, str):
            out.append(Diagnostic("params", ctx, f"expected a string literal, got {value!r}"))
        elif spec.values is not None and "{" not in value and value not in spec.values:
            # A hole defers to expansion, same as _role_type's device holes; the expanded
            # copy re-runs this check with the literal filled in.
            out.append(Diagnostic(
                "params", ctx, f"expected one of {list(spec.values)}, got {value!r}"
            ))
        return
```

- [ ] **Step 3: Engine gate** — `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .` and the `awk 'length>100'` check. The full suite matters here: examples (morbidostat) contain valve `rotation`/pump `direction` literals — if any example fails the new check, the example has been carrying an invalid value; fix the EXAMPLE only if its value is genuinely outside the device contract, and say so in the commit message.

- [ ] **Step 4: Webapp backend gate** — `cd webapp/backend && .venv/bin/python -m pytest -q` (catalog payload tests may pin the params shape; extend them for `values` rather than deleting assertions).

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(experiment): closed string params declare enum values — registry, catalog, load validation"`.

---

### Task 2: Frontend — catalog type + Inspector enum select

**Files:**
- Modify: `src/types/catalog.ts:5-11`
- Modify: `src/builder/Inspector.tsx:887-902` (`ParamInput` string branch)

**Interfaces:**
- Consumes: `values` in `GET /api/catalog` param entries (Task 1).
- Produces: `ParamSpec.values?: string[]`; enum params render a `<select>`; out-of-list current values (legacy docs, `{hole}` args) stay visible and selected.

- [ ] **Step 1: Type** — in `src/types/catalog.ts`:

```ts
export interface ParamSpec {
  name: string
  type: ParamKind
  required: boolean
  // Present when the param is a closed enum: the device accepts exactly these spellings.
  values?: string[]
}
```

- [ ] **Step 2: Widget** — in `ParamInput`, inside the `spec.type === 'string'` branch, render a select when `values` is present (before the AutoGrowTextArea return). An out-of-list current value — a legacy literal or a `{hole}` authored via for_each/group args — must stay visible, so it joins the options rather than being silently swapped for the first entry (the browser's native fallback):

```tsx
  if (spec.type === 'string') {
    if (spec.values !== undefined) {
      const current = typeof value === 'string' ? value : ''
      return (
        <select
          value={current}
          onChange={(e) => onCommit(e.target.value === '' ? undefined : e.target.value)}
          className={controlClass()}
        >
          <option value="">— unset —</option>
          {spec.values.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
          {current !== '' && !spec.values.includes(current) && (
            <option value={current}>{current}</option>
          )}
        </select>
      )
    }
    return (
      <AutoGrowTextArea
        value={typeof value === 'string' ? value : paramInputText(value)}
        onCommit={(t) => onCommit(coerceParamInput(t, 'string'))}
        placeholder={spec.required ? 'required' : 'optional'}
      />
    )
  }
```

- [ ] **Step 3: Gate** — `npm run typecheck && npm run lint && npm test -- --run && npm run build`.

- [ ] **Step 4: Commit** — `git commit -am "feat(studio): enum device params render as selects in the Inspector"`.

---

### Task 3: Devices tab — valve rotation options match the device contract

**Files:**
- Modify: `src/devices/catalog.ts:47`

- [ ] **Step 1: Fix the constant** — `cw`/`ccw` are not accepted by the device at all (`docs/lab-bridge-api-reference.md:581` lists `rotation_modes: ["shortest", "direct", "wrap"]`); the old list also omitted two real modes:

```ts
const ROTATION_OPTIONS = ['shortest', 'direct', 'wrap']
```

- [ ] **Step 2: Sweep for other stale literals** — `grep -rn "'cw'\|'ccw'" src/` must return nothing (fixture/test references included — update any).

- [ ] **Step 3: Gate + commit** — `npm run typecheck && npm test -- --run`, then `git commit -am "fix(studio): valve rotation options are shortest/direct/wrap, not cw/ccw"`.

---

### Task 4: Blank units serialize as "unitless"

**Files:**
- Modify: `src/builder/convert.ts:97,232`
- Modify: `src/builder/StreamsPanel.tsx` (two `placeholder="units"` inputs)
- Test: `src/builder/convert.test.ts`

**Interfaces:**
- Produces: `treeToDoc` never emits `units: null`; `docToTree` maps `"unitless"` → `null`. Round-trip of a doc carrying `"unitless"` is byte-identical.

- [ ] **Step 1: Failing test** — in `convert.test.ts`, following the file's existing minimal-doc fixture pattern (reuse its smallest ExperimentDocJson builder; add a stream with `units: "unitless"` and one with `units: null` on the tree side):

```ts
describe('unitless streams', () => {
  it('loads "unitless" as a blank field and serializes blank back to "unitless"', () => {
    const doc = minimalDoc({ streams: { od: { units: 'unitless' } } })
    const content = docToTree(doc)
    expect(content.streams['od'].units).toBeNull()
    expect(treeToDoc(content).workflow.streams['od'].units).toBe('unitless')
  })
  it('leaves real units untouched', () => {
    const doc = minimalDoc({ streams: { od: { units: 'AU' } } })
    expect(treeToDoc(docToTree(doc)).workflow.streams['od'].units).toBe('AU')
  })
})
```

(`minimalDoc` = whatever the file's existing helper is called; do not invent a second fixture builder.) Run `npm test -- --run convert` → FAIL.

- [ ] **Step 2: Implement** — `docToTree` (line 97): `units: decl.units === 'unitless' ? null : (decl.units ?? null),` with a one-line comment: the engine spells "no unit" as the literal `"unitless"` (`units.py` `_UNITLESS_TEXTS`); the Studio spells it as a blank field, converting at the boundary in both directions. `treeToDoc` (line 232): `units: s.units ?? 'unitless',`.

- [ ] **Step 3: Placeholders** — both units inputs in `StreamsPanel.tsx` (the per-row one and the new-stream one) change `placeholder="units"` → `placeholder="unitless"`.

- [ ] **Step 4: Full frontend gate** — `npm test -- --run && npm run typecheck && npm run lint`. The byte no-op tests over `examples/*.json` must stay green (they will: explicit `"unitless"` round-trips to itself).

- [ ] **Step 5: Commit** — `git commit -am "feat(studio): blank stream units mean unitless — serialized explicitly, no more typing the word"`.

---

### Task 5: Save prompts for a name on never-saved documents

**Files:**
- Modify: `src/builder/Toolbar.tsx:84-115`

**Interfaces:**
- Produces: `save()` on `serverId === null` runs the same prompt+create flow as Save as, but with the doc's current name as the prompt default (no "(copy)"); cancel creates nothing. Existing-doc save (PUT) unchanged.

- [ ] **Step 1: Extract the shared flow** — replace `save`/`saveAs` with:

```tsx
  // Shared by Save-on-a-new-doc and Save as: prompt for a name, create, adopt the server id.
  // pauseHistory around the rename so cancel/error leaves no undo step behind.
  const promptAndCreate = (title: string, defaultName: string) => {
    const newName = window.prompt(title, defaultName)
    if (!newName) return
    const previousName = useDocStore.getState().name
    void run(async () => {
      pauseHistory()
      try {
        useDocStore.getState().setName(newName)
        const snapshot = snapshotOf(selectContent(useDocStore.getState()))
        try {
          const res = await createExperiment(selectDoc(useDocStore.getState()))
          markSaved(res.id, snapshot)
        } catch (e) {
          useDocStore.getState().setName(previousName)
          throw e
        }
      } finally {
        resumeHistory()
      }
    })
  }

  // A never-saved doc has no server identity to overwrite, so Save IS Save as — minus the
  // "(copy)" suffix, because there is no original to copy.
  const save = () => {
    const state = useDocStore.getState()
    if (state.serverId === null) {
      promptAndCreate('Save…', state.name)
      return
    }
    return run(async () => {
      const doc = selectDoc(state)
      const snapshot = snapshotOf(selectContent(state))
      const res = await replaceExperiment(state.serverId as string, doc)
      markSaved(res.id, snapshot)
    })
  }

  const saveAs = () => promptAndCreate('Save as…', `${name} (copy)`)
```

Check the Save button's `onClick={() => void save()}` still typechecks (`save` now returns `void | Promise<void>`; adjust to `onClick={() => void save()}` — already compatible).

- [ ] **Step 2: Gate** — `npm run typecheck && npm run lint && npm test -- --run && npm run build` (Toolbar has no node-env tests; behavior is verified in Task 7's browser pass).

- [ ] **Step 3: Commit** — `git commit -am "feat(studio): Save on a never-saved document prompts for a name like Save as"`.

---

### Task 6: No-roles experiments can start

**Files:**
- Modify: `src/run/preflight.ts:38-39`
- Test: `src/run/preflight.test.ts`

- [ ] **Step 1: Failing test** — append to `preflight.test.ts`:

```ts
describe('mappingComplete with no roles', () => {
  it('is vacuously complete — a no-roles experiment has nothing to map', () => {
    expect(mappingComplete([])).toBe(true)
  })
})
```

Run `npm test -- --run preflight` → FAIL (`rows.length > 0` clause).

- [ ] **Step 2: Implement** — in `preflight.ts`:

```ts
export const mappingComplete = (rows: MappingRow[]): boolean =>
  rows.every((r) => r.selected !== null)
```

Keep the existing tests for partial/complete mappings green (`.every` on a non-empty array is unchanged).

- [ ] **Step 3: Gate** — `npm test -- --run && npm run typecheck`.

- [ ] **Step 4: Commit** — `git commit -am "fix(studio): experiments with no roles can start — mapping is vacuously complete"`.

---

### Task 7: End-to-end verification pass

**Files:** read-only; evidence to `docs/ui-polish/behavior/` (absolute path).

- [ ] **Step 1: All three gates in sequence** — frontend, webapp backend, engine (commands in Global Constraints). All green.

- [ ] **Step 2: Browser pass against the worktree's isolated devserver stack** (reuse PR 1 Task 7's servers; FakeLab devserver so runs can actually start): (a) new doc → Save → prompt appears with current name, cancel creates nothing, accept creates and the header shows saved; (b) existing doc → Save silently PUTs (no prompt); (c) command block on a pump role → `rotate` → direction is a select listing forward/reverse; valve `set_position` → rotation select lists shortest/direct/wrap; (d) Devices tab → valve set_position rotation options are shortest/direct/wrap; (e) a doc with zero roles + FakeLab selected → Start enabled → run starts and completes; (f) a stream left with blank units → save → re-open → still blank; exported JSON carries `"unitless"`.

- [ ] **Step 3: Commit evidence** — screenshots/notes into `docs/ui-polish/behavior/`, `git add docs/ui-polish && git commit -m "docs(studio): behavior-fix verification evidence"`.
