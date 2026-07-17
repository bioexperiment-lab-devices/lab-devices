# Experiment Studio UI Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a triaged, evidence-backed report of every visual defect in Experiment Studio 0.7.0, plus a committed fixture and a proven probe that make the audit repeatable.

**Architecture:** Two tracks. **Track A** is a DOM probe that reports boundary defects mechanically (clipped overflow, truncate-without-title, contrast, tiny targets) — no taste involved. **Track B** is screenshot judgment against a written rubric, fanned out to subagents and filtered by an adversarial skeptic pass. Two fixtures keep them honest: `morbidostat.json` (realistic) feeds judgment, a new torture doc feeds the probe. The audit changes no UI code.

**Tech Stack:** playwright + chromium (scratchpad only, per D3), Python 3 stdlib (fixture generator), vitest 4 (fixture regression guard), the existing `webapp/backend/tests/devserver.py` FakeLab + `npm run dev`.

**Spec:** `docs/superpowers/specs/2026-07-17-experiment-studio-ui-audit-design.md`. Read §3 (settled decisions), §5 (the two tracks), §6 (fixtures), §8 (the settled list) before starting.

## Global Constraints

- **Branch:** `feat/experiment-studio-ui-audit` (exists; spec committed at `7cf1fe7`). Never commit to `main` — it is ruleset-protected.
- **No UI code changes.** D4: this plan ends at a report. If you find a defect, you write it down; you do not fix it. A fix in this branch is a plan violation.
- **Target version is 0.7.0.** Local `main` and preprod are both 0.7.0. Re-assert `GET /studio/api/health` → `{"status":"ok","library":"0.7.0","studio":"0.7.0"}` before any preprod capture. A stale preprod audits an app that no longer exists, and it fails silently.
- **Scratchpad root:** `/private/tmp/claude-501/-Users-khamit-lab-devices/c94adfa3-b6a0-4098-a56e-3af8cbc5134c/scratchpad/uiaudit`. Referred to below as `$SP`.
- **Committed artifacts, exhaustively:** `webapp/fixtures/gen_torture.py`, `webapp/fixtures/ui-audit-torture.json`, `webapp/frontend/src/builder/__tests__/torture.test.ts`, `docs/ui-audit/2026-07-17.md`, `docs/ui-audit/2026-07-17/*.png` (cited screenshots only), `docs/ui-audit/2026-07-17/probe.json`. Everything else is scratchpad.
- **playwright never enters `webapp/frontend/package.json`** (D3). It is installed in `$SP` only.
- **Viewports:** probes at 1024×720, 1280×800, 1920×1080. Screenshots at 1440×900.
- **Preprod:** `https://111.88.145.138/studio/` — trailing slash is load-bearing (W6 relative-URL scheme). Self-signed cert → playwright `ignoreHTTPSErrors: true`, curl `-k`.
- **Preprod auth** is siteapp's portal, **not** Authelia's own. `POST /api/auth/firstfactor` with `{"username","password","targetURL":"/studio/","keepMeLoggedIn":true}`. Hitting `/api/firstfactor` returns **200 with portal HTML** — a success-shaped failure.

### D3 refinement (adopted by this plan)

The spec says "fixture committed, script scratchpad". A ~1,500-line hand-written JSON blob is
unmaintainable and unreviewable, so the fixture is committed **as a generator plus its output**:
`webapp/fixtures/gen_torture.py` (Python 3 stdlib, zero deps) emits
`webapp/fixtures/ui-audit-torture.json`, and both are committed. This does not violate D3's
intent, which was to keep a browser download out of the frontend gates.

---

## File Structure

| File | Responsibility |
|---|---|
| `webapp/fixtures/gen_torture.py` | **Create.** Emits the torture doc. Pure stdlib. Every boundary is a named constant so the fixture is tunable. |
| `webapp/fixtures/ui-audit-torture.json` | **Create (generated).** The committed fixture. |
| `webapp/frontend/src/builder/__tests__/torture.test.ts` | **Create.** Regression guard: the fixture converts, and covers all 14 kinds. |
| `$SP/probe.mjs` | Track A rules. Pure in-page function + a `cssPath` helper. |
| `$SP/probe-selftest.html` | Planted violations, one per rule. **The probe's own test.** |
| `$SP/probe-selftest.mjs` | Asserts the probe finds exactly the planted set. |
| `$SP/drive.mjs` | State drivers: navigate/seed/pose the app into each of the ≈42 states. |
| `$SP/capture.mjs` | Runs drivers × viewports; writes screenshots + `probe.json`. |
| `docs/ui-audit/2026-07-17.md` | **Create.** The report. |
| `docs/ui-audit/2026-07-17/` | **Create.** Cited screenshots + `probe.json`. |

---

## Task 1: The torture fixture

**Files:**
- Create: `webapp/fixtures/gen_torture.py`
- Create (generated): `webapp/fixtures/ui-audit-torture.json`
- Test: `webapp/frontend/src/builder/__tests__/torture.test.ts`

**Interfaces:**
- Consumes: `docToTree` / `DocConvertError` from `../convert` (`convert.ts:67`, `:58`); `ExperimentDocJson` from `../../types/doc`.
- Produces: `webapp/fixtures/ui-audit-torture.json` — an `ExperimentDocJson` named `"UI audit torture"`. Tasks 3–5 seed it via `POST /api/experiments/import`.

**Why this task is first and gates everything:** if `docToTree` throws on the fixture, the
Builder renders the W7 §7 note and the capture pass photographs 25 screenshots of an error card.
Nothing is captured until this test is green **and** the doc has been seen rendering in a real
browser (Step 7).

### The 14 kinds

`BuilderTab.tsx`'s `STRUCTURE_TITLES` lists 12, but that is the *palette* set. `tree.ts:26-117`
defines **fourteen** `BlockNode` kinds. The two extras — `command` and `measure` — come from the
verb palette via `newVerbNode` (`tree.ts:382`), are the most common blocks in any real
experiment, and have Inspector forms **generated from the verb registry** (S1). That generated
form is the least-reviewed layout in the app, so the fixture carries **all 16 catalog verbs**,
not a sample.

**The exact catalog at 0.7.0**, dumped from `lab_devices.experiment.verb_catalog()` — do not
guess these, and do not trust a signature you remember. Three device types, 16 verbs. `?` marks
an optional param. Widest form is `pump.dispense` (4 params); the zero-param forms
(`pump.stop`, `valve.stop`, `densitometer.measure_blank`, …) matter too — an empty generated
form is its own layout case.

