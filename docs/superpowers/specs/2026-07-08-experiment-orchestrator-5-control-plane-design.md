# Experiment Orchestrator — Increment 5: Control Plane + Disk Persistence Design

- **Date:** 2026-07-08
- **Status:** Approved for planning
- **Parent spec:** `2026-07-07-experiment-orchestrator-design.md` (as amended) — this doc
  elaborates §3.2 (control-plane tiers), §14 (pause/resume + control plane), and §15.1
  (persistence config) into a concrete runtime design. Where the parent spec speaks, it
  wins; this doc adds increment-level decisions the parent leaves open.
- **Prior increment:** `2026-07-08-experiment-orchestrator-4-executor-design.md` (D1–D8).
  This increment **replaces D4** (which rejected disk persistence) with real sinks, and
  settles the Increment-5 carry-forward tickets that increment recorded.
- **Depends on:** Increments 1–4 (`lab_devices.experiment` foundation, expressions,
  validator, async executor), all merged to main (suite: 483 passed).

## 1. Scope

Close out v1 with the operator-facing tier around a run and durable records of what a run
measured and did:

- **Disk persistence sinks** (jsonl + csv) for **both** measurement streams and the run
  log, honoring the workflow persistence config (default + per-stream override). Removes
  the D4 rejection; `in_memory` stays the default.
- **Introspection tier** (read-only, always safe): `list_devices`, `agent_info`, device
  `status`/`ping` — usable while a run executes, respecting per-device wire locks.
- **Recovery tier** (mutating, guarded): `rediscover`, guarded `disconnect` — legal only
  when the target device is idle; refuses otherwise. None of these are blocks (the
  block/control-plane split is load-bearing, parent §2).
- Settle the Increment-4 carry-forward tickets (§8).

Out of scope (parent §16, v2): parametrized/macro groups, closed-loop recovery
(auto-resume after a device drop), a YAML/DSL authoring surface. Also deferred (§8):
resource caps (nesting depth / group-DAG expansion) and the device-id shape check.

## 2. Settled decisions

User-settled at brainstorm (2026-07-08):

