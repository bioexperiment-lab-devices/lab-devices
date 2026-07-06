# lab_devices Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fully-async Python library (`lab_devices`) that discovers and imperatively drives lab instruments (peristaltic pump, distribution valve, densitometer) over the SerialHop / lab-bridge HTTP-JSON API.

**Architecture:** Two layers with a strict one-way dependency. A core `LabClient(host, port)` owns an `httpx.AsyncClient`, hands out lazy typed device handles, and routes every command through a single `transport` module that owns HTTP and maps the JSON envelope to a rich exception hierarchy. Long-running commands return a `Job` handle you poll to completion. An optional, server-only `LabRegistry` (discovery module) resolves a username → `host:port` via the internal lab-bridge roster and builds a ready `LabClient`. Results are lenient dataclasses that preserve unknown fields on `.raw`.

**Tech Stack:** Python 3.11+, `httpx` (only runtime dep), `pytest` + `pytest-asyncio` (hermetic tests via `httpx.MockTransport`), `mypy`, `ruff`, `hatchling`.

**Spec:** `docs/superpowers/specs/2026-07-06-lab-devices-library-design.md` — read it before starting.

## Global Constraints

Every task's requirements implicitly include these. Copied verbatim from the spec:

- **Python 3.11+.** Use `X | None`, `kw_only` dataclass fields, `asyncio.timeout`.
- **Runtime dependency: `httpx` only.** No pydantic, no framework. Dev-only deps: `pytest`, `pytest-asyncio`, `mypy`, `ruff`.
- **Fully async.** No synchronous public API. No blocking I/O on the event loop (the TCP liveness probe uses `asyncio.open_connection`).
- **The envelope is authoritative.** Branch on `body["status"]` / `body["error"]["code"]`, never on HTTP status alone. Any `status:"error"` raises.
- **Lenient models.** Every result dataclass subclasses `RawModel`, keeps the full JSON on `.raw`, and never crashes on unknown/missing fields.
- **Unknown error `code` strings degrade to base `LabError`** (never `KeyError`).
- **Discovery is server-only, internal roster, NO token.** `GET http://siteapp:8000/api/clients/` returning `{name:{host,port}}`; env override `LAB_DEVICES_DISCOVERY_URL`.
- **Typed package.** Ship `py.typed`. Public API re-exported from `lab_devices/__init__.py`; `LabRegistry` stays under `lab_devices.discovery`.
- **TDD + frequent commits.** Test-first, one deliverable per task, commit at the end of every task.

**Conventions used throughout:**
- Package import root: `lab_devices`. Tests live in `tests/`.
- `httpx.AsyncClient` carries the `base_url`; `Transport` never builds host strings.
- All tests are `async def` and marked with `@pytest.mark.asyncio`. `asyncio_mode = "auto"` is set in `pyproject.toml`, so the marker is implicit — plain `async def test_*` works.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/lab_devices/__init__.py`
- Create: `src/lab_devices/py.typed` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/test_smoke.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable, importable `lab_devices` package with `__version__`; a working `pytest` invocation.

- [ ] **Step 1: Write `.gitignore`**

```
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
dist/
build/
.venv/
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "lab-devices"
version = "0.1.0"
description = "Async Python library to discover and manage lab devices (pump, valve, densitometer)."
requires-python = ">=3.11"
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "mypy>=1.8", "ruff>=0.4"]

[tool.hatch.build.targets.wheel]
packages = ["src/lab_devices"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["src/lab_devices"]

[tool.ruff]
line-length = 100
target-version = "py311"
```

- [ ] **Step 3: Write `src/lab_devices/__init__.py`**

```python
"""Async library to discover and manage lab devices."""

__version__ = "0.1.0"
```

Create empty `src/lab_devices/py.typed` and empty `tests/__init__.py`.

- [ ] **Step 4: Write the failing smoke test — `tests/test_smoke.py`**

```python
import lab_devices


def test_version_exposed():
    assert isinstance(lab_devices.__version__, str)
    assert lab_devices.__version__
```

- [ ] **Step 5: Install and run**

Run:
```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_smoke.py -v
```
Expected: `test_version_exposed PASSED`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: scaffold lab_devices package"
```

---

### Task 2: Exception hierarchy

**Files:**
- Create: `src/lab_devices/errors.py`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Root `LabDevicesError(Exception)`.
  - `DiscoveryError(LabDevicesError)` + subclasses `ClientLookupEndpointUnreachable`, `ClientLookupEndpointError`, `UnknownLabClient(name, available)`, `LabOffline(name, host, port)`.
  - `LabError(LabDevicesError)` with `.code, .message, .details, .request_id`, plus subclasses `InvalidRequestError`, `UnknownDeviceError`, `DeviceUnreachableError`, `UnknownCommandError`, `InvalidParamsError`, `BusyError` (`.job_id`), `NotCalibratedError`, `NotHomedError`, `HardwareError` (`.component`), `InternalDeviceError`, `JobFailedError` (`.error`), `JobCancelledError`, `JobTimeoutError`, `DiscoveryInProgressError`, `JobInProgressError` (`.detail`), `DiscoveryFailedError`, `LabProtocolError`.
  - `map_command_error(error: dict, request_id: str) -> LabError` — maps an envelope error object to the right exception instance (unknown code → base `LabError`).

- [ ] **Step 1: Write the failing test — `tests/test_errors.py`**

```python
import pytest

from lab_devices import errors


def test_hierarchy_roots():
    assert issubclass(errors.LabError, errors.LabDevicesError)
    assert issubclass(errors.DiscoveryError, errors.LabDevicesError)
    assert issubclass(errors.BusyError, errors.LabError)


def test_map_known_code_to_subclass():
    err = errors.map_command_error(
        {"code": "busy", "message": "device busy", "details": {"job_id": "j-1"}},
        request_id="req-1",
    )
    assert isinstance(err, errors.BusyError)
    assert err.code == "busy"
    assert err.message == "device busy"
    assert err.request_id == "req-1"
    assert err.job_id == "j-1"


def test_map_unknown_code_degrades_to_base():
    err = errors.map_command_error(
        {"code": "some_future_code", "message": "hmm"}, request_id="req-2"
    )
    assert type(err) is errors.LabError
    assert err.code == "some_future_code"


def test_hardware_error_component():
    err = errors.map_command_error(
        {"code": "hardware_error", "message": "fault", "details": {"component": "motor"}},
        request_id="r",
    )
    assert isinstance(err, errors.HardwareError)
    assert err.component == "motor"


def test_unknown_lab_client_carries_names():
    err = errors.UnknownLabClient("nope", available=["a", "b"])
    assert err.name == "nope"
    assert err.available == ["a", "b"]
    assert "a" in str(err)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_errors.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.errors` / attributes missing).

- [ ] **Step 3: Write `src/lab_devices/errors.py`**

```python
"""Exception hierarchy for lab_devices. See spec §6."""

from __future__ import annotations

from typing import Any


class LabDevicesError(Exception):
    """Root of every error raised by this library."""


# --------------------------------------------------------------------------- #
# Discovery layer (lab-bridge / roster)                                        #
# --------------------------------------------------------------------------- #
class DiscoveryError(LabDevicesError):
    """Base for the discovery (LabRegistry) layer."""


class ClientLookupEndpointUnreachable(DiscoveryError):
    """Connection refused / timeout reaching the roster endpoint."""


class ClientLookupEndpointError(DiscoveryError):
    """Roster endpoint returned 5xx or a malformed/non-JSON body."""


class UnknownLabClient(DiscoveryError):
    """Requested lab name is not in the roster."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        super().__init__(f"unknown lab {name!r}; available: {', '.join(available) or '(none)'}")


class LabOffline(DiscoveryError):
    """Lab is in the roster but its tunnel is not reachable (TCP probe failed)."""

    def __init__(self, name: str, host: str, port: int) -> None:
        self.name = name
        self.host = host
        self.port = port
        super().__init__(f"lab {name!r} is offline ({host}:{port} not reachable)")


# --------------------------------------------------------------------------- #
# Device / agent layer                                                         #
# --------------------------------------------------------------------------- #
class LabError(LabDevicesError):
    """Any error from talking to a SerialHop agent."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.details = details or {}
        self.request_id = request_id
        super().__init__(message)


# -- device-command errors (code / message / details / request_id) -- #
class InvalidRequestError(LabError):
    pass


class UnknownDeviceError(LabError):
    pass


class DeviceUnreachableError(LabError):
    pass


class UnknownCommandError(LabError):
    pass


class InvalidParamsError(LabError):
    pass


class BusyError(LabError):
    @property
    def job_id(self) -> str | None:
        return self.details.get("job_id")


class NotCalibratedError(LabError):
    pass


class NotHomedError(LabError):
    pass


class HardwareError(LabError):
    @property
    def component(self) -> str | None:
        return self.details.get("component")


class InternalDeviceError(LabError):
    pass


# -- job errors -- #
class JobFailedError(LabError):
    """A job reached state 'failed'. `.error` is the raw error object from the job."""

    def __init__(self, error: dict[str, Any], *, request_id: str | None = None) -> None:
        self.error = error or {}
        super().__init__(
            self.error.get("message", "job failed"),
            code=self.error.get("code"),
            details=self.error.get("details"),
            request_id=request_id,
        )


class JobCancelledError(LabError):
    pass


class JobTimeoutError(LabError):
    pass


# -- agent-infra errors ({error, detail} shape; message + detail only) -- #
class DiscoveryInProgressError(LabError):
    pass


class JobInProgressError(LabError):
    def __init__(self, message: str, *, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(message)


class DiscoveryFailedError(LabError):
    pass


class LabProtocolError(LabError):
    """The response violated the envelope contract (bad shape, id mismatch, oversize body)."""


_COMMAND_ERROR_CLASSES: dict[str, type[LabError]] = {
    "invalid_request": InvalidRequestError,
    "unknown_device": UnknownDeviceError,
    "device_unreachable": DeviceUnreachableError,
    "unknown_command": UnknownCommandError,
    "invalid_params": InvalidParamsError,
    "busy": BusyError,
    "not_calibrated": NotCalibratedError,
    "not_homed": NotHomedError,
    "hardware_error": HardwareError,
    "internal_error": InternalDeviceError,
}


def map_command_error(error: dict[str, Any], request_id: str) -> LabError:
    """Map an envelope error object to a specific exception (unknown code -> base LabError)."""
    code = error.get("code")
    message = error.get("message", "device command failed")
    details = error.get("details")
    cls = _COMMAND_ERROR_CLASSES.get(code or "", LabError)
    return cls(message, code=code, details=details, request_id=request_id)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_errors.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: exception hierarchy and command-error mapping"
```

