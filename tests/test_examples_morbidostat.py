"""The shipped morbidostat examples, executed against a simulated culture.

Guards the examples in `examples/` against engine drift and — more importantly — proves the
control loop actually closes: a FakeLab whose densitometers model exponential growth, dilution
on injection, and drug inhibition is driven through the real workflow, and the controller must
pin each culture at its own IC50 instead of letting it run away.

See docs/superpowers/specs/2026-07-13-morbidostat-example-design.md.
"""

import json
import math
import random
from pathlib import Path
from typing import Any

import httpx
import pytest

from lab_devices.client import LabClient
from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.inputs import InputRequest
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.state import BindingValue
from tests.fakeclock import FakeClock, drive
from tests.fakelab import FakeLab

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

# Role -> device id, exactly the mapping the preprod test client takes.
MAPPING = {
    "medium_pump": "pump_1",
    "drug_pump": "pump_2",
    "waste_pump": "pump_3",
    "medium_valve": "valve_1",
    "drug_valve": "valve_2",
    "waste_valve": "valve_3",
    "od_meter_1": "densitometer_1",
    "od_meter_2": "densitometer_2",
    "od_meter_3": "densitometer_3",
}
TUBE_OF_METER = {"densitometer_1": 1, "densitometer_2": 2, "densitometer_3": 3}

# Operator-input answers = the algorithm's published parameters.
ANSWERS: dict[str, BindingValue] = {
    "od_min": 0.03,
    "od_thr": 0.15,
    "r_dil": 0.4,
    "dose_ml": 1.0,
    "drug_stock_x_mic": 10.0,
    "blanks_ready": True,
    "cultures_ready": True,
}

V_ML = 12.0  # culture volume held constant by the waste needle
R0_PER_H = 0.8  # max growth rate, no drug
IC50 = 1.0  # drug units; r(IC50) = r0/2 = r_dil, the controller's fixed point
STOCK = 10.0  # Stock A = 10x MIC, in the same units

# The freshness window each doc guards its service branches with: strictly between the growth
# phase (10 samples x the inner pace) and the cycle pace, so a sample from the previous cycle
# can never satisfy it. Pace-coupled by construction — see each doc's own prose.
FRESHNESS = {"morbidostat.json": "11min", "morbidostat-demo-speed.json": "45s"}


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
        rate = R0_PER_H / (1.0 + self.drug / IC50)  # r -> r_dil as drug -> IC50
        self.od *= math.exp(rate * dt_h)

    def inject(self, kind: str, volume_ml: float, now: float) -> None:
        """Algorithm §1 concentration recursion; OD dilutes identically either way."""
        self.grow_to(now)
        keep = V_ML / (V_ML + volume_ml)
        self.od *= keep
        self.drug *= keep
        if kind == "drug":
            self.drug += STOCK * volume_ml / (V_ML + volume_ml)
        self.injections.append(kind)


class CultureLab(FakeLab):
    """FakeLab whose densitometers read a live culture and whose pumps perturb it.

    Which tube a pump reaches is decided by its channel's valve position — exactly the
    physical coupling the workflow relies on.
    """

    def __init__(self, clock: FakeClock, start_od: dict[int, float]) -> None:
        super().__init__()
        self.clock = clock
        self.cultures = {t: Culture(od) for t, od in start_od.items()}
        self.valve_pos = {"valve_1": 0, "valve_2": 0, "valve_3": 0}
        self.noise = random.Random(20260713)
        for i in (1, 2, 3):
            self.add_device(f"pump_{i}", "pump")
            self.add_device(f"valve_{i}", "valve")
            self.add_device(f"densitometer_{i}", "densitometer")

    def _command(self, device_id: str, env: dict[str, Any]) -> httpx.Response:
        cmd, params = env.get("cmd"), env.get("params") or {}
        now = self.clock.now()
        if cmd == "set_position" and device_id in self.valve_pos:
            self.valve_pos[device_id] = int(params["position"])
        if cmd == "home" and device_id in self.valve_pos:
            self.valve_pos[device_id] = int(params["position"])
        if cmd == "dispense":
            volume = float(params["volume_ml"])
            if device_id == "pump_1":  # medium, routed by valve_1
                self._inject("medium", "valve_1", volume, now)
            elif device_id == "pump_2":  # drug, routed by valve_2
                self._inject("drug", "valve_2", volume, now)
            # pump_3 (waste) removes culture at the current OD -> concentration unchanged.
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
            culture.grow_to(self.clock.now())
            # 1% relative read noise: the slope estimator must survive a noisy trace.
            reading = culture.od * (1.0 + self.noise.gauss(0.0, 0.01))
            job.result = {"absorbance": round(max(reading, 0.0), 6), "temperature_c": 30.0}


