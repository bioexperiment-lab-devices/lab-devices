# Morbidostat demonstration experiment — design

Date: 2026-07-13
Status: settled (user-approved 2026-07-13)

A worked example that implements the morbidostat algorithm of `docs/morbidostat_algorithm.md`
(Toprak et al. 2012/2013) as an Experiment Studio document. Its job is pedagogic: show users
how a real closed-loop evolution experiment decomposes into the engine's block vocabulary.
It ships as an uploadable experiment doc, not as library code.

## 1. Scope

Three cultures, three liquid channels, one 24 h "day" of the published daily loop. Everything
outside that loop (glycerol archiving, MIC re-measurement, stock cascade, WGS) is off-scope:
those are bench steps, not orchestration.

Two documents ship, identical except for `pace`/`count` and the slope constant:

| Doc | Cycle | Cycles | Wall clock | Purpose |
|---|---|---|---|---|
| `examples/morbidostat.json` | 12 min | 120 | 24 h | The faithful protocol. |
| `examples/morbidostat-demo-speed.json` | 60 s | 25 | ~25 min | Watchable end-to-end in Studio. |

## 2. Hardware and plumbing (9 roles)

**Invariant (user-set): medium, drug, and waste never share a pipe — they meet only in the
tube.** Each liquid channel therefore gets its own pump, its own distribution valve, and its
own needle in every tube: 3 channels x 3 tubes = 9 needles.

| Role | Type | Purpose |
|---|---|---|
| `medium_pump` | pump | Drug-free medium. |
| `drug_pump` | pump | Stock A (10x MIC). |
| `waste_pump` | pump | Draws culture out to waste. |
| `medium_valve` | valve | Routes medium to tube 1/2/3. |
| `drug_valve` | valve | Routes drug to tube 1/2/3. |
| `waste_valve` | valve | Routes suction to tube 1/2/3. |
| `od_meter_1..3` | densitometer | One per tube; also the 30 °C thermostat. |

Valve positions: tube *i* -> position *i*; position **0 = all closed** is the park position
between cycles (prevents siphoning during the 10 min growth phase). Valves are homed at 0 in
setup — `home` only *declares* position, it does not move, so an operator confirmation
precedes it. `rotation: "direct"` is configured so the rotor never transits across the 0<->N
boundary. Transiting a foreign port is harmless anyway: blocks are serial, so no pump is
running during a valve move, and an idle peristaltic pump occludes its own line.

**Volume control is mechanical, not computed.** The waste needle is fixed at the 12 ml line.
After a 1 ml injection the tube holds 13 ml; the waste pump then draws `dose_ml * 1.5` — an
over-draw that hits air at the needle tip and self-limits the level to exactly V = 12 ml. The
workflow never tracks volume.

## 3. The control law

### 3.1 What the engine cannot do

The expression sublanguage offers `last / mean / min / max / count` over streams with
`last=<N>` or `last=<duration>` windows, plus arithmetic and comparison. There is no `ln` and
no regression, so the paper's `robustfit` of `ln OD` against `t` is not directly expressible.

### 3.2 Slope from two trailing means (exact)

For evenly-spaced samples, the time-centroids of the last `n` and the last `2n` samples are
separated by `n·dt/2`. For a trend of slope `m`:

```
mean(last=n) − mean(last=2n) = m · n·dt/2
⇒   m = 2·(mean(last=n) − mean(last=2n)) / (n·dt)
```

This is a difference-of-means slope estimator: unbiased for a linear trend, and it averages
noise across the whole cycle — the same job `robustfit` does. Dividing by OD converts the OD
slope into the *specific growth rate* the paper actually controls:

```
r = m / OD
```

Two properties make the substitution faithful rather than merely convenient:

- **The sign is exact.** `ln` is monotone, so `sign(d(ln OD)/dt) = sign(dOD/dt)`. The decision
  is a sign test, and it is preserved.
