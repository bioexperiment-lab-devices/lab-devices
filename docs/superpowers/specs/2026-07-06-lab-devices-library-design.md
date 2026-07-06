# Design: `lab_devices` — async Python library for discovering and managing lab devices

**Date:** 2026-07-06
**Status:** Approved (brainstorming complete)
**Source API:** [`docs/lab-bridge-api-reference.md`](../../lab-bridge-api-reference.md) (SerialHop device API + lab-bridge discovery)

## 1. Purpose & scope

A fully-async Python library that lets an experimenter **discover** and **imperatively drive** the
instruments attached to one lab: peristaltic **pumps**, distribution **valves**, and
**densitometers**. Control is command-oriented (send a command to a device, get a result or a job),
matching the underlying JSON-over-HTTP SerialHop API.

Two independent layers:

1. **Core client (`LabClient`)** — the star of the library. You give it a working `host` + `port`
   and it discovers/manages the devices on that one lab. Usable standalone in any environment.
2. **Discovery module (`LabRegistry`)** — an optional, **server-only** convenience that runs
   *inside the lab-bridge `labnet` docker network*. It resolves a `username` to a reachable
   `host:port` and hands back a ready `LabClient`, so a user can "just choose a username."

The discovery layer depends on the core layer, **never the reverse**. `import lab_devices` works
without ever touching discovery.

### In scope for v1

Full command coverage for all three device types, the async job model, the complete error
taxonomy, lenient typed result models, and the discovery module (internal roster path only).

### Explicitly out of scope for v1

Synchronous wrapper; automatic retry/backoff policies; higher-level protocol/recipe helpers;
the **public per-user token endpoint** (`/api/public/clients/{user}` with `Bearer <pass>`) — v1
uses the internal unauthenticated roster only.

## 2. Key design decisions (resolved during brainstorming)

| # | Decision | Choice |
|---|---|---|
| 1 | Device API style | **Typed classes** (`Pump`/`Valve`/`Densitometer`) with explicit methods, **plus a raw `command()` escape hatch** for anything unwrapped. |
| 2 | Job model | Start methods **return a `Job` handle immediately**; caller `await job.result()` to poll to completion. Progress + cancel + pause/resume are first-class. Same return type every time. |
| 3 | Error handling | **Rich exception hierarchy** mirroring the taxonomy; catch broad (`LabError`) or narrow (`NotCalibratedError`). The envelope is authoritative. |
| 4 | Result types | **Lenient `@dataclass` models** — typed attribute access, a `.raw` dict preserving unknown/extra firmware fields so parsing never crashes. Stdlib only (no pydantic). |
| 5 | Device access & lifecycle | `LabClient` is an **async context manager**. **Lazy typed handles** (`lab.pump(1)`) need no pre-discovery; cheap `list_devices()` (cached GET) and destructive `rediscover()` (POST /discover) mirror the API. |
| 6 | Discovery auth/source | Runs **inside labnet** → uses the **internal, unauthenticated** roster endpoint. **No token anywhere.** `connect(username)` only. Unknown username yields an error listing available names. |
| 7 | Runtime dependency | **`httpx`** only. **Python 3.11+**. |

## 3. Architecture & package layout

```
lab_devices/
├── __init__.py          # public exports: LabClient, device classes, errors, models
├── client.py            # LabClient — session + device factory + list/rediscover/disconnect/agent_info
├── transport.py         # envelope send + HTTP→exception mapping (sole owner of HTTP/JSON)
├── jobs.py              # Job / PumpJob — refresh, result(), cancel(), (pump) pause/resume
├── errors.py            # exception hierarchy rooted at LabDevicesError
├── models/
│   ├── common.py        # DeviceInfo, Identify, AgentInfo, shared value objects
│   ├── pump.py          # PumpCapabilities, PumpStatus, DispenseResult, CalibrationResult, ...
│   ├── valve.py         # ValveCapabilities, ValveStatus, ValveMoveResult, ...
│   └── densitometer.py  # DensitometerCapabilities, DensitometerStatus, MeasureResult, Reading, ...
├── devices/
│   ├── base.py          # Device: ping/status/stop/identify/get_job/command(raw); .id, .type
│   ├── pump.py          # Pump
│   ├── valve.py         # Valve
│   └── densitometer.py  # Densitometer
└── discovery.py         # LabRegistry — internal roster lookup + TCP liveness probe (server-only)
```