FLAKE = "intensity array: record header/index mismatch (button interference?)"


class FlakyLab(CultureLab):
    """A CultureLab whose densitometers fail the way real ones do.

    `densitometer_1` hiccups on every 7th read attempt — transient, so the next attempt
    always succeeds and `retry` hides it completely. This is the fault that killed the live
    run at cycle 17 of 25, verbatim. `densitometer_3` is dark for its first 30 attempts —
    the whole first growth phase (10 reads x 3 attempts), so retry cannot save those reads
    and `on_error: continue` must drop them instead.
    """

    def __init__(self, clock: FakeClock, start_od: dict[int, float]) -> None:
        super().__init__(clock, start_od)
        self.attempts: dict[str, int] = {}
        self.dropped: list[str] = []
        self._decided: set[str] = set()

    def _faulty(self, device: str, attempt: int) -> bool:
        if device == "densitometer_1":
            return attempt % 7 == 0  # never twice running: attempt n+1 always succeeds
        return device == "densitometer_3" and attempt <= 30

    def _advance(self, job: Any) -> None:
        if job.state == "running" and job.cmd == "measure" and job.job_id not in self._decided:
            self._decided.add(job.job_id)  # one verdict per dispatch; a retry is a fresh job
            n = self.attempts[job.device] = self.attempts.get(job.device, 0) + 1
            if self._faulty(job.device, n):
                job.state, job.error = "failed", {"code": "internal_error", "message": FLAKE}
                self.dropped.append(job.device)
                return
        super()._advance(job)


class DeadSensorLab(FlakyLab):
    """A CultureLab whose `densitometer_3` reads for one growth phase and then dies forever.

    The fault every retry is powerless against, and the one the whole-stream guard cannot
    see: the tube HAS read, so `count(od_3) > 0` is true for the rest of the run.
    """

    def _faulty(self, device: str, attempt: int) -> bool:
        return device == "densitometer_3" and attempt > 10  # 10 reads = cycle 1, then dark


class Answers:
    def __init__(self) -> None:
        self.asked: list[str] = []

    async def request(self, request: InputRequest) -> BindingValue:
        self.asked.append(request.name)
        return ANSWERS[request.name]


def load(name: str) -> Any:
    doc = json.loads((EXAMPLES / name).read_text())
    workflow = json.loads(json.dumps(doc["workflow"]))
    _substitute(workflow["blocks"])
    return doc, workflow_from_dict(workflow)


def _substitute(blocks: list[Any]) -> None:
    """Role name -> device id, mirroring experiment_studio.roles.substitute."""
    for block in blocks:
        for key, body in block.items():
            if key in ("label", "gap_after", "start_offset", "retry", "on_error"):
                continue
            if key in ("command", "measure"):
                body["device"] = MAPPING[body["device"]]
            for child in ("children", "body", "then", "else"):
                if isinstance(body.get(child), list):
                    _substitute(body[child])


@pytest.mark.parametrize("name", ["morbidostat.json", "morbidostat-demo-speed.json"])
def test_example_loads_and_validates(name: str) -> None:
    """Both shipped docs survive engine load + validation (ExperimentRun validates in ctor)."""
    doc, workflow = load(name)
    assert doc["doc_version"] == 1
    assert set(doc["roles"]) == set(MAPPING)
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.05, 2: 0.05, 3: 0.05})
    client = LabClient("lab", 9000, http=_http(lab))
    ExperimentRun(client, workflow, options=RunOptions(clock=clock))  # validate() in __init__


