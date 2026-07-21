"""The adaptive-bioreactor grand-tour example, executed against a simulated culture.

Guards examples/adaptive-bioreactor-tour.json against engine drift and proves the whole
schema-3 feature surface runs green at demo speed: three control regimes selected by an enum
operator input, every device verb, both loop variants, all seven group-parameter kinds, unit
casts, mode teardown, retry, per-lane fault isolation, an alarm that raises, and an abort that
aborts. Extends the morbidostat harness (tests/fakelab.py, tests/fakeclock.py) with a
rotate-mode perfusion model.

See docs/superpowers/specs/2026-07-21-adaptive-bioreactor-tour-design.md.
"""

import json
import math
import random
from pathlib import Path
from typing import Any

import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.experiment import ExperimentRun, InMemoryRunLog, RunOptions
from lab_devices.experiment.errors import AbortSignalError
from lab_devices.experiment.expand import expand_dict
from lab_devices.experiment.inputs import InputRequest
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.state import BindingValue
from tests.fakeclock import FakeClock, drive
from tests.fakelab import FakeLab

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
DOC = "adaptive-bioreactor-tour.json"

# Role -> device id, exactly the mapping the preprod test client takes (shared with the
# morbidostat: this example reuses that topology so it runs on the same lab).
MAPPING = {
    "medium_pump": "pump_1", "drug_pump": "pump_2", "waste_pump": "pump_3",
    "medium_valve": "valve_1", "drug_valve": "valve_2", "waste_valve": "valve_3",
    "od_meter_1": "densitometer_1", "od_meter_2": "densitometer_2", "od_meter_3": "densitometer_3",
}
TUBE_OF_METER = {"densitometer_1": 1, "densitometer_2": 2, "densitometer_3": 3}

# Operator-input answers. `regime` is overridden per test; the rest are the run's parameters.
BASE_ANSWERS: dict[str, BindingValue] = {
    "regime": "morbidostat", "target_od": 0.30, "cycles": 20, "warm_start": True,
    "emergency_stop": False, "od_min": 0.03, "od_thr": 0.15, "r_dil": 0.4, "dose_ml": 1.0,
    "drug_stock_x_mic": 10.0,
}

V_ML = 12.0  # culture volume held constant by the waste needle
R0_PER_H = 0.8  # max growth rate, no drug
IC50 = 1.0  # drug units; r(IC50) = r0/2 = r_dil, the morbidostat controller's fixed point
STOCK = 10.0  # Stock A = 10x MIC, in the same units


class Culture:
    """One vial: exponential growth inhibited by drug, diluted on every injection."""

    def __init__(self, od: float) -> None:
        self.od = od
        self.drug = 0.0
        self.t = 0.0  # seconds, on the run clock
        self.injections: list[str] = []

    def grow_to(self, now: float) -> None:
        dt_h = max(0.0, now - self.t) / 3600.0
        self.t = now
        rate = R0_PER_H / (1.0 + self.drug / IC50)
        self.od *= math.exp(rate * dt_h)

    def inject(self, kind: str, volume_ml: float, now: float) -> None:
        self.grow_to(now)
        keep = V_ML / (V_ML + volume_ml)
        self.od *= keep
        self.drug *= keep
        if kind == "drug":
            self.drug += STOCK * volume_ml / (V_ML + volume_ml)
        self.injections.append(kind)


