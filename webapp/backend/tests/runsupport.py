"""Harness for run-backend tests: fake roster registry, FakeLab-backed clients, fast docs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Engine test doubles live at the repo root (tests/fakelab.py); bootstrap the path so
# the webapp suite reuses them instead of forking a copy.
_ENGINE_TESTS = str(Path(__file__).resolve().parents[3] / "tests")
if _ENGINE_TESTS not in sys.path:
    sys.path.insert(0, _ENGINE_TESTS)

import httpx  # noqa: E402
from fakelab import FakeLab  # noqa: E402

from lab_devices.client import LabClient  # noqa: E402
from lab_devices.discovery import LabInfo, LabRegistry  # noqa: E402

from experiment_studio.runner import ClientFactory  # noqa: E402

LAB = "lab_a"
MAPPING = {"feed": "pump_1", "meter": "densitometer_1"}
FAST_RUN_OPTIONS: dict[str, Any] = {"job_poll_interval": 0.005, "job_poll_max": 0.01}
TERMINAL = {"completed", "failed", "aborted", "cancelled", "interrupted"}


def default_fake() -> FakeLab:
    fake = FakeLab()
    fake.add_device("pump_1", "pump")
    fake.add_device("densitometer_1", "densitometer")
    return fake


def fake_registry() -> LabRegistry:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={LAB: {"host": "lab-a", "port": 9000}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LabRegistry(url="http://siteapp:8000/api/clients/", http=http)


def fake_client_factory(fake: FakeLab) -> ClientFactory:
    def factory(info: LabInfo) -> LabClient:
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(fake.handler),
            base_url=f"http://{info.host}:{info.port}",
        )
        return LabClient(info.host, info.port, http=http)

    return factory


def make_doc(
    blocks: list[dict[str, Any]],
    *,
    name: str = "Growth run",
    roles: dict[str, dict[str, str]] | None = None,
    streams: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A schema-2 experiment doc. Roles live INSIDE the workflow now (design 2026-07-20 §5);
    the envelope carries no `roles` key. `device:` fields hold role names the engine resolves
    via RunOptions.role_mapping at run start."""
    return {
        "doc_version": 1,
        "name": name,
        "workflow": {
            "schema_version": 2,
            "metadata": {"name": name},
            "persistence": {"default": "in_memory", "format": "jsonl"},
            "roles": (
                roles
                if roles is not None
                else {"feed": {"type": "pump"}, "meter": {"type": "densitometer"}}
            ),
            "streams": streams if streams is not None else {"od": {"units": "AU"}},
            "blocks": blocks,
        },
    }


HAPPY_BLOCKS: list[dict[str, Any]] = [
    {
        "serial": {
            "children": [
                {
                    "command": {
                        "device": "feed",
                        "verb": "dispense",
                        "params": {"volume_ml": 1},
                    }
                },
                {"measure": {"device": "meter", "verb": "measure", "into": "od"}},
                {"wait": {"duration": "1ms"}},
            ]
        }
    }
]

INPUT_BLOCKS: list[dict[str, Any]] = [
    {
        "serial": {
            "children": [
                {
                    "operator_input": {
                        "name": "target",
                        "type": "int",
                        "prompt": "Target cycles?",
                        "min": 1,
                        "max": 10,
                    }
                },
                {"measure": {"device": "meter", "verb": "measure", "into": "od"}},
            ]
        }
    }
]

INVALID_BLOCKS: list[dict[str, Any]] = [
    {
        "serial": {
            "children": [
                {"command": {"device": "feed", "verb": "dispense", "params": {}}}
            ]
        }
    }
]
