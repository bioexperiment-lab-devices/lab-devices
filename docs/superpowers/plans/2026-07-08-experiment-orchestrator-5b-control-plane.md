# Experiment Orchestrator — Increment 5b: Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Stacks on plan 5a — do 5a first.**

**Goal:** Add the operator-facing control-plane tiers around a run — read-only introspection (always safe) and guarded recovery (idle-only) — via a dedicated `Console`, and settle the remaining Increment-4 lifecycle carry-forward tickets (double-abort cancellation residue; distinguishing operator abort from external cancellation).

**Architecture:** A `Console(client, run=None)` (design spec §9) wraps the `LabClient` and an optional live `ExperimentRun`. Introspection works with or without a run; when a run is live, device wire calls route through the run's per-device lock (D2), and recovery consults the run's occupancy as the idle oracle (`is_busy` = any `(device, channel)` slot held). Recovery refuses a busy device rather than force-finalizing. Lifecycle (pause/resume/abort) stays on `ExperimentRun`.

**Tech Stack:** Python ≥3.11, asyncio, strict mypy, ruff (line length 100), hermetic pytest (`asyncio_mode=auto`), `FakeLab`/`FakeClock`.

## Global Constraints

- Interpreter: `.venv/bin/python -m pytest|mypy|ruff` (bare `python` lacks deps).
- Gate (green after every task): full `pytest`; `.venv/bin/python -m mypy src`; `.venv/bin/python -m ruff check .`; `awk 'length>100' src/lab_devices/experiment/*.py tests/test_experiment_*.py tests/fakelab.py tests/fakeclock.py tests/experiment_run_helpers.py` prints nothing.
- Source: `from __future__ import annotations` + one-line docstring citing the design section. Tests: flat `tests/test_experiment_*.py`, no future-import, no docstring; use the `fake_client` fixture (`conftest.py`) and `tests/experiment_run_helpers.py` (`add_standard_devices`, `make_workflow`, `verbs`).
- **Depends on plan 5a** (branch `feat/experiment-orchestrator-5-control-plane`): `PersistenceError`, disk sinks, and the `execute()` rewrite that already introduces `RunReport.status == "cancelled"` (5a Task 8). 5b **pins** that behavior and adds the double-abort guard.
- Design spec: `docs/superpowers/specs/2026-07-08-experiment-orchestrator-5-control-plane-design.md` (§8 lifecycle tickets, §9 control plane, §10 taxonomy).
- Core control surface being wrapped: `LabClient.{list_devices,rediscover,disconnect,agent_info,device}` (`src/lab_devices/client.py`); `Device.{ping,status}` (`src/lab_devices/devices/base.py`). Model shapes (`src/lab_devices/models/common.py`): `DeviceInfo.{id,type,port,connected}`, `AgentInfo.{version,hostname,...}`, `PingResult.uptime_ms`.

---

## File Structure

- `src/lab_devices/experiment/control.py` **(new)** — `Console`: introspection + guarded recovery. One responsibility: the out-of-band operator surface.
- `src/lab_devices/experiment/errors.py` **(modify)** — add `DeviceBusyError`.
- `src/lab_devices/experiment/occupancy.py` **(modify)** — `is_busy(device)` + `busy_devices()` idle oracle.
- `src/lab_devices/experiment/run.py` **(modify)** — `abort()` double-abort guard; small public seams `is_device_busy`/`busy_devices`/`wire_lock` for the `Console`.
- `src/lab_devices/experiment/__init__.py` **(modify)** — export `Console`, `DeviceBusyError`.
- `tests/test_experiment_control.py` **(new)** — `Console` unit + E2E.
- `tests/test_experiment_abort_cancel.py` **(new)** — double-abort balance + external-cancel status.

---

## Task 1: `DeviceBusyError` in the taxonomy

**Files:**
- Modify: `src/lab_devices/experiment/errors.py`
- Modify: `src/lab_devices/experiment/__init__.py`
- Test: `tests/test_experiment_errors.py`

