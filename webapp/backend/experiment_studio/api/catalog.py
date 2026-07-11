"""Verb/expression catalog endpoint. See webapp design §4.4, §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from lab_devices.experiment import expression_functions, verb_catalog

router = APIRouter()


@router.get("/catalog")
def catalog() -> dict[str, Any]:
    return {"device_types": verb_catalog(), "expression": expression_functions()}
