# Studio role fixes — enum defaults + independent temperature read

**Date:** 2026-07-22
**Status:** approved (brainstorm), ready for implementation
**Scope:** engine (`src/lab_devices`) → public catalog → webapp backend `/catalog` → Studio
frontend (Builder + Devices tabs)

## Problem

Two device-role issues in Experiment Studio, each spanning every layer:

1. **Meaningless `— unset —` on device-command dropdowns.** The Builder's Inspector prepends a
   leading empty `— unset —` option to *every* enum and bool device-command dropdown
   (`webapp/frontend/src/builder/Inspector.tsx:903` for enums, `:935` for bools). It does this
   because the engine-served `/catalog` carries `required`/`values` but **no default**, and the
   Inspector ignores even the `required` flag it does receive. Result: pump `direction`, valve
   `rotation`, densitometer `set_thermostat.enabled`, etc. all default to a meaningless "unset",
   and two of them (`pump.rotate.direction`, `set_thermostat.enabled`) are actually **required**,
   so "unset" is an invalid selection the UI should never offer. There is **no literal `"unset"`
   enum value** anywhere in the engine — the enums are `("forward","reverse")` and
   `("shortest","direct","wrap")`. The Devices tab already solved this locally: its
   frontend-owned catalog (`webapp/frontend/src/devices/catalog.ts`) carries per-param
   `default`/`required`, and `ParamForm` seeds defaults and only shows the empty option when a
   param is optional.

2. **OD and temperature are coupled.** The densitometer's optics `measure` job returns both
   `absorbance` (OD) and `temperature_c`, but the DSL `Measure` block extracts exactly one
   `result_field` (`"absorbance"`) and discards temperature (`registry.py:138-146`,
   `execute.py:661-683`). There is no temperature-read verb at all, so a workflow cannot record
   temperature without also running the optics — and cannot record temperature independently.
   **Key hardware fact:** the densitometer's `status` command returns `temperature_c` *without
   running the optics/LED* (`docs/lab-bridge-api-reference.md` §3.8), and the registry already
   comments that "optics (LED/measure path) and thermal are independent subsystems". So a
   genuinely independent temperature read is available cheaply.

Not every "unset" is meaningless. The code has three distinct cases the fix must respect:

- **Required** (`pump.rotate.direction`, `densitometer.set_thermostat.enabled`): omitting is
  *invalid* — must seed a default and never show an empty option.
- **Optional with a natural default** (`pump.dispense.direction` — the engine method already
  defaults to `"forward"`; `densitometer.measure.include_raw` — omit ≡ false on the wire): seed
  the default; the empty option is pointless.
- **Optional where omission is meaningful** (`valve.set_position.rotation` = "use the valve's
  configured `default_rotation`"; `valve.configure.default_rotation` / `.hold_torque` =
  "leave that field unchanged" — a partial config write): keep the choice, but give the empty
  option an honest label instead of the blanket `— unset —`.

## Design

### Issue 1 — engine-declared param defaults + meaning-aware empty option

The default and the omission-semantics are **hardware facts** and belong in the engine registry
alongside the existing `required`/`values`, per "cover all layers from engine up".

**Engine — `src/lab_devices/experiment/registry.py`.** `ParamSpec` gains two optional fields:

```python
@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: Kind
    required: bool = False
    values: tuple[str, ...] | None = None
    default: str | int | bool | None = None       # UI seed value; None = no canonical default
    on_omit: Literal["default", "unchanged"] | None = None
    # What omitting the param MEANS on the wire (a documented hardware behavior):
    #   "default"   -> device applies its own configured/implicit default (e.g. valve rotation)
    #   "unchanged" -> field left unchanged (partial config write, e.g. valve.configure)
    #   None        -> omission carries no special meaning
```

`default` and `on_omit` are **UI-facing hints only** — they do not change engine
validation or execution. The engine already applies its own method-level defaults
(`pump.dispense(direction="forward")`) and rejects omitted required params at validation; these
fields just tell the Builder what to seed and how to label the empty option.

Populate them:

| verb.param | kind | required | `default` | `on_omit` |
|---|---|---|---|---|
| `pump.dispense` direction | string enum | no | `"forward"` | — |
| `pump.rotate` direction | string enum | **yes** | `"forward"` | — |
| `densitometer.set_thermostat` enabled | bool | **yes** | `True` | — |
| `densitometer.measure` include_raw | bool | no | `False` | — |
| `valve.set_position` rotation | string enum | no | — | `"default"` |
| `valve.configure` default_rotation | string enum | no | — | `"unchanged"` |
| `valve.configure` hold_torque | bool | no | — | `"unchanged"` |

