"""TeeRunLogSink: seq invariant, replay stream, close semantics. See design §7.3, §7.5."""

import asyncio
from typing import Any

from lab_devices.experiment import RunEvent

from experiment_studio.sinks import TeeRunLogSink


def _event(kind: str, ts: float = 1.0) -> RunEvent:
    return RunEvent(ts, kind, "blocks[0]", {"k": "v"})


def test_emit_appends_event_messages_with_contiguous_seq() -> None:
    tee = TeeRunLogSink()
    assert tee.last_seq == -1
    tee.emit(_event("run_started"))
    tee.append_status("running")
    tee.emit(_event("block_started", 2.0))
    assert [m["seq"] for m in tee.messages] == [0, 1, 2]
    assert tee.messages[0] == {
        "type": "event",
        "seq": 0,
        "timestamp": 1.0,
        "kind": "run_started",
        "block_id": "blocks[0]",
        "source_path": None,
        "data": {"k": "v"},
    }
    assert tee.messages[1] == {"type": "status", "seq": 1, "status": "running"}
    assert tee.last_seq == 2


def test_events_strips_envelope_and_skips_status() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    tee.append_status("running")
    tee.emit(_event("run_finished", 3.0))
    events = tee.events()
    assert [e["kind"] for e in events] == ["run_started", "run_finished"]
    assert all("seq" not in e and "type" not in e for e in events)


async def _collect(tee: TeeRunLogSink, since: int) -> list[dict[str, Any]]:
    return [message async for message in tee.stream(since)]


async def test_stream_replays_then_follows_live_until_close() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    tee.emit(_event("block_started"))
    task = asyncio.create_task(_collect(tee, since=0))
    await asyncio.sleep(0)  # let the consumer drain the replay and park
    tee.emit(_event("block_finished"))
    tee.append_status("completed")
    tee.close()
    messages = await asyncio.wait_for(task, 5)
    assert [m["seq"] for m in messages] == [1, 2, 3]
    assert messages[-1] == {"type": "status", "seq": 3, "status": "completed"}


async def test_stream_since_beyond_end_waits_for_new_messages() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    task = asyncio.create_task(_collect(tee, since=0))
    await asyncio.sleep(0)
    tee.close()
    assert await asyncio.wait_for(task, 5) == []


async def test_two_consumers_both_receive_everything() -> None:
    tee = TeeRunLogSink()
    a = asyncio.create_task(_collect(tee, since=-1))
    b = asyncio.create_task(_collect(tee, since=-1))
    await asyncio.sleep(0)
    tee.emit(_event("run_started"))
    await asyncio.sleep(0)
    tee.emit(_event("run_finished"))
    tee.close()
    got_a = await asyncio.wait_for(a, 5)
    got_b = await asyncio.wait_for(b, 5)
    assert [m["seq"] for m in got_a] == [0, 1]
    assert got_a == got_b


async def test_stream_on_closed_tee_returns_buffer_then_ends() -> None:
    tee = TeeRunLogSink()
    tee.emit(_event("run_started"))
    tee.append_status("completed")
    tee.close()
    messages = await asyncio.wait_for(_collect(tee, since=-1), 5)
    assert [m["seq"] for m in messages] == [0, 1]