**Interfaces:**
- Produces: `DeviceBusyError(ExperimentRunError)` — raised by the recovery tier when a target device (or any run device, for whole-agent recovery) is not idle.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_experiment_errors.py`:

```python
def test_device_busy_error_is_run_error():
    from lab_devices.experiment import DeviceBusyError
    from lab_devices.experiment.errors import ExperimentRunError
    err = DeviceBusyError("pump_1 is busy")
    assert isinstance(err, ExperimentRunError)
    assert "pump_1" in str(err)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_errors.py::test_device_busy_error_is_run_error -v`
Expected: FAIL — `ImportError: cannot import name 'DeviceBusyError'`.

- [ ] **Step 3: Add the error class**

In `src/lab_devices/experiment/errors.py`, after `PersistenceError` (from 5a):

```python
class DeviceBusyError(ExperimentRunError):
    """A recovery-tier action targeted a device that is not idle (design 5 §9-10)."""
```

- [ ] **Step 4: Export it**

In `src/lab_devices/experiment/__init__.py`, add `DeviceBusyError` to the errors import block and `__all__`.

- [ ] **Step 5: Run test + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_errors.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check .`
Expected: PASS; mypy/ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/errors.py src/lab_devices/experiment/__init__.py tests/test_experiment_errors.py
git commit -m "feat(experiment): add DeviceBusyError to run taxonomy (5b)"
```

---

## Task 2: occupancy idle oracle + `ExperimentRun` control seams

**Files:**
- Modify: `src/lab_devices/experiment/occupancy.py`
- Modify: `src/lab_devices/experiment/run.py`
- Test: `tests/test_experiment_occupancy.py` (existing; add tests)

**Interfaces:**
- Produces:
  - `Occupancy.is_busy(device: str) -> bool` — any `(device, channel)` slot held (a `_Hold` in-flight command *or* an `OpenMode`).
  - `Occupancy.busy_devices() -> set[str]` — the set of devices with any held slot.
  - `ExperimentRun.is_device_busy(device_id: str) -> bool`, `ExperimentRun.busy_devices() -> set[str]`, `ExperimentRun.wire_lock(device_id: str) -> asyncio.Lock` — the seams the `Console` uses (Tasks 5–6).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_experiment_occupancy.py`:

```python
def test_is_busy_tracks_holds():
    from lab_devices.experiment.occupancy import Occupancy
    occ = Occupancy()
    assert occ.is_busy("pump_1") is False
    occ.acquire("pump_1", frozenset({"motor"}), "blocks[0]")
    assert occ.is_busy("pump_1") is True
    assert occ.busy_devices() == {"pump_1"}
    occ.release("pump_1", frozenset({"motor"}), "blocks[0]")
    assert occ.is_busy("pump_1") is False
    assert occ.busy_devices() == set()


def test_is_busy_tracks_open_mode():
    from lab_devices.experiment.occupancy import OpenMode, Occupancy
    occ = Occupancy()
    occ.acquire("pump_2", frozenset({"motor"}), "blocks[1]")
    occ.register_open(OpenMode("pump_2", "rotate", "stop", {}, frozenset({"motor"}), "blocks[1]"))
    assert occ.is_busy("pump_2") is True  # mode-held slot counts as busy
    occ.register_close("pump_2", "rotate")
    assert occ.is_busy("pump_2") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_occupancy.py -k is_busy -v`
Expected: FAIL — `AttributeError: 'Occupancy' object has no attribute 'is_busy'`.

- [ ] **Step 3: Add the oracle to `Occupancy`**

In `src/lab_devices/experiment/occupancy.py`, add to the `Occupancy` class (after `open_modes`):

```python
    def is_busy(self, device: str) -> bool:
        """True if any (device, channel) slot is held — an in-flight command or open mode
        (design 5 §9 idle oracle)."""
        return any(dev == device for dev, _channel in self._slots)

    def busy_devices(self) -> set[str]:
        """Every device with at least one held slot."""
        return {dev for dev, _channel in self._slots}
```

- [ ] **Step 4: Add the seams to `ExperimentRun`**

In `src/lab_devices/experiment/run.py`, add to the `ExperimentRun` class (after `abort`):

