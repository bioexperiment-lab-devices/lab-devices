# Adaptive Bioreactor — Studio Grand Tour Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a single demo-speed experiment that exercises every schema-3 engine feature and device verb, runs green against a simulated lab per control regime, and doubles as an Experiment Studio showcase.

**Architecture:** A regime-switching 3-tube bioreactor authored as `examples/adaptive-bioreactor-tour.json` in the `{doc_version,name,description,workflow}` envelope. It reuses the morbidostat's 9-role topology and `MAPPING`, so its committed E2E test extends the morbidostat's `CultureLab` simulator. No engine or Studio code changes — data, test, and docs only.

**Tech Stack:** Python 3.14, pytest (asyncio), the shipped `lab_devices.experiment` engine (`expand_dict`, `workflow_from_dict`, `ExperimentRun`, `RunOptions`), and the test harness in `tests/fakelab.py` / `tests/fakeclock.py`.

## Global Constraints

- **No engine/Studio source changes.** Only `examples/`, `tests/`, `docs/` are touched. A genuine engine gap is a finding to report, not a workaround.
- **`schema_version` must be `3`.** Every declared stream carries `units`; every value whose derived unit differs from its target carries an `as` cast.
- **Envelope:** `{ "doc_version": 1, "name": ..., "description": ..., "workflow": { schema_version, metadata, persistence, defaults, roles, streams, groups, blocks } }`. `roles` live **inside** `workflow`.
- **Role topology + mapping (verbatim, reused from the morbidostat):**
  `medium_pump→pump_1`, `drug_pump→pump_2`, `waste_pump→pump_3`, `medium_valve→valve_1`, `drug_valve→valve_2`, `waste_valve→valve_3`, `od_meter_1→densitometer_1`, `od_meter_2→densitometer_2`, `od_meter_3→densitometer_3`.
- **Pumps are never retried** (`dispense` is relative — a retry double-doses). `defaults.retry` covers only retry-safe verbs; the OD reads additionally carry `on_error: continue`.
- **Pace-coupled constants:** inner read loop `count: 10, pace: 3s`; freshness window `last=45s` (10×3s=30s < 45s < 60s cycle pace); slope constant `480 = 2*3600/(n*dt)` with `n=5, dt=3s`. If any of `count`/`pace` change, both constants change.
- **Gates (run from repo root, the Poetry venv):** `python -m pytest && python -m mypy && python -m ruff check .`. No webapp change, so webapp gates are out of scope.
- **Test style:** mirror `tests/test_examples_morbidostat.py` exactly — `load()` (expand + `workflow_from_dict`), `Answers` input provider, `drive(clock, run.execute(), max_steps=...)`, assertions on `report.status`, `report.state.streams`, `report.alarms`, `report.tolerated_errors`, and `lab.calls`.

---

## File Structure

- **Create** `examples/adaptive-bioreactor-tour.json` — the experiment document (envelope + workflow).
- **Create** `tests/test_examples_adaptive_bioreactor.py` — load/validate, feature-shape pin, per-regime green run, hard-edge tests. Owns its own `CultureLab` subclasses (extending the morbidostat harness).
- **Modify** `examples/README.md` — table row + walkthrough section.
- **Reference only** (do not modify): `tests/fakelab.py`, `tests/fakeclock.py`, `docs/workflow-schema.md`, `docs/superpowers/specs/2026-07-21-adaptive-bioreactor-tour-design.md`.

---

## Task 1: Author the complete experiment document

**Files:**
- Create: `examples/adaptive-bioreactor-tour.json`
- Scratch (not committed): a throwaway validation script under the scratchpad.

**Interfaces:**
- Produces: an example whose `workflow` survives `expand_dict(...)` then `workflow_from_dict(...)` then `ExperimentRun(...)` (which calls `validate()` in its constructor) with no error. Later tasks consume the roles, streams (`od_1..3`, `tube_N_c_series`, `tube_N_r_series`, `blank_1..3`), the `service` group, and the operator-input names (`regime`, `target_od`, `cycles`, `warm_start`, `emergency_stop`, `dose_ml`, `od_min`, `od_thr`, `r_dil`, `drug_stock_x_mic`).

### Document shape to author

**Envelope + workflow header:**