- **The magnitude is the controlled variable.** `r = (dOD/dt)/OD` *is* the specific growth
  rate, which is what `r_dil` is compared against.

With the monitor sub-loop sampling at `dt = 1 min` and `n = 5` (10 samples per cycle):

```
r_i [1/h] = 60 · 2 · (mean(od_i, last=5) − mean(od_i, last=10)) / (5 · 1 · last(od_i))
          = 24 · (mean(od_i, last=5) − mean(od_i, last=10)) / last(od_i)
```

The constant is `60·2/(n·dt_min)`. In the demo-speed doc `dt = 3 s = 0.05 min`, so it is 480.

### 3.3 Decision (algorithm §1 step 3, verbatim)

```
last(od_i) < od_min                       → NOTHING   (no injection, no drain)
last(od_i) > od_thr  and  r_i > r_dil     → DRUG
otherwise                                 → MEDIUM
```

Driving `r → r_dil` is the design invariant `r_dil = r₀/2`, which pins each culture at its own
continuously moving IC₅₀. No separate warm-up phase is needed: a culture below `od_thr`
receives medium automatically, so the loop self-warms-up.

Window safety: the decision reads `last=10`/`last=5` over the trace, and the monitor sub-loop
writes exactly 10 samples per cycle immediately before the decision, so the window is exactly
the current cycle's growth phase — no injection discontinuity falls inside it. Windows are
trailing slices (`samples[-n:]`), so a short stream degrades gracefully rather than erroring.
Division by `last(od_i)` is guarded by the enclosing `od_min` branch.

## 4. Block structure

```
serial
├─ operator_input  od_min, od_thr, r_dil, dose_ml, drug_stock_x_mic
├─ operator_input  blanks_ready (bool)
├─ serial          3x densitometer.set_thermostat(enabled=true, target_c=30)   # see §4.2
├─ serial          3x densitometer.measure_blank → blank_i
├─ operator_input  cultures_ready (bool)   # inoculated; valves physically parked at 0
├─ serial          3x valve.home(position=0) + configure(default_rotation="direct")
└─ loop count=120 pace=12min                        # one 24 h day
   ├─ loop count=10 pace=1min                       # growth phase — fills the OD trace
   │  └─ parallel  measure od_meter_1→od_1 | od_meter_2→od_2 | od_meter_3→od_3
   ├─ <tube 1 service>                              # serial: pumps and valves are shared
   ├─ <tube 2 service>
   ├─ <tube 3 service>
   └─ parallel     3x valve.set_position(0)         # park all closed
```

Tube *i* service:

```
branch  last(od_i) >= od_min
└─ then
   ├─ branch  last(od_i) > od_thr and 24*(mean(od_i,last=5)-mean(od_i,last=10))/last(od_i) > r_dil
   │  ├─ then   drug_valve.set_position(i)   ; drug_pump.dispense(dose_ml)
   │  └─ else   medium_valve.set_position(i) ; medium_pump.dispense(dose_ml)
   ├─ waste_valve.set_position(i)
   └─ waste_pump.dispense(volume_ml = dose_ml * 1.5)     # over-draw → level pinned to V
```

The `else`-less outer branch *is* the `NOTHING` action: too-dilute tubes get no injection and
no drain, so their volume is untouched.

**Why the dilution pass is serial.** The three tubes share pumps and valves, so the engine's
occupancy checker would reject a parallel pass. Only the OD readings — three distinct
densitometers — go in a `parallel` block. This is a load-bearing teaching point, not an
incidental choice.

### 4.2 Setup is serial (amended 2026-07-13 after the first live smoke)

Setup was originally three `parallel` blocks. The first live run on `windows_arm64_test_client`
**failed 26 s in**, at `blocks[0].children[6].children[0]` — the parallel thermostat block:

```
persist thermostat: device store rename:
  C:\ProgramData\SerialHop\devicestate\densitometer-25-006.json.tmp -> .json
  The process cannot access the file because it is being used by another process.
```