class CultureLab(FakeLab):
    """FakeLab whose densitometers read a live culture and whose pumps perturb it.

    Which tube a pump reaches is decided by its channel's valve position. `medium_pump` in
    `rotate` mode perfuses the tube its valve points at, a small dilution before each read —
    the chemostat regime's continuous-flow model.
    """

    def __init__(self, clock: FakeClock, start_od: dict[int, float]) -> None:
        super().__init__()
        self.clock = clock
        self.cultures = {t: Culture(od) for t, od in start_od.items()}
        self.valve_pos = {"valve_1": 0, "valve_2": 0, "valve_3": 0}
        self.noise = random.Random(20260721)
        self.perfusing: str | None = None  # valve id medium_pump is perfusing through, or None
        for i in (1, 2, 3):
            self.add_device(f"pump_{i}", "pump")
            self.add_device(f"valve_{i}", "valve")
            self.add_device(f"densitometer_{i}", "densitometer")

    def _command(self, device_id: str, env: dict[str, Any]) -> httpx.Response:
        cmd, params = env.get("cmd"), env.get("params") or {}
        now = self.clock.now()
        if cmd in ("set_position", "home") and device_id in self.valve_pos:
            self.valve_pos[device_id] = int(params["position"])
        if cmd == "dispense":
            volume = float(params["volume_ml"])
            if device_id == "pump_1":  # medium, routed by valve_1
                self._inject("medium", "valve_1", volume, now)
            elif device_id == "pump_2":  # drug, routed by valve_2
                self._inject("drug", "valve_2", volume, now)
            # pump_3 (waste) removes culture at the current OD -> concentration unchanged.
        if cmd == "rotate" and device_id == "pump_1":
            self.perfusing = "valve_1"
        if cmd == "stop" and device_id == "pump_1":
            self.perfusing = None
        return super()._command(device_id, env)

    def _inject(self, kind: str, valve: str, volume_ml: float, now: float) -> None:
        tube = self.valve_pos[valve]
        if tube in self.cultures:
            self.cultures[tube].inject(kind, volume_ml, now)

    def _advance(self, job: Any) -> None:
        was_running = job.state == "running"
        super()._advance(job)
        if was_running and job.state == "succeeded" and job.cmd == "measure":
            tube = TUBE_OF_METER[job.device]
            culture = self.cultures[tube]
            if self.perfusing is not None:  # continuous dilution while perfusing
                pt = self.valve_pos[self.perfusing]
                if pt in self.cultures:
                    self.cultures[pt].inject("medium", 0.2, self.clock.now())
            culture.grow_to(self.clock.now())
            reading = culture.od * (1.0 + self.noise.gauss(0.0, 0.01))
            job.result = {"absorbance": round(max(reading, 0.0), 6), "temperature_c": 30.0}


FLAKE = "intensity array: record header/index mismatch (button interference?)"


class FlakyLab(CultureLab):
    """A CultureLab whose densitometers fail the way real ones do.

    `densitometer_1` hiccups on every 7th read attempt — transient, so the next attempt always
    succeeds and `retry` hides it completely. `densitometer_3` is dark for its first 30 attempts
    (a whole growth phase, 10 reads x 3 attempts), so retry cannot save those reads and
    `on_error: continue` must drop them while the sibling lanes read on.
    """

    def __init__(self, clock: FakeClock, start_od: dict[int, float]) -> None:
        super().__init__(clock, start_od)
        self.attempts: dict[str, int] = {}
        self.dropped: list[str] = []
        self._decided: set[str] = set()

    def _faulty(self, device: str, attempt: int) -> bool:
        if device == "densitometer_1":
            return attempt % 7 == 0
        return device == "densitometer_3" and attempt <= 30

    def _advance(self, job: Any) -> None:
        if job.state == "running" and job.cmd == "measure" and job.job_id not in self._decided:
            self._decided.add(job.job_id)
            n = self.attempts[job.device] = self.attempts.get(job.device, 0) + 1
            if self._faulty(job.device, n):
                job.state, job.error = "failed", {"code": "internal_error", "message": FLAKE}
                self.dropped.append(job.device)
                return
        super()._advance(job)


class Answers:
    def __init__(self, overrides: dict[str, BindingValue] | None = None) -> None:
        self.asked: list[str] = []
        self._answers = {**BASE_ANSWERS, **(overrides or {})}

    async def request(self, request: InputRequest) -> BindingValue:
        self.asked.append(request.name)
        return self._answers[request.name]


def _http(lab: CultureLab) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lab.handler), base_url="http://lab:9000"
    )


def load(name: str = DOC) -> Any:
    doc = json.loads((EXAMPLES / name).read_text())
    workflow = expand_dict(json.loads(json.dumps(doc["workflow"])))
    return doc, workflow_from_dict(workflow)


def _walk(blocks: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        out.append(block)
        for key, body in block.items():
            if key in ("label", "gap_after", "start_offset", "retry", "on_error"):
                continue
            for child in ("children", "body", "then", "else"):
                if isinstance(body.get(child), list):
                    out.extend(_walk(body[child]))
    return out


# --------------------------------------------------------------------------- load / shape


def test_example_loads_and_validates() -> None:
    """The document survives engine load + validation (ExperimentRun validates in its ctor)."""
    doc, workflow = load()
    assert doc["doc_version"] == 1
    assert doc["workflow"]["schema_version"] == 3
    assert "roles" not in doc, "roles live inside the workflow"
    assert set(workflow.roles) == set(MAPPING)
    assert workflow.role_type("od_meter_1") == "densitometer"
    assert workflow.role_type("drug_pump") == "pump"

    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.05, 2: 0.05, 3: 0.05})
    ExperimentRun(  # validate() in __init__
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(clock=clock, role_mapping=MAPPING),
    )


