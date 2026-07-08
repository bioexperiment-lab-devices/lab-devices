"""Live occupancy: (device, channel) busy slots + the open-mode registry.
See design 4-exec §7."""

from __future__ import annotations

from dataclasses import dataclass

from lab_devices.experiment.errors import InvariantViolationError


@dataclass(frozen=True)
class OpenMode:
    """One live continuous mode awaiting its close or the finalizer."""

    device: str
    mode_verb: str
    teardown_verb: str
    teardown_params: dict[str, object]
    channels: frozenset[str]
    block_id: str


@dataclass(frozen=True)
class _Hold:
    """A slot held by one in-flight command."""

    block_id: str


class Occupancy:
    """Non-blocking busy tracking. Every method is synchronous, so check-and-mark
    cannot be interleaved by a sibling asyncio task (design 4-exec §7 step 4)."""

    def __init__(self) -> None:
        self._slots: dict[tuple[str, str], _Hold | OpenMode] = {}
        self._modes: list[OpenMode] = []  # open order; the finalizer walks it reversed

    def acquire(
        self, device: str, channels: frozenset[str], block_id: str, *,
        closes: str | None = None,
    ) -> None:
        """Mark `channels` busy for `block_id` or raise. `closes` names the mode this
        command closes: the matching close may pass through its own mode's slots — the
        one exception design §12 allows."""
        for channel in sorted(channels):
            occupant = self._slots.get((device, channel))
            if occupant is None:
                continue
            if isinstance(occupant, OpenMode) and closes == occupant.mode_verb:
                continue
            what = (
                f"mode {occupant.mode_verb!r} opened by block {occupant.block_id}"
                if isinstance(occupant, OpenMode)
                else f"command in flight from block {occupant.block_id}"
            )
            raise InvariantViolationError(
                f"({device}, {channel}) is occupied by {what}; block {block_id} "
                f"cannot dispatch — scheduler invariant violated"
            )
        for channel in channels:
            if (device, channel) not in self._slots:
                self._slots[(device, channel)] = _Hold(block_id)

    def release(self, device: str, channels: frozenset[str], block_id: str) -> None:
        """Free the command holds `block_id` placed; mode-held slots are untouched."""
        for channel in channels:
            occupant = self._slots.get((device, channel))
            if isinstance(occupant, _Hold) and occupant.block_id == block_id:
                del self._slots[(device, channel)]

    def register_open(self, mode: OpenMode) -> None:
        """Convert the opener's command holds into the mode's long-lived occupancy."""
        for channel in mode.channels:
            self._slots[(mode.device, channel)] = mode
        self._modes.append(mode)

    def register_close(self, device: str, mode_verb: str) -> OpenMode | None:
        """Pop an open mode and free its channels; None if not open (legal no-op)."""
        for i, mode in enumerate(self._modes):
            if mode.device == device and mode.mode_verb == mode_verb:
                del self._modes[i]
                for channel in mode.channels:
                    if self._slots.get((mode.device, channel)) is mode:
                        del self._slots[(mode.device, channel)]
                return mode
        return None

    def open_modes(self) -> tuple[OpenMode, ...]:
        """Snapshot of live modes in open order (the finalizer tears down reversed)."""
        return tuple(self._modes)