```
pump.dispense(volume_ml:number, speed_ml_min:number?, direction:string?, drop_suckback_ml:number?)
pump.rotate(direction:string, speed_ml_min:number)
pump.stop()
pump.set_calibration(measured_volume_ml:number?, ml_per_step:number?)
valve.set_position(position:int, rotation:string?)
valve.home(position:int)
valve.configure(default_rotation:string?, hold_torque:bool?)
valve.stop()
densitometer.measure(include_raw:bool?)                      kind=measure
densitometer.measure_blank()                                 kind=measure
densitometer.set_led(level:int)
densitometer.set_thermostat(enabled:bool, target_c:number?)
densitometer.set_tube_correction(factor:number)              -- NOT (tube, factor)
densitometer.calibrate_tube(reference_absorbance:number)     -- NOT (tube)
densitometer.stop()
densitometer.stop_monitoring()
```

Only `measure` and `measure_blank` are `kind=measure` (they take `into`); the other 14 are
`kind=command`. Re-dump the catalog if anything below fails to import — the two commented lines
are signatures that were guessed wrong once already.

- [ ] **Step 1: Write the failing test**

Create `webapp/frontend/src/builder/__tests__/torture.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { docToTree } from '../convert'
import { childSlots } from '../tree'
import type { BlockNode } from '../tree'
import type { ExperimentDocJson } from '../../types/doc'

const FIXTURE = fileURLToPath(
  new URL('../../../../fixtures/ui-audit-torture.json', import.meta.url),
)

/** Every BlockNode kind in tree.ts:26-117. The audit's Inspector matrix is one state per
 * entry (design §7), so a fixture missing a kind silently shrinks the audit. */
const ALL_KINDS = [
  'command', 'measure', 'operator_input', 'wait', 'serial', 'parallel', 'loop',
  'branch', 'for_each', 'group_ref', 'compute', 'record', 'abort', 'alarm',
] as const

/** Walks via the app's own `childSlots` (tree.ts:157) rather than a hand-listed slot set.
 * A local list of ['children','body','then','else'] would silently stop descending the day a
 * new container kind lands — and a walker that quietly visits less is exactly how a fixture
 * "covers all 14 kinds" while covering twelve. */
function collectKinds(nodes: BlockNode[], acc: Set<string>): Set<string> {
  for (const n of nodes) {
    acc.add(n.kind)
    for (const [, slot] of childSlots(n)) collectKinds(slot, acc)
  }
  return acc
}

describe('ui-audit torture fixture', () => {
  const doc = JSON.parse(readFileSync(FIXTURE, 'utf8')) as ExperimentDocJson

  it('converts without throwing — the audit is blind if it does not', () => {
    expect(() => docToTree(doc)).not.toThrow()
  })

  it('covers all 14 block kinds across main + groups', () => {
    const content = docToTree(doc)
    const seen = collectKinds(content.tree, new Set<string>())
    // `groups` is OPTIONAL on DocContent (convert.ts:55) even though docToTree always
    // populates it — the `?? {}` is required under strict mode, not defensive noise.
    for (const g of Object.values(content.groups ?? {})) collectKinds(g.body, seen)
    expect([...ALL_KINDS].filter((k) => !seen.has(k))).toEqual([])
  })

  it('carries every catalog verb so every generated param form is photographed', () => {
    const content = docToTree(doc)
    const verbs = new Set<string>()
    const walk = (nodes: BlockNode[]) => {
      for (const n of nodes) {
        if (n.kind === 'command' || n.kind === 'measure') verbs.add(`${n.device}.${n.verb}`)
        for (const [, slot] of childSlots(n)) walk(slot)
      }
    }
    walk(content.tree)
    for (const g of Object.values(content.groups ?? {})) walk(g.body)
    expect(verbs.size).toBeGreaterThanOrEqual(16)
  })

  it('plants the boundary cases the probe exists to catch', () => {
    const content = docToTree(doc)
    const groups = content.groups ?? {}
    expect(Object.keys(content.streams).length).toBeGreaterThanOrEqual(30)
    expect(Object.keys(content.roles).length).toBeGreaterThanOrEqual(15)
    expect(Object.keys(groups).length).toBeGreaterThanOrEqual(5)
    // The W9 compound-path trap: repr() puts no restriction on group names and import never
    // enforces one (GROUP_NAME_RE guards only addGroup/renameGroup).
    expect(Object.keys(groups).some((n) => n.includes(' '))).toBe(true)
  })
})
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd webapp/frontend && npm test -- --run torture
```

Expected: FAIL — `ENOENT: no such file or directory ... ui-audit-torture.json`.

- [ ] **Step 3: Write the generator**

Create `webapp/fixtures/gen_torture.py`:

```python
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

        # --- DELIBERATE validation errors: these fill ProblemsPanel and must NOT break
        #     docToTree. Structure is legal; only the semantics are wrong, and validation is a
        #     backend concern (experiments.py:45 — "Never 409; no validate_doc gate").
        cmd("role_that_does_not_exist", "dispense", volume_ml=1.0),
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
            "experiment and NOT a design reference — it deliberately contains invalid role and "
            "stream references so ProblemsPanel has something to render. Regenerate with "
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
```

- [ ] **Step 4: Generate and run the test**

```bash
python3 webapp/fixtures/gen_torture.py
cd webapp/frontend && npm test -- --run torture
```

Expected: PASS, 4 tests.

**If `docToTree` throws:** do **not** weaken the test. Read the `DocConvertError` message — it
names the unsupported construct. Either the fixture used a shape the Builder genuinely cannot
open (fix the fixture), or you found an **S1 finding before the audit even started** (write it
down in `$SP/findings-early.md` and simplify that one block so the rest can be captured).

- [ ] **Step 5: Verify the backend accepts it**

```bash
cd webapp/backend && .venv/bin/python tests/devserver.py &   # :8000
curl -s -X POST localhost:8000/api/experiments/import \
     -H 'Content-Type: application/json' \
     -d @../fixtures/ui-audit-torture.json -w '\n%{http_code}\n'
```

Expected: `201` and a minted id. Import never 409s and has no `validate_doc` gate, so the
deliberate errors are fine here **by design** (parent §4.3).

- [ ] **Step 6: Run the frontend gates**

```bash
cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run
```

Expected: exit 0 (2 known oxlint fast-refresh warnings are pre-existing and do not fail).

- [ ] **Step 7: Prove it renders in a real browser — the actual gate**

A pure `docToTree` test proves **nothing** about what the Builder does. W9 paid for this lesson
twice: a byte-perfect pure round-trip coexisted with Save silently deleting the flagship's
`groups.service` body, and a green 170-test suite gave zero signal. `docToTree` bypasses the
store; the UI goes through `loadDoc` → `selectDoc`.

```bash
cd $SP && npm init -y && npm i playwright && npx playwright install chromium
```

`$SP/prove-fixture.mjs`:

