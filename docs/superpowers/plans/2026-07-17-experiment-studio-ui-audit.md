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

`$SP/probe-selftest.html` — one deliberate instance per rule, plus the traps that must **not**
fire.

**Every plant here exists to make a specific way of getting the probe wrong go red**, and the
comments say which. This matters more than it looks: an earlier version of this page planted
contrast cases as `#bbb` on `#111` — colours a naive `rgb()` regex parses perfectly — and so
sat green over a contrast rule that was *inverted* against the app's actual palette. A plant
that uses colours the app never emits tests nothing. Use the app's real shapes: Tailwind 4
oklch, `bg-black/30` scrims, and bare `fixed inset-0` dialogs.

```html
<!doctype html>
<meta charset="utf-8">
<style>
  body { margin: 0; font: 16px system-ui; }
  .box { width: 120px; }

  /* --- overflow / truncation ------------------------------------------------------------- */
  #clipped   { overflow: hidden; white-space: nowrap; }
  #clipped-y { overflow: hidden; height: 20px; }                 /* wraps, clipped on Y */
  #trunc     { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #trunc-ok  { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #trunc-aria{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  /* truncate + a title, clipped on the BLOCK axis: the ellipsis exemption must not cover Y,
     because truncate-no-title only ever inspects X. Nobody reports this if it does. */
  #trunc-y   { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
               height: 8px; line-height: 20px; }
  #scrolls   { overflow-x: auto; white-space: nowrap; }

  /* --- contrast: plain sRGB ------------------------------------------------------------- */
  #faint { color: #bbb; background: #fff; }
  #ok-contrast { color: #111; background: #fff; }

  /* --- contrast: Tailwind 4's real oklch palette ----------------------------------------- */
  /* Tailwind 4 ships every palette colour as oklch (only white/black stay hex). A regex that
     only understands rgb() reads BOTH of these as null: #oklch-bad goes silent on a genuine
     AA failure, and #oklch-ok gets walked up to body's white and reported as white-on-white. */
  #oklch-bad { color: oklch(0.704 0.04 256.788); background: #fff; }   /* text-slate-400, ~2.6 */
  #oklch-ok  { color: #fff; background: oklch(0.546 0.245 262.881); }  /* bg-blue-600, ~5.25 — legible */

  /* --- contrast: partial alpha ------------------------------------------------------------ */
  /* Treating alpha as opaque reads both of these as 21:1 and stays silent. */
  #alpha-text { color: rgba(0, 0, 0, 0.3); }                     /* over white => ~2.1 */
  #alpha-bg   { color: #fff; background: rgba(0, 0, 0, 0.3); }   /* white on grey => ~2.1 */

  /* --- contrast: image background => suspicion, never a verdict --------------------------- */
  #img-bg { color: #bbb; background-image: linear-gradient(#fff, #fff); }

  /* --- contrast: the WCAG large-text boundary --------------------------------------------- */
  /* All four are #7f7f7f on white == ratio ~4.0, which sits between the 3.0 large-text
     threshold and the 4.5 normal-text one. Large text is >=24px, or >=18.66px bold — those
     are the pt figures (18pt/14pt) converted to px, NOT 18.66px/14px. The two that must FIRE
     catch the swapped thresholds; the two that must stay SILENT catch the large-text rule
     being disabled outright. */
  .g { color: #7f7f7f; background: #fff; }
  #txt-20-normal { font-size: 20px; font-weight: 400; }   /* not large => 4.5 => must fire   */
  #txt-16-bold   { font-size: 16px; font-weight: 700; }   /* not large => 4.5 => must fire   */
  #txt-24-large  { font-size: 24px; font-weight: 400; }   /* large     => 3.0 => must be silent */
  #txt-19-bold   { font-size: 19px; font-weight: 700; }   /* large     => 3.0 => must be silent */

  /* --- controls --------------------------------------------------------------------------- */
  #zero { width: 0; height: 0; padding: 0; border: 0; }
  #tiny { width: 12px; height: 12px; padding: 0; }
  #big  { width: 40px; height: 40px; }
  /* INTERACTIVE breadth: narrowing the selector to `button` must not go unnoticed. */
  #controls-row { display: flex; gap: 8px; align-items: flex-start; }
  #controls-row > * { width: 12px; height: 12px; padding: 0; }
  #tiny-link, #tiny-role, #tiny-tab { display: inline-block; background: #ddd; }

  /* display:none ANCESTOR: `display` is not inherited, so #buried-btn still computes
     display:inline-block and its rect is 0x0 — a fabricated zero-area-control S1. */
  #buried { display: none; }

  /* --- overlap ---------------------------------------------------------------------------- */
  #over-a, #over-b { position: absolute; top: 1200px; width: 100px; height: 40px; }
  #over-a { left: 0; } #over-b { left: 60px; }
  /* opacity:0 ANCESTOR — opacity is not inherited, so the children still compute opacity:1.
     Any fade transition looks exactly like this. Must stay silent. */
  #fade { opacity: 0; }
  #fade-a, #fade-b { position: absolute; top: 1300px; width: 100px; height: 40px; }
  #fade-a { left: 0; } #fade-b { left: 60px; }

  /* --- the app's real dialog markup -------------------------------------------------------- */
  /* run/InputDialog.tsx:101 and builder/LoadDialog.tsx:71 render exactly this: no role="dialog",
     no data-dnd-overlay. The ARIA selectors match nothing, so every dialog state fabricates
     overlap S1s. These are Tailwind 4's actual emitted declarations. */
  .fixed { position: fixed; }
  .inset-0 { inset: 0; }
  .z-20 { z-index: 20; }
  .flex { display: flex; }
  .items-center { align-items: center; }
  .justify-center { justify-content: center; }
  .bg-black\/30 { background-color: oklab(0 0 0 / 0.3); }
  /* Tall enough for two non-overlapping buttons (a/b) AND a second, genuinely overlapping pair
     (c/d) in the same panel — the blanket exclusion tested only "dialog vs page is silent" and
     "dialog vs dialog is ALSO silent" with the SAME pair, which is the bug: those are two
     different guarantees and only the first one is correct. */
  .dlg-panel { position: relative; width: 220px; height: 150px; background: #fff; }
  /* dialog-vs-page silence only: these two do NOT overlap each other. */
  #dlg-a, #dlg-b { position: absolute; left: 0; width: 100px; height: 30px; }
  #dlg-a { top: 10px; } #dlg-b { top: 60px; }
  /* dialog-vs-dialog MUST still fire: two controls colliding inside the SAME overlay. */
  #dlg-c, #dlg-d { position: absolute; top: 110px; width: 100px; height: 30px; }
  #dlg-c { left: 0; } #dlg-d { left: 60px; }

  /* --- must NOT fire: a page control sitting, on screen, exactly where a dialog control sits.
     The backdrop is `position:fixed; inset:0`, centering a 220x150 panel in the selftest's fixed
     800x600 viewport: panel top-left is ((800-220)/2, (600-150)/2) = (290, 225). #dlg-a sits at
     panel-relative (0, 10), so on screen at (290, 235). This page-layer button is placed at the
     exact same screen rect, OUTSIDE the overlay: dialog-vs-page must stay silent even though the
     rects coincide 100%. */
  #page-under-dlg { position: absolute; top: 235px; left: 290px; width: 100px; height: 30px; }

  /* --- must NOT fire: an `absolute` (not `fixed`) floating layer, z-index >= 10, with an
     interactive child sitting over a plain page button below it. Mirrors fields.tsx:169's
     expression-help popover shape (no interactive descendants there today, but the shape is
     generic and the structural fallback used to only recognise `position:fixed`). */
  #pop-under { position: absolute; top: 1400px; left: 0; width: 100px; height: 40px; }
  #pop-layer { position: absolute; top: 1400px; left: 0; width: 120px; height: 60px; z-index: 10; }
  #pop-btn   { position: absolute; top: 0; left: 0; width: 90px; height: 36px; }

  /* --- page-h-scroll ---------------------------------------------------------------------- */
  /* Nested so the first offender in document order (#wide-outer, shrink-wrapped to 3000px) is
     an innocent ancestor of the real culprit. */
  #wide-outer { display: inline-block; }
  #wide { width: 3000px; height: 10px; background: #eee; }
</style>

<!-- clipped-overflow: content unreachable, X axis -->
<div class="box" id="clipped">This text is far too wide for its hidden-overflow box</div>

<!-- clipped-overflow: content unreachable, Y axis -->
<div class="box" id="clipped-y">This text wraps onto several lines and is clipped vertically by a short box</div>

<!-- truncate-no-title: the W7 bug -->
<div class="box" id="trunc">This ellipsised text has no title attribute at all</div>

<!-- must NOT fire: same truncation, but recoverable -->
<div class="box" id="trunc-ok" title="full text">This ellipsised text does have a title</div>

<!-- must NOT fire: recoverable via aria-label instead of title -->
<div class="box" id="trunc-aria" aria-label="full text">This ellipsised text has an aria-label</div>

<!-- clipped-overflow on Y: has a title, so truncate-no-title stays silent by design -->
<div class="box" id="trunc-y" title="full text">Ellipsised, titled, and also clipped vertically</div>

<!-- unexpected-scroll: suspicion, not violation -->
<div class="box" id="scrolls">This text is wide but its box scrolls on purpose</div>

<!-- low-contrast -->
<div id="faint">Faint grey on white</div>
<div id="ok-contrast">Near-black on white</div>
<div id="oklch-bad">Tailwind text-slate-400 on white</div>
<div id="oklch-ok">White on Tailwind bg-blue-600</div>
<div id="alpha-text">Thirty percent black text on white</div>
<div id="alpha-bg">White text on a thirty percent black scrim</div>
<div id="img-bg">Faint grey over an image background</div>

<!-- low-contrast: the WCAG large-text boundary -->
<div class="g" id="txt-20-normal">Twenty px normal weight</div>
<div class="g" id="txt-16-bold">Sixteen px bold</div>
<div class="g" id="txt-24-large">Twenty four px normal weight</div>
<div class="g" id="txt-19-bold">Nineteen px bold</div>

<!-- controls -->
<button id="zero">zero</button>
<button id="tiny">t</button>
<button id="big">ok</button>

<!-- INTERACTIVE breadth: none of these is a <button> -->
<div id="controls-row">
  <a href="#" id="tiny-link">l</a>
  <input id="tiny-input">
  <select id="tiny-select"><option>o</option></select>
  <textarea id="tiny-textarea"></textarea>
  <div role="button" id="tiny-role">r</div>
  <span tabindex="0" id="tiny-tab">t</span>
</div>

<!-- must NOT fire: button under a display:none ancestor -->
<div id="buried"><button id="buried-btn">buried</button></div>

<!-- overlap -->
<button id="over-a">A</button>
<button id="over-b">B</button>

<!-- must NOT fire: overlapping pair under an opacity:0 ancestor -->
<div id="fade">
  <button id="fade-a">A</button>
  <button id="fade-b">B</button>
</div>

<!-- must NOT fire (dialog-vs-page): the app's real dialog markup — bare divs, no role="dialog" -->
<div class="fixed inset-0 z-20 flex items-center justify-center bg-black/30" id="dlg-backdrop">
  <div class="dlg-panel">
    <button id="dlg-a">A</button>
    <button id="dlg-b">B</button>
    <!-- must FIRE (dialog-vs-dialog): two controls genuinely colliding inside the SAME overlay -->
    <button id="dlg-c">C</button>
    <button id="dlg-d">D</button>
  </div>
</div>

<!-- must NOT fire: a page-layer control sitting, on screen, exactly where #dlg-a sits -->
<button id="page-under-dlg">under</button>

<!-- must NOT fire: absolute (not fixed) z-index popover, interactive child over a page button -->
<button id="pop-under">under</button>
<div id="pop-layer"><button id="pop-btn">pop</button></div>

<!-- page-h-scroll -->
<div id="wide-outer"><div id="wide"></div></div>
```

