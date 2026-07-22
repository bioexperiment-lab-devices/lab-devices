# Studio role fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Builder's meaningless `— unset —` device-command dropdown entry with engine-declared defaults + meaning-aware empty labels, and add an independent densitometer `read_temperature` verb that decouples temperature from the OD `measure` job.

**Architecture:** The engine registry (`ParamSpec`/`Trait`) is the source of truth; new UI-facing hints (`default`, `on_omit`) and the new verb flow through `verb_catalog()` → `GET /catalog` → the Studio frontend. The Builder consumes them via a small pure helper; the Devices tab gets a hand-added convenience control.

**Tech Stack:** Python 3.11+ (engine + FastAPI backend), TypeScript/React + Vite + vitest (frontend).

## Global Constraints

- Engine gates: `.venv/bin/python -m pytest` · `-m mypy` · `-m ruff check .` (run from repo root). Ruff line-length 100; mypy strict.
- Backend gates (cwd `webapp/backend`): `../../.venv/bin/python -m pytest -q` · `-m mypy` · `-m ruff check .`.
- Frontend gates (cwd `webapp/frontend`): `npm run lint` · `npm test` · `npm run build`. vitest runs node-env: pure functions only, no DOM rendering.
- **No `schema_version` bump.** `read_temperature` is just a new verb string; `default`/`on_omit` are catalog-only.
- Frontend catalog types mirror the wire verbatim in snake_case (`result_field`, `retry_safe`); new fields are `default`, `on_omit` (snake_case).
- Commit after every task with a Conventional-Commit message; end bodies with the Co-Authored-By / Claude-Session trailers.

---

### Task 1: Engine — densitometer `read_temperature` device method

**Files:**
- Modify: `src/lab_devices/devices/densitometer.py`
- Test: `tests/test_densitometer.py`

**Interfaces:**
- Produces: `Densitometer.read_temperature() -> DensitometerStatus` (async), reads via the `status` command (no optics). Consumed by the executor through `getattr(device, "read_temperature")()`.

- [ ] **Step 1: Add `status` canned response to the shared fake, then write the failing test**

In `tests/test_densitometer.py`, extend `_dens()`'s `add_device(...)` call with a `status` response and add the test:

```python
# inside _dens()'s fake.add_device(...), add this kwarg:
        status={"state": "idle", "temperature_c": 36.98},
```

```python
async def test_read_temperature_reads_status_without_optics():
    fake, dens, client = _dens()
    try:
        status = await dens.read_temperature()
        from lab_devices.models.densitometer import DensitometerStatus
        assert isinstance(status, DensitometerStatus)
        assert status.temperature_c == 36.98
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_densitometer.py::test_read_temperature_reads_status_without_optics -q`
Expected: FAIL — `AttributeError: 'Densitometer' object has no attribute 'read_temperature'`.

- [ ] **Step 3: Implement the method**

In `src/lab_devices/devices/densitometer.py`, add after `read_raw` (keep `DensitometerStatus` in the existing import block from `lab_devices.models.densitometer`):

```python
    async def read_temperature(self) -> DensitometerStatus:
        """Independent temperature read: polls `status` (no optics/LED run). See spec §3.8.

        Temperature rides inside the optics `measure` job too, but `status` returns it without
        actuating anything — so a workflow can record temperature without running the optics."""
        return DensitometerStatus.from_raw(await self.command("status"))
```

Add `DensitometerStatus` to the `from lab_devices.models.densitometer import (...)` list if not already imported.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_densitometer.py -q`
Expected: PASS (all densitometer tests).

- [ ] **Step 5: Gate + commit**

```bash
.venv/bin/python -m mypy && .venv/bin/python -m ruff check .
git add src/lab_devices/devices/densitometer.py tests/test_densitometer.py
git commit -m "feat(engine): densitometer.read_temperature reads status without optics

Independent temperature read primitive; polls the status command (no LED/optics
actuation) and returns the parsed DensitometerStatus.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 2: Engine — registry `default`/`on_omit` fields + population + `read_temperature` trait

