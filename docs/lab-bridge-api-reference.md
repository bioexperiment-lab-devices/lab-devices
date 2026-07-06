# SerialHop device API reference

A self-contained reference for the API that a **SerialHop** agent exposes through its chisel
reverse tunnel. Written for developers building a Python library that manages lab devices
from the **lab-bridge** server.

It answers three questions, in the order a client needs them:

1. **[Discovering labs](#1-discovering-labs)** — how to find the running SerialHop agents and
   get a reachable base URL for each.
2. **[Discovering devices](#2-discovering-devices)** — how to enumerate the instruments
   attached to one lab and get their addressable IDs.
3. **[Sending commands](#3-sending-commands)** — the JSON command protocol, the response
   shapes, the job model, and the per-device command sets.

Everything here is high-level JSON over HTTP. There is nothing byte-level to deal with.

---

## 0. Topology and conventions

SerialHop runs on a lab PC (behind NAT, no inbound ports open) and controls the attached
instruments — peristaltic pumps, distribution valves, densitometers. It exposes a local REST
API bound to `127.0.0.1` and reaches the outside world through a **chisel reverse tunnel** it
dials out to the lab-bridge server.

```
Researcher ──JupyterLab──▶ lab-bridge server ──▶ auth proxy ──▶ chisel server
                                                                     ▲
                                                   (reverse tunnel)  │  SerialHop dials OUT
                                                                     │
                                               Lab PC: SerialHop REST API (127.0.0.1)
                                                                     │
                                                              Lab instruments
```

Your Python library runs **inside the lab-bridge server's docker network**, alongside the
`chisel` service. It reaches any lab's SerialHop API at `http://chisel:<port>/`, where
`<port>` is that lab's assigned reverse-tunnel port (see §1).

### Conventions that hold for every request

| Aspect | Value |
|---|---|
| **Base URL** | `http://chisel:<port>/` — `chisel` is the docker service name; `<port>` is unique per lab. |
| **Transport** | Plain HTTP/1.1. **No TLS at this layer** (the tunnel runs inside the trusted server network). |
| **Authentication** | **None at this layer.** Authn/authz is enforced by the upstream auth proxy that fronts this URL; SerialHop trusts every request that reaches it. |
| **Content-Type** | `application/json` on every request that has a body, and on every response. |
| **Two error shapes** | *Infra* endpoints return `{"error": "<short>", "detail": "<long>"}`. *Device command* endpoints return the [command envelope](#31-the-command-envelope). Which is which is called out per endpoint. |

### The endpoints this guide covers

| Method | Path | Section | Purpose |
|---|---|---|---|
| `GET`  | `/agent/info` | §1 | Agent self-description (confirm a lab is up, read its identity) |
| `POST` | `/api/v1/discover` | §2 | Re-probe, rebuild device sessions, return the new list |
| `GET`  | `/api/v1/devices` | §2 | Return the cached device list |
| `POST` | `/api/v1/devices/{id}/command` | §3 | Execute one JSON command against a device |
| `POST` | `/devices/disconnect` | §2 | Release device sessions (all, or one via `?port=`) |

---

## 1. Discovering labs

### 1.1 What a "lab" is

A lab is identified by its **chisel auth user** — the `user` credential the agent is
provisioned with. That single string is the lab's identity for both the tunnel connection and
the lab-bridge API (as `Authorization: Bearer <pass>`). There is no separate lab-id or
lab-name.

Once you have *reached* a lab (§1.4), you can also read its self-reported hardware identity —
`hostname` and `machine_id` — from `GET /agent/info`. Those are useful for correlating a
tunnel port back to a physical machine, but they are **not** routing keys.

### 1.2 How a lab becomes reachable (the port scheme)

The SerialHop agent dials **out** to the lab-bridge chisel server and opens one reverse route
that publishes its local REST API on the chisel server at a server-assigned port:

```
you reach:     http://chisel:<port>/   →   SerialHop REST API on the lab PC
lab identity:  the chisel `user`
```

The `<port>` is **assigned by the lab-bridge server**, not configured on the lab PC. You get
it from the lab-bridge API (§1.3).

### 1.3 Enumerating labs — a lab-bridge responsibility

> **Boundary.** The registry of *which labs exist* and *which port each maps to* lives in the
> **lab-bridge server**, not in SerialHop. SerialHop exposes no "list all labs" endpoint. Your
> library obtains the roster of provisioned `user`s and their ports from the lab-bridge API.

The relevant lab-bridge endpoints (served by lab-bridge itself at
`https://<lab-bridge-host>/...`, **not** through the SerialHop tunnel):

| Method | Path | Auth | Returns |
|---|---|---|---|
| `GET` | `/api/public/clients/{user}` | `Bearer <pass>` | `{ "port": int, "connected": bool }` — the lab's reverse-tunnel port and whether its tunnel is currently live |
| `GET` | `/api/public/server-info` | none | Shared bootstrap parameters (chisel listen port, log sink, forward tunnels) |
| `GET` | `/api/public/health` | none | `{ "chisel": "ok", "error": "" }` — chisel-server liveness |

A typical discovery loop on the lab-bridge side:

```
for each provisioned lab user U (from lab-bridge's roster):
    rec = GET https://<host>/api/public/clients/U     # Bearer = U's pass
    if rec.connected:
        base = f"http://chisel:{rec.port}/"           # reachable SerialHop API
        info = GET base + "agent/info"                # confirm & identify (§1.4)
```

`connected: false` means the lab's tunnel is not currently established — the port will refuse
connections. Don't try to reach it until it reconnects (the agent retries the tunnel
indefinitely).

### 1.4 Confirming and identifying a reached lab — `GET /agent/info`

The cheapest way to confirm a lab is up and read its identity. It is best-effort and **never
fails** (always `200`); any field it can't gather is omitted.

```json
// GET http://chisel:<port>/agent/info   →   200
{
  "version": "2.0.0+abc1234",
  "build_sha": "abc1234",
  "os": "windows",
  "arch": "amd64",
  "hostname": "LAB-PC-04",
  "machine_id": "f0c1ab12-34cd-5e67-8901-234567890abc",
  "uptime_seconds": 8412
}
```

| Field | Type | Notes |
|---|---|---|
| `version` | string | Full version string, `X.Y.Z+<build_sha>`. |
| `build_sha` | string | Everything after the first `+` in `version`. Omitted if none. |
| `os` | string | `windows` in production. |
| `arch` | string | e.g. `amd64`. |
| `hostname` | string | OS hostname of the lab PC. Empty string if unavailable. |
| `machine_id` | string | Stablest per-machine identifier. Omitted on non-Windows builds. |
| `uptime_seconds` | int | Seconds since the SerialHop process started. |

There is no lab name here — pair `machine_id`/`hostname` with the `user` you looked the port
up under to build your own lab identity.

---

## 2. Discovering devices

Everything below is served by the SerialHop agent at `http://chisel:<port>/` and is scoped to
that one lab.

### 2.1 The device-ID scheme

Every device has an `id` of the form `{type}_{n}`:

| `type` | Instrument | `identify.device_type` |
|---|---|---|
| `pump` | Peristaltic pump | `pump` |
| `valve` | Distribution valve | `distribution_valve` |
| `densitometer` | Densitometer | `densitometer` |

- `n` is **1-based** per type: the first pump is `pump_1`, the second `pump_2`, etc.
- **ID stability:** the same physical device keeps the same `id` across re-discoveries.
- **Note the valve naming split:** the `type` used in IDs and routing is `valve`, but its
  `identify.device_type` is `distribution_valve`.

### 2.2 `GET /api/v1/devices` — the cached device list

Returns the result of the **most recent discovery**, from cache, without touching hardware.
Cheap and idempotent — use this for routine "what's here?" polling.

```json
// GET /api/v1/devices   →   200
{
  "devices": [
    {
      "id": "pump_1",
      "type": "pump",
      "port": "COM3",
      "connected": true,
      "identify": {
        "device_type": "pump",
        "model": "peristaltic-1ch",
        "serial": "26-025",
        "firmware_version": "legacy",
        "protocol_version": "1.0",
        "capabilities": {
          "channels": 1,
          "speed_ml_min": { "min": 0.05, "max": 40.0 },
          "supports_gradient": true,
          "supports_drop_suckback": true
        }
      }
    },
    {
      "id": "valve_1",
      "type": "valve",
      "port": "COM7",
      "connected": false,
      "identify": null
    }
  ],
  "discovered_at": "2026-07-06T12:34:56Z"
}
```

**Device entry fields:**

| Field | Type | Meaning |
|---|---|---|
| `id` | string | `{type}_{n}` (§2.1). The path segment for command routing. |
| `type` | string | `pump` \| `valve` \| `densitometer`. |
| `port` | string | Opaque handle for where the device is attached; also the selector for `/devices/disconnect?port=`. |
| `connected` | bool | The session's **current** state — whether the driver is presently talking to the device. |
| `identify` | object \| null | The cached identify block from the last successful attach; `null` until the first attach succeeds. Persists even if the device later goes unreachable (see [memory-served commands](#35-memory-served-commands-identify-and-get_job)). |

**Top-level:**

| Field | Type | Meaning |
|---|---|---|
| `discovered_at` | RFC-3339 string (UTC, `Z`) \| null | When the last discovery ran. `null` if discovery has never run — in which case `devices` is `[]`. |

**`connected` / `identify` combinations you must handle:**

| `connected` | `identify` | Meaning |
|---|---|---|
| `true` | object | Attached and ready. |
| `false` | `null` | Discovered but has never successfully attached; retried in the background. |
| `false` | object | Attached earlier, currently unreachable; retried in the background. Cached identify still served. |

A device that fails to attach **does not disappear** — it stays listed with `connected: false`
and the session retries indefinitely with backoff (5 s doubling to 60 s).

### 2.3 `POST /api/v1/discover` — re-probe and rebuild

Tears down **every** current device session (each driver first persists its state), rebuilds
fresh sessions from a hardware re-probe, and **waits for each new session's first attach
attempt to finish** before responding — so the returned list reflects real attach outcomes
rather than a transient `connected: false`.

- **Request body:** none.
- **Response `200`:** identical shape to `GET /api/v1/devices`.

> **This is destructive.** It closes and rebuilds all sessions and re-drives hardware. Don't
> use it as a lightweight "give me current state" call — use `GET /api/v1/devices` for that.
> Reserve `discover` for when hardware actually changed.

**Timing.** The call blocks until every new session has attempted its first attach, and
re-probing drives hardware serially per device. Expect it to take **several seconds**; set a
generous client timeout (≥ 30 s).

**Errors (infra `{error, detail}` shape):**

| Status | Body | When |
|---|---|---|
| `409` | `{"error": "discovery in progress"}` (no `detail`) | Another discovery is already running. |
| `409` | `{"error": "job in progress", "detail": "pump_1 has an active job; stop it before re-discovering"}` | Some device has an active job. Stop it (`cmd: "stop"`) first, then retry. |
| `500` | `{"error": "discovery failed", "detail": "<message>"}` | The re-probe failed. |

### 2.4 `POST /devices/disconnect` — release sessions

Releases device sessions without a full re-probe. Always available. Infra response shape.

- **No query** → releases **every** open device session.
- **`?port=COM3`** → releases just the device on that port, leaving the rest intact. `404` if
  no device is registered on that port.

```json
// POST /devices/disconnect   →   200
{ "released": 3 }
```

After a disconnect, released devices vanish from `GET /api/v1/devices` until the next
`discover`.

---

## 3. Sending commands

All device control goes through a **single endpoint** with a **single request/response
envelope** shared by every device type:

```
POST /api/v1/devices/{id}/command
```

`{id}` is a device `id` from §2 (e.g. `pump_1`). The command itself — `cmd`, `params`, and the
`result` shape — is device-specific; the envelope, error taxonomy, job model, and HTTP mapping
are universal.

### 3.1 The command envelope

**Request body:**

```json
{
  "id": "req-1",
  "cmd": "dispense",
  "params": { "direction": "forward", "volume_ml": 10.0, "speed_ml_min": 3.0 }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | **yes** | Client-generated correlation id (a UUID is conventional). **Echoed back verbatim** in the response. |
| `cmd` | string | **yes** | The command name (per-device; see §3.6–§3.8). |
| `params` | object | no | Command-specific parameters. Omit when the command takes none. |

The body is capped at **32 KiB**.

**Success response:**

```json
{ "id": "req-1", "status": "ok", "result": { /* command-specific */ } }
```

**Error response:**

```json
{
  "id": "req-1",
  "status": "error",
  "error": {
    "code": "invalid_params",
    "message": "volume_ml must be positive",
    "details": { "param": "volume_ml", "value": -1 }
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `id` | string | The request's `id`, echoed. Empty string if the request omitted it. |
| `status` | string | `"ok"` or `"error"`. |
| `result` | any | Present on success; shape is per-command. |
| `error` | object | Present on error. `code` + human `message` + optional `details` (structured; e.g. which param, the offending value, a conflicting `job_id`). |

### 3.2 HTTP status vs. envelope status

**The envelope is authoritative. The HTTP status is a convenience mirror** that tells you *who
decided the outcome*, not whether the command "succeeded." Always branch on
`body.status` / `body.error.code`; use the HTTP code only for coarse routing.

| HTTP | When | Envelope |
|---|---|---|
| **200** | The **device** (or the hub's in-memory job/identify cache) decided the outcome — success *or* a device-level error. | `status: "ok"`, or `status: "error"` with a device-level `code`. |
| **404** | Unknown `{id}` — no such device. | `status: "error"`, `code: "unknown_device"`. |
| **503** | The device is **unreachable**. | `status: "error"`, `code: "device_unreachable"`. **Exception:** `identify` and `get_job` stay at **200** (§3.5). |
| **400** | Malformed JSON body, or missing `id` / `cmd`. | `status: "error"`, `code: "invalid_request"`. |

A well-formed command that a device rejects (bad params, busy, not calibrated, unknown
command, …) is a **device-level error at HTTP 200** — see the taxonomy below. The envelope is
validated before the device is looked up, so a malformed body returns **400** even for an
unknown device id.

**Worked examples:**

```json
// Device-decided error — still HTTP 200
// POST /api/v1/devices/pump_1/command
{ "id": "req-2", "cmd": "dispense", "params": { "volume_ml": -1, "speed_ml_min": 3 } }
// → 200
{ "id": "req-2", "status": "error",
  "error": { "code": "invalid_params", "message": "volume_ml must be positive",
             "details": { "param": "volume_ml", "value": -1 } } }
```

```json
// Unknown device — HTTP 404
// POST /api/v1/devices/pump_9/command   { "id": "req-3", "cmd": "identify" }
// → 404
{ "id": "req-3", "status": "error",
  "error": { "code": "unknown_device", "message": "no device with id pump_9" } }
```

```json
// Device unreachable — HTTP 503
// → 503
{ "id": "req-4", "status": "error",
  "error": { "code": "device_unreachable", "message": "device is not responding" } }
```

```json
// Malformed request (missing "id") — HTTP 400
// POST /api/v1/devices/pump_1/command   { "cmd": "dispense" }
// → 400
{ "id": "", "status": "error",
  "error": { "code": "invalid_request", "message": "\"id\" and \"cmd\" are required" } }
```

### 3.3 Error-code taxonomy

| Code | Layer | HTTP | Meaning |
|---|---|---|---|
| `invalid_request` | hub | 400 | Body isn't valid JSON, or `id`/`cmd` missing. |
| `unknown_device` | hub | 404 | No device with that `{id}`. |
| `device_unreachable` | hub | 503¹ | Session can't reach the device. |
| `unknown_command` | device | 200 | `cmd` not recognized by this device. |
| `invalid_params` | device | 200 | Missing/out-of-range param; `details` says which. |
| `busy` | device | 200 | A job/move conflicts with the command; `details.job_id` is the active job. |
| `not_calibrated` | device | 200 | Operation needs a calibration that isn't stored (pump, densitometer). |
| `not_homed` | device | 200 | Position commanded before the valve is homed (valve). |
| `hardware_error` | device | 200 | Motor/sensor/driver fault; `details.component` where applicable. |
| `internal_error` | device | 200 | Unexpected device state. |

¹ Except `identify`/`get_job`, which are memory-served at 200 (§3.5).

Not every device emits every device-level code — the per-device sections list each device's
codes. Treat the taxonomy as closed for control flow but tolerate unknown codes gracefully
(log + surface `message`).

### 3.4 The job model

Long-running operations (a dispense, a valve move, a densitometer measurement, a calibration
run) **return immediately with a job** and complete asynchronously. You then **poll** the job
with `get_job`.

A **job object** (the shape returned by `get_job`, and embedded in `status.job`):

```json
{
  "job_id": "j-7f21",
  "state": "running",
  "progress": 0.35,
  "estimated_duration_s": 200.0,
  "elapsed_s": 70.2,
  "result": null,
  "error": null
}
```

| Field | Type | Notes |
|---|---|---|
| `job_id` | string | Unique per session lifetime. |
| `state` | string | `running` \| `paused` \| `succeeded` \| `failed` \| `cancelled`. (`paused` only where the device supports it — pump.) |
| `progress` | float | `0.0`–`1.0`. Only a **verified completion** reaches `1.0`. |
| `estimated_duration_s` | float | Estimated total duration. |
| `elapsed_s` | float | Elapsed so far (frozen while `paused`). |
| `result` | object \| null | Populated when `state == "succeeded"`; shape is per-command. |
| `error` | object \| null | Populated when `state == "failed"`; an error object (`code`/`message`/`details`). |

**Rules:**

- A session runs **at most one active job**. Starting another while one is active returns the
  device-level `busy` error (`details.job_id` = the running job).
- The hub keeps the **last 8 completed jobs** per session (newest first) for `get_job` lookups
  after completion. Older history is dropped.
- **How a job is returned when started:** commands that start a job return
  `result: { "job": <job object> }` (the job wrapped under a `"job"` key). `get_job` returns
  the **bare** job object as `result`. `status` embeds the active-or-most-recent job under its
  `"job"` field (or `null`).

**Polling pattern:**

```
resp   = POST …/command {id, cmd:"dispense", params:{…}}   → result.job.job_id = "j-7f21"
loop:
    j = POST …/command {id, cmd:"get_job", params:{job_id:"j-7f21"}}   → result = <job>
    if j.state in (succeeded, failed, cancelled): break
    sleep(...)
# on succeeded → j.result ; on failed → j.error
```

### 3.5 Memory-served commands: `identify` and `get_job`

Two commands are answered from the hub's **in-memory state** rather than by talking to the
device, so they stay at **HTTP 200** even while the device is otherwise unreachable:

- **`identify`** — returns the cached identify block from the device's last successful attach,
  regardless of the *current* connection state. If no attach has **ever** succeeded (cache
  empty), it returns the normal `device_unreachable` at **503**. The exception only applies
  once the cache has been populated at least once.

  ```json
  // device currently disconnected, but attached successfully earlier
  // { "id": "req-5", "cmd": "identify" }   →   200
  { "id": "req-5", "status": "ok",
    "result": { "device_type": "pump", "model": "peristaltic-1ch", "serial": "26-025",
                "firmware_version": "legacy", "protocol_version": "1.0",
                "capabilities": { "channels": 1, "supports_gradient": true,
                                  "supports_drop_suckback": true, "speed_ml_min": null } } }
  ```

- **`get_job`** — always served from the jobs engine (active job + last-8 history ring), never
  checks the connection state. This includes reading a job that **just failed with
  `hardware_error` because the device went unreachable mid-job**. `params.job_id` is required;
  an unknown/missing `job_id` returns the ordinary `invalid_params` (still 200).

  ```json
  // { "id": "req-6", "cmd": "get_job", "params": { "job_id": "j-3" } }   →   200
  { "id": "req-6", "status": "ok",
    "result": { "job_id": "j-3", "state": "failed", "progress": 0.62,
                "estimated_duration_s": 200.0, "elapsed_s": 124.0, "result": null,
                "error": { "code": "hardware_error",
                           "message": "device became unreachable mid-job" } } }
  ```

Every **other** command — including `ping` and `status` — talks to the device and fails fast
with `device_unreachable` (503) while the device is unreachable.

### 3.6 Pump commands (`type: pump`)

All quantities are physical units (ml, ml/min, s); the device converts them via its stored
calibration. Direction values: `"forward"` | `"reverse"`.

**identify** — `capabilities`:

```json
{ "device_type": "pump", "model": "peristaltic-1ch", "serial": "26-025",
  "firmware_version": "legacy", "protocol_version": "1.0",
  "capabilities": {
    "channels": 1,
    "speed_ml_min": { "min": 0.05, "max": 40.0 },   // null until calibration is verified
    "supports_gradient": true,
    "supports_drop_suckback": true,
    "calibration_unverified": true                  // present only when a recovered
                                                    // calibration is unconfirmed
  } }
```

**Command set:**

| `cmd` | `params` | Result / job |
|---|---|---|
| `ping` | — | `{ "uptime_ms": 8123456 }` |
| `status` | — | See below. |
| `identify` | — | Memory-served identify block (§3.5). |
| `get_job` | `{job_id}` | Bare job object. |
| `rotate` | `{direction, speed_ml_min}` | `{ "state": "rotating", "direction": "forward", "speed_ml_min": 3.0 }`. Continuous until `stop`/new `rotate`. Requires calibration (`not_calibrated` otherwise). |
| `rotate_raw` | `{direction, speed_pct}` | `{ "state": "rotating", "speed_pct": 25 }`. Calibration-independent (% of max rate); for bring-up/priming. |
| `dispense` | `{direction, volume_ml, speed_ml_min, drop_suckback_ml?, speed_profile?}` | **Job.** See below. |
| `pause` | — | `{ "state": "paused", "job_id": "j-7f21", "dispensed_ml": 4.2 }`. `busy` (`details.state="idle"`) if nothing is running. |
| `resume` | — | `{ "state": "dispensing", "job_id": "j-7f21" }` |
| `stop` | — | `{ "state": "idle", "cancelled_job_id": "j-7f21", "dispensed_ml": 4.2 }`. Always succeeds. |
| `start_calibration` | `{speed_pct?}` (default 50) | **Job**; completed `result` `{ "steps": 48000, "duration_s": 118.7 }`. |
| `set_calibration` | `{job_id, measured_volume_ml}` **or** `{ml_per_step}` | `{ "ml_per_step": 0.000424 }`. Persisted. |
| `get_calibration` | — | `{ "ml_per_step": 0.000424, "set_at_uptime_ms": 120000 }` |

`dispense` params: `drop_suckback_ml` (optional, default 0) retracts the hanging drop after
delivering the full `volume_ml`; `speed_profile` (`{start_ml_min, end_ml_min, shape:
"linear"|"exponential"}`) produces a flow-rate gradient and overrides `speed_ml_min`. Immediate
result: `{ "job": { "job_id": "j-7f21", "state": "running", "estimated_duration_s": 200.0 } }`.
Completed job `result`:
`{ "dispensed_ml": 10.0, "duration_s": 199.4, "mean_speed_ml_min": 3.01, "suckback_ml": 0.05 }`.

`status` result:

```json
{ "state": "dispensing",          // idle | rotating | dispensing | calibrating | paused
  "job": { /* job object, or null when idle/rotating */ },
  "direction": "forward",         // null when idle
  "speed_ml_min": 3.0,            // instantaneous; null when idle
  "dispensed_ml": 4.2,            // current/last job
  "calibration": { "ml_per_step": 0.000424, "set_at_uptime_ms": 120000 } }  // null if never calibrated
```

**Error codes:** `invalid_request`, `unknown_command`, `invalid_params`, `busy`,
`not_calibrated`, `hardware_error`, `internal_error`. (No `not_homed`.)

**Notes:** continuous `rotate` is a *state*, not a job (only finite ops are jobs). Metered
commands (`rotate`, `dispense`) require a **verified** calibration; a recovered-but-unverified
calibration yields `not_calibrated` with `details.reason="unverified_mirror"` and a
`proposed_ml_per_step` — confirm it via `set_calibration` or re-run `start_calibration`.

### 3.7 Distribution valve commands (`type: valve`)

Routes flow to one of N outputs (N = 6 or 2); position `0` = all closed, `1..N` = that output.
**The valve has no position sensor** — after power-up it is `unhomed` and must be `home`d
before any `set_position`.

**identify** — `capabilities` (note: **no `serial`** — the valve has no serial-number command):

```json
{ "device_type": "distribution_valve", "model": "radial-6",
  "firmware_version": "legacy", "protocol_version": "1.0",
  "capabilities": { "positions": 6,                                // valid positions 0..6
                    "rotation_modes": ["shortest", "direct", "wrap"],
                    "seconds_per_position": 0.9 } }
```

**Command set:**

| `cmd` | `params` | Result / job |
|---|---|---|
| `ping` | — | `{ "uptime_ms": 8123456 }` |
| `status` | — | See below. |
| `identify` | — | Memory-served identify block (§3.5). |
| `get_job` | `{job_id}` | Bare job object. |
| `home` | `{position}` (0..N) | `{ "homed": true, "position": 0 }`. Declares the current physical position (no motion). `busy` during a move. |
| `set_position` | `{position, rotation?}` | **Job.** See below. |
| `stop` | — | `{ "state": "unhomed", "cancelled_job_id": "j-7f21" }` (see caveat). No-op when idle → `{ "state": "idle" }`. |
| `configure` | `{default_rotation?, hold_torque?}` | Echo of the effective config. Persisted across power cycles. |

`set_position` params: `position` 0..N; `rotation` optional (`"shortest"` | `"direct"` |
`"wrap"`, default = `config.default_rotation`). Rotation modes matter because every port the
rotor transits is momentarily opened — `shortest` = shorter arc; `direct` = numeric order,
never across the 0↔N boundary; `wrap` = the complementary arc, across 0↔N. Immediate result:
`{ "job": { "job_id": "j-7f21", "state": "running", "estimated_duration_s": 1.8 } }`. Completed
job `result`: `{ "position": 4, "from_position": 1, "direction": "increasing", "duration_s": 1.82 }`.
Requesting the current position succeeds instantly with a completed job. `succeeded` is reported
only after the motion physically finishes.

`status` result:

```json
{ "state": "idle",              // idle | moving | unhomed
  "homed": true,
  "position": 4,                // null while moving or unhomed
  "target_position": null,      // set while moving
  "job": null,                  // active job object while moving
  "config": { "default_rotation": "shortest", "hold_torque": false } }
```

`configure` fields: `default_rotation` (path strategy when `set_position` omits `rotation`);
`hold_torque` (bool — keep the stepper energized after a move to resist back-pressure, at the
cost of power/heat; default `false`). Omitted fields are unchanged.

**Error codes:** `invalid_request`, `unknown_command`, `invalid_params`, `busy`, `not_homed`,
`hardware_error`, `internal_error`. (No `not_calibrated`.)

> **`stop` caveat.** The valve cannot physically abort a move; `stop` lets the (short, ≤ ~6 s)
> move finish rather than leaving the rotor between detents. Depending on the build it returns
> either `unhomed` (position lost) or `idle` (position preserved). Because `stop` waits out the
> move, it can **block the session for up to ~6 s**, and commands queued behind it stall until
> it returns.

### 3.8 Densitometer commands (`type: densitometer`)

Measures optical absorbance (cell density) and regulates a thermostat. Absorbance needs a
**blank** measured first (`not_calibrated` otherwise).

**identify** — `capabilities`:

```json
{ "device_type": "densitometer", "model": "TDS909A-wide", "serial": "25-006",
  "firmware_version": "legacy", "protocol_version": "1.0",
  "capabilities": { "wavelength_nm": 600, "brightness_levels": 20,
                    "thermostat": { "min_c": 20.0, "max_c": 45.0 },
                    "temperature_sensor": "DS18B20" } }
```

**Command set:**

| `cmd` | `params` | Result / job |
|---|---|---|
| `ping` | — | `{ "uptime_ms": 8123456 }` |
| `status` | — | See below. |
| `identify` | — | Memory-served identify block (§3.5). |
| `get_job` | `{job_id}` | Bare job object. |
| `measure_blank` | — | **Job**; completed `result` `{ "slope", "temperature_c", "sweep":[…20 ints] }`. Stores the baseline. Persisted. |
| `measure` | `{include_raw?}` | **Job**; completed `result` below. `not_calibrated` if no blank. |
| `start_monitoring` | `{interval_s?}` (default 60, min ~10) | `{ "state": "monitoring", "interval_s": 30 }`. Continuous; buffers readings. |
| `get_readings` | `{since_seq?, limit?}` | `{ "readings": [{seq, uptime_ms, absorbance, temperature_c}], "dropped": 0 }`. Ring buffer of 64; `dropped>0` = polled too slowly. |
| `stop_monitoring` | — | Ends monitoring mode. |
| `stop` | — | `{ "state": "idle", "cancelled_job_id": "j-7f21" }`. Cancels job/monitoring, LED off. Always succeeds. |
| `set_thermostat` | `{enabled, target_c?}` | `{ "enabled": true, "target_c": 37.0 }`. `target_c` 20–45. Persisted. |
| `set_tube_correction` | `{factor}` (0.5–2.0) | `{ "tube_correction": 1.03 }`. Persisted. |
| `calibrate_tube` | `{reference_absorbance}` | `{ "tube_correction": 1.042, "based_on_seq": 43 }`. Uses the last measurement. Persisted. |
| `set_led` | `{level}` (0–20) | `{ "level": 12 }`. Diagnostic. |
| `read_raw` | `{level?}` | **Job**; completed `result` `{ "intensities":[…], "levels":[…], "temperature_c" }`. Diagnostic. |

`measure` completed job `result`:

```json
{ "absorbance": 0.523,            // temperature-compensated, tube-corrected
  "absorbance_raw": 0.508,        // before compensation/correction
  "slope": 74.2, "blank_slope": 123.45, "temperature_c": 36.98,
  "tube_correction": 1.03, "seq": 43,
  "raw": null }                   // 20-point sweep if include_raw = true
```

`status` result:

```json
{ "state": "idle",                // idle | measuring | monitoring
  "job": null,
  "temperature_c": 36.98,
  "thermostat": { "enabled": true, "target_c": 37.0, "heating": true, "cooling": false },
  "calibration": { "blank": { "slope": 123.45, "temperature_c": 36.90, "age_s": 754 },  // blank null if none
                   "tube_correction": 1.03 },
  "last_measurement": { "seq": 42, "absorbance": 0.523, "temperature_c": 36.98, "age_s": 12 } }  // null until first
```

**Error codes:** `invalid_request`, `unknown_command`, `invalid_params`, `busy`,
`not_calibrated`, `hardware_error` (`details.component`), `internal_error`. (No `not_homed`.)

**Notes:** while `monitoring`, a plain `measure` is rejected with `busy` — poll `get_readings`
instead. `interval_s` minimum is the sweep duration (~10 s).

---

## 4. Client design notes

Practical guidance for the library. None of this is new API surface — it's how the above
behaves under load and failure.

### 4.1 Correlation ids

Generate a **fresh unique `id`** per request (a UUID is conventional) and match it against the
echoed `id` in the response. It's a correlation aid — SerialHop does not deduplicate on it, so
a retried request with the same `id` executes again.

### 4.2 One command at a time, per device

Each device executes commands **strictly one at a time**. Concurrent commands to the *same*
device queue behind the in-flight one; commands to *different* devices run independently.
Consequences:

- A slow command blocks everything queued behind it on that device. Worst case today: valve
  `stop` (up to ~6 s, §3.7).
- While a device is unreachable and a background reconnect attempt is in progress, even
  memory-served `identify`/`get_job` can briefly block (~2–3 s). Size your per-request timeout
  accordingly (e.g. ≥ 10 s for commands, ≥ 30 s for `discover`).

### 4.3 Handling `503` / unreachable

`503 device_unreachable` means the device isn't responding *right now*; the session is already
retrying in the background (5 s → 60 s backoff, indefinitely). Don't hammer it — back off and
retry, or fall back to `identify`/`get_job` (memory-served) to read last-known state. A device
that goes unreachable **mid-job** fails that job with
`hardware_error: "device became unreachable mid-job"`, readable via `get_job`.

### 4.4 Jobs

- Treat any command whose result is `{ "job": {...} }` as asynchronous — capture
  `result.job.job_id` and poll `get_job` until `state ∈ {succeeded, failed, cancelled}`.
- Only **one active job per device**; a second job-starting command returns `busy` with
  `details.job_id`. Either wait, `stop` the current job, or `pause`/`resume` (pump only).
- History holds the **last 8** completed jobs. Poll and record terminal results promptly; a
  `job_id` older than 8 completions is evicted and `get_job` returns `invalid_params`.

### 4.5 Discover vs. list; caching

- Poll `GET /api/v1/devices` for routine state — it's cheap and idempotent.
- Call `POST /api/v1/discover` only when hardware changed. It's destructive and slow (several
  seconds), and returns `409` if any device has an active job — `stop` jobs first.
- Cache the device list keyed on `discovered_at`; a changed `discovered_at` means the session
  set was rebuilt and any prior `job_id`s are gone.

### 4.6 Quick reference

**HTTP status map:** `200` device/cache-decided · `400` invalid_request · `404` unknown_device
· `503` device_unreachable (except memory-served `identify`/`get_job`) · `409` discover
conflict (infra `{error, detail}` body).

**Universal commands (every device):** `identify` (memory-served), `get_job` (memory-served),
`ping`, `status`, `stop`.
