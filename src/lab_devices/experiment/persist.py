"""Disk persistence sinks: buffered sync writers mirroring in-memory state. See design 5 §4-7."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

from lab_devices.experiment.errors import PersistenceError
from lab_devices.experiment.runlog import RunEvent
from lab_devices.experiment.state import Sample


class StreamSink(Protocol):
    """Disk mirror of one measurement stream (sync, buffered). See design 5 §4.1."""

    def write(self, sample: Sample) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


def run_event_to_dict(event: RunEvent) -> dict[str, Any]:
    """Lossless dict form of a RunEvent for jsonl / the csv data column (design 5 §7)."""
    return {
        "timestamp": event.timestamp,
        "kind": event.kind,
        "block_id": event.block_id,
        "data": event.data,
    }


_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_stream_filename(name: str) -> str:
    """Filesystem-safe base name for a stream file (no extension). Design 5 §6.

    Reject anything that sanitizes to empty or a path-traversal token — a stream name
    is an arbitrary workflow key, never trusted as a path component.
    """
    safe = _UNSAFE.sub("_", name)
    if not safe or set(safe) <= {".", "_"} and safe.strip("._") == "":
        raise PersistenceError(f"stream name {name!r} has no filesystem-safe form")
    if safe in {".", ".."}:
        raise PersistenceError(f"stream name {name!r} is not a safe path component")
    return safe


class _JsonlWriter:
    """Shared buffered jsonl append writer; best-effort, remembers its own errors."""

    def __init__(self, path: Path) -> None:
        self.errors: list[BaseException] = []
        self._file = open(path, "w", encoding="utf-8")  # noqa: SIM115 - lifetime is the run

    def _write_obj(self, obj: dict[str, Any]) -> None:
        try:
            self._file.write(json.dumps(obj) + "\n")
        except BaseException as exc:  # noqa: BLE001 - durability is best-effort (design 5 §8)
            self.errors.append(exc)

    def flush(self) -> None:
        try:
            self._file.flush()
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(exc)

    def close(self) -> None:
        try:
            self._file.close()
        except BaseException as exc:  # noqa: BLE001
            self.errors.append(exc)


class JsonlRunLogSink(_JsonlWriter):
    """Run log as one JSON object per line (design 5 §7). Conforms to RunLogSink."""

    def emit(self, event: RunEvent) -> None:
        self._write_obj(run_event_to_dict(event))


class JsonlStreamSink(_JsonlWriter):
    """One measurement stream as {"timestamp","value"} per line (design 5 §7)."""

    def write(self, sample: Sample) -> None:
        self._write_obj({"timestamp": sample.timestamp, "value": sample.value})