---

### Task 3: Lenient model base + common models

**Files:**
- Create: `src/lab_devices/models/__init__.py`
- Create: `src/lab_devices/models/common.py`
- Test: `tests/test_models_common.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RawModel` dataclass base: `raw` field + `from_raw(cls, data) -> Self`, honoring a `_NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]]` map (`bool` = is-list).
  - `Range(min, max)`, `DeviceInfo(id, type, port, connected, identify)`, `Identify(device_type, model, serial, firmware_version, protocol_version, capabilities)`, `AgentInfo(version, build_sha, os, arch, hostname, machine_id, uptime_seconds)`, `PingResult(uptime_ms)`.
  - `models/__init__.py` re-exports all of the above.

- [ ] **Step 1: Write the failing test — `tests/test_models_common.py`**

```python
from lab_devices.models import DeviceInfo, Identify, PingResult, RawModel


def test_from_raw_keeps_unknown_fields():
    info = PingResult.from_raw({"uptime_ms": 42, "surprise_field": "kept"})
    assert info.uptime_ms == 42
    assert info.raw["surprise_field"] == "kept"


def test_missing_fields_default_to_none():
    info = PingResult.from_raw({})
    assert info.uptime_ms is None


def test_none_input_is_safe():
    info = PingResult.from_raw(None)
    assert info.uptime_ms is None
    assert info.raw == {}


def test_nested_identify_parsed():
    info = DeviceInfo.from_raw(
        {
            "id": "pump_1",
            "type": "pump",
            "port": "COM3",
            "connected": True,
            "identify": {"device_type": "pump", "model": "peristaltic-1ch"},
        }
    )
    assert info.id == "pump_1"
    assert isinstance(info.identify, Identify)
    assert info.identify.model == "peristaltic-1ch"


def test_nested_null_stays_none():
    info = DeviceInfo.from_raw(
        {"id": "valve_1", "type": "valve", "port": "COM7", "connected": False, "identify": None}
    )
    assert info.identify is None


def test_rawmodel_is_base():
    assert issubclass(DeviceInfo, RawModel)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_models_common.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `src/lab_devices/models/common.py`**

```python
"""Lenient dataclass models. Unknown/missing fields never crash parsing; the full
JSON payload is preserved on `.raw`. See spec §7."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Mapping, Self


@dataclass
class RawModel:
    """Base for all result models. Subclass fields must have defaults."""

    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, kw_only=True)

    # field_name -> (nested model, is_list)
    _NESTED: ClassVar[dict[str, tuple[type["RawModel"], bool]]] = {}

    @classmethod
    def from_raw(cls, data: Mapping[str, Any] | None) -> Self:
        data = data or {}
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name == "raw" or f.name not in data:
                continue
            value = data[f.name]
            nested = cls._NESTED.get(f.name)
            if nested is not None and value is not None:
                model, is_list = nested
                value = (
                    [model.from_raw(v) for v in value]
                    if is_list
                    else model.from_raw(value)
                )
            kwargs[f.name] = value
        return cls(raw=dict(data), **kwargs)


@dataclass
class Range(RawModel):
    min: float | None = None
    max: float | None = None


@dataclass
class Identify(RawModel):
    device_type: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware_version: str | None = None
    protocol_version: str | None = None
    # dict by default; typed devices replace this with a typed capabilities model.
    capabilities: Any = None


@dataclass
class DeviceInfo(RawModel):
    id: str | None = None
    type: str | None = None
    port: str | None = None
    connected: bool | None = None
    identify: Identify | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"identify": (Identify, False)}


@dataclass
class AgentInfo(RawModel):
    version: str | None = None
    build_sha: str | None = None
    os: str | None = None
    arch: str | None = None
    hostname: str | None = None
    machine_id: str | None = None
    uptime_seconds: int | None = None


@dataclass
class PingResult(RawModel):
    uptime_ms: int | None = None
```

- [ ] **Step 4: Write `src/lab_devices/models/__init__.py`**

```python
from lab_devices.models.common import (
    AgentInfo,
    DeviceInfo,
    Identify,
    PingResult,
    Range,
    RawModel,
)

__all__ = [
    "AgentInfo",
    "DeviceInfo",
    "Identify",
    "PingResult",
    "Range",
    "RawModel",
]
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_models_common.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: lenient RawModel base and common models"
```

---

### Task 4: Transport — device commands

**Files:**
- Create: `src/lab_devices/transport.py`
- Test: `tests/test_transport_command.py`

**Interfaces:**
- Consumes: `errors.map_command_error`, `errors.LabProtocolError`.
- Produces:
  - `Transport(client: httpx.AsyncClient, *, discover_timeout: float = 30.0)`.
  - `async command(device_id, cmd, params=None, *, request_id=None, timeout=None) -> Any` — sends the envelope to `POST /api/v1/devices/{id}/command`, generates a `uuid4` id when none given, verifies the echoed id, raises via `map_command_error` on `status:"error"`, returns `body["result"]` on success. Raises `LabProtocolError` on a >32 KiB body, a non-JSON/malformed envelope, or an id mismatch.

- [ ] **Step 1: Write the failing test — `tests/test_transport_command.py`**

```python
import httpx
import pytest

from lab_devices import errors
from lab_devices.transport import Transport


def make_transport(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://lab")
    return Transport(client), client


async def test_success_returns_result():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        import json

        env = json.loads(body)
        return httpx.Response(
            200, json={"id": env["id"], "status": "ok", "result": {"uptime_ms": 5}}
        )

    transport, client = make_transport(handler)
    try:
        result = await transport.command("pump_1", "ping")
        assert result == {"uptime_ms": 5}
    finally:
        await client.aclose()


async def test_device_error_raises_mapped_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        env = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "id": env["id"],
                "status": "error",
                "error": {"code": "invalid_params", "message": "bad", "details": {"param": "x"}},
            },
        )

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.InvalidParamsError):
            await transport.command("pump_1", "dispense", {"volume_ml": -1})
    finally:
        await client.aclose()


async def test_unreachable_503_maps_from_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        env = json.loads(request.read())
        return httpx.Response(
            503,
            json={
                "id": env["id"],
                "status": "error",
                "error": {"code": "device_unreachable", "message": "no"},
            },
        )

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.DeviceUnreachableError):
            await transport.command("pump_1", "status")
    finally:
        await client.aclose()


async def test_id_mismatch_raises_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "WRONG", "status": "ok", "result": {}})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.LabProtocolError):
            await transport.command("pump_1", "ping")
    finally:
        await client.aclose()


async def test_oversize_body_rejected_before_send():
    sent = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent = True
        return httpx.Response(200, json={})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.LabProtocolError):
            await transport.command("pump_1", "x", {"blob": "a" * 40000})
        assert sent is False
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_transport_command.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.transport`).

- [ ] **Step 3: Write `src/lab_devices/transport.py`**

```python
"""Sole owner of HTTP + JSON. Devices call semantic methods here; this module maps
the envelope and infra responses to the exception hierarchy. See spec §4.4, §6."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from lab_devices import errors

_MAX_BODY_BYTES = 32 * 1024


class Transport:
    def __init__(self, client: httpx.AsyncClient, *, discover_timeout: float = 30.0) -> None:
        self._client = client
        self._discover_timeout = discover_timeout

    async def command(
        self,
        device_id: str,
        cmd: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        req_id = request_id or str(uuid.uuid4())
        envelope: dict[str, Any] = {"id": req_id, "cmd": cmd}
        if params is not None:
            envelope["params"] = params

        payload = json.dumps(envelope).encode()
        if len(payload) > _MAX_BODY_BYTES:
            raise errors.LabProtocolError(
                f"request body {len(payload)} bytes exceeds 32 KiB cap", request_id=req_id
            )

        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = await self._client.post(
            f"/api/v1/devices/{device_id}/command", content=payload, **kwargs
        )
        return self._parse_envelope(response, req_id)

    @staticmethod
    def _parse_envelope(response: httpx.Response, req_id: str) -> Any:
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise errors.LabProtocolError(
                f"non-JSON response (HTTP {response.status_code})", request_id=req_id
            ) from exc
        if not isinstance(body, dict) or "status" not in body:
            raise errors.LabProtocolError("malformed envelope", request_id=req_id)

        echoed = body.get("id", "")
        if echoed not in (req_id, ""):
            raise errors.LabProtocolError(
                f"correlation id mismatch: sent {req_id!r}, got {echoed!r}", request_id=req_id
            )

        if body["status"] == "ok":
            return body.get("result")
        if body["status"] == "error":
            raise errors.map_command_error(body.get("error") or {}, request_id=req_id)
        raise errors.LabProtocolError(f"unknown status {body['status']!r}", request_id=req_id)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_transport_command.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: transport command envelope + error mapping"
```

---

### Task 5: Transport — infra endpoints

**Files:**
- Modify: `src/lab_devices/transport.py` (add methods to `Transport`)
- Test: `tests/test_transport_infra.py`

**Interfaces:**
- Consumes: `Transport` from Task 4; discovery/infra error classes from Task 2.
- Produces (methods on `Transport`, all returning the raw JSON dict — parsing to models happens in `client.py`):
  - `async get_devices() -> dict` — `GET /api/v1/devices`.
  - `async discover() -> dict` — `POST /api/v1/discover` (uses `discover_timeout`); maps `409 "discovery in progress"` → `DiscoveryInProgressError`, `409 "job in progress"` → `JobInProgressError(detail=...)`, `500` → `DiscoveryFailedError`.
  - `async disconnect(port: str | None = None) -> dict` — `POST /devices/disconnect` (`?port=`); `404` → `UnknownDeviceError`.
  - `async agent_info() -> dict` — `GET /agent/info`.

- [ ] **Step 1: Write the failing test — `tests/test_transport_infra.py`**

```python
import httpx
import pytest

from lab_devices import errors
from lab_devices.transport import Transport


def make_transport(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://lab")
    return Transport(client), client


async def test_get_devices_returns_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/devices"
        return httpx.Response(200, json={"devices": [], "discovered_at": None})

    transport, client = make_transport(handler)
    try:
        body = await transport.get_devices()
        assert body["devices"] == []
    finally:
        await client.aclose()


async def test_discover_409_discovery_in_progress():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "discovery in progress"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.DiscoveryInProgressError):
            await transport.discover()
    finally:
        await client.aclose()


async def test_discover_409_job_in_progress_carries_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409, json={"error": "job in progress", "detail": "pump_1 has an active job"}
        )

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.JobInProgressError) as excinfo:
            await transport.discover()
        assert "pump_1" in (excinfo.value.detail or "")
    finally:
        await client.aclose()


