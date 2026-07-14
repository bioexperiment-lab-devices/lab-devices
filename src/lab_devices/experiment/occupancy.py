"""Live occupancy: (device, channel) busy slots + the open-mode registry.
See design 4-exec §7."""

from __future__ import annotations

from dataclasses import dataclass

from lab_devices.experiment.errors import InvariantViolationError, OrphanedJobError


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


@dataclass(frozen=True)
class _Stranded:
    """A slot held by a job the engine ABANDONED and could not stop — it is still physically
    running on the hardware (design 2026-07-14 §3.2).

    Not a `_Hold`: the block that placed it is over, so `release` must never free it. Nothing
    but a successful stop (the retry's orphan-clear) or the finalizer ends this occupancy, and
    until then the channels really are busy — which is precisely what `Occupancy` models."""

    block_id: str
    job_id: str


class Occupancy:
    """Non-blocking busy tracking. Every method is synchronous, so check-and-mark
    cannot be interleaved by a sibling asyncio task (design 4-exec §7 step 4)."""

    def __init__(self) -> None:
        self._slots: dict[tuple[str, str], _Hold | OpenMode | _Stranded] = {}
        self._modes: list[OpenMode] = []  # open order; the finalizer walks it reversed

    def acquire(
        self, device: str, channels: frozenset[str], block_id: str, *,
        closes: str | None = None,
    ) -> None:
        """Mark `channels` busy for `block_id` or raise. `closes` names the mode this
        command closes: the matching close may pass through its own mode's slots — the
        one exception design §12 allows.

        A slot held by a STRANDED job raises `OrphanedJobError`, not `InvariantViolationError`:
        no proven-impossible state was observed. The engine knows exactly what is on that
        channel — a job it abandoned and could not stop — and refuses to dispatch on top of it.
        Calling that an invariant violation would blame the scheduler for a fault it detected
        and reported correctly, and (being never-tolerated) would kill a run whose author
        explicitly asked to survive device faults."""
        for channel in sorted(channels):
            occupant = self._slots.get((device, channel))
            if occupant is None:
                continue
            if isinstance(occupant, OpenMode) and closes == occupant.mode_verb:
                continue
            if isinstance(occupant, _Stranded):
                raise OrphanedJobError(
                    f"({device}, {channel}) is occupied by job {occupant.job_id}, abandoned by "
                    f"block {occupant.block_id} and still running on the hardware (the engine "
                    f"could not stop it); block {block_id} will not dispatch on top of a live job"
                )
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
        """Free the command holds `block_id` placed; mode-held and stranded-job slots are
        untouched (their occupancy outlives the block that started it)."""
        for channel in channels:
            occupant = self._slots.get((device, channel))
            if isinstance(occupant, _Hold) and occupant.block_id == block_id:
                del self._slots[(device, channel)]

    def strand(
        self, device: str, channels: frozenset[str], block_id: str, job_id: str
    ) -> None:
        """Convert `block_id`'s command holds into a stranded-job occupancy.

        The block is finished but its job is NOT: `_await_job` has two exits (a job timeout and
        an exhausted poll-failure budget) that leave a job physically running, and the retry's
        orphan-clear may fail closed rather than stop it (a device-wide stop would kill an open
        mode). Releasing those channels then would tell the rest of the run the device is free
        while a job of ours is still driving it — and the next dispatch would land on top of it,
        drawing a `busy` the executor reports as a FALSE invariant violation (design
        2026-07-14 §3.2). Keeping the slots is the truthful model: they ARE busy."""
        for channel in channels:
            occupant = self._slots.get((device, channel))
            if isinstance(occupant, _Hold) and occupant.block_id == block_id:
                self._slots[(device, channel)] = _Stranded(block_id, job_id)

    def release_stranded(self, device: str, job_id: str) -> None:
        """The stranded job was stopped for real: give its channels back. Keyed by job_id, so
        it can only ever free the slots of the job that was actually cancelled."""
        for key, occupant in list(self._slots.items()):
            if key[0] == device and isinstance(occupant, _Stranded) and occupant.job_id == job_id:
                del self._slots[key]

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

    def open_modes(self, device: str | None = None) -> tuple[OpenMode, ...]:
        """Snapshot of live modes in open order (the finalizer tears down reversed).
        With `device`, only the modes open on that device — what a device-wide command
        (a `stop`) would silently kill (design 2026-07-14 §3.3)."""
        if device is None:
            return tuple(self._modes)
        return tuple(m for m in self._modes if m.device == device)

    def is_busy(self, device: str) -> bool:
        """True if any (device, channel) slot is held — an in-flight command or open mode
        (design 5 §9 idle oracle)."""
        return any(dev == device for dev, _channel in self._slots)

    def busy_devices(self) -> set[str]:
        """Every device with at least one held slot."""
        return {dev for dev, _channel in self._slots}