def test_example_declares_its_features() -> None:
    """Pin that the grand tour actually contains every feature it claims — coverage as a test.

    The point of this document is breadth, so a future edit that quietly drops the enum branch,
    a param kind, or a device verb must fail here rather than pass unnoticed.
    """
    doc, workflow = load()
    wf = doc["workflow"]

    # one workflow-level retry default, three attempts (pumps opt out per-command, below)
    assert workflow.defaults.retry is not None and workflow.defaults.retry.attempts == 3

    # the service group exercises all seven parameter kinds and both local kinds
    group = wf["groups"]["service"]
    assert group["params"] == [
        {"name": "tube", "kind": "int"},
        {"name": "warn_od", "kind": "number"},
        {"name": "name", "kind": "string"},
        {"name": "is_control", "kind": "bool"},
        {"name": "meter", "kind": "role", "device_type": "densitometer"},
        {"name": "od", "kind": "stream"},
        {"name": "budget", "kind": "binding"},
    ]
    assert group["locals"] == {
        "c": {"kind": "binding", "init": "0"},
        "contaminated": {"kind": "binding", "init": "false"},
        "od_high": {"kind": "binding"},
        "r": {"kind": "binding"},
        "c_series": {"kind": "stream", "units": "x_MIC", "persistence": "disk"},
        "r_series": {"kind": "stream", "units": "per_hour"},
    }

    # the full operator-input palette: enum + float + int + bool
    inputs = {b["operator_input"]["name"]: b["operator_input"] for b in _walk(wf["blocks"])
              if "operator_input" in b}
    assert inputs["regime"]["type"] == "enum"
    assert inputs["regime"]["choices"] == ["turbidostat", "chemostat", "morbidostat"]
    assert inputs["target_od"]["type"] == "float"
    assert inputs["cycles"]["type"] == "int"
    assert inputs["warm_start"]["type"] == "bool"

    # the enum drives string-equality branches (the headline feature)
    branch_ifs = [b["branch"]["if"] for b in _walk(group["body"]) if "branch" in b]
    assert "regime == 'turbidostat'" in branch_ifs
    assert "regime == 'morbidostat'" in branch_ifs

    # unit casts on both recorded derived quantities
    records = [b["record"] for b in _walk(group["body"]) if "record" in b]
    assert {"per_hour", "x_MIC"} <= {r.get("as") for r in records}

    # both loop variants: the paced count loop and a bounded until+check loop
    loops = [b["loop"] for b in _walk(wf["blocks"]) if "loop" in b]
    assert any(loop.get("count") == "cycles" for loop in loops)
    until = [loop for loop in loops if "until" in loop]
    assert len(until) == 1 and until[0]["check"] == "after"

    # every device verb the tour claims to exercise, across top-level and group bodies
    group_blocks = [b for g in wf["groups"].values() for b in _walk(g["body"])]
    all_blocks = _walk(wf["blocks"]) + group_blocks
    verbs = {b["command"]["verb"] for b in all_blocks if "command" in b}
    verbs |= {b["measure"]["verb"] for b in all_blocks if "measure" in b}
    assert {
        "dispense", "rotate", "stop", "set_calibration", "set_position", "home", "configure",
        "measure", "measure_blank", "set_led", "set_thermostat", "set_tube_correction",
        "calibrate_tube",
    } <= verbs

    # no pump command is ever retried: volume_ml is relative, so a retry double-doses
    roles = wf["roles"]
    assert not any(
        "retry" in b for b in all_blocks
        if "command" in b and roles.get(b["command"]["device"], {}).get("type") == "pump"
    )


# --------------------------------------------------------------------------- per-regime run


@pytest.mark.parametrize("regime", ["turbidostat", "chemostat", "morbidostat"])
async def test_regime_runs_green(regime: str, tmp_path: Path) -> None:
    """Each of the three regimes runs to completion with its regime-specific dosing law."""
    _, workflow = load()
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    answers = Answers({"regime": regime})
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(clock=clock, input_provider=answers, output_dir=tmp_path,
                           role_mapping=MAPPING, job_poll_interval=0.05, job_poll_max=0.2),
    )
    report = await drive(clock, run.execute(), max_steps=8_000_000)

    assert report.status == "completed", f"{regime} did not complete"
    assert "regime" in answers.asked and "cycles" in answers.asked
    # tube B's lane reads every cycle with no perfusion noise: exactly 20 x 10
    assert len(report.state.streams["od_2"]) == 20 * 10
    assert len(report.state.streams["od_1"]) >= 20 * 10

    doses1 = lab.cultures[1].injections
    if regime == "morbidostat":
        assert "drug" in doses1, "morbidostat never dosed drug"
    else:
        assert "drug" not in doses1, f"{regime} must never use drug"
    assert lab.cultures[3].injections == [], "the control tube (C) must never be dosed"


