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
from lab_devices.experiment import ExperimentRun, InMemoryRunLog, RunOptions
from lab_devices.experiment.errors import AbortSignalError
from lab_devices.experiment.expand import expand_dict
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
    "emergency_stop": False,
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


class ResistantCulture(Culture):
    """A contamination organism: growth is NEVER quenched by drug (rate is always r0), the
    physical signature of a strain the algorithm's drug cannot touch. `inject` (inherited)
    still dilutes it on every injection - a contaminant is not immune to being diluted, only
    to being killed - so it keeps out-growing its dilution rather than sitting still."""

    def grow_to(self, now: float) -> None:
        dt_h = max(0.0, now - self.t) / 3600.0
        self.t = now
        self.od *= math.exp(R0_PER_H * dt_h)


class ContaminatedLab(CultureLab):
    """A CultureLab whose tube 3 is contaminated with a drug-resistant organism.

    Tube 3 never stops out-growing its dilution (ResistantCulture, above), so the controller's
    OWN decision tree - unaware anything is wrong - keeps choosing DRUG every cycle exactly as
    it would for a healthy vial fighting to stay at IC50. That walks the workflow's *believed*
    concentration `c_3` up the `c_k = c_(k-1)*V/(V+dV) + C*dV/(V+dV)` recursion toward its fixed
    point (drug_stock_x_mic), while tube 3's OD - genuinely growing, not latched on stale data -
    stays far above the healthy steady-state band. Both legs of the contamination predicate
    (`c_3 >= drug_stock_x_mic*0.99 and mean(od_3) > od_ceiling`) become true from real,
    independently-arrived-at evidence: this is what the FakeLab CAN prove that the preprod sim
    (which reads OD 0.0) cannot."""

    def __init__(self, clock: FakeClock, start_od: dict[int, float]) -> None:
        super().__init__(clock, start_od)
        self.cultures[3] = ResistantCulture(start_od[3])


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
    def __init__(self, overrides: dict[str, BindingValue] | None = None) -> None:
        self.asked: list[str] = []
        self._answers = {**ANSWERS, **(overrides or {})}

    async def request(self, request: InputRequest) -> BindingValue:
        self.asked.append(request.name)
        return self._answers[request.name]


def load(name: str) -> Any:
    doc = json.loads((EXAMPLES / name).read_text())
    workflow = json.loads(json.dumps(doc["workflow"]))
    workflow = expand_dict(workflow)  # for_each / service(tube) -> concrete roles
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

    # after the working-volume compute, one for_each(c_tube/contaminated_tube/alarmed_tube)
    # seed, and the emergency_stop operator_input
    ratchet = setup[13]["loop"]
    # The two whole-run aborts (operator emergency_stop; all three tubes contaminated) sit
    # at the very top of the cycle, before anything else happens this cycle.
    assert ratchet["body"][0]["abort"]["if"] == "emergency_stop"
    assert (
        ratchet["body"][1]["abort"]["if"]
        == "contaminated_1 and contaminated_2 and contaminated_3"
    )
    # The OD reads are now ONE for_each lane, spliced to 3 concrete reads at expand time
    # (already proven equivalent to the old 3-lane parallel by test_morbidostat_closes_the_loop,
    # which reads od_1/2/3 120*10 times each on the expanded doc).
    reads_for_each = ratchet["body"][2]["loop"]["body"][0]["parallel"]["children"][0]["for_each"]
    assert reads_for_each["in"] == [1, 2, 3]
    (read,) = reads_for_each["body"]
    assert read["on_error"] == "continue"
    assert read["measure"] == {
        "device": "od_meter_{tube}", "verb": "measure", "into": "od_{tube}"
    }

    # The three tube-service branches are now one `service(tube)` group, called once per tube
    # by a for_each. Short-circuit guard: no FRESH reading, no decision — and no empty-window
    # EvaluationError. The window is what makes it a freshness guard: the whole-stream
    # form `count(od_N) > 0` latches true forever over an append-only stream, and a
    # latched guard is an open-loop drug injector (test_a_dead_sensor_does_not_latch).
    service_call = ratchet["body"][3]["for_each"]
    assert service_call["in"] == [1, 2, 3]
    (call,) = service_call["body"]
    assert call["group_ref"] == {"name": "service", "args": {"tube": "{tube}"}}

    # The service group now leads with contamination bookkeeping (freshness-guarded OD-high
    # latch, sticky `contaminated` latch, fire-once alarm, sticky `alarmed` latch) and only
    # THEN the pre-existing freshness branch, now wrapped so a contaminated tube is dropped.
    window = FRESHNESS[name]
    service_body = doc["workflow"]["groups"]["service"]["body"]
    assert service_body[0]["compute"]["into"] == "od_high_{tube}"
    assert service_body[1]["compute"]["into"] == "contaminated_{tube}"
    assert service_body[2]["alarm"]["if"] == "contaminated_{tube} and not alarmed_{tube}"
    assert service_body[3]["compute"]["into"] == "alarmed_{tube}"
    drop_branch = service_body[4]["branch"]
    assert drop_branch["if"] == "not contaminated_{tube}"
    group_guard = drop_branch["then"][0]["branch"]["if"]
    assert group_guard.startswith(f"count(od_{{tube}}, last={window}) > 0 and ")

    # The thermostat setup is parallel again; retry is what makes that safe on a roster whose
    # devices share a serial (docs/experiment-engine-limitations.md, final section). Six
    # attempts, not three: the contending set only thins as each round's winner drops out
    # (3 -> 2 -> 1), and a jitter-free constant back-off does not de-synchronize the herd.
    thermostats = setup[6]["parallel"]["children"]
    assert [t["command"]["verb"] for t in thermostats] == ["set_thermostat"] * 3
    assert all(t["retry"]["attempts"] == 6 for t in thermostats)
    assert all("on_error" not in t for t in thermostats), "an unset thermostat must stop the run"

    # No pump may ever be retried: volume_ml is relative, so a retried dispense double-doses.
    # Pump commands now live inside the `service` group body, so walk group bodies too.
    group_blocks = [
        b for g in doc["workflow"].get("groups", {}).values() for b in _walk(g["body"])
    ]
    assert not any(
        "retry" in b for b in _walk(doc["workflow"]["blocks"]) + group_blocks if "command" in b
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
        "blanks_ready", "cultures_ready", "emergency_stop",
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
    od_3_read = "blocks[0].children[21].body[2].body[0].children[2]"
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
    od_3_read = "blocks[0].children[21].body[2].body[0].children[2]"
    assert [t.block_id for t in report.tolerated_errors] == [od_3_read] * (119 * 10)


async def test_operator_emergency_stop_aborts_and_finalizes(tmp_path: Path) -> None:
    """The workflow-declared safety switch (design 2026-07-16 §2.1, task 7): the operator
    answers `emergency_stop=true` at setup, and the whole-run `abort` at the top of the very
    first cycle must stop the run before a single OD is read, with the finalizer still
    sweeping the thermostats back off. This is the FakeLab half of the demonstrator; the
    honest gap is that the preprod sim reads OD 0.0, so only the operator switch — not the
    contamination latch below — can be proven on that hardware (task 9).
    """
    _, workflow = load("morbidostat.json")
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.05, 2: 0.05, 3: 0.05})
    run = ExperimentRun(
        LabClient("lab", 9000, http=_http(lab)),
        workflow,
        options=RunOptions(
            clock=clock,
            input_provider=Answers({"emergency_stop": True}),
            output_dir=tmp_path,
            job_poll_interval=0.05,
            job_poll_max=0.2,
            log_sink=InMemoryRunLog(),  # override the doc's disk log sink to inspect events
        ),
    )
    with pytest.raises(AbortSignalError):
        await drive(clock, run.execute(), max_steps=1_000_000)

    report = run.report
    assert report is not None
    assert report.status == "aborted"
    kinds = [e.kind for e in report.log.events]
    assert "abort_raised" in kinds
    assert "finalize_finished" in kinds

    # the abort fires before the very first OD read: nothing was ever serviced. Setup's
    # one-shot blanks DID run (they precede the loop entirely); od_N never got a chance to.
    assert all(len(c.injections) == 0 for c in lab.cultures.values())
    assert all(len(report.state.streams[f"od_{t}"]) == 0 for t in (1, 2, 3))
    assert all(len(report.state.streams[f"blank_{t}"]) == 1 for t in (1, 2, 3))

    # the finalizer still reached safe state: thermostats set up, then swept back off
    thermostats = [c[2] for c in lab.calls if c[1] == "set_thermostat"]
    assert {"enabled": True, "target_c": 30.0} in thermostats
    assert {"enabled": False} in thermostats