```jsonc
{
  "doc_version": 1,
  "name": "Adaptive Bioreactor — Studio Grand Tour (demo speed)",
  "description": "<rich house-style description — see below>",
  "workflow": {
    "schema_version": 3,
    "metadata": {"name": "Adaptive Bioreactor — Studio Grand Tour (demo speed)", "author": "lab-devices examples", "description": "<same as outer>"},
    "persistence": {"default": "in_memory", "format": "jsonl"},
    "defaults": {"retry": {"attempts": 3, "backoff": "1s"}},
    "roles": {
      "medium_pump": {"type": "pump"}, "drug_pump": {"type": "pump"}, "waste_pump": {"type": "pump"},
      "medium_valve": {"type": "valve"}, "drug_valve": {"type": "valve"}, "waste_valve": {"type": "valve"},
      "od_meter_1": {"type": "densitometer"}, "od_meter_2": {"type": "densitometer"}, "od_meter_3": {"type": "densitometer"}
    },
    "streams": {
      "od_1": {"units": "AU"}, "od_2": {"units": "AU"}, "od_3": {"units": "AU"},
      "blank_1": {"units": "unitless"}, "blank_2": {"units": "unitless"}, "blank_3": {"units": "unitless"}
    },
    "groups": { "service": { <see below> } },
    "blocks": [ <Phase 0..4, see below> ]
  }
}
```

The `description` (outer and `metadata`) is a multi-paragraph house-style string like the morbidostat's: what the experiment is, the three regimes and how the enum selects them, the pace-coupled constants warning (verbatim numbers from Global Constraints), the fault-tolerance rationale (pumps never retried, OD reads tolerated, blanks not tolerated), the "biologically meaningless at demo speed" caveat, and a "flip `emergency_stop` to see the abort path" note.

### The `service` group (exercises all seven param kinds + both local kinds)

```jsonc
"service": {
  "params": [
    {"name": "tube", "kind": "int"},
    {"name": "warn_od", "kind": "number"},
    {"name": "name", "kind": "string"},
    {"name": "is_control", "kind": "bool"},
    {"name": "meter", "kind": "role", "device_type": "densitometer"},
    {"name": "od", "kind": "stream"},
    {"name": "budget", "kind": "binding"}
  ],
  "locals": {
    "c": {"kind": "binding", "init": "0"},
    "contaminated": {"kind": "binding", "init": "false"},
    "r": {"kind": "binding"},
    "c_series": {"kind": "stream", "units": "x_MIC", "persistence": "disk"},
    "r_series": {"kind": "stream", "units": "per_hour"}
  },
  "body": [
    {"compute": {"into": "{contaminated}",
                 "value": "{contaminated} or (count({od}, last=45s) > 0 and max({od}, last=45s) > 3.0)"},
     "label": "tube {name}: contamination latch (OD stuck high)"},
    {"branch": {
      "if": "not {contaminated} and count({od}, last=45s) > 0 and last({od}) >= od_min",
      "then": [
        {"compute": {"into": "{r}",
                     "value": "480 * (mean({od}, last=5) - mean({od}, last=10)) / last({od})"},
         "label": "tube {name}: growth-rate estimate"},
        {"record": {"into": "{r_series}", "value": "{r}", "as": "per_hour"},
         "label": "tube {name}: chart growth rate"},
        {"branch": {
          "if": "is_control",
          "then": [
            {"alarm": {"if": "last({od}) > warn_od", "message": "control tube {name}: OD above warn line, not dosing"}}
          ],
          "else": [
            {"branch": {
              "if": "regime == 'turbidostat'",
              "then": [ <turbidostat arm> ],
              "else": [ {"branch": {
                "if": "regime == 'morbidostat'",
                "then": [ <morbidostat arm> ],
                "else": [ <chemostat per-tube arm: medium top-up> ]
              }} ]
            }}
          ]
        }}
      ]
    }, "label": "tube {name}: freshness-guarded service"}
  ]
}
```

- **turbidostat arm** — dilute only when above target:
  ```jsonc
  {"branch": {"if": "last({od}) > target_od", "then": [
    {"command": {"device": "medium_valve", "verb": "set_position", "params": {"position": "{tube}", "rotation": "direct"}}},
    {"command": {"device": "medium_pump", "verb": "dispense", "params": {"volume_ml": "dose_ml", "speed_ml_min": 6.0, "direction": "forward"}}},
    {"compute": {"into": "{budget}", "value": "{budget} + dose_ml"}, "label": "tube {name}: dose budget"}
  ]}}
  ```
- **morbidostat arm** — drug/medium bang-bang + concentration recursion + `c_series`:
  ```jsonc
  {"branch": {"if": "last({od}) > od_thr and {r} > r_dil",
    "then": [
      {"command": {"device": "drug_valve", "verb": "set_position", "params": {"position": "{tube}", "rotation": "direct"}}},
      {"command": {"device": "drug_pump", "verb": "dispense", "params": {"volume_ml": "dose_ml", "speed_ml_min": 6.0, "direction": "forward"}}},
      {"compute": {"into": "{c}", "value": "{c} * working_volume_ml/(working_volume_ml + dose_ml) + drug_stock_x_mic * dose_ml/(working_volume_ml + dose_ml)"}},
      {"compute": {"into": "{budget}", "value": "{budget} + dose_ml"}}
    ],
    "else": [
      {"command": {"device": "medium_valve", "verb": "set_position", "params": {"position": "{tube}", "rotation": "direct"}}},
      {"command": {"device": "medium_pump", "verb": "dispense", "params": {"volume_ml": "dose_ml", "speed_ml_min": 6.0, "direction": "forward"}}},
      {"compute": {"into": "{c}", "value": "{c} * working_volume_ml/(working_volume_ml + dose_ml)"}},
      {"compute": {"into": "{budget}", "value": "{budget} + dose_ml"}}
    ]},
  "label": "tube {name}: morbidostat decision"},
  {"record": {"into": "{c_series}", "value": "{c}", "as": "x_MIC"}, "label": "tube {name}: chart drug concentration"}
  ```
