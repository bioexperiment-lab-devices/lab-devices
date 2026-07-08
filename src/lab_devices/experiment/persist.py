"""Disk persistence sinks: buffered sync writers mirroring in-memory state. See design 5 §4-7."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from lab_devices.experiment.errors import PersistenceError
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent, RunLogSink
from lab_devices.experiment.state import Sample
from lab_devices.experiment.workflow import Workflow


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


class _CsvWriter:
    """Shared buffered csv append writer with a fixed header; best-effort."""

    def __init__(self, path: Path, header: list[str]) -> None:
        self.errors: list[BaseException] = []
        self._file = open(path, "w", encoding="utf-8", newline="")  # noqa: SIM115 - run lifetime
        self._writer = csv.writer(self._file)
        self._write_row(header)

    def _write_row(self, row: list[str]) -> None:
        try:
            self._writer.writerow(row)
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


class CsvRunLogSink(_CsvWriter):
    """Run log as csv; the event data dict is JSON-encoded into one column (design 5 §7)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, ["timestamp", "kind", "block_id", "data"])

    def emit(self, event: RunEvent) -> None:
        self._write_row([
            repr(event.timestamp),
            event.kind,
            event.block_id or "",
            json.dumps(event.data),
        ])


class CsvStreamSink(_CsvWriter):
    """One measurement stream as timestamp,value rows (design 5 §7)."""

    def __init__(self, path: Path) -> None:
        super().__init__(path, ["timestamp", "value"])

    def write(self, sample: Sample) -> None:
        self._write_row([repr(sample.timestamp), repr(sample.value)])


_RUNLOG_SINKS: dict[str, Callable[[Path], RunLogSink]] = {
    "jsonl": JsonlRunLogSink,
    "csv": CsvRunLogSink,
}
_STREAM_SINKS: dict[str, Callable[[Path], StreamSink]] = {
    "jsonl": JsonlStreamSink,
    "csv": CsvStreamSink,
}


class SinkSet:
    """Resolved persistence for one run: log sink + per-stream sinks (design 5 §4.2, §5)."""

    def __init__(
        self,
        log_sink: RunLogSink,
        stream_sinks: dict[str, StreamSink | None],
        has_disk: bool,
    ) -> None:
        self.log_sink = log_sink
        self.stream_sinks = stream_sinks
        self.has_disk = has_disk

    @classmethod
    def build(
        cls,
        workflow: Workflow,
        output_dir: Path | str | None,
        log_sink_override: RunLogSink | None,
    ) -> SinkSet:
        if output_dir is not None:
            output_dir = Path(output_dir)  # accept a plain str (spec §5: Path | str | None)
        fmt = workflow.persistence.format
        if fmt not in _RUNLOG_SINKS:
            raise PersistenceError(f"unknown persistence format {fmt!r}")
        default = workflow.persistence.default
        if default not in {"in_memory", "disk"}:
            raise PersistenceError(f"unknown persistence default {default!r}")
        for name, decl in workflow.streams.items():
            if decl.persistence is not None and decl.persistence not in {"in_memory", "disk"}:
                raise PersistenceError(
                    f"unknown persistence {decl.persistence!r} for stream {name!r}"
                )

        # 1. Decide what disk files are needed, without opening anything yet.
        log_on_disk = log_sink_override is None and default == "disk"
        stream_on_disk: dict[str, str] = {}  # stream name -> safe base filename
        used: dict[str, str] = {}  # safe base -> originating stream name (collision guard)
        for name, decl in workflow.streams.items():
            effective = decl.persistence if decl.persistence is not None else default
            if effective == "disk":
                base = safe_stream_filename(name)
                if base in used:
                    raise PersistenceError(
                        f"stream name collision: {name!r} and {used[base]!r} both map to "
                        f"{base!r}.{fmt}"
                    )
                used[base] = name
                stream_on_disk[name] = base

        any_disk = log_on_disk or bool(stream_on_disk)
        if any_disk and output_dir is None:
            raise PersistenceError("disk persistence requested but output_dir is None")

        # 2. Refuse to clobber: check every target before opening any file.
        targets: list[Path] = []
        if any_disk:
            assert output_dir is not None
            if log_on_disk:
                targets.append(output_dir / f"run_log.{fmt}")
            targets += [output_dir / f"{base}.{fmt}" for base in stream_on_disk.values()]
            for path in targets:
                if path.exists():
                    raise PersistenceError(f"persistence target already exists: {path}")
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise PersistenceError(f"cannot create output_dir {output_dir}: {exc}") from exc

        # 3. Open sinks (all guards passed). Disk-opening errors must not leak handles.
        opened: list[Any] = []
        try:
            if log_sink_override is not None:
                log_sink: RunLogSink = log_sink_override
            elif log_on_disk:
                assert output_dir is not None
                log_sink = _RUNLOG_SINKS[fmt](output_dir / f"run_log.{fmt}")
                opened.append(log_sink)
            else:
                log_sink = InMemoryRunLog()

            stream_sinks: dict[str, StreamSink | None] = {}
            for name in workflow.streams:
                disk_base = stream_on_disk.get(name)
                if disk_base is None:
                    stream_sinks[name] = None
                else:
                    assert output_dir is not None
                    sink = _STREAM_SINKS[fmt](output_dir / f"{disk_base}.{fmt}")
                    stream_sinks[name] = sink
                    opened.append(sink)
        except OSError as exc:
            for sink in opened:
                try:
                    sink.close()
                except BaseException:  # noqa: BLE001 - best-effort cleanup on failure path
                    pass
            raise PersistenceError(f"cannot open persistence file: {exc}") from exc

        return cls(log_sink, stream_sinks, has_disk=bool(stream_on_disk) or log_on_disk)

    def _disk_sinks(self) -> list[Any]:
        sinks: list[Any] = [s for s in self.stream_sinks.values() if s is not None]
        if hasattr(self.log_sink, "flush") or hasattr(self.log_sink, "errors"):
            sinks.append(self.log_sink)
        return sinks

    def flush_all(self) -> None:
        for sink in self._disk_sinks():
            if hasattr(sink, "flush"):
                sink.flush()

    def close_all(self) -> None:
        for sink in self._disk_sinks():
            if hasattr(sink, "close"):
                sink.close()

    def persistence_errors(self) -> tuple[BaseException, ...]:
        errors: list[BaseException] = []
        for sink in self._disk_sinks():
            errors.extend(getattr(sink, "errors", ()))
        return tuple(errors)