- [ ] **Step 2: Write the self-test to assert the expected set**

`$SP/probe-selftest.mjs`. Note the two habits that keep the assertions honest: **exact selector
matching** (`some(s => s.includes('trunc'))` is satisfied by `div#trunc-ok`, the very trap it is
supposed to disprove), and asserting contrast plants are **measured violations with a plausible
ratio** rather than merely present — a `suspicion` is never promoted to an S1, so a real failure
that gets downgraded is still a defect that ships.

```js
import { chromium } from 'playwright'
import { probeRules } from './probe.mjs'
import { fileURLToPath } from 'node:url'
import assert from 'node:assert/strict'

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 800, height: 600 } })
await p.goto('file://' + fileURLToPath(new URL('./probe-selftest.html', import.meta.url)))

const found = await p.evaluate(probeRules)
const rows = (r) => found.filter((v) => v.rule === r)
// Exact selector match, not .includes(): `some(s => s.includes('trunc'))` is satisfied by
// div#trunc-ok, so the false-positive trap could pass off as the plant it exists to disprove.
const hit = (r, sel) => rows(r).some((v) => v.selector === sel)

// ---------------------------------------------------------------------------------------------
// Every rule must fire on its plant.
// ---------------------------------------------------------------------------------------------
assert.equal(rows('page-h-scroll').length, 1, 'page-h-scroll missed the 3000px child')
assert.equal(rows('page-h-scroll')[0].selector, 'div#wide',
  'page-h-scroll named an ancestor rather than the deepest offender')

assert.ok(rows('clipped-overflow').some((v) => v.selector === 'div#clipped' && v.detail.axis === 'x'),
  'clipped-overflow missed the X-axis clip')
assert.ok(rows('clipped-overflow').some((v) => v.selector === 'div#clipped-y' && v.detail.axis === 'y'),
  'clipped-overflow missed the Y-axis clip')
// The axis-blind ellipsis exemption's blind spot: truncate-no-title only inspects X, so if the
// exemption also covers Y, a titled truncation clipped on Y is reported by no rule at all.
assert.ok(rows('clipped-overflow').some((v) => v.selector === 'div#trunc-y' && v.detail.axis === 'y'),
  'ellipsis exemption is axis-blind: a titled truncation clipped on Y is reported by neither rule')

assert.ok(hit('truncate-no-title', 'div#trunc'), 'truncate-no-title missed')
assert.ok(hit('unexpected-scroll', 'div#scrolls'), 'unexpected-scroll missed')

// Each of these must be a MEASURED VIOLATION, with a ratio close to the hand-computed truth.
// Existence alone is too weak an assertion: a `suspicion` is never promoted to an S1 in the
// report, so a genuine AA failure that gets downgraded is still a defect that ships. And a rule
// that fires with a fabricated number is worse than one that stays quiet.
const measured = (sel, expected, why) => {
  const v = rows('low-contrast').find((r) => r.selector === sel)
  assert.ok(v, `low-contrast missed ${sel} — ${why}`)
  assert.equal(v.severity, 'violation',
    `low-contrast downgraded ${sel} to a suspicion — its colour should be measurable (${why})`)
  assert.equal(v.detail.measured, true, `low-contrast did not actually measure ${sel} (${why})`)
  assert.ok(Math.abs(v.detail.ratio - expected) < 0.25,
    `low-contrast mismeasured ${sel}: expected ~${expected}, got ${v.detail.ratio} (${why})`)
  return v
}
measured('div#faint', 1.92, 'plain sRGB grey on white')
// Tailwind 4's palette is oklch. This is the one that matters: #bbb/#111 parse fine under a
// naive rgb() regex and hide the bug completely.
measured('div#oklch-bad', 2.63, 'Tailwind text-slate-400 on white — a real AA failure')
measured('div#alpha-text', 2.12, 'translucent text must be composited, not treated as opaque')
measured('div#alpha-bg', 2.12, 'a translucent scrim over white is grey, not black')
// WCAG large text is >=24px / >=18.66px bold. Both of these are ~4.0 and must fail at 4.5.
measured('div#txt-20-normal', 4.0, 'large text is >=24px, not >=18.66px: 20px normal owes 4.5')
measured('div#txt-16-bold', 4.0, 'bold large text is >=18.66px, not >=14px: 16px bold owes 4.5')

assert.ok(hit('zero-area-control', 'button#zero'), 'zero-area-control missed')
assert.ok(hit('tiny-target', 'button#tiny'), 'tiny-target missed')
// INTERACTIVE breadth — none of these is a <button>.
for (const sel of ['a#tiny-link', 'input#tiny-input', 'select#tiny-select',
  'textarea#tiny-textarea', 'div#tiny-role', 'span#tiny-tab']) {
  assert.ok(hit('tiny-target', sel), `INTERACTIVE narrowed: tiny-target missed ${sel}`)
}

assert.ok(hit('overlap', 'button#over-a'), 'overlap missed the A/B pair')
// Two controls colliding with EACH OTHER inside the SAME overlay must still be reported: a
// blanket "drop every overlay member" filter makes this whole defect class invisible (the
// cramped-InputDialog-at-1024x720 case), which is exactly what grouping-by-overlay-root fixes.
assert.ok(hit('overlap', 'button#dlg-c'),
  'overlap missed the in-dialog dlg-c/dlg-d pair: two controls colliding inside the SAME overlay must still be reported')

// ---------------------------------------------------------------------------------------------
// And the false-positive traps must stay silent. These assertions are the point of the file:
// a probe that cries wolf stops being read, which is the same as having no probe. Every
// violation row here is promoted into the published report as an S1/S2 with no human check,
// so each of these is a false accusation waiting to be printed.
// ---------------------------------------------------------------------------------------------
assert.ok(!hit('truncate-no-title', 'div#trunc-ok'),
  'FALSE POSITIVE: flagged truncation that has a title')
assert.ok(!hit('truncate-no-title', 'div#trunc-aria'),
  'FALSE POSITIVE: flagged truncation that has an aria-label')
assert.ok(!hit('clipped-overflow', 'div#scrolls'),
  'FALSE POSITIVE: overflow:auto reported as a clip')
assert.ok(!hit('low-contrast', 'div#ok-contrast'),
  'FALSE POSITIVE: flagged near-black on white')
// The fabricated white-on-white: an unparsed oklch background walks up to body's white and a
// perfectly legible button gets reported at ratio 1.
assert.ok(!hit('low-contrast', 'div#oklch-ok'),
  'FALSE POSITIVE: flagged white on Tailwind bg-blue-600 (real ratio ~5.25 — fabricated white-on-white?)')
assert.ok(!hit('low-contrast', 'div#txt-24-large'),
  'FALSE POSITIVE: 24px text is WCAG large text and passes at 3.0')
assert.ok(!hit('low-contrast', 'div#txt-19-bold'),
  'FALSE POSITIVE: 19px bold is WCAG large text and passes at 3.0')
assert.ok(!hit('tiny-target', 'button#big'),
  'FALSE POSITIVE: flagged a 40px button')
// display is not inherited: without an ancestor check this button reports a 0x0 rect.
assert.ok(!hit('zero-area-control', 'button#buried-btn'),
  'FALSE POSITIVE: flagged a button under a display:none ancestor as zero-area')
assert.ok(!found.some((v) => v.selector === 'button#buried-btn'),
  'FALSE POSITIVE: reported an element inside a display:none subtree')
// opacity is not inherited either: any element mid-fade-transition looks like this.
const overlapRows = rows('overlap')
assert.ok(!overlapRows.some((v) => /fade-/.test(v.selector) || /fade-/.test(String(v.detail.with))),
  'FALSE POSITIVE: flagged an overlapping pair under an opacity:0 ancestor')
// The app's dialogs are bare `fixed inset-0` divs — no role="dialog" for the probe to key on.
// This tests dialog-vs-PAGE silence ONLY: #page-under-dlg sits, on screen, exactly where #dlg-a
// sits (100% coincident rects) but is a page-layer control, outside the overlay. A dialog member
// and the page control underneath its backdrop must never be compared — the whole Critical-3
// guarantee — but that is a DIFFERENT guarantee from "dlg-c/dlg-d must fire" above: conflating the
// two into one assertion (as an earlier version of this trap did, by making dlg-a/dlg-b overlap
// EACH OTHER and asserting silence) meant no mutation could tell the fix from the bug it fixes.
assert.ok(!overlapRows.some((v) => v.selector === 'button#page-under-dlg' || v.detail.with === 'button#page-under-dlg'),
  'FALSE POSITIVE: flagged a dialog control overlapping a page control underneath the backdrop')
// The `absolute` (not `fixed`) structural-fallback plant: an absolute z-10 popover's interactive
// child sitting over a plain page button below it must not be reported either.
assert.ok(!overlapRows.some((v) => /pop-/.test(v.selector) || /pop-/.test(String(v.detail.with))),
  'FALSE POSITIVE: flagged an absolute z-index popover control overlapping the page control beneath it')

// ---------------------------------------------------------------------------------------------
// Severity split (design §5.1). auto-scroll and small targets are judgment calls, never
// verdicts. low-contrast is a verdict only when it was actually measured: an image background
// or a colour the browser could not read downgrades it to a suspicion rather than inventing a
// ratio. probe.mjs and this file disagreed about that until now.
// ---------------------------------------------------------------------------------------------
for (const v of found) {
  let expected
  if (['unexpected-scroll', 'tiny-target'].includes(v.rule)) expected = 'suspicion'
  else if (v.rule === 'low-contrast') expected = v.detail.measured ? 'violation' : 'suspicion'
  else expected = 'violation'
  assert.equal(v.severity, expected, `${v.rule} on ${v.selector} has the wrong severity`)
}
// An unmeasurable background must still be reported — as a suspicion, with no ratio asserted.
const img = rows('low-contrast').find((v) => v.selector === 'div#img-bg')
assert.ok(img, 'low-contrast missed the image-background case')
assert.equal(img.severity, 'suspicion', 'an image background cannot be measured: must be a suspicion')
assert.equal(img.detail.measured, false, 'image-background contrast must not claim to be measured')

const bySev = found.reduce((a, v) => ((a[v.severity] = (a[v.severity] || 0) + 1), a), {})
console.log(`probe self-test OK — ${found.length} rows `
  + `(${bySev.violation || 0} violations, ${bySev.suspicion || 0} suspicions), no false positives`)
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
 * Returns Violation[] = {rule, severity, selector, text, detail}.
 *
 * Every `severity:"violation"` row is promoted into the published report as an S1/S2 defect
 * with no further verification, so a false positive is a false accusation. Where this probe
 * cannot actually measure what it would be asserting, it emits `suspicion` and says why —
 * it never fabricates a number. */
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

  // --- colour reader ----------------------------------------------------------------------------
  // Declared up here, not with the other helpers at the bottom: the rule loop below calls
  // parseColor(), and `const` bindings placed after the loop would still be in the temporal dead
  // zone when it runs. (Only `function` declarations hoist.)
  //
  // Tailwind 4 emits the entire palette as oklch()/oklab() — only --color-white and --color-black
  // stay hex — so a /rgba?\(...\)/ regex parses almost nothing in this app. It returned null for
  // the foreground (the rule went silent on genuine failures like text-slate-400, ratio 2.6) and
  // null for the background (walked through to body's white, fabricating white-on-white on every
  // bg-blue-600 button). Let the browser do the conversion instead: paint the colour into a 1x1
  // sRGB canvas and read the pixel back. That handles oklch/oklab/color()/named/hex/rgb/hsl alike.
  //
  // NB: ctx.fillStyle does NOT normalise oklch to #rrggbb in current Chromium — it round-trips
  // `oklch(...)` verbatim, so reading fillStyle back is not enough. The *pixel* is. Verified
  // against screenshots of the painted swatch: readback matches what Chromium actually paints,
  // exactly, including out-of-gamut colours (which it gamut-maps, as WCAG's sRGB model needs).
  const _cv = document.createElement('canvas')
  _cv.width = _cv.height = 1
  const _ctx = _cv.getContext('2d', { willReadFrequently: true })
  _ctx.globalCompositeOperation = 'copy'   // fillRect replaces the pixel outright, alpha included
  const _colorCache = new Map()

  /** @returns {{rgb: number[], a: number}|null} null = the browser could not parse it. */
  function parseColor(css) {
    if (typeof css !== 'string' || !css.trim()) return null
    if (_colorCache.has(css)) return _colorCache.get(css)
    let v = null
    // Assigning an invalid value leaves fillStyle at its previous value, so an invalid string
    // would silently read back as whatever we last set. Two different sentinels disambiguate:
    // a valid colour reads back identically both times, an invalid one reads back the sentinels.
    _ctx.fillStyle = '#010203'
    _ctx.fillStyle = css
    const first = _ctx.fillStyle
    _ctx.fillStyle = '#040506'
    _ctx.fillStyle = css
    if (_ctx.fillStyle === first) {
      _ctx.fillRect(0, 0, 1, 1)             // fillStyle is now the parsed colour
      const d = _ctx.getImageData(0, 0, 1, 1).data
      v = { rgb: [d[0], d[1], d[2]], a: d[3] / 255 }
    }
    _colorCache.set(css, v)
    return v
  }

  // --- visibility -------------------------------------------------------------------------------
  // `display` and `opacity` are NOT inherited: getComputedStyle(child).display inside a
  // display:none parent still reports `inline-block`, and .opacity still reports '1' inside an
  // opacity:0 parent. An own-style-only check therefore fabricates a zero-area-control S1 for
  // every control in a hidden subtree, and overlap S1s for every element mid-fade.
  // checkVisibility() resolves the whole ancestor chain; the explicit walk backs it up (engines
  // have disagreed about checkOpacity's ancestor handling) and covers engines without it.
  // Deliberately does NOT test for a zero-size box: a 0x0 control is exactly what
  // zero-area-control exists to report.
  const visible = (el) => {
    if (typeof el.checkVisibility === 'function' &&
        !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true, contentVisibilityAuto: true })) {
      return false
    }
    const own = getComputedStyle(el)
    // `visibility` IS inherited and a descendant may re-declare `visible`, so an ancestor walk
    // would be wrong here — the element's own computed value already carries the answer.
    if (own.visibility === 'hidden' || own.visibility === 'collapse') return false
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const s = e === el ? own : getComputedStyle(e)
      if (s.display === 'none') return false
      if (parseFloat(s.opacity) === 0) return false
      // content-visibility:hidden skips an element's *contents*, not the element itself.
      if (e !== el && s.contentVisibility === 'hidden') return false
    }
    return true
  }

  const INTERACTIVE = 'button, a[href], input, select, textarea, [role="button"], [tabindex]'

  // --- overlay detection ------------------------------------------------------------------------
  // Deliberate overlays (modals, drag previews) are SUPPOSED to sit on top of the page, so their
  // members must not be compared against the page underneath them. The ARIA selectors alone match
  // NOTHING in this app: its dialogs are bare `<div class="fixed inset-0 z-20 flex items-center
  // justify-center bg-black/30">` (run/InputDialog.tsx:101, builder/LoadDialog.tsx:71) with no
  // role="dialog", and @dnd-kit's DragOverlay carries no data-dnd-overlay attribute. Match what is
  // actually rendered:
  //   1. the ARIA/attribute hooks, for generality and in case the app gains them;
  //   2. the app's own backdrop classes;
  //   3. a structural fallback — any position:fixed OR position:absolute ancestor stacked above
  //      the page (z-index >= 10). Covers @dnd-kit's DragOverlay (fixed, z-index:999) and floating
  //      popovers built with `absolute` instead of `fixed` — this app's expression-help popover
  //      (fields.tsx:169) has no interactive descendants today, but the shape is generic: an
  //      `absolute z-10` layer with an interactive child sitting over a button below it used to
  //      fabricate a 93% overlap violation, because only `fixed` was ever treated as a stacking
  //      layer here.
  // Class/structure coupling is acceptable in a scratchpad probe. Adding role="dialog" to the app
  // to make the ARIA selector work is NOT (constraint D4); the missing role is recorded as an
  // accessibility finding in the report instead.
  //
  // `overlayRoot(el)` returns the nearest overlay-establishing element (or `el` itself, if it is
  // the one establishing the stacking layer), or `null` for the base page. It is a GROUP KEY, not
  // a boolean: a blanket `!inOverlay(el)` filter drops every control inside every overlay from the
  // overlap rule entirely, which means two controls that collide with EACH OTHER inside the same
  // dialog are never compared either — a real defect class (a cramped InputDialog at 1024x720)
  // went invisible this way. The overlap rule below groups controls by this key and compares pairs
  // only WITHIN a group: a dialog control and a page control underneath are in different groups and
  // are never compared (the backdrop still cannot fabricate an overlap), but two controls sharing a
  // group — both on the page, or both inside the SAME dialog — are compared exactly as before.
  const OVERLAY_SEL = '[role="dialog"], [aria-modal="true"], [data-dnd-overlay], .fixed.inset-0'
  const overlayRoot = (el) => {
    const via = el.closest(OVERLAY_SEL)
    if (via) return via
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const s = getComputedStyle(e)
      if (s.position !== 'fixed' && s.position !== 'absolute') continue
      const z = parseInt(s.zIndex, 10)
      if (Number.isFinite(z) && z >= 10) return e
    }
    return null
  }

  // --- rule: page-h-scroll ----------------------------------------------------------------------
  // A desktop app should never scroll its own body sideways.
  if (document.documentElement.scrollWidth > window.innerWidth + 1) {
    const culprits = [...document.querySelectorAll('*')].filter(
      (e) => visible(e) && e.getBoundingClientRect().right > window.innerWidth + 1,
    )
    // Prefer the deepest offender. The first in document order is usually an ancestor that is
    // only over-wide because of the descendant that actually overflows — naming it sends the
    // reader to a container that is innocent.
    const culprit = culprits.find((e) => !culprits.some((o) => o !== e && e.contains(o))) || culprits[0]
    push('page-h-scroll', 'violation', culprit || document.documentElement, {
      scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
    })
  }

  for (const el of document.querySelectorAll('*')) {
    if (!visible(el)) continue
    const s = getComputedStyle(el)
    const overflowsX = el.scrollWidth > el.clientWidth + 1
    const overflowsY = el.scrollHeight > el.clientHeight + 1

    // --- rule: clipped-overflow / unexpected-scroll ----------------------------------------------
    // hidden|clip => content is unreachable, a fact. auto|scroll => intended (S1's parallel
    // lanes are SUPPOSED to scroll), so it is a suspicion for judgment, never a verdict.
    for (const [axis, overflows] of [['x', overflowsX], ['y', overflowsY]]) {
      if (!overflows) continue
      const mode = s[`overflow${axis.toUpperCase()}`]
      if (mode === 'hidden' || mode === 'clip') {
        // text-overflow:ellipsis is a deliberate, *labelled* clip — handled by its own rule.
        // But only on the inline axis, which is the only axis it renders on. Exempting BOTH
        // axes opens a hole: truncate-no-title only inspects X, so a `truncate`d element that
        // HAS a title and is clipped on Y is reported by neither rule.
        const ellipsisExempt = axis === 'x' && s.textOverflow === 'ellipsis'
        if (!ellipsisExempt) {
          push('clipped-overflow', 'violation', el, {
            axis, mode, scroll: el[axis === 'x' ? 'scrollWidth' : 'scrollHeight'],
            client: el[axis === 'x' ? 'clientWidth' : 'clientHeight'],
          })
        }
      } else if (mode === 'auto' || mode === 'scroll') {
        push('unexpected-scroll', 'suspicion', el, { axis, mode })
      }
    }

    // --- rule: truncate-no-title -----------------------------------------------------------------
    // The W7 bug, exactly: a truncated string with no way to recover the full text.
    if (s.textOverflow === 'ellipsis' && overflowsX &&
        !el.getAttribute('title') && !el.getAttribute('aria-label')) {
      push('truncate-no-title', 'violation', el, { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth })
    }

    // --- rule: low-contrast ----------------------------------------------------------------------
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
    if (own) {
      const fg = parseColor(s.color)
      const bg = effectiveBg(el)
      if (!fg || bg.kind === 'unparseable') {
        // Honest dead end. Emitting a fabricated ratio here is how "white on white" gets
        // published as an S1 against a button that is perfectly legible.
        push('low-contrast', 'suspicion', el, {
          measured: false, reason: 'unreadable-colour',
          color: s.color, bg: bg.css, fontSize: parseFloat(s.fontSize),
        })
      } else if (fg.a > 0) {   // fully transparent text is invisible, not a contrast defect
        const fgRgb = composite(fg.rgb, fg.a, bg.rgb)
        const ratio = contrast(fgRgb, bg.rgb)
        const px = parseFloat(s.fontSize)
        // WCAG 2.x large text = >=18pt or >=14pt bold. Those are POINTS: as CSS px they are
        // >=24px and >=18.66px bold. Using 18.66/14 as the px thresholds hands 20px-normal and
        // 16px-bold the lenient 3.0 they are not entitled to, and both then pass at ~4.0.
        const large = px >= 24 || (px >= 18.66 && parseInt(s.fontWeight, 10) >= 700)
        const min = large ? 3.0 : 4.5
        if (ratio < min) {
          // An image background cannot be resolved to a single colour — report it, but as a
          // suspicion: we cannot actually measure what we would be asserting.
          // colorRgb/bgRgb are the resolved, composited sRGB the ratio was actually computed
          // from: `color: "oklch(0.704 0.04 256.788)"` alone leaves a reader with no way to
          // check the number they are being asked to publish.
          push('low-contrast', bg.kind === 'image' ? 'suspicion' : 'violation', el, {
            measured: bg.kind === 'color', ratio: +ratio.toFixed(2), min, large,
            fontSize: px, color: s.color, colorRgb: round(fgRgb), bg: bg.css, bgRgb: round(bg.rgb),
          })
        }
      }
    }
  }

  // --- rules: zero-area-control / tiny-target ---------------------------------------------------
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

  // --- rule: overlap ----------------------------------------------------------------------------
  // Controls are grouped by overlayRoot() (see above) and compared for overlap ONLY within their
  // own group. A dialog member and a page member underneath the backdrop fall into different
  // groups and are never compared — that is the whole Critical-3 guarantee. Two controls sharing
  // a group (both on the page, or both inside the SAME dialog) are compared exactly as before.
  // (An earlier draft gated the *entire* rule on "a dialog exists anywhere in the DOM", which goes
  // blind for the whole page the moment any dialog node is present — e.g. one that stays mounted
  // but hidden. Per-element grouping is the precise fix; no page-wide gate.)
  const groups = new Map()
  for (const el of controls) {
    const r = el.getBoundingClientRect()
    if (r.width === 0 || r.height === 0) continue
    const key = overlayRoot(el)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push([el, r])
  }
  for (const rects of groups.values()) {
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
  /** Composite a (possibly translucent) source over an already-opaque backdrop. */
  function composite(rgb, a, bg) {
    return [0, 1, 2].map((i) => rgb[i] * a + bg[i] * (1 - a))
  }
  // `function`, not `const`: the rule loop above calls this, and a const would still be in the
  // temporal dead zone at that point.
  function round(rgb) { return rgb.map((c) => Math.round(c)) }
  /** Flatten translucent layers (innermost first) down onto an opaque base. */
  function flatten(layers, base) {
    let r = base
    for (let i = layers.length - 1; i >= 0; i--) r = composite(layers[i].rgb, layers[i].a, r)
    return r
  }
  /** Three outcomes, kept distinct on purpose. The old code conflated "transparent, keep
   *  walking" with "unparseable, give up" into a single null, which is how an oklch background
   *  got walked through to body's white. */
  function effectiveBg(el) {
    const layers = []   // translucent layers seen so far, innermost first
    // "rgba(0,0,0,0.3) over assumed white" reads honestly; naming only the layer we happened to
    // stop on would print `bg: "assumed white"` for text sitting on a 30% black scrim.
    const label = (terminal) => [...layers.map((l) => l.css), terminal].join(' over ')
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e)
      if (s.backgroundImage && s.backgroundImage !== 'none') {
        const c = parseColor(s.backgroundColor)
        const base = c && c.a > 0 ? composite(c.rgb, c.a, [255, 255, 255]) : [255, 255, 255]
        return { kind: 'image', rgb: flatten(layers, base), css: label(s.backgroundImage) }
      }
      const c = parseColor(s.backgroundColor)
      if (!c) return { kind: 'unparseable', css: label(s.backgroundColor) }
      if (c.a === 0) continue                                              // transparent: keep walking
      if (c.a >= 1) return { kind: 'color', rgb: flatten(layers, c.rgb), css: label(s.backgroundColor) }
      layers.push({ ...c, css: s.backgroundColor })   // bg-black/30 over a white panel is grey, not black
    }
    // Ran out of ancestors: the canvas behind the root paints white.
    return { kind: 'color', rgb: flatten(layers, [255, 255, 255]), css: label('assumed white') }
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