```js
import { chromium } from 'playwright'

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://localhost:5173/')
await p.getByRole('button', { name: 'Builder' }).click()
await p.getByRole('button', { name: /load/i }).click()
await p.getByText('UI audit torture').click()

// The failure this exists to catch: the W7 §7 emerald note instead of a block tree.
const note = await p.getByText(/can't open in the builder/i).count()
if (note) throw new Error('fixture does not open — audit would photograph an error card')

// Canvas.tsx has NO data-* attributes; a block card is identified by its drag handle
// (`className="flex cursor-grab items-center gap-1 px-2 py-1"`, Canvas.tsx:186). Adding a
// data-testid would be a UI code change and D4 forbids it, so selectors stay structural.
const cards = await p.locator('.cursor-grab').count()
console.log('rendered blocks:', cards)
if (cards < 20) throw new Error(`expected a dense tree, got ${cards} blocks`)

await p.screenshot({ path: 'fixture-proof.png', fullPage: true })
await b.close()
```

```bash
cd webapp/frontend && npm run dev &   # :5173
node $SP/prove-fixture.mjs
```

Expected: prints `rendered blocks: <n≥20>`, writes `fixture-proof.png`. **Open the PNG and look
at it.** If the selectors above do not match the real DOM, fix the script — not the fixture.

- [ ] **Step 8: Commit**

```bash
git add webapp/fixtures/gen_torture.py webapp/fixtures/ui-audit-torture.json \
        webapp/frontend/src/builder/__tests__/torture.test.ts
git commit -m "test(studio): add the UI-audit torture fixture

All 14 BlockNode kinds and all 16 catalog verbs, 8 parallel lanes, 8-deep
nesting, 80-char identifiers, 32 streams, 5 groups including one with a space
in its name (the W9 compound-path trap), empty containers, and deliberate
invalid role/stream refs to populate ProblemsPanel.

Committed as generator + output: a 1500-line hand-written JSON blob is not
reviewable. Guarded by torture.test.ts, which fails if a future convert.ts
change makes the fixture unopenable — which would silently blind the audit."
```

---

## Task 2: The probe, mutation-verified

**Files:**
- Create: `$SP/probe.mjs`, `$SP/probe-selftest.html`, `$SP/probe-selftest.mjs`

**Interfaces:**
- Produces: `probeRules` — an in-page function returning `Violation[]`, where
  `Violation = {rule: string, severity: 'violation'|'suspicion', selector: string, text: string, detail: object}`.
  Task 4 calls it via `page.evaluate(probeRules)` and stamps `state` + `viewport` onto each row.

**Why the self-test is not optional.** An untested probe that reports zero violations is
indistinguishable from a working app, and it is *more* dangerous than no probe because it
launders "I didn't look" into "I looked and it was clean". This repo has already paid for that
lesson: `abort-tests-must-be-mutation-verified` records four vacuous tests shipped in one
increment. **The probe must be proven to find a known-planted bug before its silence means
anything.**

- [ ] **Step 1: Write the planted-violation page**

`$SP/probe-selftest.html` — one deliberate instance per rule, and traps that must **not** fire:

```html
<!doctype html>
<meta charset="utf-8">
<style>
  body { margin: 0; font: 16px system-ui; }
  .box { width: 120px; }
  #clipped { overflow: hidden; white-space: nowrap; }
  #trunc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #trunc-ok { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #scrolls { overflow-x: auto; white-space: nowrap; }
  #faint { color: #bbb; background: #fff; }
  #ok-contrast { color: #111; background: #fff; }
  #zero { width: 0; height: 0; padding: 0; border: 0; }
  #tiny { width: 12px; height: 12px; padding: 0; }
  #big { width: 40px; height: 40px; }
  #over-a, #over-b { position: absolute; top: 300px; width: 100px; height: 40px; }
  #over-a { left: 0; } #over-b { left: 60px; }
  #wide { width: 3000px; height: 10px; background: #eee; }
</style>

<!-- clipped-overflow: content unreachable -->
<div class="box" id="clipped">This text is far too wide for its hidden-overflow box</div>

<!-- truncate-no-title: the W7 bug -->
<div class="box" id="trunc">This ellipsised text has no title attribute at all</div>

<!-- must NOT fire: same truncation, but recoverable -->
<div class="box" id="trunc-ok" title="full text">This ellipsised text does have a title</div>

<!-- unexpected-scroll: suspicion, not violation -->
<div class="box" id="scrolls">This text is wide but its box scrolls on purpose</div>

<!-- low-contrast -->
<div id="faint">Faint grey on white</div>
<div id="ok-contrast">Near-black on white</div>

<!-- controls -->
<button id="zero">zero</button>
<button id="tiny">t</button>
<button id="big">ok</button>

<!-- overlap -->
<button id="over-a">A</button>
<button id="over-b">B</button>

<!-- must NOT fire: dialog overlaps are deliberate -->
<div role="dialog">
  <button id="dlg-a" style="position:absolute;top:400px;left:0;width:100px;height:40px">A</button>
  <button id="dlg-b" style="position:absolute;top:400px;left:60px;width:100px;height:40px">B</button>
</div>

<!-- page-h-scroll -->
<div id="wide"></div>
```

- [ ] **Step 2: Write the self-test to assert the expected set**

`$SP/probe-selftest.mjs`:

```js
import { chromium } from 'playwright'
import { probeRules } from './probe.mjs'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 800, height: 600 } })
await p.goto('file://' + fileURLToPath(new URL('./probe-selftest.html', import.meta.url)))

const found = await p.evaluate(probeRules)
const by = (r) => found.filter((v) => v.rule === r).map((v) => v.selector)

// Every rule must fire on its plant.
assert.ok(by('page-h-scroll').length === 1, 'page-h-scroll missed the 3000px child')
assert.ok(by('clipped-overflow').some((s) => s.includes('clipped')), 'clipped-overflow missed')
assert.ok(by('truncate-no-title').some((s) => s.includes('trunc')), 'truncate-no-title missed')
assert.ok(by('low-contrast').some((s) => s.includes('faint')), 'low-contrast missed #faint')
assert.ok(by('zero-area-control').some((s) => s.includes('zero')), 'zero-area-control missed')
assert.ok(by('tiny-target').some((s) => s.includes('tiny')), 'tiny-target missed')
assert.ok(by('unexpected-scroll').some((s) => s.includes('scrolls')), 'unexpected-scroll missed')
assert.ok(by('overlap').length >= 1, 'overlap missed the A/B pair')

// And the false-positive traps must stay silent. These assertions are the point of the file:
// a probe that cries wolf stops being read, which is the same as having no probe.
assert.ok(!by('truncate-no-title').some((s) => s.includes('trunc-ok')),
  'FALSE POSITIVE: flagged truncation that has a title')
assert.ok(!by('clipped-overflow').some((s) => s.includes('scrolls')),
  'FALSE POSITIVE: overflow:auto reported as a clip')
assert.ok(!by('low-contrast').some((s) => s.includes('ok-contrast')),
  'FALSE POSITIVE: flagged near-black on white')
assert.ok(!by('tiny-target').some((s) => s.includes('big')),
  'FALSE POSITIVE: flagged a 40px button')
assert.ok(!by('overlap').some((s) => s.includes('dlg-')),
  'FALSE POSITIVE: flagged a deliberate dialog overlay')

// Severity split (design §5.1): auto-scroll and small targets are judgment calls, not verdicts.
for (const v of found) {
  const expected = ['unexpected-scroll', 'tiny-target'].includes(v.rule) ? 'suspicion' : 'violation'
  assert.equal(v.severity, expected, `${v.rule} has the wrong severity`)
}

console.log(`probe self-test OK — ${found.length} violations, no false positives`)
await b.close()
```

