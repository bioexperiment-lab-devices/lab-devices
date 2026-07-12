"""Shared fixtures: app factory + ASGI-transport client (no lifespan needed)."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from httpx_ws.transport import ASGIWebSocketTransport

import runsupport
from experiment_studio.app import create_app
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.docs_store import ExperimentsStore
from experiment_studio.runner import RunManager


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return create_app(Settings(static_dir=None, data_dir=tmp_path))


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://studio") as c:
        yield c
    db = getattr(app.state, "db", None)
    if db is not None:
        await db.close()


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    """Manager-level harness: real Database + RunManager over a FakeLab."""
    fake = runsupport.default_fake()
    db = await Database.connect(tmp_path / "studio.db")
    registry = runsupport.fake_registry()
    manager = RunManager(
        db,
        tmp_path,
        registry,
        client_factory=runsupport.fake_client_factory(fake),
        run_options=dict(runsupport.FAST_RUN_OPTIONS),
    )
    yield SimpleNamespace(
        fake=fake, db=db, manager=manager, docs=ExperimentsStore(db), data_dir=tmp_path
    )
    await manager.shutdown()
    await registry.aclose()
    await db.close()


@pytest.fixture
async def api(app: FastAPI, tmp_path: Path) -> AsyncIterator[SimpleNamespace]:
    """HTTP+WS harness: real app with an overridden RunManager over a FakeLab."""
    from experiment_studio.api.deps import get_run_manager

    fake = runsupport.default_fake()
    db = await Database.connect(tmp_path / "studio.db")
    app.state.db = db
    registry = runsupport.fake_registry()
    manager = RunManager(
        db,
        tmp_path,
        registry,
        client_factory=runsupport.fake_client_factory(fake),
        run_options=dict(runsupport.FAST_RUN_OPTIONS),
    )
    app.dependency_overrides[get_run_manager] = lambda: manager

    # ASGIWebSocketTransport.__aenter__ opens an anyio task group whose CancelScope
    # must be exited from the same asyncio Task it was entered in. pytest-asyncio
    # drives an async-generator fixture's setup and teardown as two separate
    # asyncio.Runner.run() calls (i.e. two different Tasks), so holding the
    # transport's `async with` open across `yield` crashes at teardown ("Attempted
    # to exit cancel scope in a different task than it was entered in"). Pin the
    # whole enter/exit pair to one dedicated background task instead.
    transport = ASGIWebSocketTransport(app=app)
    ready = asyncio.Event()
    stop = asyncio.Event()
    holder: dict[str, httpx.AsyncClient] = {}

    async def _own_client() -> None:
        async with httpx.AsyncClient(transport=transport, base_url="http://studio") as c:
            holder["client"] = c
            ready.set()
            await stop.wait()

    owner = asyncio.create_task(_own_client())
    await ready.wait()

    yield SimpleNamespace(
        client=holder["client"], fake=fake, manager=manager, db=db, data_dir=tmp_path
    )
    stop.set()
    await owner
    await manager.shutdown()
    await registry.aclose()
    await db.close()