Expected: `probe self-test OK — 24 rows (14 violations, 10 suspicions), no false positives`.

**This is a real TDD cycle — expect to iterate.** Every assertion that fails is telling you the
probe is wrong, not the plant. Do not delete an assertion to get green; that converts the
self-test into the vacuous kind this repo has already shipped once.

- [ ] **Step 6: Mutation-verify the self-test itself**

The self-test can also be vacuous — and *deletion* is the easy case. The dangerous case is
**narrowing**: a rule that still fires, just less. A previous version of this probe passed its
own self-test while five of these six narrowings survived undetected.

Break one rule at a time, run `node probe-selftest.mjs`, confirm the expected RED, revert,
confirm green. Automate it (`$SP/mutate.mjs`) and **assert each mutation's search string
matched exactly once** — a mutation that silently fails to apply reports a meaningless "caught".

| # | Mutation | Expected RED |
|---|---|---|
| 1 | `clipped-overflow` → X axis only | `clipped-overflow missed the Y-axis clip` |
| 2 | `low-contrast` threshold `4.5` → `2.5` | `low-contrast missed div#oklch-bad — Tailwind text-slate-400 on white — a real AA failure` |
| 3 | large-text rule disabled (thresholds → 9999) | `FALSE POSITIVE: 24px text is WCAG large text and passes at 3.0` |
| 4 | `INTERACTIVE` → `'button'` only | `INTERACTIVE narrowed: tiny-target missed a#tiny-link` |
| 5 | `truncate-no-title` aria-label hatch removed | `FALSE POSITIVE: flagged truncation that has an aria-label` |
| 6 | `overlap` threshold `0.25` → `0.95` | `overlap missed the A/B pair` |

If breaking a rule does not turn the self-test red, the self-test is decoration.

**Also re-introduce each historical defect** (`$SP/bug-revert.mjs`) — the three Criticals and four
Importants the review found — and confirm each is pinned by a plant. Fixing a bug without leaving
a plant behind means the next rewrite reintroduces it silently.

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