- [ ] **Step 3: Run it to verify it fails**

```bash
cd $SP && node probe-selftest.mjs
```

Expected: FAIL — `Cannot find module './probe.mjs'`.

- [ ] **Step 4: Write the probe**

`$SP/probe.mjs`:

```js
/** Track A rules — audit design §5.1. Runs in-page via page.evaluate.
 * Returns Violation[] = {rule, severity, selector, text, detail}. */
export function probeRules() {
  const out = []
  const push = (rule, severity, el, detail) =>
    out.push({
      rule, severity, selector: cssPath(el),
      text: (el.textContent || '').trim().slice(0, 120), detail,
    })

  function cssPath(el) {
    if (el === document.documentElement) return 'html'
    const parts = []
    for (let e = el; e && e.nodeType === 1 && parts.length < 5; e = e.parentElement) {
      let s = e.tagName.toLowerCase()
      if (e.id) { parts.unshift(`${s}#${e.id}`); break }
      const cls = (e.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 3)
      if (cls.length) s += '.' + cls.join('.')
      const sibs = e.parentElement ? [...e.parentElement.children].filter((c) => c.tagName === e.tagName) : []
      if (sibs.length > 1) s += `:nth-of-type(${sibs.indexOf(e) + 1})`
      parts.unshift(s)
    }
    return parts.join(' > ')
  }

  const visible = (el) => {
    const s = getComputedStyle(el)
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0'
  }

  const INTERACTIVE = 'button, a[href], input, select, textarea, [role="button"], [tabindex]'
  const inDialog = (el) => !!el.closest('[role="dialog"], [data-dnd-overlay]')
  const dialogOpen = !!document.querySelector('[role="dialog"]')

  // --- rule: page-h-scroll ------------------------------------------------------------------
  // A desktop app should never scroll its own body sideways.
  if (document.documentElement.scrollWidth > window.innerWidth + 1) {
    const culprit = [...document.querySelectorAll('*')].find(
      (e) => visible(e) && e.getBoundingClientRect().right > window.innerWidth + 1,
    )
    push('page-h-scroll', 'violation', culprit || document.documentElement, {
      scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    })
  }

  for (const el of document.querySelectorAll('*')) {
    if (!visible(el)) continue
    const s = getComputedStyle(el)
    const overflowsX = el.scrollWidth > el.clientWidth + 1
    const overflowsY = el.scrollHeight > el.clientHeight + 1

    // --- rule: clipped-overflow / unexpected-scroll ------------------------------------------
    // hidden|clip => content is unreachable, a fact. auto|scroll => intended (S1's parallel
    // lanes are SUPPOSED to scroll), so it is a suspicion for judgment, never a verdict.
    for (const [axis, overflows] of [['x', overflowsX], ['y', overflowsY]]) {
      if (!overflows) continue
      const mode = s[`overflow${axis.toUpperCase()}`]
      if (mode === 'hidden' || mode === 'clip') {
        // text-overflow:ellipsis is a deliberate, *labelled* clip — handled by its own rule.
        if (s.textOverflow !== 'ellipsis') {
          push('clipped-overflow', 'violation', el, {
            axis, mode, scroll: el[axis === 'x' ? 'scrollWidth' : 'scrollHeight'],
            client: el[axis === 'x' ? 'clientWidth' : 'clientHeight'],
          })
        }
      } else if (mode === 'auto' || mode === 'scroll') {
        push('unexpected-scroll', 'suspicion', el, { axis, mode })
      }
    }

    // --- rule: truncate-no-title -------------------------------------------------------------
    // The W7 bug, exactly: a truncated string with no way to recover the full text.
    if (s.textOverflow === 'ellipsis' && overflowsX &&
        !el.getAttribute('title') && !el.getAttribute('aria-label')) {
      push('truncate-no-title', 'violation', el, { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth })
    }

    // --- rule: low-contrast ------------------------------------------------------------------
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
    if (own) {
      const fg = parseRGB(s.color)
      const bg = effectiveBg(el)
      if (fg && bg) {
        const ratio = contrast(fg, bg.rgb)
        const px = parseFloat(s.fontSize)
        const large = px >= 18.66 || (px >= 14 && parseInt(s.fontWeight, 10) >= 700)
        const min = large ? 3.0 : 4.5
        if (ratio < min) {
          // An image background cannot be resolved to a single colour — downgrade rather
          // than assert something we cannot actually measure.
          push('low-contrast', bg.image ? 'suspicion' : 'violation', el,
            { ratio: +ratio.toFixed(2), min, fontSize: px, color: s.color, bg: bg.css })
        }
      }
    }
  }

  // --- rules: zero-area-control / tiny-target ------------------------------------------------
  const controls = [...document.querySelectorAll(INTERACTIVE)].filter(visible)
  for (const el of controls) {
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) {
      push('zero-area-control', 'violation', el, { width: r.width, height: r.height })
    } else if (r.width < 24 || r.height < 24) {
      // A 20px icon button in a dense inspector may be a considered trade-off. Suspicion.
      push('tiny-target', 'suspicion', el, { width: +r.width.toFixed(1), height: +r.height.toFixed(1) })
    }
  }

  // --- rule: overlap --------------------------------------------------------------------------
  // Skipped entirely while a dialog is open, and dialog/drag-overlay members are excluded:
  // deliberate overlays are the whole point of an overlay.
  if (!dialogOpen) {
    const rects = controls.filter((el) => !inDialog(el))
      .map((el) => [el, el.getBoundingClientRect()])
      .filter(([, r]) => r.width > 0 && r.height > 0)
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const [ea, a] = rects[i], [eb, b] = rects[j]
        if (ea.contains(eb) || eb.contains(ea)) continue   // nesting is not overlap
        const w = Math.min(a.right, b.right) - Math.max(a.left, b.left)
        const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)
        if (w <= 0 || h <= 0) continue
        const smaller = Math.min(a.width * a.height, b.width * b.height)
        if ((w * h) / smaller > 0.25) {
          push('overlap', 'violation', ea, { with: cssPath(eb), overlapPct: +((w * h) / smaller * 100).toFixed(0) })
        }
      }
    }
  }

  // --- colour helpers ---------------------------------------------------------------------------
  function parseRGB(css) {
    const m = /rgba?\(([^)]+)\)/.exec(css || '')
    if (!m) return null
    const [r, g, b, a] = m[1].split(',').map((x) => parseFloat(x))
    return a === 0 ? null : [r, g, b]
  }
  function effectiveBg(el) {
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e)
      if (s.backgroundImage && s.backgroundImage !== 'none') {
        const rgb = parseRGB(s.backgroundColor) || [255, 255, 255]
        return { rgb, css: s.backgroundImage, image: true }
      }
      const rgb = parseRGB(s.backgroundColor)
      if (rgb) return { rgb, css: s.backgroundColor, image: false }
    }
    return { rgb: [255, 255, 255], css: 'assumed white', image: false }
  }
  function lum([r, g, b]) {
    const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4 }
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  function contrast(a, b) {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p)
    return (x + 0.05) / (y + 0.05)
  }

  return out
}
```

- [ ] **Step 5: Run the self-test until green**

```bash
cd $SP && node probe-selftest.mjs
```

Expected: `probe self-test OK — <n> violations, no false positives`.

**This is a real TDD cycle — expect to iterate.** Every assertion that fails is telling you the
probe is wrong, not the plant. Do not delete an assertion to get green; that converts the
self-test into the vacuous kind this repo has already shipped once.

- [ ] **Step 6: Mutation-verify the self-test itself**

The self-test can also be vacuous. Prove it fails when the probe is broken:

```bash
# Temporarily break one rule, e.g. change the truncate-no-title condition to `if (false)`.
node probe-selftest.mjs   # MUST fail with 'truncate-no-title missed'
# Revert.
node probe-selftest.mjs   # green again
```

Do this for at least `truncate-no-title` and `clipped-overflow`. If breaking a rule does not
turn the self-test red, the self-test is decoration.

---

## Task 3: The capture harness

**Files:**
- Create: `$SP/drive.mjs`, `$SP/capture.mjs`

**Interfaces:**
- Consumes: `probeRules` from `./probe.mjs`; the seeded fixture id from Task 1.
- Produces: `STATES` — `Array<{id: string, tab: string, setup: (page) => Promise<void>}>`, one
  entry per state in design §7. `capture.mjs` writes `$SP/out/<state>@<viewport>.png` and
  `$SP/out/probe.json`.

- [ ] **Step 1: Start the local stack and seed both fixtures**

```bash
cd webapp/backend && .venv/bin/python tests/devserver.py &        # :8000 FakeLab
cd webapp/frontend && npm run dev &                                # :5173
curl -s -X POST localhost:8000/api/experiments/import -H 'Content-Type: application/json' \
     -d @webapp/fixtures/ui-audit-torture.json
