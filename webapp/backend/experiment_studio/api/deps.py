"""Request-scoped dependencies shared by run, record, and WebSocket routes.

These take HTTPConnection (not Request) so WebSocket endpoints can reuse them. Lazy
construction is the test-only path; production pre-populates app.state in lifespan.
"""

from __future__ import annotations

from fastapi import Depends
from starlette.requests import HTTPConnection

from lab_devices.discovery import LabRegistry

from experiment_studio.db import Database
from experiment_studio.records import RecordsStore
from experiment_studio.runner import RunManager


async def get_db(conn: HTTPConnection) -> Database:
    db = getattr(conn.app.state, "db", None)
    if db is None:
        settings = conn.app.state.settings
        db = await Database.connect(settings.data_dir / "studio.db")
        conn.app.state.db = db
    return db


async def get_records_store(
    conn: HTTPConnection, db: Database = Depends(get_db)
) -> RecordsStore:
    return RecordsStore(db, conn.app.state.settings.data_dir)


async def get_run_manager(
    conn: HTTPConnection, db: Database = Depends(get_db)
) -> RunManager:
    manager = getattr(conn.app.state, "run_manager", None)
    if manager is None:
        manager = RunManager(db, conn.app.state.settings.data_dir, LabRegistry())
        conn.app.state.run_manager = manager
    return manager