async def test_contaminated_tube_is_alarmed_and_dropped_from_service(tmp_path: Path) -> None:
    """The contamination story task 7 exists for: a drug-resistant contaminant in tube 3
    keeps out-growing its dilution no matter how much drug it gets (`ResistantCulture`), so
    the controller's OWN decision tree - unaware anything is wrong - keeps choosing DRUG,
    walking the workflow's *believed* concentration `c_3` up to the stock ceiling while OD
    stays far above the healthy band. Both contamination-predicate legs become true from
    real, independently-arrived-at evidence (not a stale/latched read): the tube is alarmed
    exactly once (fire-once idiom: alarm on the edge, then a sticky `compute` latch) and
    dropped from service for the rest of the run, while its healthy neighbours are serviced
    on every one of the 120 cycles, unaffected.
    """
    _, workflow = load("morbidostat.json")
    clock = FakeClock()
    lab = ContaminatedLab(clock, {1: 0.05, 2: 0.05, 3: 0.2})
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
    report = await drive(clock, run.execute(), max_steps=2_000_000)

    assert report.status == "completed", "one contaminated tube must not abort the whole run"

    t1, t2, t3 = (lab.cultures[t] for t in (1, 2, 3))

    # --- the healthy neighbours are untouched: serviced every one of the 120 cycles ---
    assert len(t1.injections) == 120 and len(t2.injections) == 120

    # --- tube 3 is dropped from service partway through, and never dosed again ---
    assert 0 < len(t3.injections) < 120, "tube 3 must be serviced for a while, then dropped"
    assert set(t3.injections) == {"drug"}, "tube 3 never dipped below od_thr, so only DRUG fired"
    assert report.state.bindings["contaminated_3"] is True
    assert report.state.bindings["contaminated_1"] is False
    assert report.state.bindings["contaminated_2"] is False

    # --- one c_series sample per serviced cycle: recording stops exactly when service does ---
    assert len(report.state.streams["c_series_3"].samples) == len(t3.injections)

    # --- fired once (latched), and only for the contaminated tube ---
    msgs = [a.message for a in report.alarms]
    tube_3_msgs = [m for m in msgs if "tube 3" in m]
    assert len(tube_3_msgs) == 1, "the alarm must latch, not refire every remaining cycle"
    assert "contaminated" in tube_3_msgs[0] and "dropped from service" in tube_3_msgs[0]
    assert not any("tube 1" in m or "tube 2" in m for m in msgs), "healthy tubes never alarm"
