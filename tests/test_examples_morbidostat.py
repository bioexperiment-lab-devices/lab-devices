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
            if key in ("label", "gap_after", "start_offset"):
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

    # --- valves were left parked closed at the end of every cycle ---
    assert lab.valve_pos == {"valve_1": 0, "valve_2": 0, "valve_3": 0}

    # --- the finalizer swept the thermostats back off ---
    thermostats = [c[2] for c in lab.calls if c[1] == "set_thermostat"]
    assert {"enabled": True, "target_c": 30.0} in thermostats
    assert {"enabled": False} in thermostats