**Dependency rules.**

- `transport.py` is the **only** module that knows about HTTP status codes and raw JSON. Devices
  call semantic methods on the transport (`await transport.command(device_id, cmd, params)`), which
  returns a validated envelope or raises the mapped exception.
- `devices/*` depend on `transport`, `jobs`, `models`, `errors`.
- `client.py` owns the `httpx.AsyncClient`, constructs the transport, and is the factory for device
  handles.
- `discovery.py` depends on `client.py`; nothing in the core depends on `discovery.py`.

Each file has one clear purpose and is independently testable against the fake API.

## 4. Core runtime API

### 4.1 `LabClient`

```python
async with LabClient("chisel", 8089, request_timeout=10.0, discover_timeout=30.0) as lab:
    pump = lab.pump(1)                       # lazy PumpHandle bound to "pump_1"
    job = await pump.dispense(volume_ml=10, speed_ml_min=3.0)
    result = await job.result()
    print(result.dispensed_ml)               # 10.0

    for d in await lab.list_devices():       # cheap cached GET /api/v1/devices
        print(d.id, d.type, d.connected, d.identify)

    info = await lab.agent_info()            # GET /agent/info -> AgentInfo
    await lab.rediscover()                   # destructive POST /api/v1/discover
    await lab.disconnect(port="COM3")        # POST /devices/disconnect (?port=)
```

**Constructor:** `LabClient(host: str, port: int, *, request_timeout: float = 10.0,
discover_timeout: float = 30.0, http: httpx.AsyncClient | None = None)`. If `http` is supplied the
client uses it and does not close it; otherwise it creates and owns one (closed on `__aexit__`).
Base URL is `http://{host}:{port}/`.

**Device factories** (all lazy — bind an id, validate nothing up front):

- `lab.pump(n) -> Pump`, `lab.valve(n) -> Valve`, `lab.densitometer(n) -> Densitometer`
  (`n` is 1-based, forming ids `pump_1`, `valve_1`, `densitometer_1`).
- `lab.device(device_id: str) -> Device` — generic getter; dispatches to the correct typed class
  by id prefix (`pump_` / `valve_` / `densitometer_`). Raises `ValueError` on an unrecognized prefix.

A handle for a non-existent device raises `UnknownDeviceError` (HTTP 404) on its **first command**.

**Enumeration & lifecycle:**

- `await lab.list_devices() -> list[DeviceInfo]` — cached list; cheap, idempotent.
- `await lab.rediscover() -> list[DeviceInfo]` — POST `/api/v1/discover`. Destructive/slow; uses
  `discover_timeout`. `409 "discovery in progress"` → `DiscoveryInProgressError`;
  `409 "job in progress"` → `JobInProgressError(detail)`; `500` → `DiscoveryFailedError`.
- `await lab.disconnect(port: str | None = None) -> int` — POST `/devices/disconnect`; returns the
  `released` count. `?port=` for one device (`404` → `UnknownDeviceError` at the port).
- `await lab.agent_info() -> AgentInfo` — GET `/agent/info`. The endpoint itself is best-effort
  and always returns `200` with whatever fields it could gather (missing fields are simply
  omitted and surface as `None`). The client still surfaces genuine transport/protocol failures
  (unreachable, `5xx`, malformed body) as exceptions rather than swallowing them.

### 4.2 `Device` base and typed subclasses

**Base `Device`** — universal commands available on every type:

- `await device.ping() -> PingResult`
- `await device.status() -> <TypedStatus>`  (per-type status model)
- `await device.identify() -> Identify`  (memory-served; §3.5 of the API ref)
- `await device.stop() -> <result>`  (always succeeds)
- `await device.get_job(job_id: str) -> Job`  (memory-served)
- `await device.command(cmd: str, params: dict | None = None) -> dict`  — **raw escape hatch**;
  returns the parsed `result` (or raises the mapped error). This is how any un-wrapped or future
  command is reachable.
- Attributes: `device.id`, `device.type`.

**`Pump`** — `rotate(direction, speed_ml_min)`, `rotate_raw(direction, speed_pct)`,
`dispense(direction, volume_ml, speed_ml_min, drop_suckback_ml=None, speed_profile=None) -> PumpJob`,
`pause()`, `resume()`, `start_calibration(speed_pct=None) -> Job`,
`set_calibration(job_id=None, measured_volume_ml=None, ml_per_step=None)`, `get_calibration()`.

**`Valve`** — `home(position) -> ...`, `set_position(position, rotation=None) -> Job`,
`configure(default_rotation=None, hold_torque=None)`.

**`Densitometer`** — `measure_blank() -> Job`, `measure(include_raw=False) -> Job`,
`start_monitoring(interval_s=None)`, `get_readings(since_seq=None, limit=None) -> ReadingsResult`,
`stop_monitoring()`, `set_thermostat(enabled, target_c=None)`, `set_tube_correction(factor)`,
`calibrate_tube(reference_absorbance) -> ...`, `set_led(level)`, `read_raw(level=None) -> Job`.

Typed methods validate/shape params minimally on the client side (e.g. required fields present) but
defer range/state validation to the device, which returns `invalid_params` etc.

### 4.3 Jobs

Commands whose API result is `{ "job": {...} }` return a `Job` (or `PumpJob`) immediately.

```python
job = await pump.dispense(volume_ml=10, speed_ml_min=3.0)   # PumpJob
job.state            # 'running'
await job.refresh()  # re-poll get_job, refresh fields
job.progress         # 0.35
result = await job.result()          # polls to terminal; returns typed result or raises
```

**`Job` fields:** `job_id, state, progress, estimated_duration_s, elapsed_s, error, raw`.
**Methods:**