| # | Decision | Choice |
|---|---|---|
| I1 | Sink write model | **Buffered synchronous writer.** `RunLogSink.emit()` (and the new stream sink) stay **sync** — an async `emit` would break the settled sync `pause()`/`resume()`/`abort()`, add suspension points to the finalizer's never-skip path, open ordering seams in the run log, and still not deliver non-blocking disk I/O. Disk sinks `write()` synchronously into a buffered file object (userspace buffer / page cache, no fsync). |
| I2 | Durability / flush cadence | **Two-tier data model** + **periodic time-based flush.** In-memory (`RunState` + `InMemoryRunLog`) is authoritative and current with zero lag; on-disk is a lagging mirror whose staleness is bounded by a clock-driven flush task (`flush_interval`, default 30 s ≪ the couple-minutes tolerance), plus a **guaranteed final flush + close at finalize**. No fsync (power-loss durability is a v1 non-goal); process-crash loss window ≤ `flush_interval`, accepted. |
| I3 | Sink construction & file location | **`ExperimentRun` builds sinks from `workflow.persistence`** (default + per-stream override) under a caller-supplied `RunOptions.output_dir`, fixed predictable filenames, **refuse-to-clobber**. An explicitly injected `log_sink` still overrides (back-compat). Keeps the declarative persistence model (§15.1) as the primary path. |
| I4 | Control-plane API shape | **Separate `Console` object** wrapping the `LabClient` + an optional live run. Introspection works with or without a run; recovery consults the live run's occupancy for the idle-guard and routes device wire calls through the run's per-device lock. Lifecycle (pause/resume/abort) stays on `ExperimentRun`. |
| I5 | Recovery on a busy device | **Refuse when busy.** Introspection is always safe; `rediscover`/`disconnect` require the target device idle (occupancy oracle) and raise `DeviceBusyError` otherwise. No auto-finalize from inside a query — the operator uses `run.abort()` explicitly. ("Force finalize affected work" from parent §3.2 maps to the operator's explicit whole-run abort, since per-device partial finalize does not exist in v1.) |
| I6 | Abort vs external cancellation in the report | **Distinguish.** Operator abort → `status="aborted"` + `RunAbortedError` (unchanged); external cancellation → new `status="cancelled"` + re-raised `CancelledError`. On-disk reports/logs then faithfully record which happened. Small amendment to the parent §11 / 4-exec §11 outcome matrix. |
| I7 | Plan decomposition | **Two plans, one branch, one PR:** 5a persistence, then 5b control plane (5b stacks on 5a). Mirrors the proven 4a/4b rhythm; carry-forward tickets sort by plane. |

Engine-level decisions settled in this doc (marked **[settled]** where defined): the
`StreamSink` protocol and the sync buffered-write discipline (§4); sink resolution rules
and the `output_dir`/`flush_interval` options (§5); file layout, name sanitization and
clobber policy (§6); jsonl/csv schemas (§7); the measure-hook single-timestamp change
(§4.3); sink-open-before-dispatch and the guarded `run_started` emit (§8); sink write
errors remembered and surfaced on the report (§8); the `Console` API and the occupancy
idle oracle (§9); `DeviceBusyError` and `PersistenceError` taxonomy (§10).

## 3. Two-tier data model (the spine)

Every value a run produces lives in two places with different guarantees:

- **In-memory — authoritative, synchronous, zero lag.** `RunState.streams` receive each
  `Sample` at the instant of measurement (execute.py `_run_measure`); `InMemoryRunLog`
  appends each `RunEvent` synchronously via `ctx.emit`. This is what the run's own logic,
  the evaluator, and `RunReport.state`/`RunReport.log` read. Unchanged from Increment 4.
- **On-disk — a lagging durability mirror.** jsonl/csv files that trail the in-memory copy
  by at most `flush_interval`. Their purpose is surviving a process crash and being the
  shareable artifact of the run — not being read back by the running experiment.

This split is what lets writes stay synchronous and cheap (no event-loop stall, I1) while
still bounding on-disk staleness (I2). It also means correctness of the run never depends
on disk: a sink failure degrades durability, never the experiment (§8).

## 4. Persistence sinks (5a)

New module `persist.py` (`from __future__` + one-line docstring citing this section).

### 4.1 Protocols and implementations

```python
class RunLogSink(Protocol):                 # existing (runlog.py), sync — unchanged
    def emit(self, event: RunEvent) -> None: ...

class StreamSink(Protocol):                 # new
    def write(self, sample: Sample) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

Both sink protocols gain `flush()`/`close()` for the durability lifecycle (the run-log
protocol keeps `emit`; `flush`/`close` are added on the disk implementations and made
optional on the protocol via a runtime-checkable shim so `InMemoryRunLog` — which needs
neither — still conforms). Disk implementations:

- `JsonlRunLogSink`, `CsvRunLogSink` — write `RunEvent`s.
- `JsonlStreamSink`, `CsvStreamSink` — write `Sample`s.

In-memory remains the default: the in-memory run log is `InMemoryRunLog`; in-memory
streams have **no** stream sink (samples already live in `RunState`) — a `None` entry, so
`_run_measure` writes to disk only when a sink exists.

Each disk sink owns one open text-mode file object opened with buffering, holds the header
state (csv), and implements `write`/`flush`/`close`. Writes are synchronous and in-order
(no queue), so the file's byte order matches dispatch order and the in-memory copy exactly.

### 4.2 SinkSet

`SinkSet` bundles the resolved log sink + the per-stream sinks + the output directory, and
exposes `flush_all()` / `close_all()`. `ExperimentRun` builds it during `execute()` prep
(§8) and owns its lifecycle. `flush_all()` is what the periodic flush task and the final
finalize-flush call.

### 4.3 Measure hook — single timestamp

Today `_run_measure` reads the clock twice (once for `state.record`, once for the
`measure_recorded` emit). To make the persisted sample timestamp exactly equal the
in-memory one, capture `ts = ctx.clock.now()` **once**, then: `ctx.state.record(into, ts,
value)`; if `ctx.stream_sinks.get(into)` is not `None`, `sink.write(Sample(ts, value))`;
`ctx.emit("measure_recorded", ..., value=value)`. One clock read, one timestamp, three
consumers. `Stream.append`'s non-decreasing invariant is preserved (same clock).

The run log is persisted by making the effective log sink *be* a disk sink (§5) — no
separate hook; every existing `ctx.emit` call already flows through it.

## 5. Sink construction, resolution, and options

`RunOptions` gains (both optional, back-compat):

- `output_dir: Path | str | None = None` — the run's output directory. Required when any
  disk persistence is requested; a `disk` config with no `output_dir` → `PersistenceError`
  at run start (before hardware, like the old D4 check).
- `flush_interval: float = 30.0` — seconds between periodic flushes (I2).

`log_sink` changes from a defaulted `InMemoryRunLog()` to `log_sink: RunLogSink | None =
None` so "explicitly injected" is distinguishable from "use the default." **Resolution**
(at `execute()` prep):

1. If `options.log_sink is not None` → use it verbatim (injection overrides config).
2. Else if the run-log's effective persistence is `disk` → build the disk log sink of the
   configured `format`.
3. Else → `InMemoryRunLog()`.

Per-stream sink resolution, for each declared stream: effective persistence = the stream's
`persistence` override if set, else `workflow.persistence.default`; format =
`workflow.persistence.format` (single workflow-level format, per §15.1). `disk` → build
the stream sink; `in_memory` → `None`.

The resolved log sink is stored on the run and threaded as the sink `ctx.emit` uses;
`RunReport.log` is the resolved sink (not `options.log_sink`, which may be `None`).

## 6. File layout, naming, clobber policy

Under `output_dir`:

- Run log: `run_log.jsonl` or `run_log.csv` (by format).
- Each disk stream: `<safe-name>.jsonl` / `<safe-name>.csv`.

**Name sanitization [settled]:** stream names are arbitrary workflow keys. Derive a
filesystem-safe base name (allow `[A-Za-z0-9._-]`, replace the rest); reject empty or
traversal-y results; if two distinct stream names collide after sanitization →
`PersistenceError` (no silent merge). This is scoped to persistence — it is *not* the
deferred general device-id shape check.

**Directory & clobber [settled]:** create `output_dir` if absent. **Refuse to clobber:**
if any target file already exists, raise `PersistenceError` before opening anything — no
silent overwrite of a prior run's data. Uniqueness across runs is the caller's job (e.g. a
timestamped `output_dir` at the app layer); the engine does not invent run-ids.

## 7. On-disk schemas

**jsonl run log** — one `RunEvent` per line, direct serialization:
```json
{"timestamp": 12.5, "kind": "measure_recorded", "block_id": "blocks[0]...", "data": {"stream": "OD", "value": 0.52}}
```

**jsonl stream** — one `Sample` per line:
```json
{"timestamp": 12.5, "value": 0.523}
```

**csv run log** — fixed header `timestamp,kind,block_id,data`; `data` is the event's
`data` dict JSON-encoded into one column (keeps a fixed schema across heterogeneous event
kinds); `block_id` empty when `None`.

**csv stream** — fixed header `timestamp,value`; one row per sample.

Units (per-stream, constant) live in the workflow document, not repeated per row. jsonl is
the lossless/rich format; csv is the load-into-a-spreadsheet format, so the JSON `data`
column is an accepted trade. Both formats are append-only and complete/parseable after any
flush (§3).

## 8. Carry-forward tickets settled here

**Sink-open before dispatch + guarded `run_started` (disk makes this real).** Today
`execute()` emits `run_started` *outside* the finalize `try` (run.py:117); a disk sink
that fails to open on the first event would escape `execute()` with no finalize and no
report. Fix: build/open the `SinkSet` during `execute()` prep, **before** `run_started` —
open/clobber/config failures become a clean pre-dispatch `PersistenceError` with
`report` set (`status="failed"`) and no hardware touched. Then wrap the `run_started` emit
best-effort so a sink that raises on the first *event* still reaches the normal
finalize-and-report path (mirrors the finalizer's `_emit`).

**`_emit` silent-swallow → remembered errors.** The finalizer's `_emit` (and the
best-effort `run_started`) swallow sink exceptions so a raising sink can't skip the sweep.
That silence is fine for `InMemoryRunLog` but loses signal for disk. Fix: disk sinks catch
their own write/flush errors internally, keep a first-error + count, and expose them; the
run surfaces them on the report (a `persistence_errors` field / annotation) so a failed
log or stream sink is never invisible. The executor's swallow-on-emit stays (it must), but
the signal is preserved by the sink itself.

**Abort vs external cancellation (I6).** Add `status="cancelled"`. In `execute()`'s
cancelled branch: `abort_requested` → `uncancel()` + `RunAbortedError` (`status="aborted"`,
unchanged); otherwise `status="cancelled"` and re-raise `CancelledError`. `RunReport`
docstring and the run-log `run_finished` `status` carry the new value. Amend parent §11 and
4-exec §11/§15 outcome matrices to `completed | failed | aborted | cancelled`.

**Double-abort `cancelling()==1` residue.** `abort()` may call `self._task.cancel()` twice
on repeated aborts, leaving `task.cancelling() == 1` after the single `uncancel()` — latent
if `execute()` runs nested under a `TaskGroup`, which the `Console` makes likely (an
operator runs the experiment as a background task). Fix: `abort()` cancels the root task
**at most once** (guard on a `_abort_cancelled` flag), so `cancelling()` balances against
the lone `uncancel()`.

**Frozen `RunEvent` unhashable.** `RunEvent` is `frozen=True` but carries a `dict` `data`
field → unhashable. Our sinks append and never hash events. **Close as a documented
constraint** on `RunLogSink` (sinks must not hash/dedupe `RunEvent`s); no code change.

**D4 removal.** Delete `_reject_unsupported_persistence`; `UnsupportedPersistenceError` is
replaced by `PersistenceError` (§10) covering bad config, missing `output_dir`, clobber,
name collision, and I/O.

**Deferred (re-noted in ledger):** resource caps (nesting depth / group-DAG expansion —
runtime recursion mirrors AST depth, same ticket as the validator's) and the general
device-id shape check. Both orthogonal to this increment's two planes.

## 9. Control plane (5b)

New module `control.py` — `Console`, the operator's out-of-band surface (parent §3.2,
§14). Never a block.

```python
console = Console(client, run=None)   # run: the live ExperimentRun, if any
```

### 9.1 Introspection tier (always safe, read-only)

- `list_devices() -> list[DeviceInfo]` — `client.list_devices()`.
- `agent_info() -> AgentInfo` — `client.agent_info()`.
- `device_status(device_id) -> Any` — `device.status()`.
- `device_ping(device_id) -> PingResult` — `device.ping()`.

**Wire-lock coexistence [settled]:** device wire calls (`status`/`ping`) target a device
the live run may be polling/dispatching. When `run is not None` and the device is in the
run, route the call through the run's per-device lock (`run._ctx.lock(device_id)`), so an
introspection read serializes on the wire with executor traffic (D2). With no live run (or
a device the run never touched), call directly. `list_devices`/`agent_info` are
agent-level (no per-device lock).

### 9.2 Recovery tier (mutating, guarded)

- `rediscover() -> list[DeviceInfo]` — re-scan the bus. Allowed only when **no** device the
  live run is using is busy; else `DeviceBusyError`. With no live run, always allowed.
- `disconnect(device_id=None) -> int` — guarded release. Allowed only when the target
  device (or, for a whole-agent disconnect, every run-used device) is **idle**; else
  `DeviceBusyError`.

**Idle oracle [settled]:** occupancy is the complete, non-blocking oracle. Add
`Occupancy.is_busy(device_id) -> bool` = "any `(device_id, channel)` slot is held" (a
`_Hold` from an in-flight command *or* an `OpenMode`). In-flight jobs hold their slots
across the whole job wait (execute.py frees them only in `finally`), and open modes are
mode-held, so a single slot check covers commands, jobs, and modes. `touched` (ever-used)
is *not* the oracle — a device that finished all its work is idle. With no live run, the
occupancy is empty → everything idle.

No auto-finalize (I5): a busy device raises; the operator explicitly `run.abort()`s (whole-
run finalize) and retries. Closed-loop "finalize just this device then resume" is v2.

## 10. Error taxonomy additions

```
ExperimentError
└── ExperimentRunError
    ├── ... (Increment 4)
    ├── PersistenceError      # replaces UnsupportedPersistenceError: bad/missing config,
    │                         # missing output_dir, clobber, name collision, sink I/O
    └── DeviceBusyError       # recovery-tier guard: target device not idle
```

`PersistenceError` is raised at run start (pre-dispatch, like the old D4 gate) for
config/layout problems; per-sink runtime I/O errors are remembered on the sink and
surfaced on the report rather than raised into dispatch (§8). `DeviceBusyError` is raised
synchronously by the recovery methods.

## 11. Public surface

`__init__` re-exports: `StreamSink`, the disk sink classes (`JsonlRunLogSink`,
`CsvRunLogSink`, `JsonlStreamSink`, `CsvStreamSink`), `SinkSet`, `Console`,
`PersistenceError`, `DeviceBusyError`, and drops `UnsupportedPersistenceError`. `RunOptions`
gains `output_dir`, `flush_interval`, and the `log_sink: … | None` change. `RunReport`
gains the persistence-error surface and the `"cancelled"` status.

## 12. Test infrastructure & verification

Hermetic, `tmp_path`-based; disk tests stay zero-wall-clock via `FakeClock`.

- **End-to-end content assertions.** Run the §15.2-shaped workflow with `disk`
  persistence into `tmp_path`; assert **file contents** — every jsonl line / csv row
  matches the in-memory `RunState` samples and the `InMemoryRunLog` events (a mirror
  equality check), including block ids and event `data`.
- **Completeness after abort.** Abort mid-run; assert the final flush left every file
  complete and parseable (no torn last line), and the on-disk tail matches in-memory up to
  the abort.
- **Bounded staleness.** With a disk run mid-flight, advance the `FakeClock` past
  `flush_interval` and assert the file caught up; assert the flush task is cancelled at
  finalize and `drive()` keys off the run task (no perpetual-sleeper deadlock).
- **Sink failure isolation.** Inject disk failures via real filesystem conditions
  (unwritable dir; a path pre-created as a directory to force an open error) and a small
  injectable failing sink; assert the run still finalizes, the report surfaces the
  persistence error, and hardware still reaches safe state.
- **Clobber / config guards.** Missing `output_dir` with a `disk` config, a pre-existing
  target file, and a post-sanitization name collision each → `PersistenceError` before any
  hardware.
- **Control plane.** Introspection during a **live paused** run returns device
  status/ping (routed through the wire lock); a busy device refuses `disconnect`
  (`DeviceBusyError`) and succeeds after finalize; `rediscover` respects the busy guard.
  FakeLab reuses its existing discovery / `unreachable` surface — no disk support added to
  FakeLab.
- **Ticket regressions.** `"cancelled"` vs `"aborted"` status on external-cancel vs
  operator-abort; double-abort leaves `cancelling() == 0`; a raising log sink on the first
  event still finalizes and reports.

## 13. Plan decomposition (I7)

Branch `feat/experiment-orchestrator-5-control-plane` off main; single PR.

- **5a — disk persistence end-to-end:** `PersistenceError`; `StreamSink` + disk sink
  classes + `SinkSet` (`persist.py`); `RunOptions` `output_dir`/`flush_interval`/`log_sink`
  change; sink resolution + build-before-dispatch; the measure single-timestamp hook;
  periodic flush task + finalize flush/close; file layout / naming / clobber; jsonl+csv
  schemas; the run_started-guard and sink-error-surface tickets; D4 removal; disk E2E +
  content/abort/staleness/failure/clobber tests.
- **5b — control plane + lifecycle tickets:** `Console` (`control.py`) introspection +
  recovery tiers; `Occupancy.is_busy` idle oracle; wire-lock coexistence; `DeviceBusyError`;
  the abort-vs-cancel `"cancelled"` status and the double-abort fix; control-plane E2E
  against FakeLab. 5b stacks on 5a.

Spec amendments this increment lands: parent §11 and 4-exec §11/§15 outcome matrices gain
`cancelled`; parent §15.1 / §3.2 realized (persistence sinks; introspection + recovery
tiers); 4-exec D4 superseded.

## 14. Deferred

- v2 (parent §16): parametrized/macro groups; closed-loop recovery (device-drop →
  finalize → `rediscover` → resume); YAML/DSL authoring surface; pre-test cold-start
  validator warnings.
- Existing tickets: resource caps (nesting depth / group-DAG expansion); general device-id
  shape check. Both re-noted in the ledger.
- `fsync`/power-loss durability (I2 non-goal); a network/streaming sink (would use a
  background-writer sink that keeps `emit()` sync — enqueue sync, drain async — never an
  async `emit` protocol change, per I1).
