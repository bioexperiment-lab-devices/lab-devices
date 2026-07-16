# Example experiments

Import one of these into Experiment Studio (**Builder → Import**, or
`POST /api/experiments/import` with the file as the body), map its roles to your devices on the
preflight screen, and run it.

Both examples use `groups`, `for_each`, `compute`, and `abort`, which the block builder cannot
render yet (spec §13, "Reusable groups (GroupRef) editing"). So they import, save, validate, and
run — but the Builder canvas will refuse to open them, and Studio will tell you so when you import.
Pick them on the Run tab and edit them as JSON.

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
no reading this cycle           → nothing at all      (never decide without a reading)
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
no injection, and no drain either, so its volume is untouched. The outer `if` carries the
freshness guard as well, which is what folds the first row into the same missing `else`: a tube
that produced no reading *this cycle* takes the same no-op path. That guard is load-bearing —
see [Surviving a flaky device](#surviving-a-flaky-device).

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

- **The direction is exact.** `ln` is monotone, so `sign(d(ln OD)/dt) = sign(d OD/dt)`: this
  estimator can never disagree with the paper's about whether a culture is growing or shrinking.
- **The magnitude is the right variable.** `r = (dOD/dt)/OD` *is* the specific growth rate.

Note what that does *not* say. **The decision is not a sign test.** `r > r_dil` is a
**threshold** test at a positive setpoint, and the controller's whole purpose is to pin `r` at
that threshold — so in steady state the comparison is habitually marginal, and the magnitude
carries the decision, not the sign. That matters when the trace loses a sample; see
[Surviving a flaky device](#surviving-a-flaky-device).

The growth phase samples every tube 10 times (`dt = 1 min`, so `n = 5`), which collapses the
whole thing to one line the engine evaluates natively. The example gives that line a name — it
`compute`s the specific growth rate into a binding `r_1` once per cycle, and the decision reads
the binding:

```
compute r_1 = 24 * (mean(od_1, last=5) - mean(od_1, last=10)) / last(od_1)
branch  if  last(od_1) > od_thr and r_1 > r_dil   → drug, else medium
```

Naming it means the pace-coupled slope constant appears **once**, not inline in every branch —
and `r_1` is also `record`ed into a chartable `r_series_1` stream, so the growth rate the
controller is actually acting on is visible, not just inferred. The `24` is `60·2/(n·dt_min)`,
the unit conversion into "per hour". **If you change the sampling interval, you must change this
constant** (now in the one `compute`). In `morbidostat-demo-speed.json` the trace is sampled
every 3 s, so it is 480.

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
├─ parallel         thermostats → 30 °C          ← retry ×6 rides out a device-store race
├─ serial           measure_blank → blank_1..3   ← every later OD is relative to this
├─ operator_input   cultures_ready?  (valves physically parked at 0?)
├─ serial           home + configure the 3 valves
├─ for_each tube in [1,2,3]   compute c_tube = 0
└─ loop ×120, pace 12min                          ← one 24 h "day"
   ├─ loop ×10, pace 1min                         ← growth phase
   │  └─ parallel   for_each tube in [1,2,3]  measure od_tube  ← each read tolerated; lanes isolated
   ├─ for_each tube in [1,2,3]  group_ref service(tube)   ← guarded by count(od_tube, last=11min) > 0
   └─ parallel        park all 3 valves closed
```

The `groups.service` body — a single `branch` on the freshness guard, written **once** — is what
the `for_each` calls three times. See [The `service(tube)` macro](#the-servicetube-macro) below.

**Why the OD readings are `parallel` but the dilution pass is `serial`** — this is the most
useful thing in the example. The three densitometers are independent devices, so they can read
at once, and they *must*: the three tubes have to be sampled at the same instant for their
growth rates to be comparable. The three tubes, however, *share* the pumps and valves. Trying
to service them in parallel is not a style mistake; the engine's occupancy checker will reject
the workflow, because two lanes would be reaching for the same pump. The hardware topology
dictates the block structure, and the validator enforces it.

**Why the setup blocks look the way they do** — a subtler lesson, and one the validator will
*not* teach you. `set_thermostat`, `home`, and `configure` persist device state to a file on the
agent host, keyed by the device's *serial number*. On a test rig whose simulated devices are
clones (all three densitometers reporting the same serial), those three files are **one** file —
so setting three thermostats at once means three writers racing on it. Measured on real hardware
2026-07-14: **8/25 (32%)** failed in a dedicated baseline, **29/75 (38.7%)** consistently across
all thermostat trials that day — real, reproducible, and frequent enough to test against, but
rarer than first recorded. The first live run of this example died exactly that way, 26 s in.

The example originally serialised the whole setup to dodge it. It no longer has to: the
thermostat block is `parallel` again, with `retry: {attempts: 6, backoff: "1s"}` on each lane.
The race is transient and `set_thermostat` is an absolute setter, so re-issuing it lands the
same state. **Six attempts, not three — but not for the reason first written here.** The
original argument was that a jitterless back-off can't de-synchronize a thundering herd, so three
colliding lanes would retry in lockstep and only thin out 3 → 2 → 1 over three clean rounds.
**Measured on real hardware, that isn't what happens:** across 25 trials with `attempts: 6`, the
fault fired 9 times and produced 10 `block_retried` events — every single one `attempt: 1 of 6`.
No block ever reached attempt 2. A collision costs one loser exactly one extra second, because by
the next attempt the other writers have already released the file. `attempts: 2` would have
covered every observed case. Six stays — free headroom on a one-time block — but the reasoning is
corrected: a jitterless back-off didn't need to de-synchronize anything here, because collisions
resolved one loser at a time. The blanks and the valve `home`/`configure` stay serial: also
one-time, and there was nothing to buy back. The monitor loop was always parallel, because
`measure` is a pure read — verified over 90 concurrent calls. On real hardware with unique serials
none of this arises; details and the real fix in
[`../docs/experiment-engine-limitations.md`](../docs/experiment-engine-limitations.md).

`pace` is a floor, not a deadline: the 10 min growth phase plus a ~1.4 min dilution pass fits
inside the 12 min cycle, so cycles start exactly 12 min apart.

## The `service(tube)` macro

Earlier revisions of this example wrote the tube-1, tube-2, and tube-3 service logic out three
times — three copies of the freshness guard, the growth-rate `compute`, the drug/medium
`branch`, and the waste restore, differing only in a digit. That was flagged as an engine
limitation: groups existed but were not *parametrized*, so a single reusable macro could not
close over "which tube". It now can. The control law is written **once**, as a group taking a
`tube` parameter, and a `for_each` calls it once per tube:

```json
"groups": {
  "service": {
    "params": ["tube"],
    "body": [
      { "branch": {
          "if": "count(od_{tube}, last=11min) > 0 and last(od_{tube}) >= od_min",
          "then": [ "...growth rate, drug/medium branch, waste restore, all keyed by {tube}..." ]
      } }
    ]
  }
}
```

```json
{ "for_each": { "var": "tube", "in": [1, 2, 3],
    "body": [ { "group_ref": { "name": "service", "args": { "tube": "{tube}" } } } ] } }
```

`expand_dict` (design 2026-07-15 §4) splices this before the workflow ever executes: each
`for_each` iteration substitutes `{tube}` textually (`od_{tube}` → `od_1`, `od_2`, `od_3`; a
valve's `"position": "{tube}"` → the *string* `"1"`, which the engine evaluates as the expression
`1` — identical to the literal integer the old doc wrote by hand), and each parametrized
`group_ref` inlines as a `serial` wrapper around the substituted body. The expanded tree — what
actually runs — is behaviorally identical to the old doc's three hand-written copies;
`tests/test_examples_morbidostat.py` expands before executing and is the proof (same IC₅₀
fixed point, same recorded `c_series`, to 1e-9).

The same treatment collapses the seed `compute c_t = 0` steps and the OD-read `parallel`'s three
lanes into one `for_each` each — see [The shape of the run](#the-shape-of-the-run) above.

**This is what makes the design scale.** Going from 3 vials to 15 is now `"in": [1, 2, ..., 15]`
on three `for_each` blocks, plus 15× the stream declarations (`od_t`, `r_series_t`, `c_series_t`)
— the `service` group, the growth-rate formula, and the drug/medium decision are not touched, and
there is exactly one freshness-window constant to get right, not fifteen.

## Surviving a flaky device

A live run of the demo-speed doc once got to **cycle 17 of 25, 23 minutes in**, and was killed
by one transient `measure` fault on one densitometer — a block that had already succeeded ~170
times. The faithful doc takes **3,600 measurements** in 24 h and the published experiment runs
for **three weeks**, so a per-read fault probability of 1-in-1000 gives a 24 h run a ~97% chance
of dying.

That is fixed. The engine has `retry` and `on_error`, and this example uses both — it now runs
to completion *through* that class of fault. What follows is how to author them without hurting
a culture, because the features are small and the ways to misuse them are not.

**Measured on real hardware, 2026-07-14.** A 25-cycle run of `morbidostat-demo-speed.json` on
the same test rig completed: 25/25 cycles, 750/750 OD samples, zero dropped. Three transient
densitometer faults fired during the run — the same fault class that killed the historical run
above — and all three were cured on the first retry (`block_retried: 3`,
`block_error_tolerated: 0`). **The dosing arms were not exercised, though.** The test rig's
simulated densitometers read absorbance `0.0` on all 750 reads, so every cycle took the "too
dilute → no action" branch: no `dispense`, no valve actuation, ever, in that run. The run
validates setup, thermostats, measurement, the guard, branching, and fault tolerance end to end
on real hardware — it does not validate the pump/valve dosing arms on real hardware. That is a
property of the test rig's simulator, not of the engine or this example.

### `retry` — ride out a transient fault

```json
"defaults": { "retry": { "attempts": 3, "backoff": "2s" } }
```

A workflow-level default, applied to every `command`/`measure` that does not carry its own
policy. (You can put `retry` on a single block too; the thermostats do.)

- **`attempts` is the TOTAL number of tries**, not retries-after-the-first. `attempts: 3` means
  the block is dispatched at most three times.
- **`backoff` is a constant delay** between attempts (default `"1s"`). There is **no jitter** —
  but measured on real hardware (2026-07-14, 25 trials on the thermostat block), that did not
  produce a multi-round thundering herd: the fault fired 9 times, produced 10 retries, and every
  one was `attempt 1 of 6` — max observed retry depth **1**. The thermostat block still asks for
  6 attempts (free headroom on a one-time block), not because 3 rounds of thinning were needed —
  see "Why the setup blocks look the way they do" above for the measurement.
- Only *transient* errors are retried — a device or transport fault. An author error (unknown
  device, bad params, an empty stream window) fails immediately, because it would fail
  identically forever. An operator abort is never delayed.

### `allow_repeat` is **not** a safety feature

`retry` is a validation error on a verb the registry does not mark `retry_safe`, and
`allow_repeat: true` is the escape hatch. **It does not make the verb safe to retry.**

`pump.dispense` takes a **relative** `volume_ml`. If the job fails part-way through and the
engine retries it, the culture gets a **second dose on top of what already went in**.
`allow_repeat` says, in the document where a reviewer can see it: *I accept that a retry may
repeat this action* — which on a drug pump means *I accept that this culture may be
double-dosed.*

This example never writes it. Its four injection blocks are therefore **not retried at all**,
and that is deliberate: a workflow-wide `defaults.retry` **can never reach a non-idempotent
verb**, so the pumps are excluded from the default automatically. A missed injection costs one
cycle. A doubled one corrupts the experiment silently, which is worse.

### `on_error: "continue"` — where to put the catch

```json
{ "measure": { "device": "od_meter_1", "verb": "measure", "into": "od_1" },
  "on_error": "continue" }
```

`on_error` is legal on **any** block, and it absorbs a failure *at that block*: the rest of that
subtree is skipped and the parent moves on. Put it on the subtree that should absorb the fault,
which is rarely the block that fails.

Here it sits on each OD read, which are the three children of a `parallel` — and **`on_error` on
a parallel child isolates that lane.** The fault is absorbed inside that lane's task, so the
other two densitometers keep reading. One dead tube does not cost you the other two.

Tolerance is a scientific claim, not a robustness setting, so it is not applied uniformly:

| Block | Tolerated? | Why |
|---|---|---|
| OD reads | **yes** | A dropped sample costs one of ten in a cycle. |
| `measure_blank` | **no** | A failed blank is a setup failure. Stop before any culture is committed. |
| `set_thermostat` | **no** | A silently-unset thermostat is a scientific defect, not a lost sample. |
| the injections | **no** | A failure here means the tube's state is unknown. Do not carry on. |

That table is a **read/write split**, not a guess about which failures are likely. Which brings us
to the half of `on_error` that the rest of this document, and the design docs, and the engine
itself, will not warn you about.

### Tolerance is for READS. Never tolerate an actuation and then build on it.

Every piece of guidance above is about tolerating a **measurement**. A dropped sample costs you
*information*, and the guard idiom below is how you refuse to decide without it.

**A dropped actuation costs you the state of the world** — and the engine does not know that, the
validator cannot see it, and the very next block will run as though nothing happened.

The sharpest case, on exactly this hardware, and it is not hypothetical:

```json
{ "command": { "device": "drug_valve", "verb": "set_position", "params": { "position": 1 } },
  "on_error": "continue" },
{ "command": { "device": "drug_pump", "verb": "dispense", "params": { "volume_ml": 1.0 } } }
```

The `set_position` fails. `on_error` absorbs it. The run **carries straight on to the dispense** —
with the valve still on the **previous tube's port**. Tube 1 receives the dose meant for tube 2.
Silently: both blocks are accounted for, the run reports `completed`, and `tolerated_errors` holds
one valve error and not one word about a vial that got the wrong liquid.

> **The rule: tolerance is for reads. Tolerating a command that moves the world leaves the world
> in an unknown state, and every block after it inherits that state.**

If you tolerate an actuation anyway, **you** own the recovery — the engine will not do it for you:

- **Re-establish the state before anything depends on it.** Re-`home`, re-issue the
  `set_position`, re-`set_thermostat` — in the same subtree, *before* the block that assumes it.
- **The finalizer will not save you.** It sweeps every touched device to a safe state at **end of
  run**, not between blocks. In the twelve minutes between a tolerated valve fault and the
  finalizer, every dispense on that channel goes wherever the rotor happens to be sitting.
- **Usually the right move is to put the catch HIGHER instead** — on the whole tube-service
  subtree, not on the valve inside it. Then a failed valve skips the dispense *with* it, and the
  tube loses one cycle instead of receiving the wrong liquid. This is what "put `on_error` on the
  subtree that should absorb the fault" means in practice: **a fault inside a sequence of
  actuations is absorbed by abandoning the sequence, never by continuing it.** (It recovers
  cleanly here because `set_position` is *absolute*: the next cycle's service subtree re-issues it
  before its own dispense.)

This example therefore tolerates the three OD reads and **nothing else**. The four injection
blocks are not tolerated at all — a failure there means the tube's physical state is unknown, and
stopping beats guessing.

### The guard idiom — and the thing that will actually hurt you

A tolerated `measure` only *maybe* writes its stream, so the validator will no longer let a
later windowed read of it through unguarded. That is honest: if every read in a growth phase
failed, the stream is empty, and `mean()` over an empty window is a run-killing error — the very
failure we just removed. So you must guard the decision:

```json
{ "branch": { "if": "count(od_1, last=11min) > 0 and last(od_1) >= od_min",
              "then": [ ... the whole decision tree ... ] } }
```

**The rule: if you tolerate a `measure`, guard the read with a DURATION window —
`count(S, last=D) > 0` — sized to your control loop. Never a bare `count(S) > 0`.**

A bare `count(S) > 0` fails you twice. First, it does not prove a *duration*-windowed read is
safe (a stream can be non-empty while its last 30 minutes hold nothing) — the validator catches
that one. Second, and this is the one no validator can catch, because the workflow is perfectly
well-formed:

> **A bare `count(S) > 0` cannot see a sensor that has *newly* died.** A stream is
> **append-only**, so once a tube has read even once, `count(od_1) > 0` is true **forever**. A
> densitometer that dies at cycle 40 leaves the guard standing while `last(od_1)` and both
> trailing means freeze on the last successful trace. The condition becomes a **constant**, the
> same arm fires every remaining cycle with no feedback at all — and since a healthy vial is
> above `OD_THR` and out-growing its dilution *by construction*, the arm that latches is
> frequently **drug**. Every latched cycle walks `c_k = c_{k-1}·V/(V+ΔV) + C·ΔV/(V+ΔV)` toward
> its fixed point, which is `C`: the undiluted stock. **That is an open-loop drug injector
> running on a dead sensor. It sterilizes the vial, and the run reports `status: completed`.**
>
> Measured, tube 3's sensor killed after cycle 1: **120/120 injections were drug**, drug → 9.999
> (Stock A, 10× MIC), OD → 0.0003 — a **1,600× collapse**. It is pinned by
> `test_a_dead_sensor_does_not_latch_an_open_loop_injector`.

A duration window is what proves a sample landed **this cycle**, which no whole-stream predicate
can. Size it long enough to span one cycle's sampling and short enough to expire within one
cycle:

```
growth phase   10 samples × 1 min  =  10 min   ← age of this cycle's OLDEST sample at decision time
guard window                          11 min   ←  10 min  <  11 min  <  12 min
cycle pace                            12 min   ← a sample from the PREVIOUS cycle must not qualify
```

Too wide and you re-open the latch. Too narrow and you skip a tube that did read. The
demo-speed doc scales the same rule to `last=45s` (30 s < 45 s < 60 s). **This constant is
coupled to the pace, and nothing in the engine checks it** — it is the second of the two
hand-computed constants in these docs, and the more dangerous one.

Read the guard for exactly what it says: **a tube that produced no reading this cycle is skipped
entirely** — no injection of either kind — until it reads again. Skipping withholds the dilution
along with the drug, which does perturb the culture. It is far less bad than dosing a vial
nobody is watching.

### A dropped sample biases the growth rate — downward, and that is fine

The slope estimator assumes evenly spaced samples. Be precise about how a drop perturbs it,
because it is not what you would guess. `mean(od_1, last=10)` is a **sample** window —
`samples[-10:]` — so it always returns ten values. On a lossy cycle it therefore reaches back
**across the cycle boundary** and pulls in the previous cycle's final samples: taken *before*
that cycle's injection, ~6–8% higher in OD, and a full cycle older. The window is *wider* than
it looks, not narrower, and it straddles a dilution discontinuity.

Simulated against a true `r` of 0.8/h: one dropped sample biases `r_est` by −11.5% to +3.9%
depending where in the trace it falls (worst case **−15.5%**); three drops in one cycle, −12.6%.
Bounded, and biased **downward** — toward *withholding* drug, the conservative direction.

Why that is tolerable, honestly: **not** because the decision is a sign test — as noted above,
it is a *threshold* test at `r_dil`, and the controller pins the culture at that threshold, so
its decisions are habitually marginal and a 15% bias really can flip one. What makes it safe is
the **cost** of a flip, not its rarity. A flipped decision costs one wrong 1 ml injection; **ΔV
is identical in both arms**, so the dilution rate is untouched either way; and the bang-bang
loop self-corrects on the next clean cycle. (Simulated: a tube riding out ~40 transient faults
still lands at drug ≈ 1.24 ≈ IC₅₀ — the same place as the fault-free control.)

### Read the log before you trust a cycle

Retry and tolerance are recorded, never silent: `block_retried`, `block_error_tolerated` and
`job_poll_retried` events in the run log, and `tolerated_errors` in the run report. A run that
dropped 40 samples must not look like a clean one. It won't — but only if you look.

What is still *not* solved is catalogued as limitations #1–#8 in
[`../docs/experiment-engine-limitations.md`](../docs/experiment-engine-limitations.md). The one
that bites hardest here: the engine can survive a dead sensor, but it cannot **flag** one and
stop. Nothing wakes you up.

## Running it

Map the nine roles to your devices, then answer the prompts. The published parameters:

| Input | Value | Meaning |
|---|---|---|
| `od_min` | 0.03 | Below this, do nothing at all. |
| `od_thr` | 0.15 | Drug only above this. |
| `r_dil` | 0.4 | Dilution rate, 1/h. **The setpoint.** |
| `dose_ml` | 1.0 | ΔV per injection (~8% dilution of 12 ml). |
| `drug_stock_x_mic` | 10.0 | Stock A = 10× MIC. Recorded, never actuated on. |
| `emergency_stop` | `false` | Operator safety switch; `true` aborts before the first OD read. |

Before your first real run, do the pre-flight of the algorithm doc §3: measure `r₀`, confirm
`r_dil ≈ r₀/2`, and determine the MIC. **`r_dil` must be less than `r₀`** or the culture washes
out no matter what you do.

To change the cycle time, edit `pace` and `count` — they are literals, not expressions, so they
cannot be operator inputs — **and recompute BOTH pace-coupled constants: the slope constant
(`24`) and the guard's freshness window (`last=11min`).** Nothing checks either one. Getting the
slope constant wrong biases the decision; getting the freshness window wrong can latch a drug
pump open on a dead sensor. `OD_CEILING` (`2.0`) is a third, looser constant: it only needs to sit
above the healthy steady-state OD band (empirically `0.03`–`1.0` under the published parameters),
so it does not need recomputing on an ordinary pace change — only if you change the culture's
biology enough to shift that band.

## What the example now tracks — the drug concentration

Every serviced cycle, the workflow runs the algorithm §1 concentration recursion **inside the
run**. Each tube's concentration is a `compute` binding `c_t`, seeded to 0 before the cycle loop
and updated on whichever arm fired:

```
drug   → compute c_tube = c_tube * V/(V+dV) + drug_stock_x_mic * dV/(V+dV)
medium → compute c_tube = c_tube * V/(V+dV)
```

`V` (the working volume held by the waste needle) is itself a named `compute` constant; `dV` is
`dose_ml`. The value is `record`ed into a `c_series_t` stream each cycle, so the characteristic
**drug-concentration sawtooth is a first-class chartable stream** — no longer reconstructed
offline from the run log. The workflow now *knows the dose it is administering*, which is what
any dose-ramp or "stop when c exceeds X" controller needs. (See limitations #1 and #3, both
shipped.) The concentration update sits inside the freshness guard with everything else, so a
dead sensor freezes `c_t` rather than latching it toward the stock.

## The contamination guard, and the emergency stop

The freshness guard above answers "did this tube read this cycle?" It has nothing to say about
a tube that reads *fine* and is still wrong — a vial contaminated with something the drug does
not touch. That organism keeps out-growing its dilution no matter how much drug it gets, so the
controller's own decision tree — which only ever asks "is this tube growing faster than
`r_dil`?" — does exactly what it would for a healthy culture fighting to stay at IC₅₀: it keeps
choosing **drug**. Left alone, that walks the tube's concentration to the undiluted stock while
its OD sits stubbornly, genuinely, above the healthy band — a real vial, doing real (undesired)
biology, not a latched decision on stale data.

Each tube now latches a `contaminated_t` binding, seeded `false` alongside `c_t`:

```json
{ "compute": { "into": "od_high_t", "value": "count(od_t, last=11min) > 0 and mean(od_t, last=11min) > OD_CEILING" } }
{ "compute": { "into": "contaminated_t", "value": "contaminated_t or (od_high_t and c_t >= drug_stock_x_mic * 0.99)" } }
```

Two legs, both required, both independently corroborating evidence: the tube's *believed* drug
concentration (the same `c_t` binding the sawtooth above tracks) has walked to within 1% of the
stock — drug has been maxed out for a long stretch of cycles — **and** its OD is still stuck
above `OD_CEILING`, a value set well above the healthy steady-state band (§"Running it" below).
Either alone is not enough: a tube can transiently read high after a bad dilution, and drug
concentration alone says nothing about growth. Both together, sustained, is what "the drug
stopped working" looks like from the outside. `od_high_t` is a separate `compute` — not inlined
into the latch's own expression — because the validator's guard-propagation only threads a
`count(S, W) > 0` proof through an `and`-chain it is *itself* traversing; splitting the
freshness-guarded read into its own binding first, then referencing that plain binding from the
`or`-latch, keeps every windowed read inside an expression the validator can actually prove.

The latch is a sticky **OR**: once true, `contaminated_t or (...)` is true forever, regardless of
what the tube reads next — exactly like the `alarmed_t` latch below it, and for the same reason
the freshness guard exists: a stream is append-only, so nothing should ever be allowed to *heal*
a fact this consequential by accident.

**Fire once, not every remaining cycle.** An `alarm` is not a `branch` — it does not gate
anything, it just flags and continues (`report.alarms`) — so without an edge test it would refire
on every one of the (possibly hundreds of) remaining cycles. The idiom is alarm-on-the-edge, then
latch:

```json
{ "alarm": { "if": "contaminated_t and not alarmed_t", "message": "tube t contaminated - dropped from service" } }
{ "compute": { "into": "alarmed_t", "value": "alarmed_t or contaminated_t" } }
```

**Drop from service.** A contaminated tube must never be dosed again — dosing it teaches you
nothing and wastes reagent on a vial that is not the experiment anymore. The entire pre-existing
decision tree (freshness branch, growth-rate compute, drug/medium arm, waste restore, the
`c_series` record) is now wrapped:

```json
{ "branch": { "if": "not contaminated_t", "then": [ /* everything the tube used to always do */ ] } }
```

On the healthy path this branch is a no-op: `contaminated_t` stays `false`, so `not contaminated_t`
is always `true`, and the wrapped body runs exactly as before — the contamination machinery is
inert until real evidence says otherwise.

**Two whole-run `abort`s, at the very top of the cycle** (before the growth-phase OD reads):

```json
{ "abort": { "if": "emergency_stop", "message": "operator emergency stop" } }
{ "abort": { "if": "contaminated_1 and contaminated_2 and contaminated_3", "message": "all vials contaminated - nothing left to run" } }
```

`emergency_stop` is a plain `operator_input` bool, answered once at setup (`false` for a normal
run). The second condition is the natural consequence of the drop-from-service design: once
every tube has been independently dropped, the run has nothing left to do, and continuing would
just burn 12-minute cycles measuring three tubes nobody is servicing.

**The honest gap.** The preprod hardware's OD sensors, per the site's simulated backend, read
`0.0` — so `mean(od_t, ...) > OD_CEILING` can never fire there, and the contamination latch
cannot be proven live on that hardware. What *can* be proven live is the operator's own
`emergency_stop` switch: that is Task 9's job. This task's proof of the contamination path is
entirely in `tests/test_examples_morbidostat.py`, against a FakeLab culture that is genuinely
resistant to the drug (`ResistantCulture`/`ContaminatedLab`) — its growth rate never responds to
`drug`, so both legs of the predicate become true from real, independently-arrived-at simulated
biology, not from a rigged or stale reading. `test_contaminated_tube_is_alarmed_and_dropped_from_service`
pins it: the contaminated tube alarms exactly once and stops receiving injections, while its two
healthy neighbours are serviced on every one of the 120 cycles. `test_operator_emergency_stop_aborts_and_finalizes`
pins the other abort: the run stops before the first OD read, and the finalizer still sweeps the
thermostats back off.

## What the example deliberately does not do

- **There is no Stock A → Stock B escalation.** It needs a second drug line, and the
  escalation predicate is cross-cycle state the engine cannot hold.
- **A tube whose sensor merely goes dark is still not alarmed.** The freshness guard means it is
  *skipped* safely rather than dosed blindly, and the run keeps going — but nothing raises the
  alarm for *that* failure mode specifically (only for a tube that reads fine and is
  contaminated). Check `tolerated_errors` for a dark sensor; check `report.alarms` for
  contamination.

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
growth, dilution on injection, drug inhibition — and asserts the loop actually closes: that the
controller pins each culture near its IC₅₀ instead of letting it run away. It also pins the
fault tolerance described above: that a run survives the transient fault that killed the live
one, that a lane failure does not take its siblings down, and — most importantly — that **a dead
sensor does not latch the drug pump open**. If you edit an example, run that test. If you widen
or delete a guard's freshness window, that last test is the one that will catch you.

Two more tests pin the guard added above. `test_contaminated_tube_is_alarmed_and_dropped_from_service`
drives a `ResistantCulture` — a FakeLab culture whose growth never responds to drug — through the
full 120-cycle faithful doc: the contaminated tube alarms exactly once, its `contaminated`
binding latches, and it stops receiving injections while its two healthy neighbours are serviced
on every remaining cycle. `test_operator_emergency_stop_aborts_and_finalizes` answers
`emergency_stop=true` at setup and asserts the run raises `AbortSignalError`, reports
`status: "aborted"`, never reads a single OD, and still runs the finalizer's thermostat sweep. If
you touch `OD_CEILING`, the `drug_stock_x_mic * 0.99` stock ceiling, or the drop-from-service
wrap, these are the tests that will catch you.