- `await job.refresh() -> Job` — single `get_job` poll; updates fields in place.
- `await job.result(*, poll_interval: float = 0.25, max_interval: float = 2.0,
  timeout: float | None = None) -> <TypedResult>` — polls `get_job` with exponential backoff
  (`poll_interval` → `max_interval`) until `state ∈ {succeeded, failed, cancelled}`.
  `succeeded` → typed result model (parsed from the bare job object's `result`);
  `failed` → raises `JobFailedError(error)`; `cancelled` → raises `JobCancelledError`.
  `timeout` (wall-clock) → raises `JobTimeoutError` (does not cancel the device job).
- `await job.cancel() -> ...` — issues the device's `stop` (cancels the active job).

**`PumpJob`** additionally: `await job.pause()`, `await job.resume()` (pump supports paused state).

The starting method wires the correct **result model** into the `Job` so `result()` can parse the
completed payload without the caller specifying it (e.g. `dispense` → `DispenseResult`,
`set_position` → `ValveMoveResult`, `measure` → `MeasureResult`, `start_calibration` →
`CalibrationRunResult`, `read_raw` → `ReadRawResult`).

**Job history caveat:** the hub keeps only the last 8 completed jobs per session; a `job_id` older
than 8 completions returns `invalid_params` from `get_job`. `result()` surfaces that as
`InvalidParamsError` (caller polled too late). Documented, not worked around.

### 4.4 Correlation ids, timeouts, transport

- Every request gets a fresh `uuid4` `id`; the transport checks the echoed `id` and raises
  `LabProtocolError` on mismatch. Overridable per call via `request_id=`.
- Request body cap (32 KiB) is respected; oversize raises `LabProtocolError` before sending.
- `request_timeout` for commands (default 10 s — covers the ~2–3 s memory-served stalls noted in
  the API ref); `discover_timeout` for `rediscover` (default 30 s).
- **`503 device_unreachable` → `DeviceUnreachableError`; no auto-retry in v1.** The caller backs
  off; the SerialHop session already retries in the background. Last-known state stays reachable via
  memory-served `identify` / `get_job`.

## 5. Discovery module (`LabRegistry`) — server-only, inside labnet

```python
from lab_devices.discovery import LabRegistry

async with LabRegistry() as reg:                  # url from LAB_DEVICES_DISCOVERY_URL env
    names = await reg.list_labs()                 # ['khamit_desktop', 'natalya_test_user', ...]
    lab = await reg.connect("khamit_desktop")     # -> LabClient (not yet entered)
    async with lab:
        await lab.pump(1).dispense(volume_ml=10, speed_ml_min=3.0)
```

**Source of truth:** the **internal, unauthenticated** endpoint
`GET http://siteapp:8000/api/clients/` (reachable only inside labnet), which returns the full roster
as `{name: {"host": "chisel", "port": <int>}}`. **No `Authorization` header, no token** anywhere in
this layer.

**Constructor:** `LabRegistry(*, url: str | None = None, chisel_host: str | None = None,
probe_timeout: float = 0.3, http: httpx.AsyncClient | None = None)`.
`url` resolution order: explicit arg → `LAB_DEVICES_DISCOVERY_URL` env → default
`http://siteapp:8000/api/clients/`. `LabRegistry` owns its httpx client (async context manager) and
its own TCP-probe machinery.

**API:**

- `await reg.list_labs() -> list[str]` — roster names.
- `await reg.lookup(name: str) -> LabInfo` — `LabInfo(name, host, port)`; raises
  `UnknownLabClient(name, available=[...])` if absent (name list included — the internal endpoint
  makes this possible).
- `await reg.is_online(name: str) -> bool` — TCP-dial `host:port` with `probe_timeout` (0.3 s),
  replacing the `connected` field the internal endpoint omits.
- `await reg.connect(name: str, *, require_online: bool = True, **client_kwargs) -> LabClient` —
  looks up the roster, probes liveness (unless `require_online=False`), and returns an **un-entered**
  `LabClient(host, port, **client_kwargs)` so the caller owns its lifecycle. `require_online=True` +
  down probe → `LabOffline(name, host, port)`. `chisel_host` (if set) overrides the roster `host`.

**Discovery error mapping** (from verified lab-bridge behavior):

| Condition | Raised |
|---|---|
| Connection refused / timeout to `siteapp` | `ClientLookupEndpointUnreachable` |
| 5xx, malformed/missing roster, non-JSON/bad shape | `ClientLookupEndpointError` |
| Name not in roster | `UnknownLabClient(name, available=[...])` |
| Roster hit but TCP liveness probe fails | `LabOffline(name, host, port)` |

## 6. Error model

One root, two branches — the whole tree is catchable via `LabDevicesError`.

```
LabDevicesError
├── DiscoveryError                          # lab-bridge / roster layer
│   ├── ClientLookupEndpointUnreachable
│   ├── ClientLookupEndpointError
│   ├── UnknownLabClient        (.name, .available)
│   └── LabOffline              (.name, .host, .port)
└── LabError                                # any error from talking to a SerialHop agent (a LabClient)
    │
    │   # -- device-command errors: carry .code .message .details .request_id --
    ├── InvalidRequestError                 # hub, HTTP 400 — invalid_request
    ├── UnknownDeviceError                  # hub, HTTP 404 — unknown_device
    ├── DeviceUnreachableError              # hub, HTTP 503 — device_unreachable
    ├── UnknownCommandError                 # device — unknown_command
    ├── InvalidParamsError      (.details)  # device — invalid_params
    ├── BusyError               (.job_id)   # device — busy
    ├── NotCalibratedError      (.details)  # device — not_calibrated
    ├── NotHomedError                       # device — not_homed (valve)
    ├── HardwareError           (.component)# device — hardware_error
    ├── InternalDeviceError                 # device — internal_error
    │
    │   # -- job errors --
    ├── JobFailedError          (.error)    # job reached state 'failed'
    ├── JobCancelledError                   # job reached state 'cancelled'
    ├── JobTimeoutError                     # result() wall-clock timeout
    │
    │   # -- agent-infra errors: {error, detail} shape, carry .message .detail only --
    ├── DiscoveryInProgressError            # rediscover 409 "discovery in progress"
    ├── JobInProgressError      (.detail)   # rediscover 409 "job in progress"
    ├── DiscoveryFailedError                # rediscover 500
    │
    └── LabProtocolError                    # envelope violated its own contract (.message)
```

**Rules.**

- **The envelope is authoritative.** Any `status:"error"` raises, regardless of HTTP status; HTTP
  status is used only for coarse routing.
- **Unknown `code` strings degrade gracefully** to base `LabError` (surface `message`, log) rather
  than crashing control flow — the taxonomy is treated as closed for branching but tolerant of
  additions.
- **Field availability is subgroup-specific.** Device-command errors carry `code`, `message`,
  `details`, and the originating `request_id`. Agent-infra errors (`/discover`, `/disconnect`) come
  from the `{error, detail}` shape and carry only `message` + `detail` (no `code`/`request_id`).
  Job and protocol errors carry `message` (plus a wrapped `.error` for `JobFailedError`).

## 7. Models

Lenient `@dataclass` objects, each with a `raw: dict` field holding the original JSON. A
`from_raw(cls, data)` classmethod maps known keys and stashes the whole payload on `.raw`, so unknown
or newly-added firmware fields never raise. Nested capability blocks are their own dataclasses (with
`.raw`), and value objects like `speed_ml_min: {min, max}` become small typed pairs (nullable, since
the API returns `null` until calibration is verified).

Representative set (not exhaustive): `DeviceInfo`, `Identify`, `AgentInfo`, `PingResult`,
`PumpCapabilities`/`PumpStatus`/`DispenseResult`/`CalibrationRunResult`/`Calibration`,
`ValveCapabilities`/`ValveStatus`/`ValveMoveResult`,
`DensitometerCapabilities`/`DensitometerStatus`/`MeasureResult`/`ReadingsResult`/`Reading`/`ReadRawResult`,
and the `Job` data shape.

## 8. Testing strategy

**Hermetic — no hardware, no network.**

- **`FakeLab`**: an in-memory ASGI app implementing the SerialHop surface — the command envelope,
  the job lifecycle (start → running → succeeded/failed/cancelled with progress), memory-served
  `identify`/`get_job`, the infra endpoints (`/api/v1/devices`, `/api/v1/discover`,
  `/devices/disconnect`, `/agent/info`), and the error taxonomy incl. envelope-vs-HTTP-status
  divergence. Driven through `httpx.MockTransport` so `LabClient` talks to it exactly as to a real
  agent.
- **Liveness probe:** a throwaway `asyncio` TCP server (and a closed port) exercise `is_online` /
  `connect(require_online=...)` and the `LabOffline` path.
- **Discovery:** a fake roster response drives `list_labs` / `lookup` / `UnknownLabClient` name
  lists / the endpoint-error mappings.

**TDD throughout** (via the `test-driven-development` skill during implementation). Priority
coverage: job polling to each terminal state, the full error taxonomy, `503` handling, `409` on
rediscover, correlation-id echo checks, lenient model parsing (unknown fields survive on `.raw`),
and the discovery error mappings.

## 9. Packaging

- `pyproject.toml` with **hatchling**. Runtime dependency: **`httpx`**. Dev: `pytest`,
  `pytest-asyncio`, `mypy`, `ruff`. Ship `py.typed` (fully typed).
- **Python 3.11+.**
- Public API re-exported from `lab_devices/__init__.py`: `LabClient`, `Pump`, `Valve`,
  `Densitometer`, `Device`, `Job`, the model dataclasses, and the full error hierarchy.
  `LabRegistry` is imported from `lab_devices.discovery` (kept off the top-level namespace to
  reinforce that it's the optional, environment-specific layer).