```python
    # ---- control-plane seams for Console (design 5 §9) ----
    def is_device_busy(self, device_id: str) -> bool:
        return self._ctx.occupancy.is_busy(device_id)

    def busy_devices(self) -> set[str]:
        return self._ctx.occupancy.busy_devices()

    def wire_lock(self, device_id: str) -> asyncio.Lock:
        """The per-device wire lock (D2); introspection serializes on it during a live run."""
        return self._ctx.lock(device_id)
```

- [ ] **Step 5: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_occupancy.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/occupancy.py src/lab_devices/experiment/run.py`
Expected: PASS; mypy/ruff clean; awk silent.

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/occupancy.py src/lab_devices/experiment/run.py tests/test_experiment_occupancy.py
git commit -m "feat(experiment): occupancy idle oracle + ExperimentRun control seams (5b)"
```

---

## Task 3: `abort()` double-abort cancellation guard

**Files:**
- Modify: `src/lab_devices/experiment/run.py` (`abort`)
- Test: `tests/test_experiment_abort_cancel.py`

**Interfaces:**
- Consumes: existing `abort()`.
- Produces: `abort()` calls `self._task.cancel()` **at most once** across repeated aborts, so `task.cancelling()` balances the single `uncancel()` in `execute()` — closes the ledger's "double-abort leaves `cancelling()==1`" ticket (latent when `execute()` runs under a `TaskGroup`, which the `Console` makes realistic).

- [ ] **Step 1: Write the failing test**

Create `tests/test_experiment_abort_cancel.py`:

```python
import asyncio

import pytest

from lab_devices.experiment import ExperimentRun, RunAbortedError, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive

_DISPENSE = [{"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}}]


async def test_double_abort_balances_cancellation(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight
    run.abort()
    run.abort()  # second abort must NOT issue a second cancel()
    with pytest.raises(RunAbortedError):
        await task
    assert run.report is not None and run.report.status == "aborted"
    assert task.cancelling() == 0  # one cancel, one uncancel -> balanced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_abort_cancel.py::test_double_abort_balances_cancellation -v`
Expected: FAIL — `assert task.cancelling() == 0` fails (currently `1`: two `cancel()`s, one `uncancel()`).

- [ ] **Step 3: Guard the cancel**

In `src/lab_devices/experiment/run.py`, change the last line of `abort()` to only cancel on the first abort:

```python
    def abort(self) -> None:
        """Operator abort: cancel dispatch; the finalizer still reaches safe state (§10)."""
        ctx = self._ctx
        first = not ctx.abort_requested
        ctx.abort_requested = True
        if self._started and first and self.report is None:
            ctx.emit("abort_requested")
        if first and self._task is not None and not self._finalizing:
            self._task.cancel()
```

(The only change is `if first and self._task is not None ...`.)

- [ ] **Step 4: Run test + gate + full suite**

Run: `.venv/bin/python -m pytest tests/test_experiment_abort_cancel.py -v && .venv/bin/python -m pytest tests/test_experiment_abort.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check .`
Expected: new test PASS; the existing abort suite (incl. `test_abort_idempotent`) still PASS; mypy/ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/run.py tests/test_experiment_abort_cancel.py
git commit -m "fix(experiment): abort cancels the root task at most once (5b)"
```

---

## Task 4: pin operator-abort vs external-cancel status

**Files:**
- Modify: `tests/test_experiment_abort_cancel.py`

**Interfaces:**
- Consumes: the `status` distinction already implemented in 5a Task 8 (`"aborted"` for operator abort, `"cancelled"` for external cancellation). This task pins the `"cancelled"` branch (the `"aborted"` branch is already pinned in `tests/test_experiment_abort.py`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_experiment_abort_cancel.py`:

```python
async def test_external_cancel_reports_cancelled(fake_client):
    # A cancellation NOT via run.abort() (e.g. an enclosing TaskGroup) => status "cancelled",
    # and the CancelledError propagates (asyncio correctness). Distinct from operator abort.
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight
    task.cancel()  # external cancellation, abort_requested stays False
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.report is not None
    assert run.report.status == "cancelled"
    assert isinstance(run.report.error, asyncio.CancelledError)
    # finalizer still ran: the in-flight dispense's device was stopped
    from tests.experiment_run_helpers import verbs
    assert ("pump_1", "stop") in verbs(fake)
```