async def test_discover_500_maps_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "discovery failed", "detail": "boom"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.DiscoveryFailedError):
            await transport.discover()
    finally:
        await client.aclose()


async def test_disconnect_404_unknown_device():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "no device on port"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.UnknownDeviceError):
            await transport.disconnect(port="COM9")
    finally:
        await client.aclose()


async def test_disconnect_ok_returns_count():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"released": 3})

    transport, client = make_transport(handler)
    try:
        body = await transport.disconnect()
        assert body["released"] == 3
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_transport_infra.py -v`
Expected: FAIL (`AttributeError: 'Transport' object has no attribute 'get_devices'`).

- [ ] **Step 3: Add methods to `src/lab_devices/transport.py`**

Append these methods inside the `Transport` class (after `command`). Add `from typing import Any` is already imported.

```python
    async def get_devices(self) -> dict[str, Any]:
        response = await self._client.get("/api/v1/devices")
        return self._infra_body(response)

    async def discover(self) -> dict[str, Any]:
        response = await self._client.post("/api/v1/discover", timeout=self._discover_timeout)
        if response.status_code == 409:
            body = self._safe_json(response)
            if body.get("error") == "job in progress":
                raise errors.JobInProgressError(
                    body.get("error", "job in progress"), detail=body.get("detail")
                )
            raise errors.DiscoveryInProgressError(body.get("error", "discovery in progress"))
        if response.status_code >= 500:
            body = self._safe_json(response)
            raise errors.DiscoveryFailedError(
                body.get("detail") or body.get("error", "discovery failed")
            )
        return self._infra_body(response)

    async def disconnect(self, port: str | None = None) -> dict[str, Any]:
        params = {"port": port} if port is not None else None
        response = await self._client.post("/devices/disconnect", params=params)
        if response.status_code == 404:
            body = self._safe_json(response)
            raise errors.UnknownDeviceError(
                body.get("error", "no device on that port"),
                code="unknown_device",
                details={"port": port},
            )
        return self._infra_body(response)

    async def agent_info(self) -> dict[str, Any]:
        response = await self._client.get("/agent/info")
        return self._infra_body(response)

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

    def _infra_body(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 500:
            raise errors.LabProtocolError(f"server error HTTP {response.status_code}")
        body = self._safe_json(response)
        if not body:
            raise errors.LabProtocolError(f"malformed infra body (HTTP {response.status_code})")
        return body
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_transport_infra.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: transport infra endpoints (devices/discover/disconnect/agent_info)"
```

---

### Task 6: FakeLab test harness

**Files:**
- Create: `tests/fakelab.py`
- Create: `tests/conftest.py`
- Test: `tests/test_fakelab.py`

**Interfaces:**
- Consumes: `Transport`.
- Produces:
  - `FakeLab` — a stateful object whose `.handler(request) -> httpx.Response` implements the SerialHop surface: the command envelope, a deterministic job engine (a job advances one step per `get_job` poll and completes after `polls_to_complete`, default 1), memory-served `identify`/`get_job`, and the infra endpoints. Configurable knobs: `polls_to_complete`, `fail_job` (make the next job fail), `unreachable` (a set of device ids that return 503).
  - `FakeLab.add_device(id, type, identify=..., **canned)` to register devices and canned command results.
  - A pytest fixture `lab_transport` yielding `(FakeLab, Transport)` wired via `httpx.MockTransport`.

- [ ] **Step 1: Write `tests/fakelab.py`**

```python
"""In-memory fake of the SerialHop agent API for hermetic tests. No hardware, no network."""

from __future__ import annotations

import json
from typing import Any

import httpx

# Commands that start a job (immediate result is {"job": {...}}).
JOB_COMMANDS = {
    "dispense",
    "set_position",
    "measure",
    "measure_blank",
    "start_calibration",
    "read_raw",
}

# Canned "succeeded" job results per command.
JOB_RESULTS: dict[str, dict[str, Any]] = {
    "dispense": {"dispensed_ml": 10.0, "duration_s": 199.4, "mean_speed_ml_min": 3.01},
    "set_position": {"position": 4, "from_position": 1, "direction": "increasing"},
    "measure": {"absorbance": 0.523, "temperature_c": 36.98, "seq": 43},
    "measure_blank": {"slope": 123.45, "temperature_c": 36.9},
    "start_calibration": {"steps": 48000, "duration_s": 118.7},
    "read_raw": {"intensities": [1, 2, 3], "temperature_c": 36.9},
}


class FakeJob:
    def __init__(self, job_id: str, cmd: str) -> None:
        self.job_id = job_id
        self.cmd = cmd
        self.state = "running"
        self.polls = 0
        self.result: dict[str, Any] | None = None
        self.error: dict[str, Any] | None = None


class FakeLab:
    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {}
        self.jobs: dict[str, FakeJob] = {}
        self.unreachable: set[str] = set()
        self.polls_to_complete = 1
        self.fail_job = False
        self._job_counter = 0

    # ---- setup helpers ----
    def add_device(
        self, device_id: str, type_: str, identify: dict[str, Any] | None = None, **canned: Any
    ) -> None:
        self.devices[device_id] = {
            "id": device_id,
            "type": type_,
            "port": f"COM-{device_id}",
            "connected": True,
            "identify": identify,
            "_canned": canned,
        }

    # ---- request routing ----
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/devices":
            return self._devices_list()
        if path == "/api/v1/discover":
            return self._devices_list()
        if path == "/devices/disconnect":
            return httpx.Response(200, json={"released": len(self.devices)})
        if path == "/agent/info":
            return httpx.Response(200, json={"version": "2.0.0+test", "hostname": "FAKE"})
        if path.startswith("/api/v1/devices/") and path.endswith("/command"):
            device_id = path[len("/api/v1/devices/") : -len("/command")]
            return self._command(device_id, json.loads(request.read()))
        return httpx.Response(404, json={"error": "not found"})

    def _devices_list(self) -> httpx.Response:
        devices = [
            {k: v for k, v in d.items() if not k.startswith("_")} for d in self.devices.values()
        ]
        return httpx.Response(
            200, json={"devices": devices, "discovered_at": "2026-07-06T12:00:00Z"}
        )

    def _command(self, device_id: str, env: dict[str, Any]) -> httpx.Response:
        req_id = env.get("id", "")
        cmd = env.get("cmd")
        params = env.get("params") or {}

        def ok(result: Any) -> httpx.Response:
            return httpx.Response(200, json={"id": req_id, "status": "ok", "result": result})

        def err(status: int, code: str, message: str) -> httpx.Response:
            return httpx.Response(
                status,
                json={"id": req_id, "status": "error", "error": {"code": code, "message": message}},
            )

        # get_job / identify are memory-served (200 even if unreachable).
        if cmd == "get_job":
            job = self.jobs.get(params.get("job_id", ""))
            if job is None:
                return err(200, "invalid_params", "unknown job_id")
            self._advance(job)
            return ok(self._job_object(job))
        if cmd == "identify":
            ident = self.devices.get(device_id, {}).get("identify")
            if ident is None:
                return err(503, "device_unreachable", "never attached")
            return ok(ident)

        if device_id not in self.devices:
            return err(404, "unknown_device", f"no device with id {device_id}")
        if device_id in self.unreachable:
            return err(503, "device_unreachable", "device is not responding")

        if cmd == "ping":
            return ok({"uptime_ms": 8123456})
        if cmd == "status":
            return ok(self.devices[device_id].get("_canned", {}).get("status", {"state": "idle"}))
        if cmd == "stop":
            return ok({"state": "idle"})
        if cmd in JOB_COMMANDS:
            return ok({"job": self._start_job(cmd)})
        # other commands: return canned result or an empty ok.
        return ok(self.devices[device_id].get("_canned", {}).get(cmd, {}))

    # ---- job engine ----
    def _start_job(self, cmd: str) -> dict[str, Any]:
        self._job_counter += 1
        job = FakeJob(f"j-{self._job_counter}", cmd)
        self.jobs[job.job_id] = job
        return {"job_id": job.job_id, "state": "running", "estimated_duration_s": 1.0}

    def _advance(self, job: FakeJob) -> None:
        if job.state != "running":
            return
        job.polls += 1
        if job.polls >= self.polls_to_complete:
            if self.fail_job:
                job.state = "failed"
                job.error = {"code": "hardware_error", "message": "device became unreachable"}
            else:
                job.state = "succeeded"
                job.result = JOB_RESULTS.get(job.cmd, {})

    def _job_object(self, job: FakeJob) -> dict[str, Any]:
        progress = 1.0 if job.state == "succeeded" else (0.0 if job.state == "running" else 0.5)
        return {
            "job_id": job.job_id,
            "state": job.state,
            "progress": progress,
            "estimated_duration_s": 1.0,
            "elapsed_s": float(job.polls),
            "result": job.result,
            "error": job.error,
        }
```

- [ ] **Step 2: Write `tests/conftest.py`**

```python
import httpx
import pytest

from lab_devices.transport import Transport
from tests.fakelab import FakeLab


@pytest.fixture
def lab_transport():
    fake = FakeLab()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    yield fake, Transport(client)
    # AsyncClient cleanup handled per-test via the returned client is not needed for MockTransport.
```

Note: `httpx.MockTransport` needs no network teardown; leaving the client unclosed is fine in tests, but to stay tidy, tests that construct their own client should close it. This fixture is used by tests that only need the transport.

- [ ] **Step 3: Write the failing test — `tests/test_fakelab.py`**

```python
async def test_ping_and_devices_list(lab_transport):
    fake, transport = lab_transport
    fake.add_device("pump_1", "pump")
    assert (await transport.command("pump_1", "ping"))["uptime_ms"] == 8123456
    body = await transport.get_devices()
    assert body["devices"][0]["id"] == "pump_1"


async def test_job_completes_after_polls(lab_transport):
    fake, transport = lab_transport
    fake.add_device("pump_1", "pump")
    fake.polls_to_complete = 2
    started = await transport.command("pump_1", "dispense", {"volume_ml": 10, "speed_ml_min": 3})
    job_id = started["job"]["job_id"]
    first = await transport.command("pump_1", "get_job", {"job_id": job_id})
    assert first["state"] == "running"
    second = await transport.command("pump_1", "get_job", {"job_id": job_id})
    assert second["state"] == "succeeded"
    assert second["result"]["dispensed_ml"] == 10.0


async def test_unreachable_device(lab_transport):
    from lab_devices import errors

    fake, transport = lab_transport
    fake.add_device("pump_1", "pump")
    fake.unreachable.add("pump_1")
    import pytest

    with pytest.raises(errors.DeviceUnreachableError):
        await transport.command("pump_1", "status")
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_fakelab.py -v`
Expected: all PASS (the harness is exercised through the real `Transport`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "test: stateful FakeLab harness + transport fixture"
```

---

### Task 7: Job and PumpJob

**Files:**
- Create: `src/lab_devices/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `Transport`, error classes. Assumes a `device` object exposing `.id: str`, `._transport: Transport`, `async stop()`, and (for `PumpJob`) `async pause()`, `async resume()`. To avoid depending on Task 8, tests use a tiny stub device wrapping a `Transport`.
- Produces:
  - `Job(device, job_id, *, result_model=None, data=None)` with attributes `job_id, state, progress, estimated_duration_s, elapsed_s, error, raw`.
  - `async refresh() -> Self`, `async result(*, poll_interval=0.25, max_interval=2.0, timeout=None) -> Any`, `async cancel()`.
  - `PumpJob(Job)` adds `async pause()`, `async resume()`.
  - `Job.from_start_result(device, result, *, result_model=None) -> Job` — builds a job from a `{"job": {...}}` start payload.

- [ ] **Step 1: Write the failing test — `tests/test_jobs.py`**

```python
import httpx
import pytest

from lab_devices import errors
from lab_devices.jobs import Job
from lab_devices.models import RawModel
from lab_devices.transport import Transport
from tests.fakelab import FakeLab
from dataclasses import dataclass


@dataclass
class _DispenseResult(RawModel):
    dispensed_ml: float | None = None


class _StubDevice:
    def __init__(self, transport: Transport, device_id: str) -> None:
        self._transport = transport
        self.id = device_id

    async def stop(self):
        return await self._transport.command(self.id, "stop")


def _wire():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    transport = Transport(client)
    return fake, transport, _StubDevice(transport, "pump_1"), client


async def test_result_polls_to_success_and_parses_model():
    fake, transport, device, client = _wire()
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started, result_model=_DispenseResult)
        assert job.state == "running"
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, _DispenseResult)
        assert result.dispensed_ml == 10.0
        assert job.state == "succeeded"
    finally:
        await client.aclose()