- **chemostat per-tube arm** — a fixed medium top-up (the continuous-perfusion *mode* is the aggregate Phase-3 step):
  ```jsonc
  {"command": {"device": "medium_valve", "verb": "set_position", "params": {"position": "{tube}", "rotation": "direct"}}},
  {"command": {"device": "medium_pump", "verb": "dispense", "params": {"volume_ml": "dose_ml", "speed_ml_min": 6.0, "direction": "forward"}}},
  {"compute": {"into": "{budget}", "value": "{budget} + dose_ml"}}
  ```

### Top-level blocks (Phases 0–4)

**Phase 0 — operator setup + top-level bindings** (`serial`, blocks[0]):
```jsonc
{"serial": {"children": [
  {"operator_input": {"name": "regime", "type": "enum", "prompt": "Control regime.", "choices": ["turbidostat", "chemostat", "morbidostat"]}},
  {"operator_input": {"name": "target_od", "type": "float", "prompt": "Target OD (turbidostat/chemostat setpoint).", "min": 0.05, "max": 2.0}},
  {"operator_input": {"name": "cycles", "type": "int", "prompt": "Number of control cycles.", "min": 1, "max": 200}},
  {"operator_input": {"name": "warm_start", "type": "bool", "prompt": "Run the warm-up / calibration phase?"}},
  {"operator_input": {"name": "emergency_stop", "type": "bool", "prompt": "Abort immediately (safety switch)?"}},
  {"operator_input": {"name": "od_min", "type": "float", "prompt": "Min OD to act on.", "min": 0.005, "max": 0.5}},
  {"operator_input": {"name": "od_thr", "type": "float", "prompt": "Drug-injection OD threshold.", "min": 0.01, "max": 2.0}},
  {"operator_input": {"name": "r_dil", "type": "float", "prompt": "Dilution rate 1/h (morbidostat setpoint).", "min": 0.01, "max": 5.0}},
  {"operator_input": {"name": "dose_ml", "type": "float", "prompt": "Volume per injection (ml).", "min": 0.1, "max": 5.0}},
  {"operator_input": {"name": "drug_stock_x_mic", "type": "float", "prompt": "Drug stock (x MIC).", "min": 1.0, "max": 1000.0}},
  {"compute": {"into": "working_volume_ml", "value": "12.0"}, "label": "constant working volume"},
  {"compute": {"into": "settle_min", "value": "0.05"}, "label": "equilibration wait, minutes"},
  {"compute": {"into": "dose_budget_ml", "value": "0"}, "label": "seed shared dose accumulator"},
  {"compute": {"into": "budget_alarmed", "value": "false"}, "label": "fire-once latch for the budget alarm"},
  {"wait": {"duration": "settle_min * 1min"}, "label": "equilibrate (duration expression)"},
  <Phase 1 warm-up serial>,
  <Phase 2 main loop>,
  <Phase 4 wrap-up serial>
]}}
```

**Phase 1 — warm-up & calibration** (guarded by `warm_start`, staggered lanes):
```jsonc
{"branch": {"if": "warm_start", "then": [
  {"parallel": {"children": [
    {"for_each": {
      "vars": [{"name": "tube", "kind": "int"}, {"name": "meter", "kind": "role", "device_type": "densitometer"}, {"name": "blank", "kind": "stream"}],
      "in": [
        {"tube": 1, "meter": "od_meter_1", "blank": "blank_1"},
        {"tube": 2, "meter": "od_meter_2", "blank": "blank_2"},
        {"tube": 3, "meter": "od_meter_3", "blank": "blank_3"}
      ],
      "body": [
        {"serial": {"children": [
          {"command": {"device": "{meter}", "verb": "set_thermostat", "params": {"enabled": true, "target_c": 30.0}}, "retry": {"attempts": 6, "backoff": "1s"}, "label": "tube {tube}: thermostat mode"},
          {"command": {"device": "{meter}", "verb": "set_led", "params": {"level": 8}}, "label": "tube {tube}: measurement LED mode"},
          {"command": {"device": "{meter}", "verb": "set_tube_correction", "params": {"factor": 1.0}}, "label": "tube {tube}: tube correction"},
          {"measure": {"device": "{meter}", "verb": "measure_blank", "into": "{blank}"}, "label": "tube {tube}: blank baseline"},
          {"command": {"device": "{meter}", "verb": "calibrate_tube", "params": {"reference_absorbance": 0.0}}, "label": "tube {tube}: calibrate"}
        ]},
         "start_offset": "tube * 1s", "gap_after": "1s", "label": "tube {tube}: staggered warm-up"}
      ]
    }}
  ]}},
  {"parallel": {"children": [
    {"command": {"device": "medium_valve", "verb": "home", "params": {"position": 0}}},
    {"command": {"device": "drug_valve", "verb": "home", "params": {"position": 0}}},
    {"command": {"device": "waste_valve", "verb": "home", "params": {"position": 0}}},
    {"command": {"device": "medium_valve", "verb": "configure", "params": {"default_rotation": "direct", "hold_torque": false}}},
    {"command": {"device": "medium_pump", "verb": "set_calibration", "params": {"ml_per_step": 0.0008}}}
  ]}}
]}, "label": "warm-up & calibration (skippable)"}
```
Note `start_offset: "tube * 1s"` uses the `for_each` int var in a **duration expression**.

