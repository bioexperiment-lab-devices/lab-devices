# Experiment Studio — Manual device control tab ("Devices")

**Status:** design, user-settled 2026-07-21
**Target:** `experiment-studio` (webapp), `main` @ `dddf32a`
**Predecessors:** `2026-07-18-lab-independent-builder-design.md` (Builder-first tabs, the
lab-scoping model in `shell/tabs.ts`), the read-only Devices tab (`devices/DevicesTab.tsx`).

---

## 1. Problem

The Studio has no way to touch a device by hand. An operator preparing a run needs to:

- prime lines, home a valve, take a blank/measurement, ping a device — **manual prep and
  checks before an experiment runs**;
- work out **which physical unit is `pump_1` vs `pump_2`** and give each a meaningful name.

Today the **Devices** tab is deliberately read-only — its own header comment says "Device
control belongs to experiments, not this tab." That stance is right for an experiment-authoring
tool but leaves the bench-prep and device-identification workflows unserved. This increment adds
a manual-control surface and a naming layer, and reverses that stance *for manual use only*.

The library already exposes the full command surface per device type (`lab_devices.devices.*`);
what is missing is (a) a backend endpoint to run an arbitrary device command, (b) somewhere to
store operator-chosen names, and (c) the UI.

## 2. Settled decisions

Two rounds of design forks, all settled by the user:

| # | Decision |
|---|----------|
| Tab placement | **New tab**, and **rename** the current read-only `Devices` → `Labs` (it is the lab picker + roster). The new manual-control tab takes the name `Devices`. |
| Safety | **Block manual commands while a run is active** on the lab (mirror the discover 409 guard) + an **always-visible Stop**. **No per-command confirmation** — every command, including calibration writes, fires on click. |
| Naming | **Server-side, propagated everywhere** — persisted in the backend DB, surfaced in the new tab, the Labs roster, and Run's role-mapping dropdown. |
| Command scope | **Full library surface** per device type (incl. calibration/config writes). |
| Long ops | **Fire + poll**: the backend starts a job and returns a job id; the UI polls a job-status endpoint until terminal and can cancel via Stop. |
| Measurements | **Inline readout + ephemeral session log**; nothing persisted to the DB, cleared on refresh. |

Explicitly **out of scope** (YAGNI): per-command confirmation dialogs; DB-persisted manual
measurements; live charts; a backend command allowlist; websocket streaming for manual jobs.

## 3. Tabs & placement

- `shell/tabs.ts`: `TABS = ['Builder', 'Labs', 'Devices', 'Run', 'Records']`.
- The current `devices/DevicesTab.tsx` (read-only picker/roster) becomes **`labs/LabsTab.tsx`**
  (component `LabsTab`), and gains a **Name** column in its device table.
- The new manual-control tab is **`devices/DevicesTab.tsx`** (component `DevicesTab`), plus its
  supporting modules (§4–§7).
- `LAB_SCOPED` record: `Labs=false`, `Devices=false`, `Run=true` (unchanged). Both `Labs` and
  the new `Devices` carry an inline lab switcher in their own header, so per the module's
  documented test — *"does the header pill tell the user something the tab body does not?"* — the
  pill would be redundant. This is the same reasoning that already keeps the picker `false`; do
  not "fix" it to `true`.
- `shell/TabShell.tsx` maps `Labs → <LabsTab/>` and `Devices → <DevicesTab/>`.
- URL/nav state (`stores/navStore.ts`, `shell/urlState.ts` and friends): the tab id string
  changes from `Devices`→`Labs` for the picker and introduces a new `Devices`. Audit every place
  that hard-codes the `'Devices'` tab string (e.g. `PreflightPanel`'s "Go to Devices" button must
  become "Go to Labs") so a persisted hash of the old shape degrades gracefully.

## 4. Layout & interaction