**Files:**
- Modify: `src/lab_devices/experiment/registry.py`
- Test: `tests/test_experiment_registry.py`

**Interfaces:**
- Produces: `ParamSpec` gains `default: str | int | bool | None = None` and `on_omit: Literal["default", "unchanged"] | None = None`. New trait `("densitometer", "read_temperature")`: `completion="immediate"`, `state_effect="none"`, `channels=frozenset()`, `measurement=True`, `result_field="temperature_c"`, `retry_safe=True`, no params.

- [ ] **Step 1: Write the failing tests**

In `tests/test_experiment_registry.py`:

```python
def test_param_defaults_and_on_omit():
    from lab_devices.experiment.registry import _REGISTRY
    dispense = {p.name: p for p in _REGISTRY[("pump", "dispense")].params}
    assert dispense["direction"].default == "forward"
    rotate = {p.name: p for p in _REGISTRY[("pump", "rotate")].params}
    assert rotate["direction"].default == "forward"
    thermo = {p.name: p for p in _REGISTRY[("densitometer", "set_thermostat")].params}
    assert thermo["enabled"].default is True
    meas = {p.name: p for p in _REGISTRY[("densitometer", "measure")].params}
    assert meas["include_raw"].default is False
    setpos = {p.name: p for p in _REGISTRY[("valve", "set_position")].params}
    assert setpos["rotation"].on_omit == "default" and setpos["rotation"].default is None
    conf = {p.name: p for p in _REGISTRY[("valve", "configure")].params}
    assert conf["default_rotation"].on_omit == "unchanged"
    assert conf["hold_torque"].on_omit == "unchanged"


def test_read_temperature_is_a_channelless_immediate_measurement():
    t = lookup("densitometer", "read_temperature")
    assert t.completion == "immediate"
    assert t.measurement is True
    assert t.result_field == "temperature_c"
    assert t.retry_safe is True
    assert t.channels == frozenset()
    assert t.params == ()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_registry.py::test_param_defaults_and_on_omit tests/test_experiment_registry.py::test_read_temperature_is_a_channelless_immediate_measurement -q`
Expected: FAIL — `TypeError: ParamSpec.__init__() got an unexpected keyword argument 'default'` and `UnknownVerbError`.

- [ ] **Step 3: Extend `ParamSpec` and add the trait**

In `registry.py`, extend the dataclass (`Literal` is already imported):

```python
@dataclass(frozen=True)
class ParamSpec:
    """One verb parameter: its scalar kind and whether the verb requires it (design §4).
    `values` closes a string param over an explicit literal set (an enum): the device
    accepts exactly these spellings, so the validator can reject the rest at load.
    `default`/`on_omit` are UI-seed hints only (they do not change validation or execution):
    the Builder seeds `default` and labels the empty option from `on_omit`."""

    name: str
    kind: Kind
    required: bool = False
    values: tuple[str, ...] | None = None
    default: str | int | bool | None = None
    on_omit: Literal["default", "unchanged"] | None = None
```

Update the seven param declarations:

```python
# pump.dispense
        ParamSpec("direction", "string", values=("forward", "reverse"), default="forward"),
# pump.rotate
        ParamSpec("direction", "string", required=True, values=("forward", "reverse"), default="forward"),
# densitometer.measure
        params=(ParamSpec("include_raw", "bool", default=False),),
# densitometer.set_thermostat
            ParamSpec("enabled", "bool", required=True, default=True),
# valve.set_position
        ParamSpec("rotation", "string", values=("shortest", "direct", "wrap"), on_omit="default"),
# valve.configure
            ParamSpec("default_rotation", "string", values=("shortest", "direct", "wrap"), on_omit="unchanged"),
            ParamSpec("hold_torque", "bool", on_omit="unchanged"),
```

Add the new trait to `_REGISTRY` in the densitometer block (after `measure_blank`):