async def test_failed_job_raises():
    fake, transport, device, client = _wire()
    fake.fail_job = True
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started)
        with pytest.raises(errors.JobFailedError):
            await job.result(poll_interval=0.0)
    finally:
        await client.aclose()


async def test_timeout_raises_without_cancelling():
    fake, transport, device, client = _wire()
    fake.polls_to_complete = 10_000  # never completes in time
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started)
        with pytest.raises(errors.JobTimeoutError):
            await job.result(poll_interval=0.01, timeout=0.05)
    finally:
        await client.aclose()


async def test_refresh_updates_progress():
    fake, transport, device, client = _wire()
    fake.polls_to_complete = 2
    try:
        started = await transport.command("pump_1", "dispense", {"volume_ml": 10})
        job = Job.from_start_result(device, started)
        await job.refresh()
        assert job.state == "running"
        await job.refresh()
        assert job.state == "succeeded"
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.jobs`).

- [ ] **Step 3: Write `src/lab_devices/jobs.py`**

```python
"""Job handles for long-running commands. See spec §4.3."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Self

from lab_devices import errors
from lab_devices.models import RawModel

if TYPE_CHECKING:
    from lab_devices.devices.base import Device

_TERMINAL = {"succeeded", "failed", "cancelled"}


class Job:
    def __init__(
        self,
        device: "Device",
        job_id: str,
        *,
        result_model: type[RawModel] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._device = device
        self.job_id = job_id
        self._result_model = result_model
        self.state = "running"
        self.progress: float | None = None
        self.estimated_duration_s: float | None = None
        self.elapsed_s: float | None = None
        self.error: dict[str, Any] | None = None
        self.raw: dict[str, Any] = {}
        if data:
            self._update(data)

    @classmethod
    def from_start_result(
        cls,
        device: "Device",
        result: Any,
        *,
        result_model: type[RawModel] | None = None,
    ) -> Self:
        job_obj = (result or {}).get("job") if isinstance(result, dict) else None
        if not isinstance(job_obj, dict) or "job_id" not in job_obj:
            raise errors.LabProtocolError("command did not return a job object")
        return cls(device, job_obj["job_id"], result_model=result_model, data=job_obj)

    def _update(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.state = data.get("state", self.state)
        self.progress = data.get("progress", self.progress)
        self.estimated_duration_s = data.get("estimated_duration_s", self.estimated_duration_s)
        self.elapsed_s = data.get("elapsed_s", self.elapsed_s)
        self.error = data.get("error", self.error)

    async def refresh(self) -> Self:
        data = await self._device._transport.command(
            self._device.id, "get_job", {"job_id": self.job_id}
        )
        if isinstance(data, dict):
            self._update(data)
        return self

    async def result(
        self,
        *,
        poll_interval: float = 0.25,
        max_interval: float = 2.0,
        timeout: float | None = None,
    ) -> Any:
        interval = poll_interval
        try:
            async with asyncio.timeout(timeout):
                while self.state not in _TERMINAL:
                    await self.refresh()
                    if self.state in _TERMINAL:
                        break
                    await asyncio.sleep(interval)
                    interval = min(interval * 2 or max_interval, max_interval)
        except TimeoutError as exc:
            raise errors.JobTimeoutError(
                f"job {self.job_id} did not finish within {timeout}s"
            ) from exc

        if self.state == "succeeded":
            payload = self.raw.get("result")
            if self._result_model is not None:
                return self._result_model.from_raw(payload)
            return payload
        if self.state == "failed":
            raise errors.JobFailedError(self.error or {})
        raise errors.JobCancelledError(f"job {self.job_id} was cancelled")

    async def cancel(self) -> Any:
        return await self._device.stop()


class PumpJob(Job):
    async def pause(self) -> Any:
        return await self._device.pause()

    async def resume(self) -> Any:
        return await self._device.resume()
```

Note the backoff line: `interval = min(interval * 2 or max_interval, max_interval)` — when `poll_interval=0.0`, `0.0 * 2` is falsy, so it jumps to `max_interval`; tests using `poll_interval=0.0` complete in the first iteration anyway.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_jobs.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: Job/PumpJob polling, result parsing, timeout, cancel"
```

---

### Task 8: Device base class

**Files:**
- Create: `src/lab_devices/devices/__init__.py` (empty for now)
- Create: `src/lab_devices/devices/base.py`
- Test: `tests/test_device_base.py`

**Interfaces:**
- Consumes: `Transport`, `Job`, models (`PingResult`, `Identify`), errors.
- Produces:
  - `Device(transport: Transport, device_id: str)` with `.id`, `.type` (id prefix before `_`), `._transport`.
  - Classvars overridable by subclasses: `STATUS_MODEL: type[RawModel] | None = None`, `CAPABILITIES_MODEL: type[RawModel] | None = None`.
  - `async ping() -> PingResult`, `async status() -> Any` (parsed via `STATUS_MODEL` when set, else raw dict), `async identify() -> Identify` (capabilities parsed via `CAPABILITIES_MODEL` when set), `async stop() -> Any`, `async get_job(job_id) -> Job`, `async command(cmd, params=None) -> Any` (raw escape hatch).
  - Protected `_start_job(cmd, params, *, result_model, job_cls=Job) -> Job`.

- [ ] **Step 1: Write the failing test — `tests/test_device_base.py`**

```python
import httpx

from lab_devices.devices.base import Device
from lab_devices.models import Identify, PingResult
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _device(fake: FakeLab, device_id: str):
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return Device(Transport(client), device_id), client


async def test_id_and_type():
    fake = FakeLab()
    fake.add_device("densitometer_1", "densitometer")
    device, client = _device(fake, "densitometer_1")
    try:
        assert device.id == "densitometer_1"
        assert device.type == "densitometer"
    finally:
        await client.aclose()


async def test_ping_returns_model():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    device, client = _device(fake, "pump_1")
    try:
        ping = await device.ping()
        assert isinstance(ping, PingResult)
        assert ping.uptime_ms == 8123456
    finally:
        await client.aclose()


async def test_identify_memory_served():
    fake = FakeLab()
    fake.add_device("pump_1", "pump", identify={"device_type": "pump", "model": "peristaltic-1ch"})
    fake.unreachable.add("pump_1")  # still served from memory
    device, client = _device(fake, "pump_1")
    try:
        ident = await device.identify()
        assert isinstance(ident, Identify)
        assert ident.model == "peristaltic-1ch"
    finally:
        await client.aclose()


async def test_command_escape_hatch():
    fake = FakeLab()
    fake.add_device("pump_1", "pump", rotate_raw={"state": "rotating", "speed_pct": 25})
    device, client = _device(fake, "pump_1")
    try:
        result = await device.command("rotate_raw", {"direction": "forward", "speed_pct": 25})
        assert result["speed_pct"] == 25
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_device_base.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.devices.base`).

- [ ] **Step 3: Write `src/lab_devices/devices/base.py`**

```python
"""Base device: universal commands shared by every device type. See spec §4.2."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.jobs import Job
from lab_devices.models import Identify, PingResult, RawModel
from lab_devices.transport import Transport


class Device:
    STATUS_MODEL: ClassVar[type[RawModel] | None] = None
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = None

    def __init__(self, transport: Transport, device_id: str) -> None:
        self._transport = transport
        self.id = device_id
        self.type = device_id.rsplit("_", 1)[0]

    async def ping(self) -> PingResult:
        return PingResult.from_raw(await self._transport.command(self.id, "ping"))

    async def status(self) -> Any:
        result = await self._transport.command(self.id, "status")
        if self.STATUS_MODEL is not None and isinstance(result, dict):
            return self.STATUS_MODEL.from_raw(result)
        return result

    async def identify(self) -> Identify:
        result = await self._transport.command(self.id, "identify")
        identify = Identify.from_raw(result if isinstance(result, dict) else {})
        if self.CAPABILITIES_MODEL is not None and isinstance(result, dict):
            identify.capabilities = self.CAPABILITIES_MODEL.from_raw(result.get("capabilities"))
        return identify

    async def stop(self) -> Any:
        return await self._transport.command(self.id, "stop")

    async def get_job(self, job_id: str) -> Job:
        data = await self._transport.command(self.id, "get_job", {"job_id": job_id})
        return Job(self, job_id, data=data if isinstance(data, dict) else None)

    async def command(self, cmd: str, params: dict[str, Any] | None = None) -> Any:
        """Raw escape hatch for any command not wrapped by a typed method."""
        return await self._transport.command(self.id, cmd, params)

    async def _start_job(
        self,
        cmd: str,
        params: dict[str, Any] | None = None,
        *,
        result_model: type[RawModel] | None = None,
        job_cls: type[Job] = Job,
    ) -> Job:
        result = await self._transport.command(self.id, cmd, params)
        return job_cls.from_start_result(self, result, result_model=result_model)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_device_base.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: Device base with universal commands + escape hatch"