@pytest.mark.parametrize("name", ["morbidostat.json", "morbidostat-demo-speed.json"])
def test_example_declares_its_fault_tolerance(name: str) -> None:
    """The shape of the fault policy is load-bearing, so pin it (design 2026-07-14 §9).

    One `defaults.retry` rather than six copies; the OD reads tolerated and the blanks
    pointedly not; and every tube's decision tree guarded, because a tolerated read only
    *maybe* writes its stream.
    """
    doc, workflow = load(name)
    retry = workflow.defaults.retry
    assert retry is not None and retry.attempts == 3 and not retry.allow_repeat

    setup = doc["workflow"]["blocks"][0]["serial"]["children"]
    blanks = setup[7]["serial"]["children"]
    assert [b["measure"]["verb"] for b in blanks] == ["measure_blank"] * 3
    assert all("on_error" not in b for b in blanks), "a failed blank must stop the run"

    ratchet = setup[14]["loop"]  # after the four compute seeds (V, c_1, c_2, c_3)
    reads = ratchet["body"][0]["loop"]["body"][0]["parallel"]["children"]
    assert [r["on_error"] for r in reads] == ["continue"] * 3
    for i, service in enumerate(ratchet["body"][1:4], start=1):
        # Short-circuit guard: no FRESH reading, no decision — and no empty-window
        # EvaluationError. The window is what makes it a freshness guard: the whole-stream
        # form `count(od_N) > 0` latches true forever over an append-only stream, and a
        # latched guard is an open-loop drug injector (test_a_dead_sensor_does_not_latch).
        window = FRESHNESS[name]
        assert service["branch"]["if"].startswith(f"count(od_{i}, last={window}) > 0 and ")

    # The thermostat setup is parallel again; retry is what makes that safe on a roster whose
    # devices share a serial (docs/experiment-engine-limitations.md, final section). Six
    # attempts, not three: the contending set only thins as each round's winner drops out
    # (3 -> 2 -> 1), and a jitter-free constant back-off does not de-synchronize the herd.
    thermostats = setup[6]["parallel"]["children"]
    assert [t["command"]["verb"] for t in thermostats] == ["set_thermostat"] * 3
    assert all(t["retry"]["attempts"] == 6 for t in thermostats)
    assert all("on_error" not in t for t in thermostats), "an unset thermostat must stop the run"

    # No pump may ever be retried: volume_ml is relative, so a retried dispense double-doses.
    assert not any(
        "retry" in b for b in _walk(doc["workflow"]["blocks"]) if "command" in b
        and doc["roles"].get(b["command"]["device"], {}).get("type") == "pump"
    )


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


def _http(lab: CultureLab) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(lab.handler), base_url="http://lab:9000"
    )