(All other params are numeric/int or required-with-no-canonical-value and are untouched:
numbers are text inputs with no empty-enum problem.)

**Serialization — `src/lab_devices/experiment/catalog.py`.** `ParamEntry` (TypedDict) gains
`default: NotRequired[...]` and `on_omit: NotRequired[str]`; `verb_catalog()` emits each only
when set (keep the payload minimal so params without them are unchanged). Served verbatim at
`GET /catalog` (`webapp/backend/experiment_studio/api/catalog.py`, no change).

**Frontend contract — `webapp/frontend/src/types/catalog.ts`.** `ParamSpec` gains optional
`default?: string | number | boolean` and `onOmit?: 'default' | 'unchanged'` (mapped from the
snake_case wire field in the fetch layer, or read directly — match the existing convention in
`stores/catalogStore.ts`).

**Builder — `webapp/frontend/src/builder/Inspector.tsx` (`ParamInput`) + `tree.ts`
(`newVerbNode`).** New rule for enum and bool params:

- **Has `default`, or is `required`** → render the select with **no empty option**; the effective
  value is `node.params[name] ?? default` (fall back to the first enum value if a required param
  somehow lacks a default). New nodes seed the default into `params` at creation
  (`newVerbNode` pre-fills every param that has a `default`), so authored workflows carry the
  concrete value.
- **Optional and no `default`** → render the select **with** an empty option, labeled from
  `onOmit`: `"— device default —"` for `"default"`, `"— leave unchanged —"` for `"unchanged"`,
  and a plain `"— unset —"` fallback if `onOmit` is absent. The empty option stays pre-selected
  (value omitted).
- The out-of-set escape option (`Inspector.tsx:909-911`, for the torture fixture's deliberately
  invalid spellings) is **preserved** in both branches.

**Round-trip safety.** Defaults are seeded only at **node creation**. For a legacy/loaded block
that omits a param with a `default`, the select displays the default as selected (truthful — the
engine applies the same default) but the doc is **not** rewritten unless the author actively
changes the field. Loading and re-saving an example that omits `direction` yields byte-identical
output.

**Devices tab — `webapp/frontend/src/devices/catalog.ts`.** Already carries `default`/`required`
and already seeds correctly (pump direction seeds `"forward"`, no empty option). Align the
valve-rotation empty-option presentation for consistency (its `ParamForm` shows a bare `—` for
optional params; leave the mechanism, values stay as the hardware documents). No behavioral
regression.

### Issue 2 — new `read_temperature` verb (independent, no optics)

**Engine registry — new trait:**

```python
("densitometer", "read_temperature"): Trait(
    "immediate",           # status is a fast read, not a job
    "none",
    channels=frozenset(),  # a pure status read occupies NO subsystem — see invariant change
    measurement=True,
    result_field="temperature_c",
    retry_safe=True,       # idempotent pure read
),
```

**Engine device — `src/lab_devices/devices/densitometer.py`.** Add:

```python
async def read_temperature(self) -> DensitometerStatus:
    """Independent temperature read: polls `status` (no optics/LED). See spec §3.8."""
    return DensitometerStatus.from_raw(await self.command("status"))
```

The verb→method dispatch is `getattr(device, verb)(**params)` (`execute.py:174-176`), so the
method name must be `read_temperature`. `_run_measure` extracts `result.temperature_c` from the
returned `DensitometerStatus` (`execute.py:661-683`) — works for an immediate command because
`_dispatch_action` returns the raw result when `completion != "job"`. A missing `temperature_c`
(sensorless device) surfaces the existing "measure result field missing or non-numeric" error,
identical to how a missing absorbance behaves.

**Builder.** No code change: `verb_catalog()` emits `read_temperature` as a `kind:"measure"`
verb; the Inspector already lists every measure verb and gives each its own `into` stream. The
author declares a temperature stream (e.g. `"temp_1": { "units": "degC" }`) and routes
`read_temperature` into it. `measure` stays OD-only — decoupling means each reads independently.

**Devices tab — dedicated control (per user request).** Add a densitometer `CommandDef` to
`webapp/frontend/src/devices/catalog.ts` that reads temperature. The hub has no
`read_temperature` command, so it maps to the hardware `status` cmd:
`{ cmd: 'status', label: 'Read temperature', category: 'measure', isJob: false, params: [] }`.
This is a deliberate, user-requested convenience redundant with the info-category "Status"
button; it surfaces the temperature read as a first-class measure affordance.

### Two deliberate invariant changes (documented)