```

---

### Task 9: Pump

**Files:**
- Create: `src/lab_devices/models/pump.py`
- Create: `src/lab_devices/devices/pump.py`
- Modify: `src/lab_devices/models/__init__.py` (re-export pump models)
- Test: `tests/test_pump.py`

**Interfaces:**
- Consumes: `Device`, `PumpJob`, `RawModel`, `Range`.
- Produces:
  - Models: `PumpCapabilities(channels, speed_ml_min: Range, supports_gradient, supports_drop_suckback, calibration_unverified)`, `PumpStatus(state, direction, speed_ml_min, dispensed_ml, ...)`, `DispenseResult(dispensed_ml, duration_s, mean_speed_ml_min, suckback_ml)`, `CalibrationRunResult(steps, duration_s)`, `Calibration(ml_per_step, set_at_uptime_ms)`.
  - `Pump(Device)` with `STATUS_MODEL = PumpStatus`, `CAPABILITIES_MODEL = PumpCapabilities`, and methods: `rotate`, `rotate_raw`, `dispense` (→ `PumpJob`), `pause`, `resume`, `start_calibration` (→ `Job`), `set_calibration`, `get_calibration`.

- [ ] **Step 1: Write the failing test — `tests/test_pump.py`**

```python
import httpx

from lab_devices.devices.pump import Pump
from lab_devices.jobs import PumpJob
from lab_devices.models.pump import DispenseResult, PumpCapabilities
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _pump():
    fake = FakeLab()
    fake.add_device(
        "pump_1",
        "pump",
        identify={
            "device_type": "pump",
            "model": "peristaltic-1ch",
            "capabilities": {"channels": 1, "speed_ml_min": {"min": 0.05, "max": 40.0}},
        },
        rotate={"state": "rotating", "direction": "forward", "speed_ml_min": 3.0},
        get_calibration={"ml_per_step": 0.000424, "set_at_uptime_ms": 120000},
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, Pump(Transport(client), "pump_1"), client


async def test_dispense_returns_pumpjob_and_result():
    fake, pump, client = _pump()
    try:
        job = await pump.dispense(volume_ml=10, speed_ml_min=3.0)
        assert isinstance(job, PumpJob)
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, DispenseResult)
        assert result.dispensed_ml == 10.0
    finally:
        await client.aclose()


async def test_rotate_returns_state():
    fake, pump, client = _pump()
    try:
        state = await pump.rotate(direction="forward", speed_ml_min=3.0)
        assert state["direction"] == "forward"
    finally:
        await client.aclose()


async def test_identify_typed_capabilities():
    fake, pump, client = _pump()
    try:
        ident = await pump.identify()
        assert isinstance(ident.capabilities, PumpCapabilities)
        assert ident.capabilities.speed_ml_min.max == 40.0
    finally:
        await client.aclose()


async def test_get_calibration():
    fake, pump, client = _pump()
    try:
        cal = await pump.get_calibration()
        assert cal.ml_per_step == 0.000424
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_pump.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.devices.pump`).

- [ ] **Step 3: Write `src/lab_devices/models/pump.py`**

```python
"""Pump result models. See spec §3.6."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from lab_devices.models.common import Range, RawModel


@dataclass
class PumpCapabilities(RawModel):
    channels: int | None = None
    speed_ml_min: Range | None = None
    supports_gradient: bool | None = None
    supports_drop_suckback: bool | None = None
    calibration_unverified: bool | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"speed_ml_min": (Range, False)}


@dataclass
class Calibration(RawModel):
    ml_per_step: float | None = None
    set_at_uptime_ms: int | None = None


@dataclass
class PumpStatus(RawModel):
    state: str | None = None
    job: dict[str, Any] | None = None
    direction: str | None = None
    speed_ml_min: float | None = None
    dispensed_ml: float | None = None
    calibration: Calibration | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"calibration": (Calibration, False)}


@dataclass
class DispenseResult(RawModel):
    dispensed_ml: float | None = None
    duration_s: float | None = None
    mean_speed_ml_min: float | None = None
    suckback_ml: float | None = None


@dataclass
class CalibrationRunResult(RawModel):
    steps: int | None = None
    duration_s: float | None = None
```

- [ ] **Step 4: Write `src/lab_devices/devices/pump.py`**

```python
"""Peristaltic pump. See spec §3.6."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.devices.base import Device
from lab_devices.jobs import Job, PumpJob
from lab_devices.models.common import RawModel
from lab_devices.models.pump import (
    Calibration,
    CalibrationRunResult,
    DispenseResult,
    PumpCapabilities,
    PumpStatus,
)


class Pump(Device):
    STATUS_MODEL: ClassVar[type[RawModel] | None] = PumpStatus
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = PumpCapabilities

    async def rotate(self, *, direction: str, speed_ml_min: float) -> Any:
        return await self.command(
            "rotate", {"direction": direction, "speed_ml_min": speed_ml_min}
        )

    async def rotate_raw(self, *, direction: str, speed_pct: float) -> Any:
        return await self.command("rotate_raw", {"direction": direction, "speed_pct": speed_pct})

    async def dispense(
        self,
        *,
        volume_ml: float,
        speed_ml_min: float | None = None,
        direction: str = "forward",
        drop_suckback_ml: float | None = None,
        speed_profile: dict[str, Any] | None = None,
    ) -> PumpJob:
        params: dict[str, Any] = {"direction": direction, "volume_ml": volume_ml}
        if speed_ml_min is not None:
            params["speed_ml_min"] = speed_ml_min
        if drop_suckback_ml is not None:
            params["drop_suckback_ml"] = drop_suckback_ml
        if speed_profile is not None:
            params["speed_profile"] = speed_profile
        job = await self._start_job(
            "dispense", params, result_model=DispenseResult, job_cls=PumpJob
        )
        return job  # type: ignore[return-value]

    async def pause(self) -> Any:
        return await self.command("pause")

    async def resume(self) -> Any:
        return await self.command("resume")

    async def start_calibration(self, *, speed_pct: float | None = None) -> Job:
        params = {"speed_pct": speed_pct} if speed_pct is not None else None
        return await self._start_job(
            "start_calibration", params, result_model=CalibrationRunResult
        )

    async def set_calibration(
        self,
        *,
        job_id: str | None = None,
        measured_volume_ml: float | None = None,
        ml_per_step: float | None = None,
    ) -> Any:
        params: dict[str, Any] = {}
        if job_id is not None:
            params["job_id"] = job_id
        if measured_volume_ml is not None:
            params["measured_volume_ml"] = measured_volume_ml
        if ml_per_step is not None:
            params["ml_per_step"] = ml_per_step
        return await self.command("set_calibration", params)

    async def get_calibration(self) -> Calibration:
        return Calibration.from_raw(await self.command("get_calibration"))
```

- [ ] **Step 5: Modify `src/lab_devices/models/__init__.py`** — add the pump re-exports.

Append the pump imports and extend `__all__`:

```python
from lab_devices.models.pump import (
    Calibration,
    CalibrationRunResult,
    DispenseResult,
    PumpCapabilities,
    PumpStatus,
)

__all__ += [
    "Calibration",
    "CalibrationRunResult",
    "DispenseResult",
    "PumpCapabilities",
    "PumpStatus",
]
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/test_pump.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: Pump device and models"
```

---

### Task 10: Valve

**Files:**
- Create: `src/lab_devices/models/valve.py`
- Create: `src/lab_devices/devices/valve.py`
- Modify: `src/lab_devices/models/__init__.py`
- Test: `tests/test_valve.py`

**Interfaces:**
- Consumes: `Device`, `Job`, `RawModel`.
- Produces:
  - Models: `ValveCapabilities(positions, rotation_modes, seconds_per_position)`, `ValveStatus(state, homed, position, target_position, job, config)`, `ValveMoveResult(position, from_position, direction, duration_s)`, `ValveConfig(default_rotation, hold_torque)`.
  - `Valve(Device)` with `STATUS_MODEL`, `CAPABILITIES_MODEL`, methods `home`, `set_position` (→ `Job`), `configure`.

- [ ] **Step 1: Write the failing test — `tests/test_valve.py`**

```python
import httpx

from lab_devices.devices.valve import Valve
from lab_devices.jobs import Job
from lab_devices.models.valve import ValveMoveResult
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _valve():
    fake = FakeLab()
    fake.add_device(
        "valve_1",
        "valve",
        identify={
            "device_type": "distribution_valve",
            "model": "radial-6",
            "capabilities": {"positions": 6, "seconds_per_position": 0.9},
        },
        home={"homed": True, "position": 0},
        configure={"default_rotation": "shortest", "hold_torque": False},
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, Valve(Transport(client), "valve_1"), client


async def test_home_then_set_position_job():
    fake, valve, client = _valve()
    try:
        homed = await valve.home(position=0)
        assert homed["homed"] is True
        job = await valve.set_position(position=4)
        assert isinstance(job, Job)
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, ValveMoveResult)
        assert result.position == 4
    finally:
        await client.aclose()


