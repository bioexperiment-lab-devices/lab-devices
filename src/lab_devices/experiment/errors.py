"""Exception taxonomy for the experiment layer. See design §11-12."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class ExperimentError(Exception):
    """Root of every error raised by the experiment layer."""


class WorkflowLoadError(ExperimentError):
    """A workflow document is malformed or structurally invalid at load time."""


class UnknownVerbError(WorkflowLoadError):
    """A command targets a (device-type, verb) pair absent from the registry."""


class ExpressionError(WorkflowLoadError):
    """An expression string is syntactically invalid (design §6, §15)."""


class EvaluationError(ExperimentError):
    """An expression could not produce a value at runtime (fail-safe rule, design §6):
    empty stream window, unbound binding, divide-by-zero, or a type mismatch."""


@dataclass(frozen=True)
class Diagnostic:
    """One static-validation violation (design §12)."""

    category: str  # group|registry|params|type|block|declaration|data-flow|mode|affinity
    path: str  # structural block path, e.g. "blocks[0].children[2].body[1]"
    message: str

    def __str__(self) -> str:
        return f"[{self.category}] {self.path}: {self.message}"


class ValidationError(ExperimentError):
    """A workflow failed static validation (design §11-12); carries every violation found."""

    def __init__(self, diagnostics: Sequence[Diagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        lines = "\n".join(f"  - {d}" for d in self.diagnostics)
        super().__init__(f"{len(self.diagnostics)} validation error(s):\n{lines}")
