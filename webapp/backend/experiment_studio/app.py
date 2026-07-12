"""FastAPI application factory: API routers, error mapping, SPA static serving.
See webapp design §5-6."""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from lab_devices import errors as lab_errors
from lab_devices.discovery import LabRegistry
from lab_devices.experiment import EvaluationError

from experiment_studio.api.catalog import router as catalog_router
from experiment_studio.api.experiments import router as experiments_router
from experiment_studio.api.health import router as health_router
from experiment_studio.api.labs import router as labs_router
from experiment_studio.api.records import router as records_router
from experiment_studio.api.runs import router as runs_router
from experiment_studio.api.validate import router as validate_router
from experiment_studio.api.ws import router as ws_router
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.docs_store import NameConflictError, UnknownExperimentError
from experiment_studio.inputs import NoPendingInputError
from experiment_studio.labs import LabsService
from experiment_studio.records import RecordsStore, UnknownRecordError
from experiment_studio.runner import (
    PreflightError,
    RunActiveError,
    RunManager,
    StartValidationError,
    UnknownRunError,
)

_LOG = logging.getLogger(__name__)

# Spec §6: structured error envelope {detail, code}. Starlette resolves handlers along
# the raised exception's MRO, so the specific entries below (e.g. DiscoveryInProgressError)
# win over the LabError catch-all; httpx.HTTPError covers transport-level failures outside
# the lab-error hierarchy.
_ERROR_MAP: list[tuple[type[Exception], int, str]] = [
    (UnknownExperimentError, 404, "unknown_experiment"),
    (NameConflictError, 409, "name_conflict"),
    (UnknownRecordError, 404, "unknown_record"),
    (UnknownRunError, 404, "unknown_run"),
    (NoPendingInputError, 409, "no_pending_input"),
    (EvaluationError, 422, "invalid_value"),
    (lab_errors.UnknownLabClient, 404, "unknown_lab"),
    (lab_errors.LabOffline, 502, "lab_offline"),
    (lab_errors.ClientLookupEndpointUnreachable, 502, "roster_unreachable"),
    (lab_errors.ClientLookupEndpointError, 502, "roster_error"),
    (lab_errors.DiscoveryInProgressError, 409, "agent_busy"),
    (lab_errors.JobInProgressError, 409, "agent_busy"),
    (lab_errors.DiscoveryFailedError, 502, "discovery_failed"),
    (httpx.HTTPError, 502, "lab_unreachable"),
    (lab_errors.LabError, 502, "lab_error"),
]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    db = await Database.connect(settings.data_dir / "studio.db")
    app.state.db = db
    swept = await RecordsStore(db, settings.data_dir).sweep_interrupted()  # §7.6
    if swept:
        _LOG.warning("crash sweep: marked %d running record(s) interrupted", swept)
    registry = LabRegistry()
    app.state.labs = LabsService(registry)
    app.state.run_manager = RunManager(db, settings.data_dir, registry)
    try:
        yield
    finally:
        # guard each teardown so one failure cannot leak the others (W2 carry-forward)
        manager = getattr(app.state, "run_manager", None)
        if manager is not None:
            with contextlib.suppress(Exception):
                await manager.shutdown()
        labs = getattr(app.state, "labs", None)
        if labs is not None:
            with contextlib.suppress(Exception):
                await labs.aclose()  # also closes the shared registry
        current_db = getattr(app.state, "db", None)
        if current_db is not None:
            with contextlib.suppress(Exception):
                await current_db.close()


def _error_handler(
    status: int, code: str
) -> Callable[[Request, Exception], Coroutine[Any, Any, JSONResponse]]:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc), "code": code})

    return handle


async def _run_active_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RunActiveError)
    return JSONResponse(
        status_code=409,
        content={
            "detail": str(exc),
            "code": "run_active",
            "active_run_id": exc.active_run_id,
        },
    )


async def _preflight_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, PreflightError)
    return JSONResponse(
        status_code=422,
        content={
            "detail": str(exc),
            "code": "preflight_failed",
            "diagnostics": exc.diagnostics,
        },
    )


async def _start_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StartValidationError)
    return JSONResponse(
        status_code=422,
        content={
            "detail": str(exc),
            "code": "validation_failed",
            "diagnostics": exc.diagnostics,
            "record_id": exc.record_id,
        },
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    app = FastAPI(title="experiment-studio", lifespan=_lifespan)
    app.state.settings = settings
    for exc_type, status, code in _ERROR_MAP:
        app.add_exception_handler(exc_type, _error_handler(status, code))
    app.add_exception_handler(RunActiveError, _run_active_handler)
    app.add_exception_handler(PreflightError, _preflight_handler)
    app.add_exception_handler(StartValidationError, _start_validation_handler)
    app.include_router(health_router, prefix="/api")
    app.include_router(catalog_router, prefix="/api")
    app.include_router(labs_router, prefix="/api/labs")
    app.include_router(experiments_router, prefix="/api/experiments")
    app.include_router(validate_router, prefix="/api")
    app.include_router(runs_router, prefix="/api/runs")
    app.include_router(records_router, prefix="/api/records")
    app.include_router(ws_router, prefix="/api")
    if settings.static_dir is not None:
        _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve built frontend files; unknown non-API paths fall back to index.html."""
    root = static_dir.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)