async def test_configure_echo():
    fake, valve, client = _valve()
    try:
        cfg = await valve.configure(default_rotation="shortest")
        assert cfg["default_rotation"] == "shortest"
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_valve.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.devices.valve`).

- [ ] **Step 3: Write `src/lab_devices/models/valve.py`**

```python
"""Distribution valve result models. See spec §3.7."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from lab_devices.models.common import RawModel


@dataclass
class ValveCapabilities(RawModel):
    positions: int | None = None
    rotation_modes: list[str] | None = None
    seconds_per_position: float | None = None


@dataclass
class ValveConfig(RawModel):
    default_rotation: str | None = None
    hold_torque: bool | None = None


@dataclass
class ValveStatus(RawModel):
    state: str | None = None
    homed: bool | None = None
    position: int | None = None
    target_position: int | None = None
    job: dict[str, Any] | None = None
    config: ValveConfig | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"config": (ValveConfig, False)}


@dataclass
class ValveMoveResult(RawModel):
    position: int | None = None
    from_position: int | None = None
    direction: str | None = None
    duration_s: float | None = None
```

- [ ] **Step 4: Write `src/lab_devices/devices/valve.py`**

```python
"""Distribution valve. See spec §3.7."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.devices.base import Device
from lab_devices.jobs import Job
from lab_devices.models.common import RawModel
from lab_devices.models.valve import ValveCapabilities, ValveMoveResult, ValveStatus


class Valve(Device):
    STATUS_MODEL: ClassVar[type[RawModel] | None] = ValveStatus
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = ValveCapabilities

    async def home(self, *, position: int) -> Any:
        return await self.command("home", {"position": position})

    async def set_position(self, *, position: int, rotation: str | None = None) -> Job:
        params: dict[str, Any] = {"position": position}
        if rotation is not None:
            params["rotation"] = rotation
        return await self._start_job("set_position", params, result_model=ValveMoveResult)

    async def configure(
        self, *, default_rotation: str | None = None, hold_torque: bool | None = None
    ) -> Any:
        params: dict[str, Any] = {}
        if default_rotation is not None:
            params["default_rotation"] = default_rotation
        if hold_torque is not None:
            params["hold_torque"] = hold_torque
        return await self.command("configure", params)
```

- [ ] **Step 5: Modify `src/lab_devices/models/__init__.py`** — add the valve re-exports.

```python
from lab_devices.models.valve import (
    ValveCapabilities,
    ValveConfig,
    ValveMoveResult,
    ValveStatus,
)

__all__ += [
    "ValveCapabilities",
    "ValveConfig",
    "ValveMoveResult",
    "ValveStatus",
]
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/test_valve.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: Valve device and models"
```

---

### Task 11: Densitometer

**Files:**
- Create: `src/lab_devices/models/densitometer.py`
- Create: `src/lab_devices/devices/densitometer.py`
- Modify: `src/lab_devices/models/__init__.py`
- Test: `tests/test_densitometer.py`

**Interfaces:**
- Consumes: `Device`, `Job`, `RawModel`.
- Produces:
  - Models: `DensitometerCapabilities(wavelength_nm, brightness_levels, thermostat, temperature_sensor)`, `Thermostat(min_c, max_c)` and status `ThermostatState(enabled, target_c, heating, cooling)`, `DensitometerStatus(state, job, temperature_c, thermostat, calibration, last_measurement)`, `MeasureResult(absorbance, absorbance_raw, slope, blank_slope, temperature_c, tube_correction, seq, raw)`, `Reading(seq, uptime_ms, absorbance, temperature_c)`, `ReadingsResult(readings, dropped)`, `ReadRawResult(intensities, levels, temperature_c)`.
  - `Densitometer(Device)` with `STATUS_MODEL`, `CAPABILITIES_MODEL`, methods `measure_blank` (→`Job`), `measure` (→`Job`), `start_monitoring`, `get_readings`, `stop_monitoring`, `set_thermostat`, `set_tube_correction`, `calibrate_tube`, `set_led`, `read_raw` (→`Job`).

- [ ] **Step 1: Write the failing test — `tests/test_densitometer.py`**

```python
import httpx

from lab_devices.devices.densitometer import Densitometer
from lab_devices.jobs import Job
from lab_devices.models.densitometer import MeasureResult, ReadingsResult
from lab_devices.transport import Transport
from tests.fakelab import FakeLab


def _dens():
    fake = FakeLab()
    fake.add_device(
        "densitometer_1",
        "densitometer",
        identify={
            "device_type": "densitometer",
            "model": "TDS909A-wide",
            "capabilities": {"wavelength_nm": 600, "thermostat": {"min_c": 20.0, "max_c": 45.0}},
        },
        set_thermostat={"enabled": True, "target_c": 37.0},
        get_readings={"readings": [{"seq": 1, "absorbance": 0.5, "temperature_c": 37.0}], "dropped": 0},
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return fake, Densitometer(Transport(client), "densitometer_1"), client


async def test_measure_job_result():
    fake, dens, client = _dens()
    try:
        job = await dens.measure()
        assert isinstance(job, Job)
        result = await job.result(poll_interval=0.0)
        assert isinstance(result, MeasureResult)
        assert result.absorbance == 0.523
    finally:
        await client.aclose()


async def test_set_thermostat():
    fake, dens, client = _dens()
    try:
        res = await dens.set_thermostat(enabled=True, target_c=37.0)
        assert res["target_c"] == 37.0
    finally:
        await client.aclose()


async def test_get_readings_typed():
    fake, dens, client = _dens()
    try:
        readings = await dens.get_readings()
        assert isinstance(readings, ReadingsResult)
        assert readings.readings[0].absorbance == 0.5
        assert readings.dropped == 0
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_densitometer.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.devices.densitometer`).

- [ ] **Step 3: Write `src/lab_devices/models/densitometer.py`**

```python
"""Densitometer result models. See spec §3.8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from lab_devices.models.common import RawModel


@dataclass
class Thermostat(RawModel):
    min_c: float | None = None
    max_c: float | None = None


@dataclass
class DensitometerCapabilities(RawModel):
    wavelength_nm: int | None = None
    brightness_levels: int | None = None
    thermostat: Thermostat | None = None
    temperature_sensor: str | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"thermostat": (Thermostat, False)}


@dataclass
class ThermostatState(RawModel):
    enabled: bool | None = None
    target_c: float | None = None
    heating: bool | None = None
    cooling: bool | None = None


@dataclass
class DensitometerStatus(RawModel):
    state: str | None = None
    job: dict[str, Any] | None = None
    temperature_c: float | None = None
    thermostat: ThermostatState | None = None
    calibration: dict[str, Any] | None = None
    last_measurement: dict[str, Any] | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {
        "thermostat": (ThermostatState, False)
    }


@dataclass
class MeasureResult(RawModel):
    absorbance: float | None = None
    absorbance_raw: float | None = None
    slope: float | None = None
    blank_slope: float | None = None
    temperature_c: float | None = None
    tube_correction: float | None = None
    seq: int | None = None
    raw: Any = None  # 20-point sweep when include_raw=True (distinct from RawModel.raw)


@dataclass
class Reading(RawModel):
    seq: int | None = None
    uptime_ms: int | None = None
    absorbance: float | None = None
    temperature_c: float | None = None


@dataclass
class ReadingsResult(RawModel):
    readings: list[Reading] | None = None
    dropped: int | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"readings": (Reading, True)}


@dataclass
class ReadRawResult(RawModel):
    intensities: list[float] | None = None
    levels: list[int] | None = None
    temperature_c: float | None = None
```

Note: `MeasureResult.raw` is a real API field (the optional sweep), so it shadows `RawModel.raw`. That is intentional here — `MeasureResult` keeps only the API's `raw`. If you also need the full payload, read it from `job.raw["result"]`. (This is the one deliberate exception to the `.raw`-holds-everything rule; documented so it is not mistaken for a bug.)

- [ ] **Step 4: Write `src/lab_devices/devices/densitometer.py`**

```python
"""Densitometer. See spec §3.8."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.devices.base import Device
from lab_devices.jobs import Job
from lab_devices.models.common import RawModel
from lab_devices.models.densitometer import (
    DensitometerCapabilities,
    DensitometerStatus,
    MeasureResult,
    ReadingsResult,
    ReadRawResult,
)


class Densitometer(Device):
    STATUS_MODEL: ClassVar[type[RawModel] | None] = DensitometerStatus
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = DensitometerCapabilities

    async def measure_blank(self) -> Job:
        return await self._start_job("measure_blank")

    async def measure(self, *, include_raw: bool = False) -> Job:
        params = {"include_raw": include_raw} if include_raw else None
        return await self._start_job("measure", params, result_model=MeasureResult)

    async def start_monitoring(self, *, interval_s: float | None = None) -> Any:
        params = {"interval_s": interval_s} if interval_s is not None else None
        return await self.command("start_monitoring", params)

    async def get_readings(
        self, *, since_seq: int | None = None, limit: int | None = None
    ) -> ReadingsResult:
        params: dict[str, Any] = {}
        if since_seq is not None:
            params["since_seq"] = since_seq
        if limit is not None:
            params["limit"] = limit
        return ReadingsResult.from_raw(await self.command("get_readings", params or None))

    async def stop_monitoring(self) -> Any:
        return await self.command("stop_monitoring")

    async def set_thermostat(self, *, enabled: bool, target_c: float | None = None) -> Any:
        params: dict[str, Any] = {"enabled": enabled}
        if target_c is not None:
            params["target_c"] = target_c
        return await self.command("set_thermostat", params)

    async def set_tube_correction(self, *, factor: float) -> Any:
        return await self.command("set_tube_correction", {"factor": factor})

    async def calibrate_tube(self, *, reference_absorbance: float) -> Any:
        return await self.command("calibrate_tube", {"reference_absorbance": reference_absorbance})

    async def set_led(self, *, level: int) -> Any:
        return await self.command("set_led", {"level": level})

    async def read_raw(self, *, level: int | None = None) -> Job:
        params = {"level": level} if level is not None else None
        return await self._start_job("read_raw", params, result_model=ReadRawResult)
```

- [ ] **Step 5: Modify `src/lab_devices/models/__init__.py`** — add the densitometer re-exports.

```python
from lab_devices.models.densitometer import (
    DensitometerCapabilities,
    DensitometerStatus,
    MeasureResult,
    ReadRawResult,
    Reading,
    ReadingsResult,
    Thermostat,
    ThermostatState,
)

__all__ += [
    "DensitometerCapabilities",
    "DensitometerStatus",
    "MeasureResult",
    "ReadRawResult",
    "Reading",
    "ReadingsResult",
    "Thermostat",
    "ThermostatState",
]
```

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest tests/test_densitometer.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: Densitometer device and models"
```

---

### Task 12: LabClient

**Files:**
- Create: `src/lab_devices/client.py`
- Modify: `src/lab_devices/devices/__init__.py` (re-export device classes)
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `Transport`, `Pump`, `Valve`, `Densitometer`, `Device`, `DeviceInfo`, `AgentInfo`, error classes.
- Produces:
  - `LabClient(host: str, port: int, *, request_timeout: float = 10.0, discover_timeout: float = 30.0, http: httpx.AsyncClient | None = None)`.
  - Async context manager (`__aenter__`/`__aexit__`); closes the client only if it created it.
  - `pump(n: int) -> Pump`, `valve(n: int) -> Valve`, `densitometer(n: int) -> Densitometer`, `device(device_id: str) -> Device` (dispatch by prefix; unknown prefix → `ValueError`).
  - `async list_devices() -> list[DeviceInfo]`, `async rediscover() -> list[DeviceInfo]`, `async disconnect(port=None) -> int`, `async agent_info() -> AgentInfo`.

- [ ] **Step 1: Write the failing test — `tests/test_client.py`**

```python
import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.devices.densitometer import Densitometer
from lab_devices.devices.pump import Pump
from lab_devices.devices.valve import Valve
from lab_devices.models import AgentInfo, DeviceInfo
from tests.fakelab import FakeLab


def _client(fake: FakeLab) -> LabClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler), base_url="http://lab")
    return LabClient("chisel", 8089, http=http)


async def test_handle_factories_typed():
    fake = FakeLab()
    async with _client(fake) as lab:
        assert isinstance(lab.pump(1), Pump)
        assert isinstance(lab.valve(2), Valve)
        assert isinstance(lab.densitometer(1), Densitometer)
        assert lab.pump(1).id == "pump_1"
        assert isinstance(lab.device("valve_3"), Valve)


async def test_device_unknown_prefix_raises():
    fake = FakeLab()
    async with _client(fake) as lab:
        with pytest.raises(ValueError):
            lab.device("thermometer_1")


async def test_list_devices_returns_models():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    fake.add_device("valve_1", "valve")
    async with _client(fake) as lab:
        devices = await lab.list_devices()
        assert all(isinstance(d, DeviceInfo) for d in devices)
        assert {d.id for d in devices} == {"pump_1", "valve_1"}


async def test_agent_info_typed():
    fake = FakeLab()
    async with _client(fake) as lab:
        info = await lab.agent_info()
        assert isinstance(info, AgentInfo)
        assert info.hostname == "FAKE"


async def test_disconnect_returns_count():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    async with _client(fake) as lab:
        assert await lab.disconnect() == 1


async def test_drive_pump_end_to_end():
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    async with _client(fake) as lab:
        job = await lab.pump(1).dispense(volume_ml=10, speed_ml_min=3.0)
        result = await job.result(poll_interval=0.0)
        assert result.dispensed_ml == 10.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.client`).

