"""Lifespan wiring: eager services, crash sweep, guarded shutdown. See design §7.6."""

from pathlib import Path

from experiment_studio.app import create_app
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.labs import LabsService
from experiment_studio.records import RecordsStore
from experiment_studio.runner import RunManager


async def test_lifespan_constructs_services_and_sweeps(tmp_path: Path) -> None:
    db = await Database.connect(tmp_path / "studio.db")
    await RecordsStore(db, tmp_path).create(
        record_id="phantom",
        name="crashed",
        experiment_id=None,
        experiment_name="Exp",
        lab="lab_a",
        role_mapping={},
        started_at="2026-07-12T10:00:00+00:00",
        dir="runs/phantom",
    )
    await db.close()

    app = create_app(Settings(static_dir=None, data_dir=tmp_path))
    async with app.router.lifespan_context(app):
        assert isinstance(app.state.labs, LabsService)
        assert isinstance(app.state.run_manager, RunManager)
        record = await RecordsStore(app.state.db, tmp_path).get("phantom")
        assert record["status"] == "interrupted"
        assert record["ended_at"] is not None