```python
    # Independent temperature read: `status` returns temperature_c without running the optics,
    # so it occupies NO subsystem (channels=frozenset()) and can run while the thermostat mode
    # is open on _THERMAL. Immediate (status is a fast read, not a job), pure read → retry_safe.
    ("densitometer", "read_temperature"): Trait(
        "immediate",
        "none",
        channels=frozenset(),
        measurement=True,
        result_field="temperature_c",
        retry_safe=True,
    ),
```

- [ ] **Step 4: Fix the two invariant tests + the spot-checks the defaults touch**

In `tests/test_experiment_registry.py`:

Replace `test_every_entry_declares_channels`:

```python
def test_every_actuating_entry_declares_channels():
    for key, trait in _REGISTRY.items():
        if key == ("densitometer", "read_temperature"):
            assert trait.channels == frozenset()  # a pure status read occupies no subsystem
        else:
            assert trait.channels, f"{key} has no channels"
```

Replace `test_measurement_flags`:

```python
def test_measurement_flags():
    measuring = {key for key, t in _REGISTRY.items() if t.measurement}
    assert measuring == {
        ("densitometer", "measure"),
        ("densitometer", "measure_blank"),
        ("densitometer", "read_temperature"),
    }
    # Job-based measurements poll to completion; read_temperature is an immediate status read.
    for key in [("densitometer", "measure"), ("densitometer", "measure_blank")]:
        assert _REGISTRY[key].completion == "job"
    assert _REGISTRY[("densitometer", "read_temperature")].completion == "immediate"
```

Add the `read_temperature` channel row to `test_channel_table`:

```python
    assert lookup("densitometer", "read_temperature").channels == frozenset()
```

Update the two `ParamSpec` equality spot-checks in `test_param_specs_spot_checks` that now carry a default:

```python
    assert rotate["direction"] == ParamSpec(
        "direction", "string", required=True, values=("forward", "reverse"), default="forward"
    )
    ...
    assert thermo["enabled"] == ParamSpec("enabled", "bool", required=True, default=True)
```

- [ ] **Step 5: Run the registry tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_registry.py -q`
Expected: PASS.

- [ ] **Step 6: Gate + commit**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
git add src/lab_devices/experiment/registry.py tests/test_experiment_registry.py
git commit -m "feat(engine): param default/on_omit hints + densitometer read_temperature trait

ParamSpec gains UI-seed hints (default, on_omit); populate direction/rotation/
enabled/include_raw. New channelless immediate measurement verb read_temperature
(result_field temperature_c). Relaxes two test-encoded invariants: a pure read
declares no channels, and a measurement need not be a job.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 3: Engine — catalog serialization of `default`/`on_omit` + `read_temperature`

**Files:**
- Modify: `src/lab_devices/experiment/catalog.py`
- Test: `tests/test_experiment_catalog.py`

**Interfaces:**
- Consumes: `ParamSpec.default`, `ParamSpec.on_omit` (Task 2).
- Produces: `ParamEntry` TypedDict with `default: NotRequired[str | int | bool]` and `on_omit: NotRequired[str]`, emitted only when set. `read_temperature` appears under `densitometer` with `kind:"measure"`, `result_field:"temperature_c"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_experiment_catalog.py`:

```python
def test_catalog_declares_param_defaults():
    cat = verb_catalog()
    dispense = {p["name"]: p for p in cat["pump"]["dispense"]["params"]}
    assert dispense["direction"]["default"] == "forward"
    rotate = {p["name"]: p for p in cat["pump"]["rotate"]["params"]}
    assert rotate["direction"]["default"] == "forward"
    thermo = {p["name"]: p for p in cat["densitometer"]["set_thermostat"]["params"]}
    assert thermo["enabled"]["default"] is True
    meas = {p["name"]: p for p in cat["densitometer"]["measure"]["params"]}
    assert meas["include_raw"]["default"] is False


def test_catalog_declares_on_omit():
    cat = verb_catalog()
    setpos = {p["name"]: p for p in cat["valve"]["set_position"]["params"]}
    assert setpos["rotation"]["on_omit"] == "default"
    assert "default" not in setpos["rotation"]
    conf = {p["name"]: p for p in cat["valve"]["configure"]["params"]}
    assert conf["default_rotation"]["on_omit"] == "unchanged"
    assert conf["hold_torque"]["on_omit"] == "unchanged"