- [ ] **Step 3: Write `src/lab_devices/client.py`**

```python
"""LabClient — core entry point for one lab. See spec §4.1."""

from __future__ import annotations

from typing import Any, Self

import httpx

from lab_devices.devices.base import Device
from lab_devices.devices.densitometer import Densitometer
from lab_devices.devices.pump import Pump
from lab_devices.devices.valve import Valve
from lab_devices.models import AgentInfo, DeviceInfo
from lab_devices.transport import Transport

_PREFIX_TO_CLASS: dict[str, type[Device]] = {
    "pump": Pump,
    "valve": Valve,
    "densitometer": Densitometer,
}


class LabClient:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        request_timeout: float = 10.0,
        discover_timeout: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=f"http://{host}:{port}", timeout=request_timeout
        )
        self._transport = Transport(self._http, discover_timeout=discover_timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ---- device handles (lazy) ----
    def pump(self, n: int) -> Pump:
        return Pump(self._transport, f"pump_{n}")

    def valve(self, n: int) -> Valve:
        return Valve(self._transport, f"valve_{n}")

    def densitometer(self, n: int) -> Densitometer:
        return Densitometer(self._transport, f"densitometer_{n}")

    def device(self, device_id: str) -> Device:
        prefix = device_id.rsplit("_", 1)[0]
        cls = _PREFIX_TO_CLASS.get(prefix)
        if cls is None:
            raise ValueError(f"unrecognized device id prefix: {device_id!r}")
        return cls(self._transport, device_id)

    # ---- enumeration & lifecycle ----
    async def list_devices(self) -> list[DeviceInfo]:
        body = await self._transport.get_devices()
        return [DeviceInfo.from_raw(d) for d in body.get("devices", [])]

    async def rediscover(self) -> list[DeviceInfo]:
        body = await self._transport.discover()
        return [DeviceInfo.from_raw(d) for d in body.get("devices", [])]

    async def disconnect(self, port: str | None = None) -> int:
        body = await self._transport.disconnect(port)
        return int(body.get("released", 0))

    async def agent_info(self) -> AgentInfo:
        return AgentInfo.from_raw(await self._transport.agent_info())
```

- [ ] **Step 4: Write `src/lab_devices/devices/__init__.py`**

```python
from lab_devices.devices.base import Device
from lab_devices.devices.densitometer import Densitometer
from lab_devices.devices.pump import Pump
from lab_devices.devices.valve import Valve

__all__ = ["Device", "Densitometer", "Pump", "Valve"]
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_client.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: LabClient core entry point"
```

---

### Task 13: Discovery — LabRegistry

**Files:**
- Create: `src/lab_devices/discovery.py`
- Test: `tests/test_discovery.py`

**Interfaces:**
- Consumes: `LabClient`, discovery error classes.
- Produces:
  - `LabInfo(name, host, port)` dataclass.
  - `LabRegistry(*, url: str | None = None, chisel_host: str | None = None, probe_timeout: float = 0.3, http: httpx.AsyncClient | None = None)`. `url` order: arg → env `LAB_DEVICES_DISCOVERY_URL` → default `http://siteapp:8000/api/clients/`.
  - Async context manager.
  - `async list_labs() -> list[str]`, `async lookup(name) -> LabInfo`, `async is_online(name) -> bool`, `async connect(name, *, require_online=True, **client_kwargs) -> LabClient`.
  - Roster-fetch errors mapped: connect/timeout → `ClientLookupEndpointUnreachable`; 5xx/malformed → `ClientLookupEndpointError`; unknown name → `UnknownLabClient`; probe fail with `require_online` → `LabOffline`.
  - Liveness probe uses `asyncio.open_connection` wrapped in `asyncio.timeout(probe_timeout)`. The probe target host/port is overridable for tests via a `_probe` seam.

- [ ] **Step 1: Write the failing test — `tests/test_discovery.py`**

```python
import asyncio

import httpx
import pytest

from lab_devices import errors
from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry

ROSTER = {
    "khamit_desktop": {"host": "chisel", "port": 8089},
    "natalya_test_user": {"host": "chisel", "port": 8087},
}


def _registry(*, roster=ROSTER, status=200, body=None, boom=None) -> LabRegistry:
    def handler(request: httpx.Request) -> httpx.Response:
        if boom is not None:
            raise boom
        return httpx.Response(status, json=body if body is not None else roster)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://siteapp:8000")
    return LabRegistry(url="http://siteapp:8000/api/clients/", http=http)


async def test_list_labs():
    async with _registry() as reg:
        names = await reg.list_labs()
        assert set(names) == {"khamit_desktop", "natalya_test_user"}


async def test_lookup_known():
    async with _registry() as reg:
        info = await reg.lookup("khamit_desktop")
        assert info == LabInfo(name="khamit_desktop", host="chisel", port=8089)


async def test_lookup_unknown_lists_names():
    async with _registry() as reg:
        with pytest.raises(errors.UnknownLabClient) as excinfo:
            await reg.lookup("ghost")
        assert "khamit_desktop" in excinfo.value.available


async def test_endpoint_unreachable():
    async with _registry(boom=httpx.ConnectError("refused")) as reg:
        with pytest.raises(errors.ClientLookupEndpointUnreachable):
            await reg.list_labs()


async def test_endpoint_5xx():
    async with _registry(status=502, body={"error": "bad gateway"}) as reg:
        with pytest.raises(errors.ClientLookupEndpointError):
            await reg.list_labs()


async def test_connect_online_returns_labclient(monkeypatch):
    async with _registry() as reg:
        # Force the liveness probe to report online without real sockets.
        async def fake_probe(host, port):
            return True

        monkeypatch.setattr(reg, "_probe", fake_probe)
        lab = await reg.connect("khamit_desktop")
        assert isinstance(lab, LabClient)
        assert lab.host == "chisel"
        assert lab.port == 8089
        await lab.aclose()


async def test_connect_offline_raises(monkeypatch):
    async with _registry() as reg:
        async def fake_probe(host, port):
            return False

        monkeypatch.setattr(reg, "_probe", fake_probe)
        with pytest.raises(errors.LabOffline):
            await reg.connect("khamit_desktop")


async def test_probe_against_real_server():
    async with _registry() as reg:
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            assert await reg._probe("127.0.0.1", port) is True
        finally:
            server.close()
            await server.wait_closed()
        # nothing listening now -> offline
        assert await reg._probe("127.0.0.1", port) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_discovery.py -v`
Expected: FAIL (`ModuleNotFoundError: lab_devices.discovery`).

- [ ] **Step 3: Write `src/lab_devices/discovery.py`**

```python
"""LabRegistry — server-only lab discovery via the internal lab-bridge roster.

Runs inside labnet. Hits the unauthenticated internal endpoint
`GET http://siteapp:8000/api/clients/` -> {name: {host, port}}. No token. See spec §5."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Self

import httpx

from lab_devices import errors
from lab_devices.client import LabClient

_DEFAULT_URL = "http://siteapp:8000/api/clients/"


@dataclass(frozen=True)
class LabInfo:
    name: str
    host: str
    port: int