async def test_morbidostat_closes_the_loop(tmp_path: Path) -> None:
    """The flagship: 120 real cycles against simulated cultures.

    Tube 2 starts below OD_MIN (unreadable -> no action at all), tubes 1 and 3 start in the
    band. The controller must exercise all three arms of the decision table and pin the
    cultures at their IC50 rather than letting them grow away.
    """
    _, workflow = load("morbidostat.json")
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.05, 2: 0.01, 3: 0.05})
    answers = Answers()
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(
            clock=clock,
            input_provider=answers,
            output_dir=tmp_path,  # the docs declare disk persistence (Studio forces it per-run)
            job_poll_interval=0.05,
            job_poll_max=0.2,
        ),
    )
    report = await drive(clock, run.execute(), max_steps=1_000_000)

    assert report.status == "completed"
    assert answers.asked == [
        "od_min", "od_thr", "r_dil", "dose_ml", "drug_stock_x_mic",
        "blanks_ready", "cultures_ready",
    ]

    # Every tube was read on every cycle: 120 cycles x 10 samples.
    for t in (1, 2, 3):
        assert len(report.state.streams[f"od_{t}"]) == 120 * 10
        assert len(report.state.streams[f"blank_{t}"]) == 1

    t1, t2, t3 = (lab.cultures[t] for t in (1, 2, 3))

    # --- NOTHING arm: tube 2 started at 0.01, below OD_MIN, so its first cycles are silent.
    # It grows undiluted until it crosses OD_MIN and joins in — the recovery the decision
    # table promises. Tubes 1 and 3 started in the band and are serviced on every cycle.
    assert len(t1.injections) == 120 and len(t3.injections) == 120
    assert len(t2.injections) < 120, "NOTHING arm never fired: tube 2 acted on every cycle"
    assert t2.injections[0] == "medium", "a tube climbing out of OD_MIN must get medium first"

    # --- DRUG and MEDIUM arms both fired on the tubes that started in the band ---
    for culture in (t1, t3):
        assert "drug" in culture.injections, "drug arm never fired"
        assert "medium" in culture.injections, "medium arm never fired"
        # Bang-bang, not latched: drug is the minority action that holds c at IC50.
        drug_fraction = culture.injections.count("drug") / len(culture.injections)
        assert 0.02 < drug_fraction < 0.40, f"drug fraction {drug_fraction:.2f} is not bang-bang"

    # --- the loop actually closed: drug drove growth down to the dilution rate ---
    for t, culture in ((1, t1), (2, t2), (3, t3)):
        rate = R0_PER_H / (1.0 + culture.drug / IC50)
        assert 0.2 <= rate <= 0.6, f"tube {t}: growth rate {rate:.3f} not pinned near r_dil=0.4"
        # A runaway culture would be orders of magnitude up; a killed one would wash out.
        assert 0.03 < culture.od < 1.0, f"tube {t}: OD {culture.od:.3f} left the band"

    # Steady-state drug concentration is the IC50 the controller is defined to find.
    for t, culture in ((1, t1), (3, t3)):
        assert 0.5 * IC50 < culture.drug < 2.0 * IC50, f"tube {t}: drug {culture.drug:.3f}"

    # --- the controller now KNOWS its own drug concentration (limitations #1) and RECORDS it
    # (limitations #3). The workflow's `compute c_t` walks the §1 recursion on the same V, dV,
    # and stock the simulator does, so the recorded c_series must track the simulated drug to
    # floating-point — the sawtooth is no longer reconstructed offline, it is a first-class
    # stream. r_series carries the named growth rate the decision now reads. ---
    for t, culture in ((1, t1), (3, t3)):
        c_series = report.state.streams[f"c_series_{t}"].samples
        r_series = report.state.streams[f"r_series_{t}"].samples
        assert len(c_series) == 120 and len(r_series) == 120, f"tube {t}: a serviced cycle records"
        assert abs(c_series[-1].value - culture.drug) < 1e-9, (
            f"tube {t}: recorded c {c_series[-1].value:.6f} != simulated drug {culture.drug:.6f}"
        )
    # Tube 2 (NOTHING arm on its early cycles) records only the cycles it was serviced on.
    assert 0 < len(report.state.streams["c_series_2"].samples) < 120
    assert abs(report.state.streams["c_series_2"].samples[-1].value - t2.drug) < 1e-9

    # --- valves were left parked closed at the end of every cycle ---
    assert lab.valve_pos == {"valve_1": 0, "valve_2": 0, "valve_3": 0}

    # --- the finalizer swept the thermostats back off ---
    thermostats = [c[2] for c in lab.calls if c[1] == "set_thermostat"]
    assert {"enabled": True, "target_c": 30.0} in thermostats
    assert {"enabled": False} in thermostats


async def test_morbidostat_survives_a_transient_device_fault(tmp_path: Path) -> None:
    """The proof of the fault-tolerance feature, on the shipped doc.

    A live run of this doc died at cycle 17 of 25, 23 minutes in, on ONE flaky densitometer
    read (docs/experiment-engine-limitations.md §0). Here that same fault recurs every 7th
    read on tube 1, and tube 3's sensor is dark for a whole growth phase on top of it. The
    run must now finish: retry hides the transient fault entirely, and the persistent one
    costs tube 3 the samples it could not take and its neighbours nothing.
    """
    _, workflow = load("morbidostat-demo-speed.json")
    clock = FakeClock()
    lab = FlakyLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})  # high enough to stay readable for 25 cycles
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(
            clock=clock,
            input_provider=Answers(),
            output_dir=tmp_path,
            job_poll_interval=0.05,
            job_poll_max=0.2,
        ),
    )
    report = await drive(clock, run.execute(), max_steps=1_000_000)

    assert report.status == "completed", "the fault that killed the live run still kills it"

    # --- retry: the transient fault is invisible. Every sample tube 1 owes is present. ---
    assert lab.dropped.count("densitometer_1") > 0, "the transient fault never fired"
    assert len(report.state.streams["od_1"]) == 25 * 10

    # --- on_error: a fault retry cannot cure costs its own samples, and nothing else. The
    # two sibling lanes of the same `parallel` read right through it (per-lane isolation). ---
    assert lab.dropped.count("densitometer_3") == 30  # a whole growth phase: 10 reads x 3
    assert len(report.state.streams["od_3"]) == 24 * 10
    assert len(report.state.streams["od_2"]) == 25 * 10

    # --- and the run says so: a run that dropped 10 samples must not look like a clean one ---
    od_3_read = "blocks[0].children[14].body[0].body[0].children[2]"
    assert [t.block_id for t in report.tolerated_errors] == [od_3_read] * 10
    assert all(FLAKE in t.error for t in report.tolerated_errors)

    # --- the guard: no reading, no decision. Tube 3 is not serviced on the cycle it went
    # dark (and the empty od_3 window never reaches the evaluator); its neighbours are. ---
    t1, t2, t3 = (lab.cultures[t] for t in (1, 2, 3))
    assert len(t1.injections) == 25 and len(t2.injections) == 25
    assert len(t3.injections) == 24, "the guard must skip exactly the cycle with no reading"