**Phase 2 — adaptive control loop** (`loop`, `count` expression, `pace`):
```jsonc
{"loop": {
  "count": "cycles",
  "pace": "60s",
  "body": [
    {"abort": {"if": "emergency_stop", "message": "operator emergency stop"}, "label": "whole-run abort (operator switch)"},
    {"abort": {"if": "tube_1_contaminated and tube_2_contaminated and tube_3_contaminated", "message": "all vials contaminated"}, "label": "whole-run abort (all tubes contaminated)"},
    {"loop": {"count": 10, "pace": "3s", "body": [
      {"parallel": {"children": [
        {"for_each": {
          "vars": [{"name": "tube", "kind": "int"}, {"name": "meter", "kind": "role", "device_type": "densitometer"}, {"name": "od", "kind": "stream"}],
          "in": [
            {"tube": 1, "meter": "od_meter_1", "od": "od_1"},
            {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
            {"tube": 3, "meter": "od_meter_3", "od": "od_3"}
          ],
          "body": [ {"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}, "on_error": "continue", "label": "tube {tube} OD"} ]
        }}
      ]}}
    ]}, "label": "growth phase: 10 reads per tube"},
    {"for_each": {
      "vars": [
        {"name": "tube", "kind": "int"}, {"name": "warn", "kind": "number"}, {"name": "name", "kind": "string"},
        {"name": "control", "kind": "bool"}, {"name": "meter", "kind": "role", "device_type": "densitometer"}, {"name": "od", "kind": "stream"}
      ],
      "in": [
        {"tube": 1, "warn": 1.5, "name": "A", "control": false, "meter": "od_meter_1", "od": "od_1"},
        {"tube": 2, "warn": 1.5, "name": "B", "control": false, "meter": "od_meter_2", "od": "od_2"},
        {"tube": 3, "warn": 1.5, "name": "C", "control": true,  "meter": "od_meter_3", "od": "od_3"}
      ],
      "body": [
        {"group_ref": {"name": "service", "as": "tube_{tube}",
          "args": {"tube": "{tube}", "warn_od": "{warn}", "name": "{name}", "is_control": "{control}", "meter": "{meter}", "od": "{od}", "budget": "dose_budget_ml"}}}
      ]
    }},
    {"branch": {"if": "regime == 'chemostat'", "then": [ <Phase 3 perfusion, below> ]}, "label": "chemostat continuous perfusion"},
    {"serial": {"children": [
      {"alarm": {"if": "dose_budget_ml > 12.0 and not budget_alarmed", "message": "cumulative dose budget exceeded"}, "label": "dose-budget alarm (fire once)"},
      {"compute": {"into": "budget_alarmed", "value": "budget_alarmed or (dose_budget_ml > 12.0)"}}
    ]}, "label": "cycle aggregate"}
  ]
}, "label": "adaptive control loop"}
```

**Phase 3 — chemostat perfusion** (`until`+`check` loop + `rotate` mode, counter-bounded):
```jsonc
{"serial": {"children": [
  {"command": {"device": "medium_valve", "verb": "set_position", "params": {"position": 1, "rotation": "direct"}}},
  {"command": {"device": "medium_pump", "verb": "rotate", "params": {"direction": "forward", "speed_ml_min": 3.0}}, "label": "perfusion MODE open"},
  {"compute": {"into": "settle_iters", "value": "0"}},
  {"loop": {
    "until": "settle_iters >= 5 or mean(od_1, last=3) < target_od",
    "check": "after",
    "pace": "3s",
    "body": [
      {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}, "on_error": "continue"},
      {"compute": {"into": "settle_iters", "value": "settle_iters + 1"}}
    ]
  }, "label": "settle until at target (bounded until-loop)"},
  {"command": {"device": "medium_pump", "verb": "stop"}, "label": "perfusion MODE teardown"}
]}}
```