class LabRegistry:
    def __init__(
        self,
        *,
        url: str | None = None,
        chisel_host: str | None = None,
        probe_timeout: float = 0.3,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url or os.environ.get("LAB_DEVICES_DISCOVERY_URL") or _DEFAULT_URL
        self._chisel_host = chisel_host
        self._probe_timeout = probe_timeout
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _fetch_roster(self) -> dict[str, dict[str, Any]]:
        try:
            response = await self._http.get(self.url)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise errors.ClientLookupEndpointUnreachable(str(exc)) from exc
        except httpx.TransportError as exc:
            raise errors.ClientLookupEndpointUnreachable(str(exc)) from exc
        if response.status_code >= 500:
            raise errors.ClientLookupEndpointError(f"roster endpoint HTTP {response.status_code}")
        try:
            body = response.json()
        except (ValueError, httpx.DecodingError) as exc:
            raise errors.ClientLookupEndpointError("roster body is not JSON") from exc
        if not isinstance(body, dict):
            raise errors.ClientLookupEndpointError("roster body is not an object")
        return body

    async def list_labs(self) -> list[str]:
        return sorted((await self._fetch_roster()).keys())

    async def lookup(self, name: str) -> LabInfo:
        roster = await self._fetch_roster()
        entry = roster.get(name)
        if entry is None:
            raise errors.UnknownLabClient(name, available=sorted(roster.keys()))
        host = self._chisel_host or entry.get("host", "chisel")
        return LabInfo(name=name, host=host, port=int(entry["port"]))

    async def is_online(self, name: str) -> bool:
        info = await self.lookup(name)
        return await self._probe(info.host, info.port)

    async def connect(
        self, name: str, *, require_online: bool = True, **client_kwargs: Any
    ) -> LabClient:
        info = await self.lookup(name)
        if require_online and not await self._probe(info.host, info.port):
            raise errors.LabOffline(name, info.host, info.port)
        return LabClient(info.host, info.port, **client_kwargs)

    async def _probe(self, host: str, port: int) -> bool:
        try:
            async with asyncio.timeout(self._probe_timeout):
                reader, writer = await asyncio.open_connection(host, port)
        except (OSError, TimeoutError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_discovery.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: LabRegistry discovery (internal roster + TCP liveness)"
```

---

### Task 14: Public API, docs, full-suite gate

**Files:**
- Modify: `src/lab_devices/__init__.py` (public re-exports)
- Create: `README.md`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: everything.
- Produces: a curated top-level namespace. `LabClient`, `Pump`, `Valve`, `Densitometer`, `Device`, `Job`, `PumpJob`, all model dataclasses, and the full error hierarchy are importable from `lab_devices`. `LabRegistry` stays under `lab_devices.discovery` (imported explicitly).

- [ ] **Step 1: Write the failing test — `tests/test_public_api.py`**

```python
import lab_devices


def test_top_level_exports():
    for name in [
        "LabClient",
        "Pump",
        "Valve",
        "Densitometer",
        "Device",
        "Job",
        "PumpJob",
        "LabError",
        "LabDevicesError",
        "DeviceUnreachableError",
        "BusyError",
        "NotCalibratedError",
        "DeviceInfo",
        "DispenseResult",
        "MeasureResult",
        "ValveMoveResult",
    ]:
        assert hasattr(lab_devices, name), f"missing export: {name}"


def test_registry_not_top_level_but_importable():
    assert not hasattr(lab_devices, "LabRegistry")
    from lab_devices.discovery import LabRegistry  # noqa: F401


def test_all_is_sorted_and_complete():
    assert lab_devices.__all__ == sorted(lab_devices.__all__)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_public_api.py -v`
Expected: FAIL (`missing export: LabClient`).

- [ ] **Step 3: Rewrite `src/lab_devices/__init__.py`**

```python
"""Async library to discover and manage lab devices (pump, valve, densitometer).

Quick start:

    from lab_devices import LabClient

    async with LabClient("chisel", 8089) as lab:
        job = await lab.pump(1).dispense(volume_ml=10, speed_ml_min=3.0)
        result = await job.result()

Server-only discovery (inside labnet):

    from lab_devices.discovery import LabRegistry

    async with LabRegistry() as reg:
        lab = await reg.connect("khamit_desktop")
"""

from __future__ import annotations

from lab_devices.client import LabClient
from lab_devices.devices import Densitometer, Device, Pump, Valve
from lab_devices.errors import (
    BusyError,
    ClientLookupEndpointError,
    ClientLookupEndpointUnreachable,
    DeviceUnreachableError,
    DiscoveryError,
    DiscoveryFailedError,
    DiscoveryInProgressError,
    HardwareError,
    InternalDeviceError,
    InvalidParamsError,
    InvalidRequestError,
    JobCancelledError,
    JobFailedError,
    JobInProgressError,
    JobTimeoutError,
    LabDevicesError,
    LabError,
    LabOffline,
    LabProtocolError,
    NotCalibratedError,
    NotHomedError,
    UnknownCommandError,
    UnknownDeviceError,
    UnknownLabClient,
)
from lab_devices.jobs import Job, PumpJob
from lab_devices.models import (
    AgentInfo,
    Calibration,
    CalibrationRunResult,
    DensitometerCapabilities,
    DensitometerStatus,
    DeviceInfo,
    DispenseResult,
    Identify,
    MeasureResult,
    PingResult,
    PumpCapabilities,
    PumpStatus,
    Range,
    RawModel,
    ReadRawResult,
    Reading,
    ReadingsResult,
    Thermostat,
    ThermostatState,
    ValveCapabilities,
    ValveConfig,
    ValveMoveResult,
    ValveStatus,
)

__version__ = "0.1.0"

__all__ = sorted(
    [
        "AgentInfo",
        "BusyError",
        "Calibration",
        "CalibrationRunResult",
        "ClientLookupEndpointError",
        "ClientLookupEndpointUnreachable",
        "DensitometerCapabilities",
        "Densitometer",
        "DensitometerStatus",
        "Device",
        "DeviceInfo",
        "DeviceUnreachableError",
        "DiscoveryError",
        "DiscoveryFailedError",
        "DiscoveryInProgressError",
        "DispenseResult",
        "HardwareError",
        "Identify",
        "InternalDeviceError",
        "InvalidParamsError",
        "InvalidRequestError",
        "Job",
        "JobCancelledError",
        "JobFailedError",
        "JobInProgressError",
        "JobTimeoutError",
        "LabClient",
        "LabDevicesError",
        "LabError",
        "LabOffline",
        "LabProtocolError",
        "MeasureResult",
        "NotCalibratedError",
        "NotHomedError",
        "PingResult",
        "Pump",
        "PumpCapabilities",
        "PumpJob",
        "PumpStatus",
        "Range",
        "RawModel",
        "ReadRawResult",
        "Reading",
        "ReadingsResult",
        "Thermostat",
        "ThermostatState",
        "UnknownCommandError",
        "UnknownDeviceError",
        "UnknownLabClient",
        "Valve",
        "ValveCapabilities",
        "ValveConfig",
        "ValveMoveResult",
        "ValveStatus",
    ]
)
```

- [ ] **Step 4: Write `README.md`**

```markdown
# lab_devices

Async Python library to discover and manage lab devices — peristaltic pumps,
distribution valves, and densitometers — over the SerialHop / lab-bridge API.

## Install

    pip install -e ".[dev]"

## Core usage (host + port)

```python
import asyncio
from lab_devices import LabClient

async def main():
    async with LabClient("chisel", 8089) as lab:
        pump = lab.pump(1)
        job = await pump.dispense(volume_ml=10, speed_ml_min=3.0)
        result = await job.result()
        print(result.dispensed_ml)

asyncio.run(main())
```

## Server-only discovery (inside labnet)

```python
from lab_devices.discovery import LabRegistry

async with LabRegistry() as reg:            # LAB_DEVICES_DISCOVERY_URL overrides the endpoint
    print(await reg.list_labs())
    lab = await reg.connect("khamit_desktop")
    async with lab:
        await lab.densitometer(1).measure()
```

Discovery uses the internal, unauthenticated roster endpoint and needs no token.
It only works from inside the lab-bridge network.

## Development

    python -m pytest         # hermetic; no hardware needed
    python -m mypy
    python -m ruff check .
```

- [ ] **Step 5: Run the full suite + type/lint gate**

Run:
```bash
python -m pytest -v
python -m mypy
python -m ruff check src tests
```
Expected: all tests PASS; `mypy` reports no errors; `ruff` clean. Fix anything that fails before committing.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: public API surface, README, full-suite gate"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task(s) |
|---|---|
| §1 two-layer architecture, dependency direction | 12 (LabClient), 13 (LabRegistry depends on client) |
| §2 decision 1 typed classes + escape hatch | 8 (`command`), 9–11 |
| §2 decision 2 Job handle + explicit wait | 7 |
| §2 decision 3 rich exception hierarchy | 2 |
| §2 decision 4 lenient dataclass models | 3, 9–11 |
| §2 decision 5 async CM + lazy handles + list/rediscover | 12 |
| §2 decision 6 internal-roster discovery, no token, name lists | 13 |
| §2 decision 7 httpx-only, 3.11+ | 1 (pyproject) |
| §3 package layout | 1, 3, 8, 12, 13 (dirs created as tasks land) |
| §4.1 LabClient API | 12 |
| §4.2 Device base + typed devices, full command coverage | 8, 9, 10, 11 |
| §4.3 Jobs (refresh/result/cancel/pause/resume, result models, history caveat) | 7 (+ `InvalidParamsError` surfaced for evicted job via transport) |
| §4.4 correlation ids, timeouts, 32 KiB cap, 503 no-retry | 4, 12 |
| §5 LabRegistry (list/lookup/is_online/connect, error mappings, probe) | 13 |
| §6 error model (all branches, envelope authoritative, unknown-code degrade) | 2, 4, 5, 7 |
| §7 models incl. `.raw` passthrough, nested parsing | 3, 9, 10, 11 |
| §8 hermetic FakeLab + TCP probe tests | 6, 13 |
| §9 packaging, py.typed, curated exports | 1, 14 |

No gaps.

**2. Placeholder scan:** No `TBD`/`TODO`/"add error handling"/"similar to Task N". Every code step contains complete code. The one intentional note (`MeasureResult.raw` shadowing) is documented behavior, not a placeholder.

**3. Type consistency:** Signatures verified across tasks:
- `Transport(client, *, discover_timeout=30.0)` — defined Task 4, constructed Tasks 6/8/9/10/11/12 consistently.
- `Job.from_start_result(device, result, *, result_model=None)` and `Job(device, job_id, *, result_model=None, data=None)` — defined Task 7, used by `Device._start_job` (Task 8) and every device.
- `Device(transport, device_id)`, `.id`, `._transport`, `_start_job(cmd, params, *, result_model, job_cls=Job)` — defined Task 8, used Tasks 9–12.
- `PumpJob` from `lab_devices.jobs` — defined Task 7, used Task 9.
- `RawModel.from_raw` + `_NESTED` — defined Task 3, used by all models.
- `LabClient(host, port, *, request_timeout, discover_timeout, http)` with `.host`/`.port`/`.aclose()` — defined Task 12, used Task 13 (`connect` returns it; `.host`/`.port` asserted in tests).
- `LabRegistry._probe(host, port)` seam — defined Task 13, monkeypatched in tests.
- Error class names identical between Task 2 definitions, Task 4/5 raises, and Task 14 re-exports.

No inconsistencies found.