curl -s -X POST localhost:8000/api/experiments/import -H 'Content-Type: application/json' \
     -d @examples/morbidostat.json
curl -s localhost:8000/api/experiments | python3 -m json.tool     # note both ids
```

- [ ] **Step 2: Write the state drivers**

`$SP/drive.mjs`. Each entry poses the app and returns; `capture.mjs` does the shooting.

```js
export const BASE = process.env.STUDIO_BASE || 'http://localhost:5173/'

const tab = (p, name) => p.getByRole('button', { name: new RegExp(`^\\d?\\s*${name}$`, 'i') }).click()

async function openDoc(p, name) {
  await tab(p, 'Builder')
  await p.getByRole('button', { name: /load/i }).click()
  await p.getByText(name, { exact: false }).click()
  await p.waitForTimeout(300)
}

/** No data-* attributes exist in Canvas.tsx and D4 forbids adding any, so a card is located by
 * its drag handle (`.cursor-grab`, Canvas.tsx:186) and identified by its `blockSummary` text
 * (`<span className="truncate">`, Canvas.tsx:198). NOTE that span is truncate-with-no-title —
 * at narrow viewports its text may be ellipsised, and `hasText` matches the DOM text, not the
 * painted text, so this keeps working. If a selector misses, fix the driver, never the app. */
const CARD = '.cursor-grab'

async function selectKind(p, kindLabel) {
  await p.locator(CARD).filter({ hasText: kindLabel }).first().click()
  await p.waitForTimeout(150)
}