**Phase 4 — wrap-up** (`serial`):
```jsonc
{"serial": {"children": [
  {"parallel": {"children": [
    {"command": {"device": "od_meter_1", "verb": "set_led", "params": {"level": 0}}, "label": "LED off"},
    {"command": {"device": "od_meter_2", "verb": "set_led", "params": {"level": 0}}},
    {"command": {"device": "od_meter_3", "verb": "set_led", "params": {"level": 0}}}
  ]}},
  {"parallel": {"children": [
    {"command": {"device": "od_meter_1", "verb": "set_thermostat", "params": {"enabled": false}}, "label": "thermostat off"},
    {"command": {"device": "od_meter_2", "verb": "set_thermostat", "params": {"enabled": false}}},
    {"command": {"device": "od_meter_3", "verb": "set_thermostat", "params": {"enabled": false}}}
  ]}},
  {"record": {"into": "od_1", "value": "last(od_1)", "as": "AU"}, "label": "final OD snapshot"}
]}, "label": "wrap-up: modes off"}
```

- [ ] **Step 1: Write the example file** with the full structure above (author the complete `description`, expand every `<...>` placeholder into the concrete blocks shown). Save as `examples/adaptive-bioreactor-tour.json`.

- [ ] **Step 2: Write a scratch validator** at `<scratchpad>/validate_tour.py`:

```python
import json, sys
from pathlib import Path
from lab_devices.experiment.expand import expand_dict
from lab_devices.experiment.serialize import workflow_from_dict
doc = json.loads(Path("examples/adaptive-bioreactor-tour.json").read_text())
wf = expand_dict(json.loads(json.dumps(doc["workflow"])))
w = workflow_from_dict(wf)
print("OK roles:", sorted(w.roles))
print("OK streams:", sorted(wf["streams"]))
```

- [ ] **Step 3: Run it until clean.**
Run: `cd /Users/khamit/lab-devices-adaptive-bioreactor-tour && python -m pytest -q` won't cover it yet; run the scratch validator with the repo venv python.
Expected: prints `OK roles: [...]` and `OK streams: [...]`, listing the 9 roles and the expanded streams including `tube_1_c_series` etc. Fix any `WorkflowLoadError`/expansion error until it prints OK. Common fixes: a reference hole concatenated with text; a duration slot missing its unit; a bare number in a duration slot; a stream missing `units`.

- [ ] **Step 4: Commit.**
```bash
git add examples/adaptive-bioreactor-tour.json
git commit -m "feat(examples): adaptive-bioreactor grand-tour experiment document"
```

---

## Task 2: Load/validate + feature-shape pinning test

**Files:**
- Create: `tests/test_examples_adaptive_bioreactor.py`

**Interfaces:**
- Consumes: `examples/adaptive-bioreactor-tour.json` from Task 1.
- Produces: `load(name)`, `MAPPING`, `TUBE_OF_METER`, `BASE_ANSWERS`, and the `Answers` provider — reused by Tasks 3–4.

- [ ] **Step 1: Write the module header + harness + shape test.**

```python
"""The adaptive-bioreactor grand-tour example, executed against a simulated culture.

Guards examples/adaptive-bioreactor-tour.json against engine drift and proves the whole
schema-3 feature surface runs green at demo speed. See
docs/superpowers/specs/2026-07-21-adaptive-bioreactor-tour-design.md.
"""
import json
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

MAPPING = {
    "medium_pump": "pump_1", "drug_pump": "pump_2", "waste_pump": "pump_3",
    "medium_valve": "valve_1", "drug_valve": "valve_2", "waste_valve": "valve_3",
    "od_meter_1": "densitometer_1", "od_meter_2": "densitometer_2", "od_meter_3": "densitometer_3",
}
TUBE_OF_METER = {"densitometer_1": 1, "densitometer_2": 2, "densitometer_3": 3}

BASE_ANSWERS: dict[str, BindingValue] = {
    "target_od": 0.30, "cycles": 20, "warm_start": True, "emergency_stop": False,
    "od_min": 0.03, "od_thr": 0.15, "r_dil": 0.4, "dose_ml": 1.0, "drug_stock_x_mic": 10.0,
}


class Answers:
    def __init__(self, overrides: dict[str, BindingValue] | None = None) -> None:
        self.asked: list[str] = []
        self._answers = {**BASE_ANSWERS, **(overrides or {})}
    async def request(self, request: InputRequest) -> BindingValue:
        self.asked.append(request.name)
        return self._answers[request.name]


def load(name: str = DOC) -> Any:
    doc = json.loads((EXAMPLES / name).read_text())
    workflow = expand_dict(json.loads(json.dumps(doc["workflow"])))
    return doc, workflow_from_dict(workflow)


def test_example_loads_and_validates() -> None:
    doc, workflow = load()
    assert doc["doc_version"] == 1
    assert doc["workflow"]["schema_version"] == 3
    assert "roles" not in doc, "roles live inside the workflow"
    assert set(workflow.roles) == set(MAPPING)
    assert workflow.role_type("od_meter_1") == "densitometer"
    assert workflow.role_type("drug_pump") == "pump"
```

