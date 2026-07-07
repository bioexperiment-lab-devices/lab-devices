"""Exception taxonomy for the experiment layer. See design §11-12."""

from __future__ import annotations


class ExperimentError(Exception):
    """Root of every error raised by the experiment layer."""


class WorkflowLoadError(ExperimentError):
    """A workflow document is malformed or structurally invalid at load time."""


class UnknownVerbError(WorkflowLoadError):
    """A command targets a (device-type, verb) pair absent from the registry."""