Device-type-first navigation. The command controls are **common per device type**; the operator
picks a target device from the list, then a command.

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Lab: [chisel ▾] ● online     [⟳ Refresh]      ⚠ run active — control locked │  ← shared global selected lab
├──────────────┬────────────────────────────────────────────────────────────┤
│ TYPE NAV     │  Pumps in chisel                                            │
│ ───────      │   ○ pump_1  [ Culture pump   ✎ ]  connected   [Locate]      │  ← radio = command target
│ ▸ Pumps  (2) │   ● pump_2  [ Waste pump     ✎ ]  connected   [Locate]      │     inline name edit
│   Valves (1) │                                                             │
│   Densi… (1) │  Commands — pump_2 · Waste pump              [ ■ Stop ]      │  ← shared per-type panel
│              │   Info:       ping   identify   status                       │
│              │   Measure:    get_calibration                                │
│              │   Actuate:    dispense   rotate   rotate_raw  pause  resume   │
│              │   Cal/Config: start_calibration  set_calibration             │
│              │                                                             │
│              │   ▸ dispense    volume_ml [10]  speed_ml_min [3.0]           │  ← param form for picked cmd
│              │      direction [forward ▾]                       [ Run ▶ ]   │
│              │                                                             │
│              │  Activity                                                    │  ← ephemeral session log
│              │   10:02:11  dispense → job 3f… running 40%                   │
│              │   10:01:50  ping → uptime 42.1 s                             │
└──────────────┴────────────────────────────────────────────────────────────┘
```

- **Header bar**: compact lab switcher bound to the single global selected lab
  (`labsStore.selected`), an online dot, Refresh, and — when a run is active on the lab — a
  "control locked" banner that disables the panel (§6).
- **Type nav (left)**: the device types **present in the roster**, grouped from `device.type`,
  with counts. Selecting a type shows its devices.
- **Device list**: one row per device of the selected type — radio to select the command target,
  the id, an inline editable **name**, connection state, and a per-row **Locate** quick action.
- **Command panel (shared for the type)**: commands grouped by category (Info / Measure /
  Actuate / Cal-Config). A command with no params runs on click; a command with params reveals an
  inline param form + **Run**. An always-present **Stop** targets the selected device.
- **Activity**: an ephemeral, session-scoped log of `command → result / error`, newest first,
  with in-flight job progress. Cleared on refresh.

**Locate** is the device-identification aid: a bounded, visibly-actuating command per type so the
operator can see which physical unit responds before naming it —
pump: a tiny `dispense` (e.g. 0.2 ml); valve: `set_position` to the next slot; densitometer:
`measure` (its LED visibly cycles). Modeled as an ordinary catalog command flagged `locate`, so it
reuses the same execution path.

## 5. Command catalog (frontend-owned)

`devices/catalog.ts` — a pure module, the analog of the Builder's block/param definitions
(`builder/paletteSections.ts`). It is **UI metadata only**; the backend forwards any `cmd`
generically (§6), so extending the catalog is a source-only edit.

```ts
type ParamKind = 'number' | 'int' | 'enum' | 'bool'
interface ParamDef {
  name: string            // wire name, e.g. 'volume_ml'
  label: string
  kind: ParamKind
  unit?: string           // 'ml', 'ml/min', '°C', 'steps'…
  default?: number | string | boolean
  min?: number; max?: number
  options?: string[]      // enum values, e.g. ['forward','reverse']
  required?: boolean      // omitted-if-undefined semantics mirror the library methods
}
interface CommandDef {
  cmd: string             // wire name passed straight to the device
  label: string
  category: 'info' | 'measure' | 'actuate' | 'cal-config'
  isJob: boolean          // job-returning → poll; else immediate result
  params: ParamDef[]
  locate?: { params: Record<string, unknown> }  // preset for the per-row Locate action
}
type DeviceType = 'pump' | 'valve' | 'densitometer'
const CATALOG: Record<DeviceType, CommandDef[]>
```

Coverage (from `src/lab_devices/devices/*.py`):

- **Universal (all types)**: `ping`, `identify`, `status` (info); `stop` is the Stop button, not a
  listed command.
- **pump**: `rotate` (direction, speed_ml_min), `rotate_raw` (direction, speed_pct), `dispense`
  (volume_ml, speed_ml_min?, direction, drop_suckback_ml?) — *job*, `pause`, `resume`,
  `start_calibration` (speed_pct?) — *job*, `set_calibration` (job_id?/measured_volume_ml?/
  ml_per_step?), `get_calibration`.
- **valve**: `home` (position), `set_position` (position, rotation?) — *job*, `configure`
  (default_rotation?, hold_torque?).
- **densitometer**: `measure_blank` — *job*, `measure` (include_raw?) — *job*, `start_monitoring`
  (interval_s?), `get_readings` (since_seq?, limit?), `stop_monitoring`, `set_thermostat`
  (enabled, target_c?), `set_tube_correction` (factor), `calibrate_tube` (reference_absorbance),
  `set_led` (level), `read_raw` (level?) — *job*.

`speed_profile` on `dispense` is out of scope for the manual UI (structured nested object; not a
prep control). Optional params render blank and are **omitted from the wire payload when empty**,
matching the library's `if x is not None` construction — the param→payload builder (`buildPayload`)
is a pure, unit-tested function (§9).

Forms are built from `ui/controls.ts` (`controlClass`, 24px height, `width` passed as an option —
never concatenated) and lucide icons only, per `webapp/frontend/CLAUDE.md`.

## 6. Backend API

All under the existing `/api/labs` prefix, in `api/labs.py`. The stateless per-request
`LabsService` pattern holds: jobs live on the lab agent, so each request opens a fresh
`LabClient`, does one thing, and closes it — nothing is held open between requests.

### 6.1 Run a command

`POST /api/labs/{lab}/devices/{device_id}/command`  body `{ "cmd": str, "params": object|null }`

1. Guard: if `RunManager.active()` is on `lab`, raise `RunActiveError` → 409 `run_active`
   (identical to the discover guard).
2. Look up the lab, open a `LabClient`, resolve the device handle
   (`client.device(device_id)`), and call `device.command(cmd, params)`.
3. Return `{ "result": <raw> }`. For immediate commands this is the value; for job-returning
   commands it is the job-start envelope (contains the `job_id`).

The backend does **not** distinguish job vs immediate — the frontend catalog's `isJob` flag
decides whether to poll. No command allowlist: an unknown `cmd` is rejected by the device
(`UnknownCommandError`) and surfaced as an error (§6.4).

### 6.2 Poll a job

`GET /api/labs/{lab}/devices/{device_id}/jobs/{job_id}`

Opens a client, calls `device.get_job(job_id)`, returns the serialized job (status, progress,
result, error). The frontend polls this (~1 s) for `isJob` commands until a terminal status.

### 6.3 Stop

Stop reuses `POST …/command` with `{ "cmd": "stop" }` (the universal device halt). It is a
distinct request, so it interrupts regardless of any poll in flight. It is subject to the same
run-active guard — during a run the whole manual surface is locked and the experiment owns abort.

### 6.4 Error surfacing

Command-time failures are `lab_devices.errors.LabError` subclasses. Today they fall through to the
`LabError` catch-all (502 `lab_error`), which is too coarse for an operator log. Extend `_ERROR_MAP`
in `app.py` so the common ones read meaningfully:

| Exception | HTTP | code |
|---|---|---|
| `InvalidParamsError`, `InvalidRequestError` | 422 | `invalid_params` |
| `UnknownCommandError` | 400 | `unknown_command` |
| `UnknownDeviceError` | 404 | `unknown_device` |
| `BusyError`, `JobInProgressError`* | 409 | `agent_busy` |
| `NotCalibratedError`, `NotHomedError` | 409 | `not_ready` |
| `DeviceUnreachableError` | 502 | `device_unreachable` |

(*`JobInProgressError` already maps to 409 `agent_busy`.) The `{detail, code}` body drives the
activity-log message. Ordering respects MRO (specific before the `LabError` catch-all), as the
existing map already documents.

## 7. Naming: persistence & propagation

### 7.1 Store & migration

New `experiment_studio/device_names.py` — `DeviceNamesStore(db)` with `get_all(lab) ->
dict[device_id, name]`, `set(lab, device_id, name)`, `clear(lab, device_id)`. Append one migration
to `db.py` `MIGRATIONS` (append-only; bumps `user_version`):

```sql
CREATE TABLE device_names (
    lab TEXT NOT NULL,
    device_id TEXT NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (lab, device_id)
)
```

Names key on `(lab, device_id)`. A device unplugged later leaves a harmless orphan row.

### 7.2 Endpoint

`PUT /api/labs/{lab}/devices/{device_id}/name`  body `{ "name": str }`. An empty/whitespace name
clears the row. Returns the stored value (or null when cleared).

### 7.3 Propagation via one server-side join

`GET /api/labs/{lab}/devices` and `POST /api/labs/{lab}/discover` merge the stored name into each
device payload. `device_json` (or the route) gains `name: str | None`. The frontend `LabDevice`
type gains `name: string | null`. Every consumer then gets names for free:

- the new **Devices** tab (edit + display),
- the **Labs** roster's new Name column,
- **Run**'s `PreflightPanel` role-mapping dropdown — option text becomes `"<name> — <device_id>"`
  when a name exists, else the bare id.

The join lives in one place (a small `_merge_names(devices, names)` helper used by both routes);
`LabsService` stays pure lab-access and the route layer owns the DB read (`get_db` dep, as the
records/runs routes already do).

## 8. Frontend execution model

- A `devices/deviceControlStore.ts` (Zustand, same shape as `runStore`) owns: the selected device
  id, the in-flight command, a job-poll loop, and the session activity log.
- **Immediate command**: POST → append started → append `{result}` or error.
- **Job command**: POST → read `job_id` from the result → append started → poll §6.2 every ~1 s,
  updating progress → append terminal result/error. A single poll loop at a time; superseding it
  cancels the previous.
- **Stop**: POST `{cmd:'stop'}` to the selected device, independent of any poll.
- **Run-active lock**: the tab reads the run state the frontend already tracks (`runStore`) for the
  selected lab and disables the panel proactively with the banner; the 409 guard is the backstop
  if state is stale.

Only pure logic is unit-testable in this repo's node-env vitest (payload builder, poll-state
reducer, name-merge join, catalog integrity). DOM wiring is checked by the probe harness.

## 9. Testing

**Frontend (vitest, node-env — pure functions only):**
- `catalog.ts` integrity — every command's params have valid kinds/defaults/enum options; every
  `locate` preset references real params.
- `buildPayload` — required present, optional-empty omitted, enums/numbers coerced.
- job-poll reducer — `started → running(progress) → succeeded/failed/cancelled` transitions;
  superseded poll drops cleanly.
- name-merge join — devices × names → enriched payload; missing name → null; orphan name ignored.

**Frontend (probe harness, `npm run capture`):** control-height parity (R4) and text-contrast
(R5) on the new type-nav, device list, command panel, and activity log. Run against a real doc
after touching any control class, per `webapp/frontend/CLAUDE.md`.

**Backend (pytest):**
- command passthrough (immediate + job-start), with a fake `LabClient`/device;
- run-active 409 guard on both command and stop;
- job-status endpoint;
- device-names CRUD (set/clear/get_all) + migration applies on a fresh DB;
- name-merge in `GET …/devices` and `POST …/discover` payloads;
- the new `_ERROR_MAP` codes for representative command errors.

**Gates (must be green before merge):** backend `python -m pytest -q · python -m mypy ·
python -m ruff check .`; frontend `npm run lint · npm test · npm run build`; plus `npm run
capture` for the visual rules. The root `lab_devices` library is untouched.

## 10. Delivery plan (two sequential PRs)

**PR A — backend contract + persistence.** `device_names` migration + store + name endpoint;
command passthrough + job-status endpoints + run-active guard; `_ERROR_MAP` additions; name-merge
in the devices/discover payloads. Independently green (pytest/mypy/ruff). No UI.

**PR B — frontend.** Rename Devices→Labs (+ Name column); new Devices control tab (catalog,
command forms, activity log, name editor, `deviceControlStore`); wire `shell/tabs.ts`,
`TabShell.tsx`, nav/url state; Run `PreflightPanel` name propagation; `LabDevice.name` type.
Consumes PR A. Independently green (lint/vitest/build/capture) since frontend tests are pure and
do not hit the network.

Sequential, not stacked: merge PR A to `main`, then branch/finish PR B off the updated `main`.
Each lands green→green.