The SerialHop agent's device-state store is not concurrency-safe. Measured over 6 trials of
three devices in parallel: `set_thermostat` failed **2/6** in parallel and **0/6** serial;
`measure` (pure read) survived **90 concurrent calls** through the engine with zero failures;
valve `configure`/`set_position` were clean 0/6.

So: every state-persisting setup command is now serial (~2 s, one time), and the monitor loop's
three simultaneous `measure` calls — the parallelism the science actually needs — stay parallel.
This is an **agent** bug, not an engine one; it is catalogued in
`docs/experiment-engine-limitations.md` and warrants a `lab-bridge` issue. Nothing in the engine
or the validator warns an author about it, which is what makes it dangerous.

### 4.1 Timing budget

Faithful doc: 10 min monitor + dilution pass. At 6 ml/min a 1 ml dose takes 10 s and a 1.5 ml
draw 15 s; with two ~1 s valve moves that is ~27 s per tube, ~1.4 min for three, comfortably
inside the 12 min `pace`. `pace` is a floor, so an overrun would stretch the cycle rather than
fail — but the budget holds. The demo-speed doc pumps at 60 ml/min to fit its 60 s cycle.

## 5. Streams and parameters

Streams: `od_1/od_2/od_3` (units `AU`, one sample per tube per minute — the decision *and* the
live chart read the same trace) and `blank_1/blank_2/blank_3` (the `measure_blank` slope).

Operator inputs (engine types are `float | int | bool | enum`):

| Name | Type | Default in prompt | Role |
|---|---|---|---|
| `od_min` | float | 0.03 | Below this, no action at all. |
| `od_thr` | float | 0.15 | Drug only above this. |
| `r_dil` | float | 0.4 | Dilution rate [1/h]; the controller's setpoint. |
| `dose_ml` | float | 1.0 | ΔV per injection. |
| `drug_stock_x_mic` | float | 10.0 | Provenance only — recorded, never actuated. |

`pace` and `count` are duration/int literals, not expressions, so cycle time and cycle count
cannot be operator inputs. They are the two fields a user edits in the doc.

## 6. What this example deliberately does not do

Each of these is an engine limitation, catalogued with the rest in
`docs/experiment-engine-limitations.md`:

- **Drug concentration `c_k` is not tracked.** There is no accumulator binding, so the §1
  concentration recursion cannot run in-engine. Every injection is in the run log, so `c_k` is
  reconstructed offline. The example documents this rather than faking it.
- **The three tube-service subtrees are near-copies.** Groups exist but are not parametrized,
  so one reusable `service(tube)` macro is not expressible.
- **No Stock A→B escalation.** It needs a second drug line, and the escalation predicate is
  cross-cycle state the engine cannot hold.

## 7. Verification

1. `POST /api/validate` on both docs → zero diagnostics (real engine validator via placeholder
   substitution).
2. **Simulated-culture execution** (`tests/test_examples_morbidostat.py`): a FakeLab whose
   densitometers model exponential growth, dilution on injection, and drug inhibition. Asserts
   the loop actually closes — tubes below `od_min` get nothing, a growing tube above `od_thr`
   gets drug, and the controller holds OD in a band instead of running away.
3. **Live smoke on preprod** (`windows_arm64_test_client`: 3 pumps, 3 valves, 3 densitometers)
   of the demo-speed doc through the Studio REST API, answering operator inputs via
   `POST /runs/{id}/input`. Pumps are pre-calibrated out of band (`set_calibration`), since
   calibration is device provisioning, not experiment logic.

## 8. Deliverables

- `examples/morbidostat.json`, `examples/morbidostat-demo-speed.json`
- `examples/README.md` — paper→blocks walkthrough including the slope derivation
- `tests/test_examples_morbidostat.py`
- `docs/experiment-engine-limitations.md` (session's second deliverable)
