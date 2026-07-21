#!/usr/bin/env python3
"""Emit ui-audit-run.json — the one seeded doc that can actually start and finish a run.

Neither of the other two seeded docs can. examples/morbidostat.json declares roles of device
types FakeLab's dev registry (webapp/backend/tests/runsupport.py: exactly one pump, pump_1,
and one densitometer, densitometer_1 -- no valve) doesn't provide, so its valve rows can never
be mapped and Start stays disabled forever. ui-audit-torture.json (gen_torture.py) fails
validation by design -- it plants 33 diagnostics on purpose, and Start requires `clean`.
Without a third, minimal, *runnable* doc, the Run tab's post-preflight states (running,
operator input, paused, finished) and the Records viewer (which needs at least one completed
run with data) are unreachable in the UI audit.

Role names `feed`/`meter` are not required by the engine, but they match the pair the backend
test-suite already uses everywhere else (tests/runsupport.py's MAPPING, devserver.py's
docstring) -- a maintainer chasing a Run-tab bug against this fixture is chasing the same
names as every other backend test, not a fresh pair invented just for this file.

Run:  python3 webapp/fixtures/gen_run.py
Verify it validates clean:
  cd webapp/backend && .venv/bin/python -c "
  import json
  from experiment_studio.docs_store import validate_doc, ExperimentDoc
  d = validate_doc(ExperimentDoc.model_validate(json.load(open('../fixtures/ui-audit-run.json'))))
  print(d); assert d == [], f'run fixture must validate clean, got {len(d)}'
  print('OK')"
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

# Reuse gen_torture.py's `cmd`/`meas` instead of re-typing the same block shape here — both
# scripts live in this directory and both are plain, uncompiled entry points (each guarded by
# `if __name__ == "__main__":`), so importing gen_torture's module-level helpers for their
# side-effect-free definitions is safe: it does not run gen_torture's `build()` or write its
# fixture. Python puts a script's own directory on sys.path first, so this import resolves
# regardless of the caller's cwd (e.g. `python3 webapp/fixtures/gen_run.py` from the repo
# root). Keeping one definition means the two scripts cannot drift if the block shape changes.
from gen_torture import cmd, meas

OUT = pathlib.Path(__file__).parent / "ui-audit-run.json"


def cycle(wait_s: str) -> list[dict[str, Any]]:
    return [
        cmd("feed", "dispense", volume_ml=1.0),
        meas("meter", "measure", into="od"),
        {"wait": {"duration": wait_s}},
    ]


def build() -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [
        {
            "serial": {
                "children": [
                    *cycle("2s"),
                    *cycle("2s"),
                    *cycle("2s"),
                    # An operator_input mid-run so the Run tab's InputDialog state (blocking
                    # modal, .fixed.inset-0 with no role="dialog") is actually reachable --
                    # neither examples/morbidostat.json nor the torture doc can ever get here
                    # since neither can start a run at all.
                    {
                        "operator_input": {
                            "name": "cycles",
                            "type": "int",
                            "prompt": "How many more cycles?",
                            "min": 1,
                            "max": 5,
                        }
                    },
                    *cycle("1s"),
                ]
            }
        },
    ]
    return {
        "doc_version": 1,
        "name": "UI audit run",
        "description": (
            "Minimal runnable fixture (design 2026-07-17 addendum): the only seeded doc that "
            "both validates clean and completes a run against the devserver's FakeLab, so the "
            "Run tab's post-preflight states and the Records viewer are reachable. NOT a "
            "realistic experiment. Regenerate with `python3 webapp/fixtures/gen_run.py`."
        ),
        "workflow": {
            "schema_version": 2,
            "metadata": {"name": "UI audit run"},
            "persistence": {"default": "in_memory", "format": "jsonl"},
            "roles": {"feed": {"type": "pump"}, "meter": {"type": "densitometer"}},
            "streams": {"od": {"units": "AU"}},
            "blocks": blocks,
        },
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")
