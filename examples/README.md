# Example experiments

Upload one of these to Experiment Studio (**Experiments → Import**, or
`POST /api/experiments` with the file as the body), map its roles to your devices on the
preflight screen, and run it.

| File | What it is |
|---|---|
| `morbidostat.json` | The morbidostat of Toprak et al. — three cultures held at their own moving IC₅₀. One 24 h "day": 120 cycles of 12 min. |
| `morbidostat-demo-speed.json` | The same control loop compressed to ~25 min (25 cycles of 60 s) so you can watch it run end to end. Biologically meaningless intervals — for learning the structure, not for doing science. |

---

# Morbidostat — a walkthrough

The morbidostat is a continuous-culture device that keeps a bacterial population under
*constant growth inhibition* while the drug concentration is free to rise. Because the
controller's setpoint is "grow at half your maximum rate", it automatically tracks the
population's IC₅₀ as resistance evolves — for weeks, over three orders of magnitude.

The algorithm is in [`../docs/morbidostat_algorithm.md`](../docs/morbidostat_algorithm.md).
This walkthrough is about how it becomes blocks.

## The decision, and why it is the whole experiment

Every cycle, each tube gets **1 ml of liquid — always the same volume**. The only question is
*what is in it*:

```
OD below OD_MIN (0.03)          → nothing at all      (too dilute to trust the reading)
OD above OD_THR (0.15)  and  r > r_dil   → 1 ml of drug
otherwise                       → 1 ml of plain medium
```

Because both injections are the same volume, the **dilution rate is fixed** and the decision
changes only the drug content. That is what makes the loop stable: the culture is always being
washed out at `r_dil = 0.4 /h`, so the only way it can persist is by growing at exactly that
rate. Drug is added whenever it grows faster. The controller therefore drives

```
r → r_dil = r₀ / 2
```

and "the concentration at which growth is halved" *is the definition of IC₅₀*. The device
reports the quantity it is regulating.

In the doc this is two nested `branch` blocks. The outer one has no `else` — **that missing
`else` is the "do nothing" row of the table.** A tube too dilute to read is skipped entirely:
no injection, and no drain either, so its volume is untouched.

## Growth rate without a regression

The paper fits `ln OD` against `t` with a robust linear regression. The expression language
has no `ln` and no regression — it has `last`, `mean`, `min`, `max`, `count` over stream
windows. So the example computes the slope a different way, and gets the same answer.

For evenly spaced samples, the *time-centroid* of the last `n` samples and that of the last
`2n` samples are separated by `n·dt/2`. So for any trend of slope `m`:

```
mean(last=n) − mean(last=2n)  =  m · n·dt / 2

              2 · ( mean(last=n) − mean(last=2n) )
     ⇒   m = ──────────────────────────────────────
                            n · dt
```

That is a *difference-of-means* slope estimator. It is unbiased for a linear trend and it
averages noise over the entire cycle — the same job `robustfit` is doing. Dividing by OD turns
the OD slope into the **specific growth rate**, which is the quantity `r_dil` is compared with:

```
r = m / OD
```

Two things make this faithful rather than merely convenient:

- **The sign is exact.** `ln` is monotone, so `sign(d(ln OD)/dt) = sign(d OD/dt)`. The decision
  is fundamentally a sign test, and it is preserved perfectly.
- **The magnitude is the right variable.** `r = (dOD/dt)/OD` *is* the specific growth rate.

The growth phase samples every tube 10 times (`dt = 1 min`, so `n = 5`), which collapses the
whole thing to one line the engine evaluates natively:

```
24 * (mean(od_1, last=5) - mean(od_1, last=10)) / last(od_1)  >  r_dil
```

The `24` is just `60·2/(n·dt_min)` — the unit conversion into "per hour". **If you change the
sampling interval, you must change this constant.** In `morbidostat-demo-speed.json` the trace
is sampled every 3 s, so it is 480.

The windows are trailing slices, and the monitor sub-loop writes exactly 10 samples
immediately before the decision — so `last=10` is precisely this cycle's growth phase, with no
injection discontinuity inside it.

## Plumbing: nine needles, three liquids

**Medium, drug, and waste never share a pipe.** They meet only in the tube. So each liquid
channel gets its own pump *and its own distribution valve*, with its own needle in every tube:

```
medium_pump ── medium_valve ─┬─> tube 1     drug_pump ── drug_valve ─┬─> tube 1
                             ├─> tube 2                              ├─> tube 2
                             └─> tube 3                              └─> tube 3

waste_pump ── waste_valve ─┬─> tube 1   (needle fixed at the 12 ml line)
                           ├─> tube 2
                           └─> tube 3
```

**The volume is held constant mechanically, not by arithmetic.** The waste needle sits at the
12 ml line. After a 1 ml injection the tube holds 13 ml, and the waste pump then draws
`dose_ml * 1.5` — deliberately more than it needs. It hits air at the needle tip and stops
moving liquid, so the level self-limits to exactly 12 ml. The workflow never tracks volume;
the needle height *is* the volume.

Position `0` on every valve means **all ports closed**. The valves are parked there during the
growth phase so nothing can siphon. Note that `home` only *declares* where the rotor is — it
does not move it — which is why an operator confirmation comes first.

## The shape of the run

