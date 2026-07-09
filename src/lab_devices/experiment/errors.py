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


class ExperimentRunError(ExperimentError):
    """Base for errors raised while executing a workflow (design 4-exec §15)."""


class BlockFailedError(ExperimentRunError):
    """A block failed at dispatch or completion; `__cause__` carries the original error."""

    def __init__(self, block_id: str, message: str) -> None:
        self.block_id = block_id
        super().__init__(f"block {block_id}: {message}")


class InvariantViolationError(ExperimentRunError):
    """A proven-impossible occupancy state was observed (busy-slot conflict or hardware
    BusyError). Never retried: the static proof was violated (design 4-exec §7)."""


class RunAbortedError(ExperimentRunError):
    """The operator aborted the run; the finalizer has completed (design 4-exec §10)."""


class FinalizeError(ExperimentRunError):
    """The run completed, but the finalizer could not fully reach safe state (D8)."""

    def __init__(self, errors: Sequence[BaseException]) -> None:
        self.errors = tuple(errors)
        super().__init__(
            f"{len(self.errors)} finalizer error(s); hardware may not be in a safe state"
        )


class PersistenceError(ExperimentRunError):
    """A persistence sink could not be built: bad/missing config, missing output_dir,
    a target file already exists, a stream-name collision, or a bad format (design 5 §10)."""


class DeviceBusyError(ExperimentRunError):
    """A recovery-tier action targeted a device that is not idle (design 5 §9-10)."""