/** design §7 — ≈42 states. Inspector gets one entry per BlockNode kind (14). */
export const STATES = [
  // --- Devices (4) ---
  { id: 'devices/no-lab', tab: 'Devices', setup: async (p) => { await tab(p, 'Devices') } },
  { id: 'devices/roster', tab: 'Devices', setup: async (p) => {
      await tab(p, 'Devices')
      await p.getByRole('button', { name: /discover/i }).click()
      await p.waitForTimeout(800)
    } },
  { id: 'devices/discovering', tab: 'Devices', setup: async (p) => {
      await tab(p, 'Devices')
      await p.getByRole('button', { name: /discover/i }).click()   // shoot mid-flight
    } },
  { id: 'devices/error', tab: 'Devices', setup: async (p) => {
      await p.route('**/api/labs**', (r) => r.abort('failed'))
      await tab(p, 'Devices')
      await p.reload()
      await p.waitForTimeout(500)
    } },

  // --- Builder (≈28) ---
  { id: 'builder/empty', tab: 'Builder', setup: async (p) => { await tab(p, 'Builder') } },
  { id: 'builder/morbidostat-main', tab: 'Builder', setup: async (p) => openDoc(p, 'Morbidostat') },
  { id: 'builder/morbidostat-group', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'Morbidostat')
      await p.getByRole('combobox').first().selectOption({ label: /service/i })
      await p.waitForTimeout(200)
    } },
  { id: 'builder/torture', tab: 'Builder', setup: async (p) => openDoc(p, 'UI audit torture') },
  { id: 'builder/torture-lanes', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      await p.getByText(/8 lanes/i).scrollIntoViewIfNeeded()
    } },
  { id: 'builder/torture-deep', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      await p.getByText(/Nested 8 deep/i).scrollIntoViewIfNeeded()
    } },
  { id: 'builder/load-dialog', tab: 'Builder', setup: async (p) => {
      await tab(p, 'Builder')
      await p.getByRole('button', { name: /load/i }).click()
    } },
  { id: 'builder/problems', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      await p.waitForTimeout(900)   // let validation land — the fixture plants real errors
    } },
  { id: 'builder/dirty', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      await selectKind(p, 'Wait')
      await p.getByLabel(/label/i).fill('edited — now dirty')
      await p.waitForTimeout(200)
    } },
  { id: 'builder/drag', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      // W3 dnd recipe: pointer down -> 12px jiggle -> glide. Stop mid-drag, do not drop.
      const src = p.locator(CARD).first()
      const box = await src.boundingBox()
      await p.mouse.move(box.x + 20, box.y + 10)
      await p.mouse.down()
      await p.mouse.move(box.x + 32, box.y + 10, { steps: 3 })
      await p.mouse.move(box.x + 120, box.y + 180, { steps: 10 })
    } },
  { id: 'builder/drop-hover', tab: 'Builder', setup: async (p) => {
      // Rubric item 4: is a drop slot *obviously* droppable? Only visible while held over one,
      // so the drag is parked on the empty serial's bare slot and never released.
      await openDoc(p, 'UI audit torture')
      const src = p.locator(CARD).first()
      const sbox = await src.boundingBox()
      // DropSlot renders two variants (DropSlot.tsx): a dashed "drop here" hint box for empty
      // lists, and — between blocks — an 8px BARE DIV that is `bg-transparent` until hovered.
      // The bar has no text, no role, and no data attribute, so it is not addressable and the
      // probe's tiny-target rule cannot see it either (INTERACTIVE won't match a plain div).
      // The fixture's empty serial gives us a hint box to aim at. Log this gap in the report.
      const slot = p.getByText('drop here').first()
      await slot.scrollIntoViewIfNeeded()
      const dbox = await slot.boundingBox()
      await p.mouse.move(sbox.x + 20, sbox.y + 10)
      await p.mouse.down()
      await p.mouse.move(sbox.x + 32, sbox.y + 10, { steps: 3 })
      await p.mouse.move(dbox.x + dbox.width / 2, dbox.y + dbox.height / 2, { steps: 10 })
      await p.waitForTimeout(200)
    } },
  // Palette.tsx renders Structure/Control/Repeat AND RolesPanel (:250) AND StreamsPanel (:253)
  // in one column. With 15 roles and 32 streams that column is long — the panels are only
  // reachable by scrolling, so each gets its own state rather than riding along with the top.
  { id: 'builder/palette', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      await p.getByText('Structure', { exact: true }).scrollIntoViewIfNeeded()
    } },
  { id: 'builder/roles-panel', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      await p.getByText('Roles', { exact: false }).first().scrollIntoViewIfNeeded()
    } },
  { id: 'builder/streams-panel', tab: 'Builder', setup: async (p) => {
      await openDoc(p, 'UI audit torture')
      await p.getByText('Streams', { exact: false }).first().scrollIntoViewIfNeeded()
    } },
  // Inspector: one state per BlockNode kind (tree.ts:26-117).
  ...['Command', 'Measure', 'Operator input', 'Wait', 'Serial', 'Parallel', 'Loop', 'Branch',
      'For each', 'Group ref', 'Compute', 'Record', 'Abort', 'Alarm'].map((k) => ({
    id: `builder/inspector/${k.toLowerCase().replace(/ /g, '-')}`,
    tab: 'Builder',
    setup: async (p) => { await openDoc(p, 'UI audit torture'); await selectKind(p, k) },
  })),

  // --- Run (6) ---
  { id: 'run/preflight-unmapped', tab: 'Run', setup: async (p) => { await tab(p, 'Run') } },
  { id: 'run/preflight-ready', tab: 'Run', setup: async (p) => {
      await tab(p, 'Run')
      for (const s of await p.getByRole('combobox').all()) {
        await s.selectOption({ index: 1 }).catch(() => {})
      }
    } },
  { id: 'run/running', tab: 'Run', setup: async (p) => {
      await tab(p, 'Run')
      await p.getByRole('button', { name: /^start/i }).click()
      await p.waitForTimeout(2500)   // let the live WS chart accumulate points
    } },
  { id: 'run/input-dialog', tab: 'Run', setup: async (p) => {
      await tab(p, 'Run')
      await p.getByRole('button', { name: /^start/i }).click()
      await p.waitForSelector('[role="dialog"]', { timeout: 15000 })
    } },
  { id: 'run/paused', tab: 'Run', setup: async (p) => {
      await tab(p, 'Run')
      await p.getByRole('button', { name: /pause/i }).click()
      await p.waitForTimeout(400)
    } },
  { id: 'run/finished', tab: 'Run', setup: async (p) => {
      await tab(p, 'Run')
      await p.waitForSelector('text=/completed|aborted|failed/i', { timeout: 60000 })
    } },

  // --- Records (4) ---
  { id: 'records/empty', tab: 'Records', setup: async (p) => { await tab(p, 'Records') } },
  { id: 'records/table', tab: 'Records', setup: async (p) => { await tab(p, 'Records') } },
  { id: 'records/viewer', tab: 'Records', setup: async (p) => {
      await tab(p, 'Records')
      await p.locator('tbody tr').first().click()
      await p.waitForTimeout(600)
    } },
  { id: 'records/snapshot', tab: 'Records', setup: async (p) => {
      await tab(p, 'Records')
      await p.locator('tbody tr').first().click()
      await p.getByRole('button', { name: /workflow|snapshot/i }).click()
    } },
]
```

**These selectors are a first draft written from source, not from a running app.** Expect to fix
them against the real DOM. When one does not match, fix the driver — never the app (D4).

- [ ] **Step 3: Write the capture runner**

`$SP/capture.mjs`:

```js
import { chromium } from 'playwright'
import { mkdirSync, writeFileSync } from 'node:fs'
import { probeRules } from './probe.mjs'
import { STATES, BASE } from './drive.mjs'

const PROBE_VIEWPORTS = [[1024, 720], [1280, 800], [1920, 1080]]
const SHOT = [1440, 900]
const OUT = new URL('./out/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const only = process.argv[2]                     // optional: capture one state by id prefix
const states = only ? STATES.filter((s) => s.id.startsWith(only)) : STATES

const browser = await chromium.launch()
const all = []
const failures = []

for (const st of states) {
  // Judgment screenshot at 1440x900 (design D2).
  for (const [w, h] of [SHOT, ...PROBE_VIEWPORTS]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h }, ignoreHTTPSErrors: true })
    const page = await ctx.newPage()
    try {
      await page.goto(BASE)
      await st.setup(page)
      if (w === SHOT[0]) {
        await page.screenshot({ path: `${OUT}${st.id.replace(/\//g, '__')}@${w}x${h}.png`, fullPage: true })
      } else {
        const found = await page.evaluate(probeRules)
        all.push(...found.map((v) => ({ state: st.id, viewport: `${w}x${h}`, ...v })))
      }
    } catch (e) {
      // A driver that throws must be LOUD. A silently skipped state is a state the report
      // implies was audited and was not.
      failures.push({ state: st.id, viewport: `${w}x${h}`, error: String(e).slice(0, 200) })
      console.error(`FAILED ${st.id} @ ${w}x${h}: ${e}`)
    }
    await ctx.close()
  }
  console.log(`captured ${st.id}`)
}

