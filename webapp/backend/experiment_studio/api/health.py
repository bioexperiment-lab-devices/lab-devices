"""Liveness + version endpoint. See webapp design §6."""

from __future__ import annotations

from importlib.metadata import version

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "library": version("bioexperiment-lab-devices"),
        "studio": version("experiment-studio"),
    }