# --------------------------------------------------------------------------- hard edges


async def test_retry_and_isolation(tmp_path: Path) -> None:
    """A transient fault is hidden by retry; a persistent one costs only its own samples, and
    its two sibling lanes of the same parallel read right through it (per-device isolation)."""
    _, workflow = load()
    clock = FakeClock()
    lab = FlakyLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"regime": "turbidostat"}),
                           output_dir=tmp_path, role_mapping=MAPPING,
                           job_poll_interval=0.05, job_poll_max=0.2),
    )
    report = await drive(clock, run.execute(), max_steps=8_000_000)

    assert report.status == "completed"
    # retry: the transient fault fired and was invisible — every sample tube 1 owes is present
    assert lab.dropped.count("densitometer_1") > 0, "the transient fault never fired"
    assert len(report.state.streams["od_1"]) == 20 * 10
    # on_error + isolation: tube 3 lost exactly its first growth phase; the neighbours did not
    assert lab.dropped.count("densitometer_3") == 30
    assert len(report.state.streams["od_3"]) == 19 * 10
    assert len(report.state.streams["od_2"]) == 20 * 10
    # a dropped read is loud, not silent
    assert len(report.tolerated_errors) == 10
    assert all(FLAKE in t.error for t in report.tolerated_errors)


async def test_dose_budget_alarm_fires_once(tmp_path: Path) -> None:
    """The cumulative-dose alarm raises exactly once (fire-once latch), driven by an accumulator
    rather than sensor values, so it fires deterministically."""
    _, workflow = load()
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.9, 2: 0.9, 3: 0.9})  # high OD -> dosed early and often
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"regime": "turbidostat"}),
                           output_dir=tmp_path, role_mapping=MAPPING,
                           job_poll_interval=0.05, job_poll_max=0.2, log_sink=InMemoryRunLog()),
    )
    report = await drive(clock, run.execute(), max_steps=8_000_000)

    assert report.status == "completed"
    msgs = [a.message for a in report.alarms]
    assert msgs.count("cumulative dose budget exceeded") == 1, f"alarm fired {msgs.count('cumulative dose budget exceeded')}x, want 1"
    assert "tube A washed out" not in msgs, "the guarded washout alarm must not fire on a healthy run"


async def test_emergency_stop_aborts_and_finalizes(tmp_path: Path) -> None:
    """The operator safety switch: emergency_stop=true fires the whole-run abort at the top of
    the first cycle (status 'aborted'), with the finalizer still sweeping the modes off."""
    _, workflow = load()
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"emergency_stop": True}),
                           output_dir=tmp_path, role_mapping=MAPPING,
                           job_poll_interval=0.05, job_poll_max=0.2, log_sink=InMemoryRunLog()),
    )
    with pytest.raises(AbortSignalError):
        await drive(clock, run.execute(), max_steps=1_000_000)

    report = run.report
    assert report is not None and report.status == "aborted"
    kinds = [e.kind for e in report.log.events]
    assert "abort_raised" in kinds and "finalize_finished" in kinds
    # nothing was serviced: the abort fires before the first cycle's reads
    assert all(len(c.injections) == 0 for c in lab.cultures.values())


async def test_modes_are_opened_and_torn_down(tmp_path: Path) -> None:
    """Every continuous mode — thermostat, LED, and pump rotate — is opened and closed."""
    _, workflow = load()
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"regime": "chemostat"}),
                           output_dir=tmp_path, role_mapping=MAPPING,
                           job_poll_interval=0.05, job_poll_max=0.2),
    )
    await drive(clock, run.execute(), max_steps=8_000_000)

    calls = lab.calls
    assert any(c[1] == "set_thermostat" and c[2].get("enabled") is True for c in calls)
    assert any(c[1] == "set_thermostat" and c[2].get("enabled") is False for c in calls)
    assert any(c[1] == "set_led" and c[2].get("level") == 8 for c in calls)
    assert any(c[1] == "set_led" and c[2].get("level") == 0 for c in calls)
    assert any(c[1] == "rotate" for c in calls)
    assert any(c[1] == "stop" and c[0] == "pump_1" for c in calls)