```
serial
├─ operator_input   od_min, od_thr, r_dil, dose_ml, drug_stock_x_mic
├─ operator_input   blanks_ready?
├─ serial           thermostats → 30 °C          ← serial on purpose, see below
├─ serial           measure_blank → blank_1..3   ← every later OD is relative to this
├─ operator_input   cultures_ready?  (valves physically parked at 0?)
├─ serial           home + configure the 3 valves
└─ loop ×120, pace 12min                          ← one 24 h "day"
   ├─ loop ×10, pace 1min                         ← growth phase
   │  └─ parallel   read tube 1 | tube 2 | tube 3
   ├─ tube 1 service ─┐
   ├─ tube 2 service  ├─ serial — see below
   ├─ tube 3 service ─┘
   └─ parallel        park all 3 valves closed
```

**Why the OD readings are `parallel` but the dilution pass is `serial`** — this is the most
useful thing in the example. The three densitometers are independent devices, so they can read
at once, and they *must*: the three tubes have to be sampled at the same instant for their
growth rates to be comparable. The three tubes, however, *share* the pumps and valves. Trying
to service them in parallel is not a style mistake; the engine's occupancy checker will reject
the workflow, because two lanes would be reaching for the same pump. The hardware topology
dictates the block structure, and the validator enforces it.

**Why the setup is `serial` even though it looks parallelisable** — a subtler lesson, and one
the validator will *not* teach you. `set_thermostat`, `home`, and `configure` persist device
state to a file on the agent host, keyed by the device's *serial number*. On a test rig whose
simulated devices are clones (all three densitometers reporting the same serial), those three
files are **one** file — so setting three thermostats at once means three writers racing on it,
which fails ~92% of the time and kills the run. The first live run of this example died exactly
that way, 26 s in. Serialising costs about two seconds. The monitor loop stays parallel because
`measure` is a pure read — verified over 90 concurrent calls. On real hardware with unique
serials this should not arise; details and the fix in
[`../docs/experiment-engine-limitations.md`](../docs/experiment-engine-limitations.md).

`pace` is a floor, not a deadline: the 10 min growth phase plus a ~1.4 min dilution pass fits
inside the 12 min cycle, so cycles start exactly 12 min apart.

## Before you trust this with a real experiment

> **A single flaky sensor read will destroy your run.** The engine has no retry and no error
> tolerance: any device error fails the whole experiment. A live run of the demo-speed doc got
> to cycle 17 of 25 and was killed by one transient `measure` fault on one densitometer — a
> block that had already succeeded ~170 times.
>
> The faithful doc takes **3,600 measurements** in 24 h, and the published experiment runs for
> **three weeks**. Until the engine gains a retry policy, treat a long unattended run as a
> lottery, and watch it. This is limitation #0 in
> [`../docs/experiment-engine-limitations.md`](../docs/experiment-engine-limitations.md) — it
> is not a flaw in the algorithm or in this document, and there is no workflow-level fix.

## Running it

Map the nine roles to your devices, then answer the prompts. The published parameters:

| Input | Value | Meaning |
|---|---|---|
| `od_min` | 0.03 | Below this, do nothing at all. |
| `od_thr` | 0.15 | Drug only above this. |
| `r_dil` | 0.4 | Dilution rate, 1/h. **The setpoint.** |
| `dose_ml` | 1.0 | ΔV per injection (~8% dilution of 12 ml). |
| `drug_stock_x_mic` | 10.0 | Stock A = 10× MIC. Recorded, never actuated on. |

Before your first real run, do the pre-flight of the algorithm doc §3: measure `r₀`, confirm
`r_dil ≈ r₀/2`, and determine the MIC. **`r_dil` must be less than `r₀`** or the culture washes
out no matter what you do.

To change the cycle time, edit `pace` and `count` — they are literals, not expressions, so
they cannot be operator inputs — **and remember to update the slope constant.**

## What the example deliberately does not do

- **It does not track the drug concentration.** The engine has no accumulator variable, so the
  concentration recursion of algorithm §1 cannot run inside the workflow. It does not need to:
  every injection is in the run log, so `c_k` is reconstructed offline. Nothing is faked.
- **The three tube-service subtrees are near-copies.** Groups exist but are not parametrized,
  so a single reusable `service(tube)` macro is not yet expressible.
- **There is no Stock A → Stock B escalation.** It needs a second drug line, and the
  escalation predicate is cross-cycle state the engine cannot hold.

These are engine limitations, not modelling choices, and they are catalogued in
[`../docs/experiment-engine-limitations.md`](../docs/experiment-engine-limitations.md).

## Other modes, for free

Algorithm §8: the same hardware becomes a different instrument by editing one condition.

```
MORBIDOSTAT   OD > OD_THR and r > r_dil  → drug, else medium     (this example)
CHEMOSTAT     always                     → medium                (delete the inner branch)
TURBIDOSTAT   OD > OD_TARGET             → medium, else nothing  (invert the outer branch)
```

## Verifying changes

`tests/test_examples_morbidostat.py` runs these docs against simulated cultures — exponential
growth, dilution on injection, drug inhibition — and asserts the loop actually closes: that
the controller pins each culture near its IC₅₀ instead of letting it run away. If you edit an
example, run that test.
