"""FastAPI application factory: API routers, error mapping, SPA static serving.
See webapp design §5-6."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from lab_devices import errors as lab_errors

from experiment_studio.api.catalog import router as catalog_router
from experiment_studio.api.experiments import router as experiments_router
from experiment_studio.api.health import router as health_router
from experiment_studio.api.labs import router as labs_router
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.docs_store import NameConflictError, UnknownExperimentError

# Spec §6: structured error envelope {detail, code}. Starlette resolves handlers along
# the raised exception's MRO, so the specific entries below (e.g. DiscoveryInProgressError)
# win over the LabError catch-all; httpx.HTTPError covers transport-level failures outside
# the lab-error hierarchy.
_ERROR_MAP: list[tuple[type[Exception], int, str]] = [
    (UnknownExperimentError, 404, "unknown_experiment"),
    (NameConflictError, 409, "name_conflict"),
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
    app.state.db = await Database.connect(settings.data_dir / "studio.db")
    yield
    db = getattr(app.state, "db", None)
    if db is not None:
        await db.close()
    labs = getattr(app.state, "labs", None)
    if labs is not None:
        await labs.aclose()


def _error_handler(
    status: int, code: str
) -> Callable[[Request, Exception], Coroutine[Any, Any, JSONResponse]]:
    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc), "code": code})

    return handle


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    app = FastAPI(title="experiment-studio", lifespan=_lifespan)
    app.state.settings = settings
    for exc_type, status, code in _ERROR_MAP:
        app.add_exception_handler(exc_type, _error_handler(status, code))
    app.include_router(health_router, prefix="/api")
    app.include_router(catalog_router, prefix="/api")
    app.include_router(labs_router, prefix="/api/labs")
    app.include_router(experiments_router, prefix="/api/experiments")
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
