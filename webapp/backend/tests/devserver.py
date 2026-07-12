"""FakeLab-backed dev server — the W5 manual-gate backend (spec §12 W5).

Usage:
    cd webapp/backend && .venv/bin/python tests/devserver.py [--port 8000]

Serves the real app (API only; run `npm run dev` in webapp/frontend for the UI)
with labs/runs wired to an in-process FakeLab (pump_1 + densitometer_1). Data
lands in webapp/backend/.devdata — delete the directory to reset.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI

import runsupport
from experiment_studio.api.deps import get_db, get_run_manager
from experiment_studio.api.labs import get_labs_service
from experiment_studio.app import create_app
from experiment_studio.config import Settings
from experiment_studio.db import Database
from experiment_studio.labs import LabsService
from experiment_studio.runner import RunManager

DATA_DIR = Path(__file__).resolve().parents[1] / ".devdata"


async def _online(name: str) -> bool:
    return True


def build_app() -> FastAPI:
    app = create_app(Settings(static_dir=None, data_dir=DATA_DIR))
    fake = runsupport.default_fake()
    registry = runsupport.fake_registry()
    factory = runsupport.fake_client_factory(fake)
    holder: dict[str, RunManager] = {}

    async def dev_run_manager(db: Database = Depends(get_db)) -> RunManager:
        if "manager" not in holder:
            holder["manager"] = RunManager(
                db,
                DATA_DIR,
                registry,
                client_factory=factory,
                run_options={"job_poll_interval": 0.05, "job_poll_max": 0.2},
            )
        return holder["manager"]

    def dev_labs_service() -> LabsService:
        return LabsService(registry, client_factory=factory, probe=_online)

    app.dependency_overrides[get_run_manager] = dev_run_manager
    app.dependency_overrides[get_labs_service] = dev_labs_service
    return app


app = build_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    uvicorn.run(app, host="127.0.0.1", port=parser.parse_args().port)
