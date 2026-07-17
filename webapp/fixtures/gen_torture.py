#!/usr/bin/env python3
"""Emit ui-audit-torture.json — the boundary-stress fixture (audit design §6.2).

This is NOT a realistic experiment and must never be presented as one. examples/morbidostat.json
is what the audit judges aesthetics on; this doc is what it *measures boundaries* with. Judging
taste on this document produces findings a reader correctly discards ("nobody would do that"),
and the true findings go in the bin with them.

Run:  python3 webapp/fixtures/gen_torture.py
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

OUT = pathlib.Path(__file__).parent / "ui-audit-torture.json"

# --- The boundaries, each one named so it can be tuned -------------------------------------
LONG_NAME = "role_" + "n" * 75                    # 80-char identifier
LONG_STREAM = "stream_" + "s" * 73                # 80-char stream name
LONG_LABEL = "Label that keeps going " * 6        # ~130 chars — the W7 truncate class
LONG_MSG = (
    "Culture temperature has been outside the permitted band for more than five consecutive "
    "cycles; the thermostat may have failed open. Check the heater block and the tube seating "
    "before allowing the run to continue past the next dilution."
)                                                  # ~230 chars
LONG_EXPR = " + ".join(f"mean(od_{i:02d}, last=5)" for i in range(1, 13)) + " > 0.6"  # ~250 chars
LANES = 8                                          # S1 renders parallel as N side-by-side lanes
DEPTH = 8                                          # Canvas indentation stress
N_STREAMS = 32
N_ROLES = 15

PUMPS = [f"pump_{i:02d}" for i in range(1, 7)]
VALVES = [f"valve_{i:02d}" for i in range(1, 6)]
METERS = [f"od_meter_{i:02d}" for i in range(1, 4)]


def cmd(role: str, verb: str, **params: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"device": role, "verb": verb}
    if params:
        body["params"] = params
    return {"command": body}


def meas(role: str, verb: str, into: str, **params: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"device": role, "verb": verb, "into": into}
    if params:
        body["params"] = params
    return {"measure": body}


def every_catalog_verb() -> list[dict[str, Any]]:
    """All 16 verbs at 0.7.0 — one block each, so every generated param form is photographed.

    Verified against lab_devices.experiment.verb_catalog(). If the catalog grows, this list is
    the thing that silently goes stale: torture.test.ts asserts >= 16 as the tripwire.
    """
    return [
        cmd(PUMPS[0], "dispense", volume_ml=1.0, speed_ml_min=2.5,
            direction="forward", drop_suckback_ml=0.05),   # widest form: 4 params
        cmd(PUMPS[1], "rotate", direction="reverse", speed_ml_min=1.0),
        cmd(PUMPS[2], "stop"),                              # zero-param form
        cmd(PUMPS[3], "set_calibration", measured_volume_ml=1.02, ml_per_step=0.001),
        cmd(VALVES[0], "set_position", position=3, rotation="cw"),
        cmd(VALVES[1], "home", position=1),
        cmd(VALVES[2], "configure", default_rotation="ccw", hold_torque=True),
        cmd(VALVES[3], "stop"),
        meas(METERS[0], "measure", into="od_01", include_raw=True),
        meas(METERS[0], "measure_blank", into="blank_01"),
        cmd(METERS[0], "set_led", level=128),
        cmd(METERS[1], "set_thermostat", enabled=True, target_c=37.0),
        cmd(METERS[1], "set_tube_correction", factor=1.02),
        cmd(METERS[2], "calibrate_tube", reference_absorbance=0.5),
        cmd(METERS[2], "stop"),
        cmd(METERS[2], "stop_monitoring"),
    ]


def deep_nest(depth: int) -> dict[str, Any]:
    """serial > loop > parallel > branch > for_each > serial > loop > command, `depth` deep."""
    inner: dict[str, Any] = cmd(PUMPS[0], "stop")
    for i in range(depth):
        if i % 4 == 0:
            inner = {"serial": {"children": [inner]}}
        elif i % 4 == 1:
            inner = {"loop": {"count": 2, "body": [inner]}}
        elif i % 4 == 2:
            inner = {"parallel": {"children": [inner]}}
        else:
            inner = {"branch": {"if": "od_01 > 0.4", "then": [inner]}}
    return {"serial": {"label": f"Nested {depth} deep", "children": [inner]}}


def wide_parallel(lanes: int) -> dict[str, Any]:
    return {
        "parallel": {
            "label": f"{lanes} lanes — S1 says parallelism is spatially visible",
            "children": [
                {"serial": {"label": f"lane {i + 1}", "children": [
                    cmd(PUMPS[i % len(PUMPS)], "dispense", volume_ml=1.0, speed_ml_min=2.0),
                    {"wait": {"duration": "30s"}},
                ]}}
                for i in range(lanes)
            ],
        }
    }


def build() -> dict[str, Any]:
    roles: dict[str, Any] = {}
    for p in PUMPS:
        roles[p] = {"type": "pump"}
    for v in VALVES:
        roles[v] = {"type": "valve"}
    for m in METERS:
        roles[m] = {"type": "densitometer"}
    roles[LONG_NAME] = {"type": "pump"}               # 80-char role name
    assert len(roles) >= N_ROLES, f"need >= {N_ROLES} roles, got {len(roles)}"

    streams: dict[str, Any] = {f"od_{i:02d}": {"units": "AU"} for i in range(1, 13)}
    streams.update({f"blank_{i:02d}": {"units": "AU"} for i in range(1, 4)})
    streams.update({f"c_series_{i:02d}": {"units": "ug/ml"} for i in range(1, 9)})
    streams.update({f"r_series_{i:02d}": {"units": "1/h"} for i in range(1, 9)})
    streams[LONG_STREAM] = {"units": "arbitrary units with a long name"}
    assert len(streams) >= N_STREAMS, f"need >= {N_STREAMS} streams, got {len(streams)}"

    blocks: list[dict[str, Any]] = [
        # --- operator_input, one per type, incl. a prompt long enough to truncate -----------
        {"operator_input": {"name": "cycles", "type": "int", "prompt": LONG_MSG,
                            "min": 1, "max": 999}},
        {"operator_input": {"name": "od_thr", "type": "float", "prompt": "OD threshold",
                            "min": 0.01, "max": 1.0}},
        {"operator_input": {"name": "dry_run", "type": "bool", "prompt": "Dry run?"}},
        {"operator_input": {"name": "mode", "type": "enum", "prompt": "Feedback mode",
                            "choices": ["bang-bang", "proportional", "off",
                                        "a choice label that is really quite long indeed"]}},

        # --- every generated param form ------------------------------------------------------
        {"serial": {"label": "Every catalog verb", "children": every_catalog_verb()}},

        # --- the horizontal-overflow gun -----------------------------------------------------
        wide_parallel(LANES),

        # --- indentation stress ---------------------------------------------------------------
        deep_nest(DEPTH),

        # --- empty containers: bare drop slots -------------------------------------------------
        {"serial": {"label": "Empty serial (bare drop slot)", "children": []}},
        {"loop": {"count": 3, "label": "Empty loop body", "body": []}},

        # --- control leaves, pushed --------------------------------------------------------
        {"compute": {"into": "r_est", "value": LONG_EXPR}},
        {"compute": {"into": "literal_int", "value": 12}},   # coerceValueInput's JSON-number case
        {"record": {"into": "c_series_01", "value": "r_est * 2"}},
        {"abort": {"if": LONG_EXPR, "message": LONG_MSG}},
        {"alarm": {"if": "od_01 > 0.95", "message": LONG_MSG}},

        # --- repetition ------------------------------------------------------------------------
        {"for_each": {"var": "tube", "in": [1, 2, 3],
                      "body": [meas(METERS[0], "measure", into="od_01")]}},
        {"for_each": {"in": [{"tube": 1, "port": 2}, {"tube": 2, "port": 3}],
                      "body": [cmd(VALVES[0], "set_position", position=1)]}},

        # --- group refs, incl. the spaced name --------------------------------------------------
        {"group_ref": {"name": "service", "args": {"tube": 1}}},
        {"group_ref": {"name": "wash cycle", "args": {"port": 2}}},
        {"group_ref": {"name": "long_label_group"}},

        # --- a label long enough to truncate a card --------------------------------------------
        {"wait": {"duration": "1h", "label": LONG_LABEL}},

        # --- DELIBERATE validation errors: ENGINE-level only, not role-level. These fill
        #     ProblemsPanel and must NOT break docToTree. Structure is legal; only the
        #     semantics are wrong, and validation is a backend concern (experiments.py:45 —
        #     "Never 409; no validate_doc gate"). validate_doc (docs_store.py:264) returns
        #     right after role diagnostics, before the engine validate() pass ever runs — so
        #     a single unknown-role reference here would silently suppress every engine
        #     diagnostic below. Measured on this fixture: an unknown-role `command` block
        #     collapses the panel to 1 diagnostic (category `roles`); removing it and keeping
        #     only the undeclared-stream `record` and unknown-binding `branch` yields 33
        #     diagnostics across 4 categories (declaration 1, affinity 2, mode 4, data-flow 26).
        #     Do not add a role-level error back here — it would trade the dense, four-category
        #     panel this fixture exists to produce for a single row.
        {"record": {"into": "stream_that_was_never_declared", "value": 1.0}},
        {"branch": {"if": "no_such_binding > 1", "then": [cmd(PUMPS[0], "stop")]}},
    ]

    groups: dict[str, Any] = {
        "service": {"params": ["tube"], "body": [
            cmd(PUMPS[0], "dispense", volume_ml=1.0, speed_ml_min=2.0),
            {"wait": {"duration": "10s"}},
        ]},
        # The W9 compound-path trap: a space inside a structural token. repr() puts no
        # restriction on group names and import never enforces one — GROUP_NAME_RE guards only
        # addGroup/renameGroup. Compound + bare + spaced fails closed, by documented design.
        "wash cycle": {"params": ["port"], "body": [
            cmd(VALVES[0], "set_position", position=1),
            cmd(PUMPS[1], "dispense", volume_ml=5.0, speed_ml_min=5.0),
        ]},
        "long_label_group": {"body": [{"wait": {"duration": "5s", "label": LONG_LABEL}}]},
        "empty_body_group": {"body": []},
        "deep_group": {"params": ["a", "b", "c", "d", "e"], "body": [deep_nest(4)]},
    }
    assert len(groups) >= 5, f"need >= 5 groups, got {len(groups)}"

    return {
        "doc_version": 1,
        "name": "UI audit torture",
        "description": (
            "Boundary-stress fixture for the UI audit (design 2026-07-17 §6.2). NOT a runnable "
            "experiment and NOT a design reference — it deliberately contains invalid stream and "
            "binding references so ProblemsPanel has something to render. Regenerate with "
            "`python3 webapp/fixtures/gen_torture.py`."
        ),
        "roles": roles,
        "workflow": {
            "schema_version": 1,
            "metadata": {"author": "ui-audit", "description": "torture"},
            "streams": streams,
            "groups": groups,
            "blocks": blocks,
        },
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")