- [ ] **Step 2: Run test to verify it passes (behavior from 5a)**

Run: `.venv/bin/python -m pytest tests/test_experiment_abort_cancel.py -v`
Expected: PASS. If `status` is `"aborted"` instead of `"cancelled"`, 5a Task 8's status logic was not applied — fix `execute()` (the `aborted = cancelled and ctx.abort_requested` branch) before proceeding.

- [ ] **Step 3: Gate + commit**

Run: `.venv/bin/python -m pytest tests/test_experiment_abort_cancel.py -q && .venv/bin/python -m ruff check . && awk 'length>100' tests/test_experiment_abort_cancel.py`
Expected: PASS; ruff clean; awk silent.

```bash
git add tests/test_experiment_abort_cancel.py
git commit -m "test(experiment): pin external-cancel 'cancelled' vs operator-abort 'aborted' status (5b)"
```

---

## Task 5: `Console` — introspection tier

**Files:**
- Create: `src/lab_devices/experiment/control.py`
- Modify: `src/lab_devices/experiment/__init__.py`
- Test: `tests/test_experiment_control.py`

**Interfaces:**
- Consumes: `LabClient.{list_devices,agent_info,device}`, `Device.{ping,status}`, `ExperimentRun.wire_lock` (Task 2).
- Produces:
  - `Console(client: LabClient, run: ExperimentRun | None = None)`.
  - `async list_devices() -> list[DeviceInfo]`, `async agent_info() -> AgentInfo`, `async device_status(device_id) -> Any`, `async device_ping(device_id) -> PingResult`.
  - Device wire calls route through `run.wire_lock(device_id)` when a run is present (D2), else call directly.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_experiment_control.py`:

```python
import asyncio

from lab_devices.experiment import Console, ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive

_DISPENSE = [{"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}}]


async def test_console_without_run_introspects(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    console = Console(client)
    devices = await console.list_devices()
    assert {d.id for d in devices} == {"pump_1", "pump_2", "valve_1", "densitometer_1"}
    info = await console.agent_info()
    assert info.version == "2.0.0+test"
    ping = await console.device_ping("densitometer_1")
    assert ping.uptime_ms == 8123456
    status = await console.device_status("densitometer_1")
    assert status == {"state": "idle"}


async def test_introspection_during_live_run_routes_through_wire_lock(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    console = Console(client, run)
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight; pump_1 busy but wire lock free between polls
    ping = await console.device_ping("pump_1")  # coexists via the shared wire lock (D2)
    assert ping.uptime_ms == 8123456
    fake.held_jobs.discard("dispense")
    await drive(clock, task)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_control.py -v`
Expected: FAIL — `ImportError: cannot import name 'Console'`.

- [ ] **Step 3: Implement the introspection tier**

Create `src/lab_devices/experiment/control.py`:

```python
"""Operator control plane: introspection + guarded recovery around a run. See design 5 §9."""

from __future__ import annotations

from typing import Any

from lab_devices.client import LabClient
from lab_devices.experiment.errors import DeviceBusyError
from lab_devices.experiment.run import ExperimentRun
from lab_devices.models import AgentInfo, DeviceInfo, PingResult


class Console:
    """Out-of-band operator surface (parent §3.2, design 5 §9). Never a block."""

    def __init__(self, client: LabClient, run: ExperimentRun | None = None) -> None:
        self._client = client
        self._run = run

    # ---- introspection (always safe, read-only) ----
    async def list_devices(self) -> list[DeviceInfo]:
        return await self._client.list_devices()

    async def agent_info(self) -> AgentInfo:
        return await self._client.agent_info()

    async def device_status(self, device_id: str) -> Any:
        device = self._client.device(device_id)
        if self._run is not None:
            async with self._run.wire_lock(device_id):
                return await device.status()
        return await device.status()

    async def device_ping(self, device_id: str) -> PingResult:
        device = self._client.device(device_id)
        if self._run is not None:
            async with self._run.wire_lock(device_id):
                return await device.ping()
        return await device.ping()
```

- [ ] **Step 4: Export `Console`**

In `src/lab_devices/experiment/__init__.py`, add `from lab_devices.experiment.control import Console` and add `"Console"` to `__all__`.

- [ ] **Step 5: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_control.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/control.py tests/test_experiment_control.py`
Expected: PASS; mypy/ruff clean; awk silent.

- [ ] **Step 6: Commit**

```bash
git add src/lab_devices/experiment/control.py src/lab_devices/experiment/__init__.py tests/test_experiment_control.py
git commit -m "feat(experiment): Console introspection tier with wire-lock routing (5b)"
```

---

## Task 6: `Console` — guarded recovery tier

**Files:**
- Modify: `src/lab_devices/experiment/control.py`
- Test: `tests/test_experiment_control.py`

**Interfaces:**
- Consumes: `LabClient.{rediscover,disconnect,list_devices}`, `ExperimentRun.{is_device_busy,busy_devices}` (Task 2), `DeviceBusyError` (Task 1).
- Produces:
  - `async rediscover() -> list[DeviceInfo]` — refuses if any run device is busy.
  - `async disconnect(device_id: str | None = None) -> int` — whole-agent (`None`) refuses if any run device busy; per-device refuses if that device busy, else resolves its port and disconnects it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_experiment_control.py`:

```python
import pytest

from lab_devices.experiment import DeviceBusyError


async def test_rediscover_without_run_allowed(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    console = Console(client)
    devices = await console.rediscover()
    assert len(devices) == 4


async def test_disconnect_refuses_busy_then_succeeds(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    console = Console(client, run)
    task = asyncio.ensure_future(run.execute())
    await clock.settle()  # dispense in flight -> pump_1 busy
    assert run.is_device_busy("pump_1")
    with pytest.raises(DeviceBusyError, match="pump_1"):
        await console.disconnect("pump_1")
    with pytest.raises(DeviceBusyError):
        await console.rediscover()  # any busy device blocks a bus rescan
    # after the run finishes, pump_1 is idle -> recovery allowed
    fake.held_jobs.discard("dispense")
    await drive(clock, task)
    assert not run.is_device_busy("pump_1")
    released = await console.disconnect("pump_1")
    assert released >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_experiment_control.py -k "rediscover or disconnect" -v`
Expected: FAIL — `AttributeError: 'Console' object has no attribute 'rediscover'`.

- [ ] **Step 3: Implement the recovery tier**

Add to `src/lab_devices/experiment/control.py` (`Console` class):

```python
    # ---- recovery (mutating, guarded: idle-only, design 5 §9) ----
    async def rediscover(self) -> list[DeviceInfo]:
        self._refuse_if_any_busy()
        return await self._client.rediscover()

    async def disconnect(self, device_id: str | None = None) -> int:
        if device_id is None:
            self._refuse_if_any_busy()
            return await self._client.disconnect()
        if self._run is not None and self._run.is_device_busy(device_id):
            raise DeviceBusyError(
                f"device {device_id!r} is busy; abort the run or wait before disconnecting"
            )
        return await self._client.disconnect(await self._port_of(device_id))

    def _refuse_if_any_busy(self) -> None:
        if self._run is None:
            return
        busy = self._run.busy_devices()
        if busy:
            raise DeviceBusyError(
                f"cannot recover while devices are busy: {sorted(busy)}; abort the run first"
            )

    async def _port_of(self, device_id: str) -> str | None:
        for info in await self._client.list_devices():
            if info.id == device_id:
                return info.port
        raise ValueError(f"unknown device id: {device_id!r}")
```

- [ ] **Step 4: Run tests + gate**

Run: `.venv/bin/python -m pytest tests/test_experiment_control.py -v && .venv/bin/python -m mypy src && .venv/bin/python -m ruff check . && awk 'length>100' src/lab_devices/experiment/control.py tests/test_experiment_control.py`
Expected: PASS; mypy/ruff clean; awk silent.

- [ ] **Step 5: Commit**

```bash
git add src/lab_devices/experiment/control.py tests/test_experiment_control.py
git commit -m "feat(experiment): Console guarded recovery tier (idle-only) (5b)"
```

---

## Task 7: E2E — introspection during a live paused run; wrap 5b

**Files:**
- Modify: `tests/test_experiment_control.py`
- Modify: `.superpowers/sdd/progress.md` (append 5b section)

**Interfaces:**
- Consumes: `Console`, `run.pause()`, `FakeLab.hold_job`.

- [ ] **Step 1: Write the failing test — introspection during a live *paused* run**

Append to `tests/test_experiment_control.py`:

```python
async def test_introspection_during_paused_run(fake_client):
    # Pause quiesces dispatch; introspection stays available and safe (parent §14).
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow(_DISPENSE)
    clock = FakeClock()
    run = ExperimentRun(client, wf, RunOptions(clock=clock))
    console = Console(client, run)
    task = asyncio.ensure_future(run.execute())
    await clock.settle()
    run.pause()
    await clock.settle()
    # while paused: introspection works, list_devices reflects the bus
    devices = await console.list_devices()
    assert any(d.id == "densitometer_1" for d in devices)
    status = await console.device_status("densitometer_1")
    assert status == {"state": "idle"}
    # a busy device still refuses disconnect even while paused
    with pytest.raises(DeviceBusyError):
        await console.disconnect("pump_1")
    # resume + finish
    run.resume()
    fake.held_jobs.discard("dispense")
    report = await drive(clock, task)
    assert report.status == "completed"
```

- [ ] **Step 2: Run test + full suite**

Run: `.venv/bin/python -m pytest tests/test_experiment_control.py -v && .venv/bin/python -m pytest -q`
Expected: PASS; whole suite green.

- [ ] **Step 3: Full gate + line-length sweep**

Run:
```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy src
.venv/bin/python -m ruff check .
awk 'length>100' src/lab_devices/experiment/*.py tests/test_experiment_*.py tests/fakelab.py tests/fakeclock.py tests/experiment_run_helpers.py
```
Expected: all green; awk silent. Record the passing count.

- [ ] **Step 4: Append the 5b ledger section**

Add a `# Increment 5b` section to `.superpowers/sdd/progress.md`: tasks 1–7 complete, passing count, the double-abort fix, the `"cancelled"` status pin, and the `Console` tiers. (Git-ignored; confirm with `git check-ignore .superpowers/sdd/progress.md`; no commit needed.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_experiment_control.py
git commit -m "test(experiment): introspection during a live paused run; Increment 5b complete (5b)"
```

---

## Self-Review (author checklist — completed at write time)

**Spec coverage (design 5 §8–§10):**
- §8 lifecycle tickets: double-abort guard → Task 3; abort-vs-cancel `"cancelled"` pin → Task 4 (code in 5a Task 8). (run_started guard + remembered sink errors + D4 removal are 5a.)
- §9 control plane: `Console` object → Tasks 5–6; introspection tier (list_devices/agent_info/status/ping) → Task 5; wire-lock coexistence → Tasks 5, 7; recovery tier (rediscover/disconnect) + idle oracle (`is_busy`) + refuse-when-busy → Tasks 2, 6; introspection during a live paused run → Task 7.
- §10 taxonomy: `DeviceBusyError` → Task 1.

**Placeholder scan:** no TBD/TODO; every code step shows complete code.

**Type consistency:** `Console(client, run=None)`, `wire_lock`/`is_device_busy`/`busy_devices`, `is_busy`/`busy_devices` on `Occupancy`, `DeviceBusyError`, `_port_of`/`_refuse_if_any_busy` used consistently across Tasks 1–7. Model shapes match `models/common.py` (`DeviceInfo.id/port`, `AgentInfo.version`, `PingResult.uptime_ms`) and the FakeLab canned values (`agent_info` version `2.0.0+test`, ping `uptime_ms` `8123456`, status `{"state": "idle"}`).

**Cross-plan dependency:** 5b relies on 5a Task 8's `execute()` rewrite for the `"cancelled"` status (Task 4 asserts it, with a fallback note if not yet applied). Everything else in 5b is self-contained.