def test_catalog_omits_default_and_on_omit_when_absent():
    volume = {p["name"]: p for p in verb_catalog()["pump"]["dispense"]["params"]}["volume_ml"]
    assert "default" not in volume and "on_omit" not in volume


def test_catalog_exposes_read_temperature_measurement():
    dens = verb_catalog()["densitometer"]
    assert dens["read_temperature"]["kind"] == "measure"
    assert dens["read_temperature"]["result_field"] == "temperature_c"
    assert dens["read_temperature"]["params"] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_catalog.py -q -k "defaults or on_omit or read_temperature or omits_default"`
Expected: FAIL (KeyError on `default`/`on_omit`/`read_temperature`).

- [ ] **Step 3: Extend `ParamEntry` and the serializer**

In `catalog.py`:

```python
class ParamEntry(TypedDict):
    name: str
    type: str
    required: bool
    values: NotRequired[list[str]]
    default: NotRequired[str | int | bool]
    on_omit: NotRequired[str]
```

Replace the param-building comprehension in `verb_catalog()` with an explicit helper:

```python
def _param_entry(p: ParamSpec) -> ParamEntry:
    entry: ParamEntry = {"name": p.name, "type": p.kind, "required": p.required}
    if p.values is not None:
        entry["values"] = list(p.values)
    if p.default is not None:
        entry["default"] = p.default
    if p.on_omit is not None:
        entry["on_omit"] = p.on_omit
    return entry
```

and in the loop:

```python
            params=[_param_entry(p) for p in trait.params],
```

Add the import: `from lab_devices.experiment.registry import _REGISTRY, ParamSpec`.

- [ ] **Step 4: Run the catalog tests**

Run: `.venv/bin/python -m pytest tests/test_experiment_catalog.py -q`
Expected: PASS (existing exact-dict test on `volume_ml` still passes — it has no default).

- [ ] **Step 5: Gate + commit**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
git add src/lab_devices/experiment/catalog.py tests/test_experiment_catalog.py
git commit -m "feat(engine): serialize param default/on_omit + read_temperature in /catalog

verb_catalog() now emits default/on_omit (only when set) and the new
densitometer read_temperature measure verb.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 4: Engine — end-to-end `read_temperature` measurement (execute + occupancy)

**Files:**
- Test: `tests/test_experiment_read_temperature.py` (new)

**Interfaces:**
- Consumes: the `read_temperature` trait + device method; the existing `_run_measure` extraction path.

This task proves the immediate measurement records into a stream and does not conflict with an open thermostat mode. Model the harness on the existing measure/occupancy tests — find one with `rg -l "measure_recorded|_run_measure|Occupancy\(" tests` and copy its fixture setup (RunContext/clock/fake device) rather than inventing one.

- [ ] **Step 1: Locate the measure-execution test harness**

Run: `rg -l "measure_recorded|role_type|RunContext" tests | head`
Read the closest match (e.g. `tests/test_experiment_execute*.py`) to reuse its workflow-builder + fake-device fixtures.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_experiment_read_temperature.py` with two tests, using the harness idioms discovered in Step 1:

1. `test_read_temperature_records_temperature_into_stream`: a workflow with a densitometer role, a declared temperature stream, and a single `measure` block `{verb: "read_temperature", into: "<temp stream>"}`; assert the run records the fake device's `status.temperature_c` into that stream (assert on `measure_recorded` event value or the recorded sample).
2. `test_read_temperature_runs_while_thermostat_open`: open a thermostat mode (`set_thermostat` enabled=True) then run `read_temperature` in the same run; assert it completes without `InvariantViolationError` (channelless read never conflicts).

Use the fake device's `status` response `{"state": "idle", "temperature_c": 36.98}`.

