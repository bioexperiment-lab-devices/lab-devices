"""Stateless draft-validation endpoint. See webapp design §4.3, §6."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from experiment_studio.docs_store import ExperimentDoc, binding_types_for_doc, validate_doc

router = APIRouter()


@router.post("/validate")
def validate_document(doc: ExperimentDoc) -> dict[str, Any]:
    diagnostics = validate_doc(doc)
    return {
        "ok": not diagnostics,
        "diagnostics": diagnostics,
        "binding_types": binding_types_for_doc(doc),
    }
