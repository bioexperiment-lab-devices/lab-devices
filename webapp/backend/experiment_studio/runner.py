"""RunManager: at most one in-process experiment run per app instance. See design §7."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry
from lab_devices.experiment import (
    BindingValue,
    ExperimentRun,
    RunOptions,
    RunReport,
    ValidationError,
    WorkflowLoadError,
    workflow_from_dict,
)

from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentDoc, ExperimentsStore
from experiment_studio.inputs import WebInputProvider
from experiment_studio.records import RecordsStore
from experiment_studio.roles import substitute
from experiment_studio.sinks import TeeRunLogSink

_LOG = logging.getLogger(__name__)

ClientFactory = Callable[[LabInfo], LabClient]


class RunActiveError(Exception):
    """A run is already active (S8); also raised by guards that refuse work mid-run."""

    def __init__(self, active_run_id: str) -> None:
        super().__init__("a run is already active")
        self.active_run_id = active_run_id


class PreflightError(Exception):
    """Role mapping incomplete/mistyped or devices missing from the roster (§7.1.2)."""

    def __init__(self, diagnostics: list[dict[str, str]]) -> None:
        super().__init__(f"{len(diagnostics)} preflight error(s)")
        self.diagnostics = diagnostics


class StartValidationError(Exception):
    """Engine rejected the substituted workflow at construction (§7.1: 422 + record)."""

    def __init__(self, diagnostics: list[dict[str, str]], record_id: str) -> None:
        super().__init__(f"{len(diagnostics)} validation error(s)")
        self.diagnostics = diagnostics
        self.record_id = record_id


class UnknownRunError(Exception):
    """Control request for a run id that is not the active run (§6: 404)."""


@dataclass
class ActiveRun:
    run_id: str
    record_id: str
    experiment_id: str
    experiment_name: str
    lab: str
    role_mapping: dict[str, str]
    status: str  # running | paused; terminal statuses land on the record row
    run: ExperimentRun
    tee: TeeRunLogSink
    inputs: WebInputProvider
    client: LabClient
    artifact_dir: Path
    task: asyncio.Task[None] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _default_record_name(experiment_name: str) -> str:
    local = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    return f"{experiment_name} — {local}"


def _diag(role: str, message: str) -> dict[str, str]:
    return {"category": "mapping", "path": f"roles[{role!r}]", "message": message}


def _mapping_diagnostics(
    doc: ExperimentDoc, role_mapping: dict[str, str]
) -> list[dict[str, str]]:
    """§7.1.2 shape checks (roster existence is checked separately, needs the lab)."""
    diagnostics: list[dict[str, str]] = []
    for role, spec in doc.roles.items():
        device_id = role_mapping.get(role)
        if device_id is None:
            diagnostics.append(_diag(role, f"role {role!r} is not mapped to a device"))
        elif device_id.rsplit("_", 1)[0] != spec.type:
            diagnostics.append(
                _diag(role, f"device {device_id!r} is not a {spec.type!r}")
            )
    for extra in sorted(set(role_mapping) - set(doc.roles)):
        diagnostics.append(_diag(extra, f"mapping references unknown role {extra!r}"))
    return diagnostics


def _force_disk_persistence(workflow: dict[str, Any]) -> None:
    """§7.2: run copies always persist every stream to disk as CSV (S5)."""
    workflow["persistence"] = {"default": "disk", "format": "csv"}
    streams = workflow.get("streams")
    if isinstance(streams, dict):
        for decl in streams.values():
            if isinstance(decl, dict):
                decl.pop("persistence", None)


def _engine_diagnostics(exc: ValidationError | WorkflowLoadError) -> list[dict[str, str]]:
    if isinstance(exc, ValidationError):
        return [
            {"category": d.category, "path": d.path, "message": d.message}
            for d in exc.diagnostics
        ]
    return [{"category": "schema", "path": "workflow", "message": str(exc)}]


def _write_run_log(artifact_dir: Path, tee: TeeRunLogSink) -> None:
    lines = [json.dumps(event) for event in tee.events()]
    text = "\n".join(lines) + ("\n" if lines else "")
    (artifact_dir / "run_log.jsonl").write_text(text)


def _write_report(
    artifact_dir: Path,
    *,
    report: RunReport | None,
    status: str,
    clock_origin: float | None,
    started_at: str,
    ended_at: str,
    experiment_name: str,
    lab: str,
    role_mapping: dict[str, str],
    error: str | None = None,
    diagnostics: list[dict[str, str]] | None = None,
) -> None:
    if report is not None and report.error is not None:
        error = str(report.error)
    payload = {
        "status": status,
        "error": error,
        "finalize_errors": [str(e) for e in report.finalize_errors] if report else [],
        "persistence_errors": (
            [str(e) for e in report.persistence_errors] if report else []
        ),
        # Failures absorbed by `on_error: continue`. A run that dropped 40 samples still
        # reports `completed`, so without this it would look identical to a clean one.
        # This payload is built field-by-field: a new RunReport field is silently DROPPED
        # unless it is added here.
        "tolerated_errors": (
            [{"block_id": t.block_id, "error": t.error} for t in report.tolerated_errors]
            if report
            else []
        ),
        "diagnostics": diagnostics or [],
        "clock_origin": clock_origin,
        "started_at": started_at,
        "ended_at": ended_at,
        "experiment_name": experiment_name,
        "lab": lab,
        "role_mapping": role_mapping,
    }
    (artifact_dir / "report.json").write_text(json.dumps(payload, indent=2))


_TERMINAL_STATUSES = frozenset({"completed", "failed", "aborted", "cancelled", "interrupted"})


class RunManager:
    """Process singleton owning at most one (LabClient, ExperimentRun, Task) (§7.1)."""

    def __init__(
        self,
        db: Database,
        data_dir: Path,
        registry: LabRegistry,
        *,
        client_factory: ClientFactory | None = None,
        run_options: dict[str, Any] | None = None,
    ) -> None:
        self._db = db
        self._data_dir = data_dir
        self._registry = registry  # not owned: LabsService/lifespan closes it
        self._client_factory: ClientFactory = client_factory or (
            lambda info: LabClient(info.host, info.port)
        )
        self._run_options = dict(run_options or {})
        # kept after terminal so WS replay survives until the next start (§7.5)
        self._current: ActiveRun | None = None

    # ---- introspection ----

    def active(self) -> ActiveRun | None:
        current = self._current
        if current is None or current.task is None or current.task.done():
            return None
        if current.status in _TERMINAL_STATUSES:
            return None  # finalization window (§7.1.5): run is over, task still flushing
        return current

    def active_payload(self) -> dict[str, Any] | None:
        """GET /api/runs/active — everything a fresh browser needs to reattach (§6)."""
        current = self.active()
        if current is None:
            return None
        pending = current.inputs.pending
        return {
            "run_id": current.run_id,
            "record_id": current.record_id,
            "experiment": {"id": current.experiment_id, "name": current.experiment_name},
            "lab": current.lab,
            "status": current.status,
            "seq": current.tee.last_seq,
            "pending_input": dataclasses.asdict(pending) if pending is not None else None,
        }

    def current_task(self) -> asyncio.Task[None] | None:
        return self._current.task if self._current is not None else None

    def stream(self, run_id: str, since: int) -> AsyncIterator[dict[str, Any]]:
        """WS source: replay + live for the current (possibly finished) run (§7.5)."""
        current = self._current
        if current is None or current.run_id != run_id:
            raise UnknownRunError(f"no run {run_id!r}")
        return current.tee.stream(since)

    # ---- lifecycle ----

    async def start(
        self, experiment_id: str, lab: str, role_mapping: dict[str, str]
    ) -> str:
        active = self.active()
        if active is not None:
            raise RunActiveError(active.run_id)
        stored = await ExperimentsStore(self._db).get(experiment_id)
        doc = ExperimentDoc.model_validate(stored["doc"])
        diagnostics = _mapping_diagnostics(doc, role_mapping)
        if diagnostics:
            raise PreflightError(diagnostics)
        info = await self._registry.lookup(lab)
        client = self._client_factory(info)
        try:
            return await self._start_checked(
                client, stored, doc, experiment_id, lab, role_mapping
            )
        except BaseException:
            await client.aclose()
            raise

    async def _start_checked(
        self,
        client: LabClient,
        stored: dict[str, Any],
        doc: ExperimentDoc,
        experiment_id: str,
        lab: str,
        role_mapping: dict[str, str],
    ) -> str:
        present = {device.id for device in await client.list_devices() if device.id}
        roster_diags = [
            _diag(role, f"device {device_id!r} not found in lab {lab!r}")
            for role, device_id in sorted(role_mapping.items())
            if device_id not in present
        ]
        if roster_diags:
            raise PreflightError(roster_diags)
        substituted, ref_diags = substitute(doc.workflow, role_mapping)
        if ref_diags:
            raise PreflightError(ref_diags)
        _force_disk_persistence(substituted)

        run_id = str(uuid4())
        dir_rel = f"runs/{run_id}"
        artifact_dir = self._data_dir / dir_rel
        artifact_dir.mkdir(parents=True, exist_ok=False)
        started_at = _utc_now()
        records = RecordsStore(self._db, self._data_dir)
        await records.create(
            record_id=run_id,
            name=_default_record_name(doc.name),
            experiment_id=experiment_id,
            experiment_name=doc.name,
            lab=lab,
            role_mapping=role_mapping,
            started_at=started_at,
            dir=dir_rel,
        )
        try:
            (artifact_dir / "doc.json").write_text(json.dumps(stored["doc"], indent=2))
            (artifact_dir / "workflow.json").write_text(
                json.dumps(substituted, indent=2)
            )

            tee = TeeRunLogSink()
            inputs = WebInputProvider()
            options = RunOptions(
                log_sink=tee,
                input_provider=inputs,
                output_dir=artifact_dir,
                **self._run_options,
            )
            try:
                # construction runs the engine validator against the REAL device ids —
                # this is the real-mapping re-validation (two roles on one device etc.)
                run = ExperimentRun(client, workflow_from_dict(substituted), options)
            except (ValidationError, WorkflowLoadError) as exc:
                diagnostics = _engine_diagnostics(exc)
                ended_at = _utc_now()
                _write_report(
                    artifact_dir,
                    report=None,
                    status="failed",
                    clock_origin=None,
                    started_at=started_at,
                    ended_at=ended_at,
                    experiment_name=doc.name,
                    lab=lab,
                    role_mapping=role_mapping,
                    error=str(exc),
                    diagnostics=diagnostics,
                )
                await records.finalize(run_id, status="failed", ended_at=ended_at)
                raise StartValidationError(diagnostics, run_id) from exc

            clock_origin = options.clock.now()
            current = ActiveRun(
                run_id=run_id,
                record_id=run_id,
                experiment_id=experiment_id,
                experiment_name=doc.name,
                lab=lab,
                role_mapping=dict(role_mapping),
                status="running",
                run=run,
                tee=tee,
                inputs=inputs,
                client=client,
                artifact_dir=artifact_dir,
            )
            # must run before self._current/create_task below: if start() is
            # cancelled here, no task is running yet and the guard below finalizes
            # the record as failed instead of yanking the client out from under
            # the just-launched task (see Finding 3 in the run-backend review).
            try:
                await records.save_mapping(experiment_id, lab, role_mapping)  # S2 memory
            except Exception:
                _LOG.exception("failed saving role mapping for %s", run_id)
            self._current = current
            tee.append_status("running")
            current.task = asyncio.create_task(
                self._execute(current, clock_origin=clock_origin, started_at=started_at)
            )
            return run_id
        except StartValidationError:
            raise  # its own path already finalized the record
        except BaseException as exc:
            # any other failure after records.create() above — e.g. an OSError
            # writing artifacts, a bad **self._run_options key, or cancellation —
            # must not leave a phantom 'running' record (design §10).
            ended_at = _utc_now()
            with contextlib.suppress(Exception):
                _write_report(
                    artifact_dir,
                    report=None,
                    status="failed",
                    clock_origin=None,
                    started_at=started_at,
                    ended_at=ended_at,
                    experiment_name=doc.name,
                    lab=lab,
                    role_mapping=role_mapping,
                    error=str(exc),
                )
            with contextlib.suppress(Exception):
                await records.finalize(run_id, status="failed", ended_at=ended_at)
            raise

    async def _execute(
        self, current: ActiveRun, *, clock_origin: float, started_at: str
    ) -> None:
        try:
            await current.run.execute()
        except BaseException:  # outcome (incl. abort/cancel) lives on run.report
            pass
        finally:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()  # abort() cancelled us once; finalization must proceed
            report = current.run.report
            status = report.status if report is not None else "interrupted"
            current.status = status
            ended_at = _utc_now()
            try:
                _write_run_log(current.artifact_dir, current.tee)
            except Exception:
                _LOG.exception("failed writing run log for run %s", current.run_id)
            try:
                _write_report(
                    current.artifact_dir,
                    report=report,
                    status=status,
                    clock_origin=clock_origin,
                    started_at=started_at,
                    ended_at=ended_at,
                    experiment_name=current.experiment_name,
                    lab=current.lab,
                    role_mapping=current.role_mapping,
                )
            except Exception:
                _LOG.exception("failed writing report for run %s", current.run_id)
            try:
                await RecordsStore(self._db, self._data_dir).finalize(
                    current.record_id, status=status, ended_at=ended_at
                )
            except Exception:
                _LOG.exception("failed finalizing record %s", current.record_id)
            current.tee.append_status(status)
            current.tee.close()
            try:
                await current.client.aclose()
            except Exception:
                _LOG.exception("failed closing lab client for run %s", current.run_id)

    # ---- controls (§6) ----

    def _require_active(self, run_id: str) -> ActiveRun:
        current = self.active()
        if current is None or current.run_id != run_id:
            raise UnknownRunError(f"no active run {run_id!r}")
        return current

    def pause(self, run_id: str) -> None:
        current = self._require_active(run_id)
        if current.status != "paused":
            current.run.pause()
            current.status = "paused"
            current.tee.append_status("paused")

    def resume(self, run_id: str) -> None:
        current = self._require_active(run_id)
        if current.status != "running":
            current.run.resume()
            current.status = "running"
            current.tee.append_status("running")

    def abort(self, run_id: str) -> None:
        """Idempotent while active (§6); the engine's abort() is itself idempotent."""
        self._require_active(run_id).run.abort()

    def submit_input(self, run_id: str, value: BindingValue) -> None:
        self._require_active(run_id).inputs.submit(value)

    async def shutdown(self) -> None:
        """Graceful teardown: abort any active run and wait for its finalization."""
        current = self._current
        if current is None or current.task is None or current.task.done():
            return
        current.run.abort()
        try:
            await asyncio.wait_for(asyncio.shield(current.task), timeout=15)
        except (TimeoutError, asyncio.CancelledError):
            _LOG.warning("run %s did not finalize during shutdown", current.run_id)
