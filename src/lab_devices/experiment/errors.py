"""Exception taxonomy for the experiment layer. See design §11-12."""

from __future__ import annotations


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