- [ ] **Step 3: Run to verify they fail (before wiring the fake's status), then make them pass**

Because the trait + device method already exist (Tasks 1–2), these tests may pass immediately once the fake returns a `status` with `temperature_c`. If a harness gap makes them fail, fix the test fixture (not engine code) until green. If they surface a real engine gap (e.g. an assumption that `measurement ⇒ job`), stop and reassess — the spec claims none exists.

Run: `.venv/bin/python -m pytest tests/test_experiment_read_temperature.py -q`
Expected: PASS.

- [ ] **Step 4: Gate + commit**

```bash
.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .
git add tests/test_experiment_read_temperature.py
git commit -m "test(engine): read_temperature records into a stream and coexists with thermostat

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 5: Backend — `/catalog` reflects the new fields + verb

**Files:**
- Test: `webapp/backend/tests/test_catalog.py`

**Interfaces:**
- Consumes: `GET /catalog` (unchanged backend code; serves `verb_catalog()` verbatim).

- [ ] **Step 1: Read the existing backend catalog test**

Run: `cat webapp/backend/tests/test_catalog.py` — see what shape it asserts, and whether any exact-equality assertion will break from the added fields.

- [ ] **Step 2: Add/adjust assertions**

Add a test that the served payload includes the new densitometer verb and a param default:

```python
def test_catalog_exposes_read_temperature_and_defaults(client):
    body = client.get("/catalog").json()
    dens = body["device_types"]["densitometer"]
    assert dens["read_temperature"]["result_field"] == "temperature_c"
    direction = {p["name"]: p for p in body["device_types"]["pump"]["dispense"]["params"]}
    assert direction["direction"]["default"] == "forward"
```

Match the existing test's client fixture name and response-shape (`device_types` vs top-level) — adjust the keys above to whatever the existing tests use. Fix any exact-equality assertion the new fields break.

- [ ] **Step 3: Run + gate + commit**

```bash
cd webapp/backend && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m mypy && ../../.venv/bin/python -m ruff check . && cd ../..
git add webapp/backend/tests/test_catalog.py
git commit -m "test(backend): /catalog exposes read_temperature + param defaults

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 6: Frontend — catalog types + `paramDefaults` pure helper

**Files:**
- Modify: `webapp/frontend/src/types/catalog.ts`
- Create: `webapp/frontend/src/builder/paramDefaults.ts`
- Test: `webapp/frontend/src/builder/paramDefaults.test.ts` (new)

**Interfaces:**
- Produces:
  - `ParamSpec` gains `default?: string | number | boolean` and `on_omit?: 'default' | 'unchanged'`.
  - `seedParams(specs: ParamSpec[]): Record<string, ParamValue>` — the params to pre-fill a new node with (every spec whose `default` is set).
  - `emptyOptionLabel(spec: ParamSpec): string | null` — the label for the empty enum/bool option, or `null` when it must be omitted (`default` present or `required`).

- [ ] **Step 1: Extend the catalog type**

In `types/catalog.ts`, add to `ParamSpec`:

```ts
export interface ParamSpec {
  name: string
  type: ParamKind
  required: boolean
  // Present when the param is a closed enum: the device accepts exactly these spellings.
  values?: string[]
  // UI-seed hints (webapp design): the Builder seeds `default` and labels the empty option
  // from `on_omit`. Absent when the param has no canonical default / no special omit meaning.
  default?: string | number | boolean
  on_omit?: 'default' | 'unchanged'
}
```

- [ ] **Step 2: Write the failing helper test**

Create `webapp/frontend/src/builder/paramDefaults.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { seedParams, emptyOptionLabel } from './paramDefaults'
import type { ParamSpec } from '../types/catalog'

const p = (o: Partial<ParamSpec> & { name: string }): ParamSpec => ({
  type: 'string', required: false, ...o,
})

describe('seedParams', () => {
  it('pre-fills only params that declare a default', () => {
    expect(
      seedParams([
        p({ name: 'direction', values: ['forward', 'reverse'], default: 'forward' }),
        p({ name: 'enabled', type: 'bool', required: true, default: false }),
        p({ name: 'volume_ml', type: 'number', required: true }),
        p({ name: 'rotation', values: ['shortest'], on_omit: 'default' }),
      ]),
    ).toEqual({ direction: 'forward', enabled: false })
  })
})

describe('emptyOptionLabel', () => {
  it('omits the empty option when a default is present', () => {
    expect(emptyOptionLabel(p({ name: 'direction', default: 'forward' }))).toBeNull()
  })
  it('omits the empty option for a required param', () => {
    expect(emptyOptionLabel(p({ name: 'enabled', type: 'bool', required: true }))).toBeNull()
  })
  it('labels a deferring optional param', () => {
    expect(emptyOptionLabel(p({ name: 'rotation', on_omit: 'default' }))).toBe('— device default —')
  })
  it('labels a leave-unchanged optional param', () => {
    expect(emptyOptionLabel(p({ name: 'hold_torque', type: 'bool', on_omit: 'unchanged' }))).toBe(
      '— leave unchanged —',
    )
  })
  it('falls back to unset for a plain optional param', () => {
    expect(emptyOptionLabel(p({ name: 'x' }))).toBe('— unset —')
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run (cwd `webapp/frontend`): `npm test -- paramDefaults`
Expected: FAIL — cannot resolve `./paramDefaults`.

- [ ] **Step 4: Implement the helper**

Create `webapp/frontend/src/builder/paramDefaults.ts`:

```ts
import type { ParamSpec } from '../types/catalog'
import type { ParamValue } from '../types/doc'

/** Params to pre-fill a freshly-created device-command/measure node with: every spec that
 * declares a `default`. Seeding at creation (not on load) keeps the authored doc explicit
 * while leaving legacy omitted params byte-stable. */
export function seedParams(specs: ParamSpec[]): Record<string, ParamValue> {
  const out: Record<string, ParamValue> = {}
  for (const s of specs) if (s.default !== undefined) out[s.name] = s.default
  return out
}

/** The empty ("omit this param") option's label for an enum/bool select, or null when the
 * option must not be shown. Hidden when the param has a canonical `default` or is `required`
 * (omission is pointless or invalid); otherwise labelled from `on_omit`. */
export function emptyOptionLabel(spec: ParamSpec): string | null {
  if (spec.default !== undefined || spec.required) return null
  if (spec.on_omit === 'default') return '— device default —'
  if (spec.on_omit === 'unchanged') return '— leave unchanged —'
  return '— unset —'
}
```

- [ ] **Step 5: Run to verify pass**

Run (cwd `webapp/frontend`): `npm test -- paramDefaults`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/types/catalog.ts webapp/frontend/src/builder/paramDefaults.ts webapp/frontend/src/builder/paramDefaults.test.ts
git commit -m "feat(studio): param default/on_omit catalog types + seed/label helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 7: Frontend — `newVerbNode` seeds defaults

**Files:**
- Modify: `webapp/frontend/src/builder/tree.ts:415-419`
- Test: `webapp/frontend/src/builder/tree.test.ts`

**Interfaces:**
- Consumes: `seedParams` (Task 6).

- [ ] **Step 1: Write the failing test**

Add to `tree.test.ts` (inside the `newPaletteNode seeds` describe or a new one):

```ts
it('newVerbNode seeds params that declare a default', () => {
  const node = newVerbNode('feed_pump', 'dispense', {
    kind: 'command',
    params: [
      { name: 'volume_ml', type: 'number', required: true },
      { name: 'direction', type: 'string', required: false, values: ['forward', 'reverse'], default: 'forward' },
    ],
    result_field: null,
    retry_safe: false,
  } as VerbSpec)
  expect(node.kind === 'command' && node.params).toEqual({ direction: 'forward' })
})
```

- [ ] **Step 2: Run to verify it fails**

Run (cwd `webapp/frontend`): `npm test -- tree`
Expected: FAIL — `params` is `{}`.

- [ ] **Step 3: Wire `seedParams` into `newVerbNode`**

In `tree.ts`, import and use it:

```ts
import { seedParams } from './paramDefaults'
...
export function newVerbNode(role: string, verb: string, spec: VerbSpec): BlockNode {
  const params = seedParams(spec.params)
  return spec.kind === 'measure'
    ? { ...nodeBase(), kind: 'measure', device: role, verb, into: '', params }
    : { ...nodeBase(), kind: 'command', device: role, verb, params }
}
```

- [ ] **Step 4: Run to verify pass**

Run (cwd `webapp/frontend`): `npm test -- tree`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/tree.ts webapp/frontend/src/builder/tree.test.ts
git commit -m "feat(studio): seed device-command defaults into new Builder nodes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 8: Frontend — Inspector `ParamInput` renders defaults + labeled empty option

**Files:**
- Modify: `webapp/frontend/src/builder/Inspector.tsx:887-947` (`ParamInput`)

**Interfaces:**
- Consumes: `emptyOptionLabel` (Task 6). No new exported interface (DOM wiring; verified via `npm run build` + capture, per the node-env testing rule).

- [ ] **Step 1: Import the helper**

Add near the other builder imports in `Inspector.tsx`:

```ts
import { emptyOptionLabel } from './paramDefaults'
```

- [ ] **Step 2: String-enum branch — seed default, conditional labeled empty option**

Replace the string-enum `<select>` block (currently `Inspector.tsx:897-912`) with:

```tsx
      const dflt = typeof spec.default === 'string' ? spec.default : ''
      const current = typeof value === 'string' ? value : dflt
      const empty = emptyOptionLabel(spec)
      return (
        <select
          value={current}
          onChange={(e) => onCommit(e.target.value === '' ? undefined : e.target.value)}
          className={controlClass()}
        >
          {empty !== null && <option value="">{empty}</option>}
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
```

- [ ] **Step 3: Bool branch — seed default, conditional labeled empty option**

Replace the bool select (currently `Inspector.tsx:923-938`) so the current value falls back to the default and the empty option is conditional:

```tsx
  if (spec.type === 'bool' && !exprMode && typeof value !== 'string') {
    const dfltBool = typeof spec.default === 'boolean' ? (spec.default ? 'true' : 'false') : ''
    const current = value === true ? 'true' : value === false ? 'false' : dfltBool
    const empty = emptyOptionLabel(spec)
    return (
      <div className="flex items-center gap-1">
        <select
          value={current}
          onChange={(e) => {
            const v = e.target.value
            onCommit(v === '' ? undefined : v === 'true')
          }}
          className={controlClass()}
        >
          {empty !== null && <option value="">{empty}</option>}
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        <IconButton
          icon={SquareFunction}
          label="Use an expression"
          onClick={() => setExprMode(true)}
          className="border border-slate-300"
        />
      </div>
    )
  }
```

- [ ] **Step 4: Typecheck + build + full frontend suite**

Run (cwd `webapp/frontend`): `npm run build && npm test`
Expected: build succeeds; all tests pass (existing `torture`/`summary`/`tree` suites still green — the out-of-set escape option is preserved).

- [ ] **Step 5: Commit**

```bash
git add webapp/frontend/src/builder/Inspector.tsx
git commit -m "feat(studio): Builder dropdowns seed defaults, drop meaningless empty option

Enum/bool device-command params seed their catalog default and hide the empty
option when a default exists or the param is required; deferring params keep a
meaningfully-labeled option (device default / leave unchanged) instead of the
blanket '— unset —'.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 9: Frontend — Devices tab "Read temperature" control

**Files:**
- Modify: `webapp/frontend/src/devices/catalog.ts` (densitometer list)
- Modify: `webapp/frontend/src/devices/CommandPanel.tsx:79` (React key)
- Test: `webapp/frontend/src/devices/catalog.test.ts`

**Interfaces:**
- Produces: a densitometer `CommandDef` `{ cmd: 'status', label: 'Read temperature', category: 'measure', isJob: false, params: [] }` (a deliberate convenience alias of the `status` cmd). CommandPanel buttons key on the unique `label`; the catalog integrity test enforces unique labels within a device type (cmd may alias).

- [ ] **Step 1: Update the duplicate test to labels + add a read-temperature assertion**

In `catalog.test.ts`, replace the `no duplicate command names within a device type` test:

```ts
  it('no duplicate labels within a device type', () => {
    for (const cmds of Object.values(CATALOG)) {
      const labels = cmds.map((c) => c.label)
      expect(new Set(labels).size).toBe(labels.length)
    }
  })

  it('densitometer exposes a Read temperature control backed by status', () => {
    const temp = CATALOG.densitometer.find((c) => c.label === 'Read temperature')
    expect(temp).toBeDefined()
    expect(temp?.cmd).toBe('status')
    expect(temp?.category).toBe('measure')
  })
```

- [ ] **Step 2: Run to verify the new assertion fails**

Run (cwd `webapp/frontend`): `npm test -- devices/catalog`
Expected: FAIL — no `Read temperature` command yet.

- [ ] **Step 3: Add the command**

In `devices/catalog.ts`, add to the `densitometer` array (measure category, near `measure`):

```ts
    { cmd: 'status', label: 'Read temperature', category: 'measure', isJob: false, params: [] },
```

- [ ] **Step 4: Key CommandPanel buttons by label (cmd may now alias)**

In `CommandPanel.tsx`, change the button key at line 79 from `key={cmd.cmd}` to:

```tsx
                  key={cmd.label}
```

(`picked`/`run`/`active` keep using `cmd.cmd`, correct: both status buttons run `status`; neither takes params so `picked` is never set to an ambiguous value.)

- [ ] **Step 5: Run + build**

Run (cwd `webapp/frontend`): `npm test -- devices && npm run build`
Expected: PASS + build OK.

- [ ] **Step 6: Commit**

```bash
git add webapp/frontend/src/devices/catalog.ts webapp/frontend/src/devices/CommandPanel.tsx webapp/frontend/src/devices/catalog.test.ts
git commit -m "feat(studio): Devices tab 'Read temperature' control (status-backed)

Dedicated measure-category control that reads temperature via the status cmd
(no optics). CommandPanel keys buttons by label so a convenience cmd-alias is
allowed; integrity test now enforces unique labels within a device type.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01KPs8vJbrWADNuLg6LHCXD5"
```

---

### Task 10: Full gate sweep + visual capture + finalize

**Files:** none (verification only).

- [ ] **Step 1: Engine gates**

Run: `.venv/bin/python -m pytest -q && .venv/bin/python -m mypy && .venv/bin/python -m ruff check .`
Expected: all pass.

- [ ] **Step 2: Backend gates**

Run: `cd webapp/backend && ../../.venv/bin/python -m pytest -q && ../../.venv/bin/python -m mypy && ../../.venv/bin/python -m ruff check . && cd ../..`
Expected: all pass.

- [ ] **Step 3: Frontend gates**

Run: `cd webapp/frontend && npm run lint && npm test && npm run build && cd ../..`
Expected: lint clean (no new warnings), tests pass, build OK.

- [ ] **Step 4: Visual capture (best-effort, non-CI)**

Run the capture harness against a doc exercising a densitometer measure + a pump/valve command, and confirm the enum/bool dropdowns render without the stray empty option and pass the probe's contrast/height rules. If capture requires both servers and is impractical here, note it as manually deferred (it is not a CI gate).

- [ ] **Step 5: Push + open PR** (handled outside the plan by the PR/CI/merge flow).

## Notes on risk (from the spec)

- Additive `/catalog` fields can break exact-equality snapshots — the only exact-dict engine assertion is on `volume_ml` (no default), which stays 3-key. Backend exact assertions handled in Task 5.
- `frozenset()` channels: `Occupancy.acquire`/`release` iterate the set (no-op on empty); `mode_action`/`finalize` key off `state_effect`/teardown, not channel non-emptiness. Task 4 proves coexistence with an open thermostat mode.
- Round-trip byte-stability: defaults seed only at node creation (Task 7), never on load; `ParamInput` displays a default for a legacy omitted param without rewriting the doc.