async def test_a_dead_sensor_does_not_latch_an_open_loop_injector(tmp_path: Path) -> None:
    """The regression the freshness window exists for, on the shipped 120-cycle doc.

    `densitometer_3` reads cycle 1 and is dark forever after. Under the whole-stream guard
    `count(od_3) > 0` — true for the rest of the run once the tube has ever read — every
    stat in tube 3's decision tree freezes on its last successful trace, the condition
    becomes a CONSTANT, and the same arm fires on all 120 cycles with no feedback. The arm
    that latches is DRUG (a healthy vial is above OD_THR and out-growing its dilution by
    construction), so the §1 recursion walks the vial's drug concentration to the undiluted
    stock: measured, 120/120 drug injections, c -> 9.999 (= Stock A, 10x MIC), OD -> 0.0003.
    A sterilized culture, and a run that reports `completed`.

    `count(od_3, last=11min) > 0` proves a sample landed during THIS cycle's growth phase,
    so the tube is serviced once and then left alone — alive, and visibly abandoned in the
    run log. This test FAILS on the old guard: tube 3 takes 120 injections, not 1.

    All three tubes start in the band (above OD_THR, growing at r0 = 2 * r_dil), which is
    what makes DRUG the arm that latches — the healthy, and therefore the dangerous, case.
    """
    _, workflow = load("morbidostat.json")
    clock = FakeClock()
    lab = DeadSensorLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(
            clock=clock,
            input_provider=Answers(),
            output_dir=tmp_path,
            job_poll_interval=0.05,
            job_poll_max=0.2,
        ),
    )
    report = await drive(clock, run.execute(), max_steps=5_000_000)

    assert report.status == "completed"
    assert len(report.state.streams["od_3"]) == 10, "tube 3 read cycle 1 and nothing after"

    t1, t2, t3 = (lab.cultures[t] for t in (1, 2, 3))

    # --- THE REGRESSION. Servicing a tube stops when its sensor stops, and stays stopped:
    # the injection count is BOUNDED by the cycles it actually had data for. The old guard
    # leaves it latched instead — 120 injections, every one of them drug. ---
    assert t3.injections == ["drug"], "a dead sensor latched the decision tree open"

    # c is one injection's worth of stock (10 * 1/13 = 0.769). The latched run walks it up
    # the §1 recursion to 9.999 — the fixed point is C, the undiluted stock — while diluting
    # the vial 120 times: OD 0.00031, a 1,600x collapse, reported as a completed run.
    assert t3.drug < 0.5 * STOCK, f"tube 3: drug {t3.drug:.3f} is walking toward the stock"
    # The simulator only advances a culture on a read or an injection, so this is tube 3's
    # OD as of the moment it was abandoned: still in the band, not diluted to death.
    assert t3.od > 0.1, f"tube 3: OD {t3.od:.5f} — the culture was diluted to death"

    # --- and the neighbours are untouched: serviced every cycle, still pinned at r_dil ---
    for t, culture in ((1, t1), (2, t2)):
        assert len(culture.injections) == 120
        rate = R0_PER_H / (1.0 + culture.drug / IC50)
        assert 0.2 <= rate <= 0.6, f"tube {t}: growth rate {rate:.3f} not pinned near r_dil"

    # --- the abandonment is loud, not silent: every lost read is in the report ---
    od_3_read = "blocks[0].children[14].body[0].body[0].children[2]"
    assert [t.block_id for t in report.tolerated_errors] == [od_3_read] * (119 * 10)