writeFileSync(`${OUT}probe.json`, JSON.stringify({ all, failures }, null, 2))
console.log(`\n${all.length} violations across ${states.length} states; ${failures.length} driver failures`)
if (failures.length) console.log('UNCAPTURED STATES:', failures.map((f) => f.state).join(', '))
await browser.close()
```

- [ ] **Step 4: Smoke one state**

```bash
cd $SP && node capture.mjs builder/torture
```

Expected: one PNG in `$SP/out/`, `probe.json` written, zero driver failures. **Open the PNG.**

---

## Task 4: The local capture run

**Files:** produces `$SP/out/*.png`, `$SP/out/probe.json`

- [ ] **Step 1: Full run**

```bash
cd $SP && node capture.mjs 2>&1 | tee capture.log
```

Expected: ≈42 `captured …` lines, `0 driver failures`.

- [ ] **Step 2: Drive failures to zero**

Any state in `UNCAPTURED STATES` is a hole in the audit. Fix its selectors and re-run **that
state only** (`node capture.mjs <id>`). Do not proceed with a non-empty failure list, and do not
delete a state to make the list empty — if a state is genuinely unreachable, that is itself a
finding and gets written up in Task 8 rather than dropped.

- [ ] **Step 3: Triage the probe output**

```bash
python3 - <<'EOF'
import json, collections
d = json.load(open('out/probe.json'))
c = collections.Counter((v['rule'], v['severity']) for v in d['all'])
for (rule, sev), n in c.most_common():
    print(f'{n:5d}  {sev:10s} {rule}')
print('\nstates with violations:',
      len({v['state'] for v in d['all'] if v['severity'] == 'violation'}))
EOF
```

**Read this before believing it.** Two failure modes:
- **Zero violations everywhere** → suspect the probe, not the app. Task 2 Step 6 proved it can
  fire; re-run the self-test.
- **Thousands of one rule** → a systematic false positive. Fix the rule and add the case to
  `probe-selftest.html`, so it can never regress.

- [ ] **Step 4: Stash the artifacts**

```bash
cd $SP && cp out/probe.json probe-local.json
```

---

## Task 5: Preprod capture

**Files:** produces `$SP/out-preprod/*.png`

Preprod's job is the three things local cannot fake: the **real 7-device roster**, a
**real-hardware run**, and the **`/studio/` sub-path proxy**. Nothing else.

- [ ] **Step 1: Re-assert the version — do not skip this**

```bash
curl -sk -c $SP/c.txt -X POST https://111.88.145.138/api/auth/firstfactor \
  -H 'Content-Type: application/json' \
  -d '{"username":"khamitovdr","password":"U$rKtI3N2M*5*Wg","targetURL":"/studio/","keepMeLoggedIn":true}'
curl -sk -b $SP/c.txt https://111.88.145.138/studio/api/health
```

Expected: `{"status":"ok","library":"0.7.0","studio":"0.7.0"}`.

**If it is not 0.7.0, stop.** A 0.6.0 preprod has no Control palette, no scope switcher, no
`for_each` rendering — you would be auditing an app that no longer exists, and it does not
announce itself. Report the drift and skip this task rather than capturing fiction.

- [ ] **Step 2: Capture the three preprod-only states**

```js
// $SP/preprod.mjs
import { chromium } from 'playwright'
import { probeRules } from './probe.mjs'
import { mkdirSync, writeFileSync } from 'node:fs'

const OUT = new URL('./out-preprod/', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })

const b = await chromium.launch()
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true })
const p = await ctx.newPage()

await p.goto('https://111.88.145.138/login')
await p.getByLabel(/user/i).fill('khamitovdr')
await p.getByLabel(/password/i).fill(process.env.PREPROD_PW)
await p.getByRole('button', { name: /sign in|log in/i }).click()
await p.waitForURL(/\/studio\//, { timeout: 30000 })   // trailing slash is load-bearing (W6)

const health = await p.evaluate(() => fetch('api/health').then((r) => r.json()))
if (health.studio !== '0.7.0') throw new Error(`preprod is ${health.studio}, expected 0.7.0`)

const rows = []
for (const [id, go] of [
  ['devices/real-roster', async () => {
    await p.getByRole('button', { name: /^\d?\s*Devices$/i }).click()
    await p.waitForTimeout(1500)
  }],
  ['records/real', async () => {
    await p.getByRole('button', { name: /^\d?\s*Records$/i }).click()
    await p.waitForTimeout(1000)
  }],
  ['builder/subpath', async () => {
    await p.getByRole('button', { name: /^\d?\s*Builder$/i }).click()
  }],
]) {
  await go()
  await p.screenshot({ path: `${OUT}${id.replace(/\//g, '__')}.png`, fullPage: true })
  rows.push(...(await p.evaluate(probeRules)).map((v) => ({ state: id, viewport: '1440x900', ...v })))
  console.log('captured', id)
}
writeFileSync(`${OUT}probe.json`, JSON.stringify(rows, null, 2))
await b.close()
```

```bash
cd $SP && PREPROD_PW='U$rKtI3N2M*5*Wg' node preprod.mjs
```

- [ ] **Step 3: Compare rosters**

Open `out-preprod/devices__real-roster.png` next to `out/devices__roster@1440x900.png`. Real
device names and types are longer than FakeLab's — anything that fits locally and breaks here is
a finding local capture structurally cannot produce.

---

## Task 6: Review fan-out and skeptic verification

**Files:** produces `$SP/findings-raw.json`, `$SP/findings-verified.json`

- [ ] **Step 1: Fan out one reviewer per component**

Dispatch parallel subagents — one per component group (Toolbar, Palette, Canvas, Inspector,
ProblemsPanel, RolesPanel/StreamsPanel, LoadDialog, DevicesTab, PreflightPanel, RunView/EventLog,
StreamChart, RecordsTable/RecordViewer). Each gets: its screenshots, the `probe.json` rows for
its states, the §5.3 rubric, and the §8 settled list.

Prompt each with:

> Review these screenshots of the <component> component of Experiment Studio against the rubric
> below. Report only defects a competent frontend reviewer would raise in a PR.
>
> RUBRIC: hierarchy (is the primary action obvious?), rhythm (consistent spacing/border/radius on
> Tailwind's scale), alignment (label/field), affordance (is a drop slot obviously droppable? is
> disabled obviously disabled vs just gray?), state legibility (running vs paused vs aborted at a
> glance), error presentation (does colour match severity?), empty states (do they say what to do
> next?), cross-tab consistency.
>
> SETTLED — do NOT report these as defects; they are deliberate: <paste §8 table>.
>
> These screenshots include a deliberately pathological fixture ("UI audit torture"): 80-char
> names, 8 parallel lanes, 32 streams. Do NOT report "the name is too long" as a design defect —
> the fixture made it long on purpose. DO report what the app *does* with it (clips it, overlaps
> a neighbour, pushes a control off-screen).
>
> Return JSON: [{component, state, viewport, screenshot, what, why_it_matters, suggested_fix,
> severity: "S1"|"S2"|"S3"}]. S1 = a user cannot complete the task. S2 = works but confusing at a
> supported viewport. S3 = taste. Return [] if the component is fine — an empty list is a
> perfectly good answer and far better than an invented nitpick.

Collect into `$SP/findings-raw.json`.

- [ ] **Step 2: Skeptic pass**

For each raw finding, dispatch a subagent instructed to **refute** it:

> Here is a claimed UI defect in Experiment Studio, with its screenshot: <finding>.
>
> Your job is to REFUTE it. Look at the screenshot. Check the DOM evidence. Consider: is this
> actually the pathological fixture doing what it was built to do? Is it a settled design
> decision (list below)? Is it invisible to a real user at a supported viewport? Is it taste
> dressed as a defect?
>
> Default to refuted=true when uncertain. A false finding costs the reader more than a missed one
> costs the audit, because a report with three invented nitpicks gets its true findings ignored.
>
> Return {refuted: bool, reason: string, severity_should_be: "S1"|"S2"|"S3"|null}.

Keep survivors in `$SP/findings-verified.json`, with the skeptic's severity when it disagrees.

- [ ] **Step 3: Fold in the mechanical track**

Every `severity: "violation"` probe row is a finding **without** a skeptic pass — it is a
measurement, not an opinion. Map: `clipped-overflow` / `truncate-no-title` / `zero-area-control`
/ `page-h-scroll` → **S1** (content unreachable or unrecoverable); `low-contrast` → **S2**.
Dedup by `(state, selector, rule)`. `suspicion` rows are *not* findings — they were input to
Step 1's judgment and stay there.

---

## Task 7: The settled list, re-examined

**Files:** produces `$SP/settled-verdicts.md`

Spec §8 lists ten settled decisions. Each is **re-examined**, not muted: the list keeps settled
forks out of the main findings, but a mute list is where bad decisions hide.

- [ ] **Step 1: One verdict per item**

For each row of §8, answer its re-examine question against the captured evidence and write:

```markdown
### S1 — Parallel renders as N side-by-side lanes
**Rationale on record:** parallelism is *spatially* visible; Blockly stacks arms vertically.
**Evidence:** `builder__torture-lanes@1024x720.png`, probe rows for `builder/torture-lanes`.
**Verdict:** holds | worth revisiting
**Because:** <what the screenshot actually shows at 8 lanes / 1024px>
```

Cover all ten: S1 lanes, S6 stepper-styled tabs, S5 no-persistence-knobs, P4 no expansion
preview, `for_each` omitted block-level keys, `abort` no On-error row, the ƒ/✎/⚠/⛔ glyph family,
the `∀`/`⧉` cards, the W7 emerald note, `record.into` as a picker.

- [ ] **Step 2: The emerald note needs a genuinely unopenable doc**

W9 made `morbidostat.json` open, so the §7 path is no longer reachable through it — the
mechanism remains for genuinely unopenable docs. Construct one (a doc using a construct
`convert.ts` rejects), import it, and assert the note renders **emerald, not red**:

```js
const cls = await p.locator('text=/can.t open in the builder/i').first()
  .evaluate((el) => el.closest('[class]').className)
console.log(cls)   // MUST contain emerald-*, MUST NOT contain red-*
```

Rendering it red would tell users the flagship example failed to import when it imported fine.
Screenshot it for the report.

---

## Task 8: The report

**Files:**
- Create: `docs/ui-audit/2026-07-17.md`, `docs/ui-audit/2026-07-17/`

- [ ] **Step 1: Copy in the cited evidence only**

```bash
mkdir -p docs/ui-audit/2026-07-17
# For each finding's screenshot:
cp $SP/out/<cited>.png docs/ui-audit/2026-07-17/
cp $SP/out/probe.json docs/ui-audit/2026-07-17/probe.json
```

D5: cited screenshots only. The full ≈126-capture set stays in scratchpad.

- [ ] **Step 2: Write the report**

```markdown
# Experiment Studio — UI audit, 2026-07-17

**Target:** 0.7.0 (`main` @ d3b022f), local devserver + preprod.
**Method:** `docs/superpowers/specs/2026-07-17-experiment-studio-ui-audit-design.md`.
**Coverage:** <n> states × 3 viewports (probe), 1440×900 (judgment). <n> states uncaptured: <list or "none">.

## Summary

| Severity | Count |
|---|---|
| S1 broken | n |
| S2 degraded | n |
| S3 polish | n |

## S1 — broken

### 1. <one-line claim>
**Component:** … **Viewport:** … **Track:** mechanical | judgment
![](2026-07-17/<shot>.png)
**Repro:** …
**What's wrong:** …
**Why it matters:** …
**Suggested fix:** …

## S2 — degraded
…
## S3 — polish
…

## Settled decisions, re-examined
<Task 7 verdicts>

## Coverage gaps
<states not captured; rules not run; anything the method structurally cannot see — §13 of the spec>
```

**Three gaps are known in advance and must appear here rather than being discovered by a reader:**

1. **dnd-kit droppables are invisible to the probe.** `DropSlot`'s between-blocks variant is a
   bare `div` — no role, no tabindex, `bg-transparent` until hovered. The `INTERACTIVE` selector
   cannot match it, so `tiny-target` and `zero-area-control` never evaluate an 8px drop bar.
   Judgment (`builder/drop-hover`) is the only track that sees it.
2. **1440×900 is the sole judgment viewport** (spec §13). A layout that is fine at 1440 and ugly
   at 1600 goes unseen unless a probe flags it.
3. **No baseline.** This finds defects, not regressions.

**Order findings by severity, then by how many states they affect.** A single truncation bug in a
shared component that fires in 12 states outranks a unique one.

- [ ] **Step 3: Verify every claim in the report**

Before committing, re-open each cited screenshot and confirm it shows what the finding says it
shows. A report is a claim about what you saw; the screenshot is the evidence a reader will
check first, and a mismatch there discredits every other finding on the page.

- [ ] **Step 4: Confirm no UI code changed (D4)**

```bash
git status --short
git diff --stat main...HEAD -- webapp/frontend/src webapp/backend/experiment_studio
```

Expected: the second command prints **nothing**. The only `webapp/` changes on this branch are
`webapp/fixtures/*` and `webapp/frontend/src/builder/__tests__/torture.test.ts`.

- [ ] **Step 5: Commit**

```bash
git add docs/ui-audit/
git commit -m "docs: UI audit of Experiment Studio 0.7.0

<n> findings: <n> S1, <n> S2, <n> S3, across <n> states x 3 viewports.
Mechanical track (probe) found <n>; judgment track found <n> after <n> were
refuted by the skeptic pass. Ten settled decisions re-examined: <n> hold,
<n> worth revisiting.

No UI code changed (D4) — fixes are a separate increment."
```

---

## Acceptance (spec §12)

- [ ] `ui-audit-torture.json` imports **and renders** in a real browser — proven before any capture.
- [ ] Probe self-test green, and **mutation-verified**: breaking a rule turns it red.
- [ ] Probes ran across ≈42 states × 3 viewports; `probe.json` committed.
- [ ] `/studio/api/health` re-asserted as 0.7.0 before preprod capture.
- [ ] Every finding: component, viewport, screenshot, repro, why-it-matters, fix, severity.
- [ ] Every judgment finding survived the skeptic pass.
- [ ] Every §8 settled item has a verdict with evidence.
- [ ] Report + cited screenshots + fixture committed; **zero UI code changed**.
- [ ] Uncaptured states are reported as coverage gaps, not silently dropped.