- [ ] **Step 2: Add the feature-shape pin** `test_example_declares_its_features` (asserts the tour actually contains every feature — this is what makes coverage regression-proof). Assert:
  - `workflow.defaults.retry.attempts == 3`.
  - the `service` group `params` list equals the seven-kind list from Task 1 and `locals` equals the two-local-kind map.
  - the operator-input names/types are present including `type == "enum"` with the three `choices`, and one each of `float`/`int`/`bool`.
  - the group body contains a `regime == 'turbidostat'` and a `regime == 'morbidostat'` string-equality branch.
  - a `record` carries `"as": "per_hour"` and another `"as": "x_MIC"`.
  - a `loop` with `until` and `check` exists (Phase 3), and the main `loop` uses `"count": "cycles"`.
  - the verb set across `blocks` + `groups` (walk with a local `_walk` copied from `tests/test_examples_morbidostat.py:387`) is a superset of `{"dispense","rotate","stop","set_calibration","set_position","home","configure","measure","measure_blank","set_led","set_thermostat","set_tube_correction","calibrate_tube"}`.
  - no `command` whose role type is `pump` carries a `retry` key.

  Copy `_walk` verbatim from the morbidostat test.

- [ ] **Step 3: Run.**
Run: `cd /Users/khamit/lab-devices-adaptive-bioreactor-tour && python -m pytest tests/test_examples_adaptive_bioreactor.py -v`
Expected: both tests PASS. If the verb-superset assert fails, the document is missing a verb — add it in the relevant phase and re-run Task 1's validator first.

- [ ] **Step 4: Commit.**
```bash
git add tests/test_examples_adaptive_bioreactor.py
git commit -m "test(examples): load/validate + feature-shape pin for the grand tour"
```

---

## Task 3: Extended `CultureLab` simulator + per-regime green run

**Files:**
- Modify: `tests/test_examples_adaptive_bioreactor.py`

**Interfaces:**
- Consumes: `load`, `Answers`, `MAPPING`, `TUBE_OF_METER`.
- Produces: `Culture`, `CultureLab` (with rotate-mode perfusion), `_http`, and the per-regime run tests.

- [ ] **Step 1: Port the culture model + `CultureLab` from the morbidostat test**, extended for rotate-mode continuous perfusion. Copy `Culture` (grow/inject) and `CultureLab` from `tests/test_examples_morbidostat.py:69-143` and add rotate handling to `_command`:

```python
# in CultureLab.__init__: self.perfusing: str | None = None
# in CultureLab._command, before the super() return:
if cmd == "rotate" and device_id == "pump_1":
    self.perfusing = "valve_1"     # continuous medium via medium_valve's tube
if cmd == "stop" and device_id == "pump_1":
    self.perfusing = None
# in _advance, on a successful measure, dilute a perfusing tube a step before reading:
if self.perfusing is not None:
    tube = self.valve_pos[self.perfusing]
    if tube in self.cultures:
        self.cultures[tube].inject("medium", 0.2, self.clock.now())
```
(Keep the growth/dilution/noise exactly as the morbidostat's so behaviour is comparable.)

- [ ] **Step 2: Write the parametrized green-run test.**

```python
@pytest.mark.parametrize("regime", ["turbidostat", "chemostat", "morbidostat"])
async def test_regime_runs_green(regime: str, tmp_path: Path) -> None:
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
    report = await drive(clock, run.execute(), max_steps=5_000_000)
    assert report.status == "completed", f"{regime} did not complete"
    assert "regime" in answers.asked and "cycles" in answers.asked
    assert len(report.state.streams["od_2"]) == 20 * 10   # tube 2 read every cycle
    doses1 = lab.cultures[1].injections
    if regime == "morbidostat":
        assert "drug" in doses1, "morbidostat never dosed drug"
    else:
        assert "drug" not in doses1, f"{regime} must never use drug"
    assert lab.cultures[3].injections == [], "the control tube must never be dosed"
```

Tune `start_od` / `BASE_ANSWERS` so each regime completes and the dosing asserts hold. If chemostat's `od_1` count is brittle (extra perfusion reads), assert `>= 20*10` for `od_1` and `== 20*10` for `od_2`/`od_3`.

- [ ] **Step 3: Run.**
Run: `cd /Users/khamit/lab-devices-adaptive-bioreactor-tour && python -m pytest tests/test_examples_adaptive_bioreactor.py -v -k regime`
Expected: three PASS (one per regime). Debug with `report.log.events` if a regime hangs (likely the `until`-loop — confirm the counter cap `settle_iters >= 5` is reachable).

- [ ] **Step 4: Commit.**
```bash
git add tests/test_examples_adaptive_bioreactor.py
git commit -m "test(examples): per-regime green run against a simulated culture"
```

---

## Task 4: Hard-edge tests (retry, isolation, alarm, abort, mode teardown)

**Files:**
- Modify: `tests/test_examples_adaptive_bioreactor.py`

**Interfaces:**
- Consumes: everything from Tasks 2–3.
- Produces: `FlakyLab` and four hard-edge tests.

- [ ] **Step 1: Port `FlakyLab`** from `tests/test_examples_morbidostat.py:176-208` verbatim (densitometer_1 hiccups every 7th read; densitometer_3 dark for its first 30 attempts). It already models both the transient (retry-absorbed) and persistent (on_error-dropped) fault.

- [ ] **Step 2: Write the four tests** (`test_retry_and_isolation`, `test_dose_budget_alarm_fires`, `test_emergency_stop_aborts_and_finalizes`, `test_modes_are_torn_down`):

```python
async def test_retry_and_isolation(tmp_path: Path) -> None:
    """Transient fault absorbed by retry; a persistent one costs its own samples only,
    and its two sibling lanes read right through it (per-device isolation)."""
    _, workflow = load()
    clock = FakeClock()
    lab = FlakyLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    run = ExperimentRun(LabClient("lab", 9000, http=_http(lab)), workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"regime": "turbidostat"}),
            output_dir=tmp_path, role_mapping=MAPPING, job_poll_interval=0.05, job_poll_max=0.2))
    report = await drive(clock, run.execute(), max_steps=5_000_000)
    assert report.status == "completed"
    assert lab.dropped.count("densitometer_1") > 0, "the transient fault never fired"
    assert len(report.state.streams["od_1"]) == 20 * 10, "retry must hide the transient fault"
    assert lab.dropped.count("densitometer_3") == 30
    assert len(report.state.streams["od_3"]) == 19 * 10, "tube 3 lost exactly its first growth phase"
    assert len(report.state.streams["od_2"]) == 20 * 10, "sibling lane read through the fault"
    assert len(report.tolerated_errors) == 30

async def test_dose_budget_alarm_fires(tmp_path: Path) -> None:
    """The cumulative-dose alarm raises exactly once (fire-once latch), independent of sensor noise."""
    _, workflow = load()
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.9, 2: 0.9, 3: 0.9})  # high OD -> dosed every cycle
    run = ExperimentRun(LabClient("lab", 9000, http=_http(lab)), workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"regime": "turbidostat"}),
            output_dir=tmp_path, role_mapping=MAPPING, job_poll_interval=0.05, job_poll_max=0.2,
            log_sink=InMemoryRunLog()))
    report = await drive(clock, run.execute(), max_steps=5_000_000)
    assert report.status == "completed"
    msgs = [a.message for a in report.alarms]
    assert msgs.count("cumulative dose budget exceeded") == 1, "budget alarm must fire exactly once"

async def test_emergency_stop_aborts_and_finalizes(tmp_path: Path) -> None:
    _, workflow = load()
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    run = ExperimentRun(LabClient("lab", 9000, http=_http(lab)), workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"emergency_stop": True}),
            output_dir=tmp_path, role_mapping=MAPPING, job_poll_interval=0.05, job_poll_max=0.2,
            log_sink=InMemoryRunLog()))
    with pytest.raises(AbortSignalError):
        await drive(clock, run.execute(), max_steps=1_000_000)
    report = run.report
    assert report is not None and report.status == "aborted"
    kinds = [e.kind for e in report.log.events]
    assert "abort_raised" in kinds and "finalize_finished" in kinds

async def test_modes_are_torn_down(tmp_path: Path) -> None:
    """Thermostat, LED, and rotate modes are opened and closed (finalizer + explicit teardown)."""
    _, workflow = load()
    clock = FakeClock()
    lab = CultureLab(clock, {1: 0.5, 2: 0.5, 3: 0.5})
    run = ExperimentRun(LabClient("lab", 9000, http=_http(lab)), workflow,
        options=RunOptions(clock=clock, input_provider=Answers({"regime": "chemostat"}),
            output_dir=tmp_path, role_mapping=MAPPING, job_poll_interval=0.05, job_poll_max=0.2))
    await drive(clock, run.execute(), max_steps=5_000_000)
    calls = lab.calls
    assert any(c[1] == "set_thermostat" and c[2].get("enabled") is True for c in calls)
    assert any(c[1] == "set_thermostat" and c[2].get("enabled") is False for c in calls)
    assert any(c[1] == "set_led" and c[2].get("level") == 0 for c in calls)
    assert any(c[1] == "rotate" for c in calls) and any(c[1] == "stop" and c[0] == "pump_1" for c in calls)
```

- [ ] **Step 3: Run the whole file.**
Run: `cd /Users/khamit/lab-devices-adaptive-bioreactor-tour && python -m pytest tests/test_examples_adaptive_bioreactor.py -v`
Expected: all tests PASS. Tune thresholds if `test_dose_budget_alarm_fires` fires zero or multiple times (adjust the `> 12.0` threshold in the document + latch, then re-validate Task 1), or if `test_retry_and_isolation` sample counts are off (keep it on `regime: turbidostat`, which has no perfusion reads, so counts are clean).

- [ ] **Step 4: Commit.**
```bash
git add tests/test_examples_adaptive_bioreactor.py
git commit -m "test(examples): hard-edge coverage — retry, isolation, alarm, abort, mode teardown"
```

---

## Task 5: Docs — README row + walkthrough

**Files:**
- Modify: `examples/README.md`

- [ ] **Step 1: Add a table row** under the existing two:
```markdown
| `adaptive-bioreactor-tour.json` | A regime-switching 3-tube bioreactor (turbidostat / chemostat / morbidostat, chosen at run start) that exercises **every** schema-3 feature and device verb. Demo speed, ~20–25 min. The Studio grand tour. |
```

- [ ] **Step 2: Add a walkthrough section** after the morbidostat walkthrough: a "Studio grand tour" heading that maps each feature and Studio surface to where it appears (regime enum → string-equality branch; the `service` group's seven param kinds; both loop variants; the mode verbs; the expression editor over the guards; the read-only Bindings panel; draft+URL persistence; export/import; the multi-stream live chart; in-run operator prompts). Include the "flip `emergency_stop` to see the abort path" note and the group/for_each canvas-editing caveat already stated for the morbidostat. Mention CSV persistence as a one-line variant.

- [ ] **Step 3: Verify the docs/examples guards still pass.**
Run: `cd /Users/khamit/lab-devices-adaptive-bioreactor-tour && python -m pytest tests/test_docs_workflow_schema.py -q`
Expected: PASS (nothing in `docs/workflow-schema.md` changed; run it to confirm no regression).

- [ ] **Step 4: Commit.**
```bash
git add examples/README.md
git commit -m "docs(examples): grand-tour README row + Studio walkthrough"
```

---

## Task 6: Full gate sweep, PR, CI, merge

**Files:** none (verification + integration).

- [ ] **Step 1: Run the full root gate.**
Run: `cd /Users/khamit/lab-devices-adaptive-bioreactor-tour && python -m pytest -q && python -m mypy && python -m ruff check .`
Expected: all green. Fix any ruff/mypy nits in the test module (type the fixtures like the morbidostat test does).

- [ ] **Step 2: Push and open the PR.**
```bash
git push -u origin feat/adaptive-bioreactor-tour
gh pr create --fill --title "feat(examples): adaptive-bioreactor Studio grand tour"
```
PR body: what it is, the two goals, the feature-coverage summary, and the honest live-run split. End with the Claude Code footer.

- [ ] **Step 3: Wait for CI, then merge.**
Watch `gh pr checks --watch`. On green, `gh pr merge --squash`. If CI fails, read the log, fix on the branch, push, re-watch. Stop and surface only a genuinely blocking failure.

- [ ] **Step 4: Clean up the worktree** once merged: from the primary checkout, `git worktree remove /Users/khamit/lab-devices-adaptive-bioreactor-tour` and delete the branch.

---

## Self-Review

**Spec coverage:** §1 goals → Task 1 (document) + Task 5 (showcase docs). §2 regimes → Task 1 group regime branch + Task 3 per-regime run. §3 timeline → Task 1 Phases 0–4. §4.1 block types → Task 1 + Task 2 pin. §4.2 verbs → Task 1 + Task 2 verb-superset assert. §4.3 group kinds → Task 1 group + Task 2 params/locals pin. §4.4 hard edges → Task 4. §4.5 Studio surfaces → Task 5 walkthrough. §5 deliverables → Tasks 1/2/3/4/5. §6 non-goals → Global Constraints (no source changes). §7 risks → determinism handled in Tasks 3–4 tuning notes.

**Placeholder scan:** the `<...>` markers in Task 1 are all expanded immediately below or in the arm snippets; the `description` prose is the one authored artifact (intentional, house-style, not a placeholder to skip). No TBD/TODO in steps.

**Type consistency:** `load()`, `Answers`, `MAPPING`, `CultureLab`, `FlakyLab`, `_http` names are used identically across Tasks 2–4. Operator-input names in `BASE_ANSWERS` match the `operator_input` blocks in Task 1. The shared accumulator is `dose_budget_ml` (top-level) passed as the group's `budget` binding param — consistent between the group body and Phase 2 aggregate.