1. **A pure read may declare no channels.** `read_temperature` uses `channels=frozenset()`.
   `Occupancy.acquire`/`release` iterate over the channel set, so empty is a clean no-op
   (`occupancy.py:65-88`, verified) — the read never conflicts and, importantly, can run **while
   the thermostat mode is open on `_THERMAL`** (monitoring temperature during regulation is the
   whole point). Giving it `_THERMAL` would wrongly conflict with `set_thermostat`; giving it
   `_OPTICS` would wrongly conflict with `measure`. Update
   `tests/test_experiment_registry.py::test_every_entry_declares_channels` to reflect the real
   invariant: **every *actuating* entry declares a channel; a pure read may occupy none.** Add a
   `test_channel_table` assertion `read_temperature.channels == frozenset()`.

2. **A measurement need not be a job.** `test_experiment_registry.py::test_measurement_flags`
   asserts every `measurement` verb has `completion == "job"`. `read_temperature` is
   `completion == "immediate"`. The executor already supports immediate measurements
   mechanically; update the test to include `read_temperature` in the measuring set and to drop
   the "all measuring verbs are jobs" assertion (or scope it to the job-based ones).

### Non-changes / out of scope

- **No `schema_version` bump.** Workflow document shape is unchanged: `read_temperature` is just a
  new verb string in a `measure` block, and `default`/`on_omit` live only in the catalog, never
  in a saved workflow.
- **`measure` stays OD-only.** No multi-output measure block.
- **The typed group-parameter bool editor** (`Inspector.tsx:456`, `ParamValueInput`) is for
  *author-defined* workflow parameters, not device roles — its `— unset —` is legitimately
  meaningful and is left as-is.
- The two frontend catalogs (engine-served `/catalog` for the Builder;
  hand-maintained `devices/catalog.ts` for the Devices tab) stay separate — unifying them is a
  larger refactor unrelated to this work.

## Testing

**Engine (`poetry run pytest` / `mypy` / `ruff check .`):**
- `test_experiment_registry.py`: channel-table + measurement-flags invariant updates (above);
  `ParamSpec` equality spot-checks that now carry a `default` (`rotate.direction`,
  `set_thermostat.enabled`) updated; add `read_temperature` trait assertions.
- `test_experiment_catalog.py`: `verb_catalog()` now emits `default`/`on_omit` and the new verb.
- New: `_run_measure` extracts `temperature_c` from a `read_temperature` (immediate) dispatch;
  a temperature `measure` block validates and records into its stream; `read_temperature` runs
  with a thermostat mode open (no occupancy conflict).
- `test_densitometer.py`: `read_temperature()` issues `status` and parses `temperature_c`.
- `validate.py`: `read_temperature` accepted as a measurement verb (generic — no code change
  expected; add a test).

**Webapp backend (`python -m pytest -q` / `mypy` / `ruff`):**
- `webapp/backend/tests/test_catalog.py`: `/catalog` shape now includes `default`/`on_omit` and
  the new densitometer verb.

**Frontend (`npm run lint` / `npm test` / `npm run build`):**
- `builder/tree.test.ts`: `newVerbNode` seeds defaults.
- New Inspector-logic unit coverage (pure functions per frontend testing rules): the
  empty-option decision (`hasDefault || required` ⇒ no empty; else labeled empty from `onOmit`)
  and the effective-value fallback. Factor the decision into a small pure helper so it is
  vitest-testable without rendering.
- `devices/catalog.test.ts` / `buildPayload.test.ts`: the new "Read temperature" command.
- `builder/__tests__/torture.test.ts`: out-of-set enum spellings still render the escape option.
- Adding a field to `/catalog` will break any exact-equality catalog assertions (the known
  "response-add breaks equality tests" pattern) — update them.

**Visual (non-CI, best-effort):** `npm run capture` after the Inspector change to confirm the
enum/bool dropdowns render without the stray empty option and pass the probe's contrast/height
rules.

## Risks

- **Exact-equality catalog snapshots** across engine, backend, and frontend break when `/catalog`
  gains fields — enumerated above; all are additive and updated in lockstep.
- **`frozenset()` channels** — audit the executor/finalizer for any code assuming non-empty
  channels beyond the one invariant test (none found: `acquire`/`release`/`mode_action`/
  `finalize` all iterate channels or key off `state_effect`/teardown).
- **Round-trip byte-equality** for examples that omit defaulted params — mitigated by seeding
  only at node creation, never on load (above).

## Rollout

Single PR (`feat(studio): role fixes — enum defaults + independent temperature read`), consistent
with prior bundled behavior-fix PRs (e.g. #72). Both issues share the `registry.py`/`catalog.py`
plumbing, so splitting them would only create conflicts.
