# Experiment engine — known limitations

Found while implementing the morbidostat example (`examples/morbidostat.json`) — a real
closed-loop evolution experiment, and the most demanding workflow the engine has been asked to
express so far. Everything here is a limitation I actually hit, with what it cost and what
would fix it. Nothing is speculative.

The headline: **the morbidostat is fully implementable today.** Every limitation below had a
workaround — every one except #0, which had none at all. But the workarounds cluster, and the
cluster has a shape — the engine can *read* state richly and *act* on it, but it cannot *hold*
derived state or *abstract over* repetition.

Ranked by what they would actually unlock.

**Update, 2026-07-14: #0 shipped.** It was the one with no workaround, and the only one that
made the example unusable for its actual purpose. It is now closed. **Update, 2026-07-15:** #1 and
#3 (computed bindings/streams, Increment 6) and #4 (parametrized groups, Increment 7) have since
shipped too — see their sections; #2 and #5–#8 remain open, and everything written about those
still holds. **Update, 2026-07-16:** #7 (`abort`/`alarm`, Increment 8) has since shipped too — see
its section; #2, #5, #6, and #8 remain open, and everything written about those still holds.
**Update, 2026-07-20:** #4 (parametrized groups) was re-shipped typed (Increment 9) — see its
section; #2, #5, #6, and #8 remain open, and everything written about those still holds.

---

## 0. No retry, and no tolerance for a transient device fault — **FIXED (2026-07-14)**

**This was the one that mattered most, and the only one that made the example unusable for its
actual purpose.** It was found by running the example on real hardware, not by reading the
code. The engine now has retry, error tolerance, per-device fault isolation, and resilient job
polling. Design: [`superpowers/specs/2026-07-14-engine-fault-tolerance-design.md`](superpowers/specs/2026-07-14-engine-fault-tolerance-design.md).

The incident stays here, because it is the whole reason any of this exists, and because it is
what the shape of the feature is answering.

**Where it bit.** The live run of the demo-speed doc on `windows_arm64_test_client` reached
**cycle 17 of 25 — 23 minutes in — and then died** on a single flaky read:

```
block_failed  blocks[0].children[10].body[0].body[0].children[0]
  "intensity array: record header/index mismatch (button interference?)"
```

One densitometer, one measurement, one transient firmware hiccup. Nothing was wrong with the
workflow — the same block had already succeeded about 170 times. The run was destroyed anyway,
and every culture in it with it.

Now scale that. The faithful doc takes **3,600 measurements** over 24 h. The published
experiment runs for **three weeks**. A per-measurement fault probability of even 1-in-1000
gives a ~97% chance of losing a 24 h run, and a rounding error's chance of surviving three
weeks. It was never that the algorithm was hard to express — it isn't; the rest of this
document is a footnote by comparison — it was that the engine treated a flaky sensor read as
fatal, and the author had no lever at all: a workflow could not catch, could not retry, could
not skip a cycle.

### What shipped

- **`retry: {attempts, backoff, allow_repeat}`** on `command` and `measure`. A transient device
  or transport error is re-dispatched from scratch; an author error (`InvalidParams`,
  `UnknownDevice`, an empty-window `EvaluationError`) is not, because it would fail identically
  forever. An operator abort and an `InvariantViolationError` escape *both* mechanisms — they
  are never retried and never tolerated.
- **`on_error: "fail" | "continue"`** on **any** block. `"continue"` absorbs a failure at that
  block: the rest of that subtree is skipped and the parent moves to the next sibling. It is a
  *catch*, and where you put it is the whole design decision.
- **Per-device fault isolation.** `on_error: "continue"` on a **child of a `parallel`** absorbs
  the fault inside that lane's task, so the `TaskGroup` never sees an exception and the sibling
  lanes keep running. One bad vial no longer kills the other fourteen. This is feature 3 of the
  three I asked for, and it cost nothing — it fell out of the `TaskGroup` for free.
- **Workflow-level `defaults: {retry: {...}}`** — applies to every `command`/`measure` without
  its own policy. It is what makes this usable at 15 vials while #4 (groups are not
  parametrized) is still open; without it the faithful doc would carry ~60 hand-copied clauses.
  It carries `retry` only, never `on_error`: a blanket "tolerate everything" would silently make
  a missed *injection* survivable, and where tolerance sits is a per-subtree scientific choice.
- **Resilient job polling.** A transient failure of a `get_job` poll no longer abandons a live
  job — the engine keeps polling, up to `RunOptions.job_poll_max_failures` (default 5)
  *consecutive* failures, and logs `job_poll_retried`. A flaky poll on a dispense that is
  physically running is exactly the fault you least want to react to by giving up.
- **Reporting.** `RunReport.tolerated_errors`, plus `block_retried`,
  `block_error_tolerated` and `job_poll_retried` run-log events, all surfaced in Studio. A run
  that dropped 40 samples must not look identical to a clean one. `status` stays `"completed"` —
  the information is in the field, not in a fifth status.

`examples/morbidostat.json` is the proof: it now runs to completion *through* the class of fault
that killed it, and the one-time thermostat setup went back to being `parallel` (see the
duplicate-serial section below — retry rides the race out).

**Measured on real hardware, 2026-07-14.** A 25-cycle run of `morbidostat-demo-speed.json` on
`windows_arm64_test_client` completed: 25/25 cycles, 750/750 OD samples recorded, zero dropped.
Three transient densitometer faults fired during the run — the same fault class that killed the
historical cycle-17 run above — and all three were cured on the first retry (`block_retried: 3`,
`block_error_tolerated: 0`). The parallel thermostat race did not even fire this run; it happened
to win clean.

**Honest gap: dosing was never exercised.** The test client's simulated densitometers read
absorbance **0.0** on all 750 reads, so every cycle took the "too dilute → no action" branch —
no `dispense`, no valve actuation, ever, in this run. The run validates setup, thermostats,
measurement, the freshness guard, branching, and fault tolerance end to end on real hardware. It
does **not** validate the pump/valve dosing arms on real hardware. That gap is a property of the
test rig's simulator, not of the engine, and "runs to completion" above should be read for what
it actually covers.

### How to use it without hurting a culture

This is the part that matters. The features are small; the ways to misuse them are not.

**`retry`.**

```json
{ "measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"},
  "retry": {"attempts": 3, "backoff": "2s"} }
```

`attempts` is the **total** number of tries, not retries-after-the-first — `attempts: 3` means
the block is dispatched at most three times. (My original sketch said `times: 3`, which is
ambiguous, and on a `pump.dispense` that ambiguity is a dosing hazard.) `backoff` is a
**constant** delay between attempts, default `"1s"`. There is no jitter. I originally argued from
that fact that the example's thermostat block, whose three lanes contend on one file, needed
**6** attempts rather than 3: a jitterless back-off cannot de-synchronize a thundering herd, so
three lanes that collide would retry together, and the contending set would only thin out as
each round's winner drops out (3 → 2 → 1) — three clean rounds needed, so 3 attempts would leave
exactly zero headroom.

**That argument is wrong, and measured hardware says so.** Across 25 trials with `attempts: 6`
on this exact roster (2026-07-14), the fault fired in 9 and produced 10 `block_retried` events —
**every one of them `attempt: 1 of 6`.** Not one block ever reached attempt 2. A collision
produces **one loser at a time**, and that loser wins on its very next attempt, one second later,
because by then the other writers have already finished and released the file. `attempts: 2`
would have sufficed in every observed trial. **`attempts: 6` stays** — it is free headroom on a
one-time block and costs nothing — but the reasoning that used to justify it was speculative and
is now known to be false. State what was actually measured, not the thundering-herd story.

**`allow_repeat` is not a safety feature.** `retry` on a verb the registry does not mark
`retry_safe` is a validation error, and `allow_repeat: true` is the escape hatch. It does not
make the verb safe. `pump.dispense` takes a **relative** `volume_ml`: if the job fails partway
through and you retry it, the culture gets a **second dose on top of what already went in**.
`allow_repeat` says, in the document, where a reviewer can read it: *I accept that a retry may
repeat this action.* On a drug pump that means: *I accept that this culture may be
double-dosed.* Write it only when you mean it. A workflow-wide `defaults.retry` can never reach
such a verb — a default silently does not apply to a non-`retry_safe` verb, and it is a
validation error for a default to carry `allow_repeat` at all.

**`on_error`.** Put it on the subtree that should *absorb* the fault, which is rarely the block
that fails.

```json
{ "measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"},
  "on_error": "continue" }
```

On a `measure` inside a `parallel`, that costs one sample in one lane and the other two tubes
read on. On a whole tube-service subtree, a fault costs that tube one cycle rather than the
experiment. On the `parallel` block *itself* it means something quite different — the container
is abandoned and its surviving lanes are cancelled — so the placement is the semantics, not a
detail. And tolerance is a scientific statement: in the example the OD reads are tolerated, the
**blanks are not** (a failed blank is a setup failure and must stop the run before any culture
is committed) and the **thermostat is not** (a silently-unset thermostat is a scientific
defect).

### Tolerance is for reads. I did not write this down, and it is the sharper hazard.

Everything above — and everything in the design doc, and everything in the example's prose — is
about tolerating a **measurement**. Not one line of it warns about the other half, so here it is,
because it is the more dangerous of the two and I only saw it on the way out:

> **`on_error: "continue"` on a command that moves the world leaves the world in an unknown
> state, and every block after it inherits that state.**

The case that makes it concrete, on exactly the hardware this document is about:

```json
{ "command": {"device": "valve_2", "verb": "set_position", "params": {"position": 1}},
  "on_error": "continue" },
{ "command": {"device": "pump_2", "verb": "dispense", "params": {"volume_ml": 1.0}} }
```

The `set_position` fails, the tolerance absorbs it, and the run **proceeds to the dispense** —
with the valve still on the **previous tube's port**. The drug goes into the wrong vial. Nothing
in the run says so: both blocks are accounted for, the status is `"completed"`, and
`tolerated_errors` holds one valve error and no hint whatsoever that a dose landed in a tube that
was not supposed to receive it. A tolerated *read* costs a sample, and the guard idiom below is
how you refuse to decide without one. A tolerated *actuation* costs the integrity of the
experiment, and it costs it silently — there is no guard idiom for it, because the damage is done
before any expression is evaluated.

The engine will not repair this. There is no automatic re-home, no state reconciliation between
blocks, and the finalizer — the one mechanism that *does* sweep every touched device back to a
safe state — runs at **end of run**, not between blocks. Between a tolerated valve fault and the
finalizer sits every dispense of every remaining cycle, each one going wherever the rotor happens
to be.

So if you tolerate an actuation, you own re-establishing the state — re-`home`, re-`set_position`,
re-`set_thermostat` — *before* anything depends on it. Better still, do not tolerate the actuation
at all: put the catch **higher**, on the whole subtree the actuation serves, so the fault skips
the dependent blocks along with it. That is what the example does. Its OD reads are tolerated and
nothing else is; its four injection blocks fail the run outright, because a failure there means
the tube's physical state is unknown and I would rather stop the run than guess at it.

### The guard idiom, and its sharpest edge

A tolerated `measure` only *maybe* writes its stream, so the path analyzer stops being able to
prove the stream non-empty, and it rejects any later windowed read of it. That rejection is
honest — if every read in a growth phase failed, the stream *is* empty, and a `mean()` over an
empty window is a run-killing `EvaluationError`, which is the exact failure this feature exists
to remove. So the author's obligation is to **guard the read**, and the validator's job is to
check they did:

```json
{ "branch": {"if": "count(od_1, last=11min) > 0 and last(od_1) >= od_min",
             "then": [ ... the whole decision tree ... ]} }
```

**The rule: if you tolerate a `measure`, guard the read with a DURATION window** —
`count(S, last=D) > 0` — **sized to your control loop.** Not a bare `count(S) > 0`.

Two reasons, and the second one is the one that will hurt you.

1. **A bare `count(S) > 0` does not discharge a duration-windowed read.** A stream can be
   non-empty while its last 30 minutes hold nothing. The validator knows this (`analyze.py`'s
   `proof_covers`) and will reject the pairing, so this one you find out about at load.
2. **A bare `count(S) > 0` cannot detect a sensor that has *newly* died** — and *this* one the
   validator cannot help you with, because the workflow is perfectly well-formed. `Stream` is
   **append-only**, so `count(S) > 0` is a whole-stream predicate: once a tube has read even
   once, it is true **forever**. A densitometer that dies at cycle 40 leaves the guard standing
   while `last(od)` and both trailing means freeze on the last successful trace. The control
   expression becomes a **constant**, the same branch fires every remaining cycle with no
   feedback at all — and because a healthy vial is above `OD_THR` and out-growing its dilution
   *by construction*, the arm that latches is frequently **drug**. Each latched cycle applies
   the concentration recursion `c_k = c_{k-1}·V/(V+ΔV) + C·ΔV/(V+ΔV)`, whose fixed point is `C`:
   the undiluted stock. That is an **open-loop drug injector running on a dead sensor.** It
   sterilizes the vial and the run still reports `status: "completed"`. Measured, on the
   faithful doc with tube 3's sensor killed after cycle 1: **120 of 120 injections were drug**,
   drug concentration → **9.999** (= Stock A, 10× MIC), OD → **0.0003** — a **1,600× collapse**.
   That is the regression test `test_a_dead_sensor_does_not_latch_an_open_loop_injector`.

A duration window is what lets the guard see a *newly* dead sensor: it proves a sample landed
during **this cycle**, which no whole-stream predicate can. Size it to the control loop —
**long enough to span one cycle's sampling, short enough to expire within one cycle**:

```
growth phase   10 samples × 1 min = 10 min   ← the age of this cycle's OLDEST sample
guard window                        11 min   ← 10 min  <  11 min  <  12 min
cycle pace                          12 min   ← a sample from the PREVIOUS cycle must not qualify
```

Too wide and you re-open the latch. Too narrow and you skip a tube that did in fact read. In
`morbidostat-demo-speed.json` the same rule gives `last=45s` (30 s < 45 s < 60 s).

Then read the guard for what it actually says: **a tube that produced no reading this cycle is
skipped entirely** — no injection of either kind — and stays skipped until it reads again.
Skipping withholds the dilution as well as the drug, which does perturb the culture. It is far
less bad than dosing a vial nobody is watching.

### The dropped-sample caveat

Tolerating a read means the trace can lose samples, and the morbidostat's slope estimator
(§2) assumes evenly spaced ones. It is worth being precise about *how* a drop perturbs it,
because it is not what you would guess. `mean(od, last=10)` is a **sample** window —
`samples[-10:]` over an append-only stream — so it always returns ten values. On a lossy cycle
it therefore reaches back **across the cycle boundary** and pulls in the previous cycle's final
samples: taken *before* that cycle's injection, ~6–8% higher in OD, and a full cycle older. The
span is *longer* than it looks, not shorter, and it straddles a dilution discontinuity.

Simulated on the faithful doc against a true `r` of 0.8/h: one dropped sample biases `r_est` by
−11.5% to +3.9% depending on where in the trace it falls (worst case −15.5%); three drops in one
cycle, −12.6%. Bounded, and biased **downward** — toward *withholding* drug, the conservative
direction.

Why that is tolerable, stated honestly: **not** because the decision is a sign test. It is not.
`24 * (mean(last=5) - mean(last=10)) / last(od) > r_dil` is a **threshold test at `r_dil`**, and
by the controller's own design invariant (`r_dil = r₀/2`) the culture is pinned *at* that
threshold in steady state — so its decisions are habitually marginal, which is exactly the
regime in which a 15% bias can flip one. What makes it safe is the **cost** of a flip, not its
rarity: a flipped decision costs one wrong 1 ml injection; ΔV is identical in both arms, so the
dilution rate is untouched either way; and the bang-bang loop corrects itself on the next clean
cycle. (Simulated: a tube riding out ~40 transient faults still lands at drug ≈ 1.24 ≈ IC₅₀ —
the same place as the fault-free control.) Retry makes drops rare to begin with, and every one
is in the run log.

### What is still not solved

- **The guard's freshness window is a pace-coupled constant, and nothing checks it.** It is the
  same class of sharp edge as the slope constant of #2: change either loop's `count` or `pace`
  and *two* constants must be recomputed by hand. The engine has no freshness primitive and no
  way to derive one from a loop's own pace. A guard that is silently too wide is an open-loop
  drug injector, which makes this the most dangerous unchecked constant in the document.
- **A `measure` whose job is still tracked when it fails is not retried at all.** The executor
  refuses a retry whose orphan-clearing `stop` would close an open mode, and a densitometer's
  `stop` closes optics *and* thermal — so on a rig where `set_thermostat` holds a thermal mode
  open, a job **timeout** or an exhausted poll budget falls straight through to `on_error` and
  costs its sample rather than being retried. The incident's actual fault (the job reports
  `failed`, which untracks it before the error surfaces) *is* retried, which is the case that
  mattered. But the coverage is not uniform, and the reason is invisible in the document.
- **A stranded channel is never reclaimed mid-run.** When a job is abandoned while still
  *physically running* — a job timeout, an exhausted poll budget, or a cancellation landing on a
  live job — the engine keeps that job's `(device, channel)` slots held. That is deliberate:
  nothing may dispatch on top of a job that is still on the hardware. But the engine has also
  stopped polling that job, so if it later finishes on its own **the engine never notices**, and
  every later block on those channels is refused (`OrphanedJobError`) **for the rest of the run**.
  Only a device-wide `stop` that actually succeeds hands the channels back — the retry's
  orphan-clear, or the finalizer at end of run — and a workflow's *own* `stop` block on that
  device would itself be refused by the strand. It fails safe (a refusal before the wire, never a
  second job stacked on a live one), but it is permanent, and one stranded channel means that
  device is dark until the run ends.

  **The sharp edge is `on_error` on a `parallel` *container*.** Put the tolerance on the
  container rather than on its lanes and a *failing* lane cancels its *innocent* siblings (that
  is what a `TaskGroup` does with a raising child); the cancellation lands inside a sibling's
  live job, that job is stranded, and the container's tolerance then absorbs the whole group. A
  perfectly healthy device goes dark for the remainder of the run — every later block on it
  refused — while the run still reports `"completed"`. **If you want per-device isolation, put
  `on_error` on the lanes, not on the container.** A tolerated lane absorbs its own fault inside
  its own task, so the `TaskGroup` never sees an exception at all and no sibling is ever
  cancelled. The shipped `morbidostat.json` does exactly that — all three of its `on_error`s sit
  on the `measure` lanes of the OD `parallel`, never on the `parallel` itself — which is why it
  is not affected.
- **Back-off has no jitter**, so it cannot de-synchronize contending lanes (above).
- **A tolerated block may leave a device mid-operation** — a pump that failed part-way through
  a dispense, or a valve that never reached the port the *next* block is about to pump into
  ("Tolerance is for reads", above). The finalizer sweeps every touched device at run end, but
  *within* the run the next block simply proceeds, on whatever physical state the failure left
  behind. Nothing re-establishes it and nothing warns. Writing `on_error: "continue"` on an
  actuation is accepting that, and there is no validator check and no guard idiom that can make
  it safe for you.
- **There is still no way to stop.** A run can now survive a dead sensor; it cannot *flag* one
  and halt. `tolerated_errors` is a post-hoc record — nothing wakes the operator. That is #7
  (no abort/alarm block), and this feature makes it *more* wanted, not less: the failure mode
  above ("completed", with a sterilized vial) is precisely what an `alarm` block is for.
- **#1–#8 below are all still open.** Retry does not give the engine a memory, a `slope`
  function, a computed stream, or a parametrized group.

---

## 1. No computed bindings (no accumulator) — **SHIPPED (2026-07-15)**

**Shipped as the `compute` block** (Increment 6), together with #3. Design:
[`superpowers/specs/2026-07-15-experiment-orchestrator-6-computed-values-design.md`](superpowers/specs/2026-07-15-experiment-orchestrator-6-computed-values-design.md).
`{compute: {into: "c", value: "<expr>"}}` evaluates an expression and binds the result (a number
**or** a boolean) into the same namespace `operator_input` writes; the binding survives across
loop iterations, so the same `compute` run each cycle **is** the accumulator. An unseeded
self-referential accumulator is a read-before-write load error, so the seed (a plain `compute`
before the loop) is checked, not assumed. `examples/morbidostat.json` now runs the concentration
recursion below inside the workflow and knows the dose it is administering; the escalation counter
is now expressible too. The original problem statement is kept below as motivation.

**What.** Bindings are written only by `operator_input`. Streams are written only by a
`measure` on a real device. There is no block that computes a value and names it. Nothing in a
workflow can carry a derived number from one cycle to the next.

**Where it bit.** The morbidostat's drug concentration obeys a recursion (algorithm §1):

```
INJECT_DRUG :   c_k = c_{k-1}·V/(V+ΔV) + C·ΔV/(V+ΔV)
INJECT_MEDIUM:  c_k = c_{k-1}·V/(V+ΔV)
```

This cannot run inside the workflow. The example therefore **does not know the drug
concentration it is administering** — it is reconstructed offline from the run log. That is
acceptable for the published algorithm (which is bang-bang and needs no `c`), but it rules out
the entire class of controllers that *do*: anything with an integral term, any dose ramp, any
"stop when c exceeds X".

It also means no counters. "How many drug injections in a row?" is not expressible, which is
precisely the predicate the Stock A → Stock B escalation rule needs.

**Workaround used.** Reconstruct `c_k` offline. Document it honestly in the example.

**Suggested feature.** A `compute` (or `let`) block: `{compute: {into: "c", value: "<expr>"}}`,
writing a binding readable by later expressions. Its value must survive across loop iterations
for this to be worth anything. This is the single highest-leverage addition on this list —
it turns the engine from a reactive sequencer into a controller.

---

## 2. Expressions have no math functions

**What.** The expression sublanguage has exactly five stat functions — `last`, `mean`, `min`,
`max`, `count` — over stream windows, plus `+ - * /`, comparisons, and `and/or/not`. There are
no scalar functions at all: no `ln`, `exp`, `abs`, `sqrt`, `pow`, no two-argument `min`/`max`.

**Where it bit.** The algorithm specifies a robust linear regression of **`ln OD`** against
time. Neither the `ln` nor the regression is expressible.

**Workaround used.** A difference-of-means slope estimator, which turns out to be exact:

```
m = 2·(mean(last=n) − mean(last=2n)) / (n·dt)        and        r = m / OD
```

This is genuinely faithful — `ln` is monotone, so the *sign* of the slope (which is what the
decision tests) is preserved exactly, and `r = (dOD/dt)/OD` *is* the specific growth rate. But
it cost a derivation, and it leaves a magic unit-conversion constant (`24`) hard-coded in the
branch condition that **silently becomes wrong if the sampling interval is changed.** That is a
sharp edge pointed straight at the user.

**Suggested features, in order of value:**
- `slope(stream, last=N)` as a stat function. This is the primitive the whole class of
  growth-rate controllers wants, and it would delete the derivation *and* the magic constant.
- `median(stream, window)` — the paper median-filters its raw signal; `mean` is the wrong tool
  against the electrical spikes that clumping actually produces.
- `stddev` — the natural way to express "the reading is unstable, don't trust it".
- Scalar `ln`, `exp`, `abs`. `abs` alone would make tolerance bands expressible.

---

## 3. Streams cannot hold computed values — **SHIPPED (2026-07-15)**

**Shipped as the `record` block** (Increment 6), together with #1. Design:
[`superpowers/specs/2026-07-15-experiment-orchestrator-6-computed-values-design.md`](superpowers/specs/2026-07-15-experiment-orchestrator-6-computed-values-design.md).
`{record: {into: "r_1", value: "<expr>"}}` appends a computed number to a **declared** stream via
the identical data path a `measure` uses — same in-memory stream, same disk sink — so a computed
quantity is charted, CSV-exported, and readable by later expressions for free. A stream is
written by `measure` **or** `record`, never both. `examples/morbidostat.json` now records both the
growth rate (`r_series_t`) and the drug concentration (`c_series_t`), so the characteristic
drug-concentration sawtooth is a first-class chartable stream. The original problem statement is
kept below as motivation.

**What.** `measure.into` requires a device verb whose trait is a measurement. There is no way
to append a derived number to a stream.

**Where it bit.** The two most scientifically interesting quantities in the morbidostat — the
**growth rate** and the **drug concentration** — cannot be recorded as streams. So they cannot
be charted. Studio's live chart shows raw OD and nothing else; the operator watches the input
to the controller and never sees the controller's own state. A morbidostat's characteristic
plot is the drug-concentration sawtooth, and this example cannot draw it.

**Workaround used.** None available. Labels on the injection blocks make the run log readable,
and the quantities are recovered offline.

**Suggested feature.** A `record` block — `{record: {into: "r_1", value: "<expr>"}}` — writing
a computed sample into a declared stream. It composes with #1 and #2 and would immediately make
derived quantities first-class in the chart, the CSV export, and later expressions. Cheap
relative to its payoff.

---

## 4. Groups are not parametrized — **SHIPPED (2026-07-15)**

**Shipped as `for_each` + parametrized groups** (Increment 7), then **re-shipped typed**
(Increment 9, 2026-07-20). Designs:
[`superpowers/specs/2026-07-15-experiment-orchestrator-7-parametrized-repetition-design.md`](superpowers/specs/2026-07-15-experiment-orchestrator-7-parametrized-repetition-design.md)
and
[`superpowers/specs/2026-07-20-typed-group-parameters-design.md`](superpowers/specs/2026-07-20-typed-group-parameters-design.md).
Current syntax lives in [`workflow-schema.md`](workflow-schema.md) — read that, not this.

Increment 7 shipped the macros untyped: `params` was a `list[str]` and `for_each` took a scalar
`var` over a bare item list, so a hole was a bare textual macro interpolated into every string
in the body. That worked and it scaled the control law from three hand-copied subtrees to one,
which is what this limitation asked for. What it could not do was *check* anything: in
`examples/morbidostat.json` the single `tube` param was simultaneously a stream suffix
(`od_{tube}`), a binding suffix (`c_{tube}`), an `int` verb param (`position: "{tube}"`), and a
role suffix (`od_meter_{tube}`), and none of those is a name until expansion has already
produced one. A typo was not a load error; it was a residual-hole error at some expanded index,
or a silently valid name that read another tube's data.

Increment 9 gives each of those four things a kind. `params` is an ordered list of typed
declarations, `for_each` takes `vars` + a typed row table (the scalar shorthand is removed), and
`groups` gain `locals` — the streams and bindings a group owns, emitted under a qualified
instance name (`tube_1_c_series`) and seeded by a constant `init` that the expander hoists,
which is what deleted the doc's hand-written seeding `for_each`. Roles moved into the workflow
in the same increment, so a `role<densitometer>` column replaces `od_meter_{tube}` string
surgery. Everything is checked before expansion; `schema_version` is `2` and v1 documents using
`groups` or `for_each` do not load, because their param types were never recorded.
(Stream declarations are no longer hand-written per tube where a group owns them — that half of
the old caveat is closed; streams a group merely *reads* are still declared explicitly.)

**What.** `groups` + `group_ref` exist, but a group takes no arguments. Its body hard-codes its
device roles and stream names.

**Where it bit.** The three tube-service subtrees in the morbidostat are near-identical —
same logic, differing only in tube index (1/2/3), stream (`od_1/2/3`), and valve position.
They cannot be one reusable `service(tube)` macro, so the doc carries three copies. Edit the
control law and you must edit it three times, identically, by hand.

The published experiment runs **15 vials.** At 15 copies this stops being an inconvenience and
becomes a correctness hazard, and it is the single reason this example is capped at three.

**Suggested feature.** Group parameters and `group_ref` arguments, with substitution into
device roles, stream names, and expression text. Already on the v2 backlog as "parametrized/
macro groups" — this example is the concrete argument for it. A `for_each` block over a list of
parameter bindings would subsume it and is what the 15-vial case really wants.

---

## 5. `enum` operator inputs are unusable in expressions — **SHIPPED (2026-07-21)**

**Shipped in Increment 10 (Engine A, the type-system lattice).** Design:
[`superpowers/specs/2026-07-21-experiment-type-system-design.md`](superpowers/specs/2026-07-21-experiment-type-system-design.md).
The expression language now has **single-quoted string literals** (`'chemostat'`) and
**string equality** (`==` / `!=` over strings), so an `enum` operator input is branchable:
`{"branch": {"if": "mode == 'chemostat'", ...}}`. The type checker tracks a `string` type end
to end — a string still may not be used in arithmetic or a mixed string/number comparison, and
that is now caught at **load** time rather than mid-run — and the evaluator compares two strings
directly. `mode == 'chemostat'` uses single quotes precisely so it needs no escaping inside the
JSON string that carries the expression. The original problem statement is kept below as
motivation.

**What.** An `operator_input` of type `enum` binds a **string**. The evaluator rejects string
bindings outright (`binding 'x' holds a string; expressions evaluate numbers and booleans`),
and the static analyser flags them too. So an enum choice can be *collected* and *logged*, but
never *branched on*.

**Where it bit.** Algorithm §8 notes that the same hardware is a morbidostat, a chemostat, or a
turbidostat depending on one conditional. The natural design is an enum input — "Mode?" —
branched on at the top of the cycle. That is not expressible. The example instead documents
the source edit required to switch modes.

More generally: *no operator choice can ever influence control flow*, unless it is squeezed
through a `bool` (two-way only) or a magic-number `float`. This makes `enum` close to a
decorative type.

**Suggested feature.** String equality/inequality in expressions (`mode == "chemostat"`). The
type checker already tracks a `string` binding type, so this is a narrow, well-scoped change
with an outsized effect on how configurable a single doc can be.

---

## 6. Durations and counts are literals, not expressions

**What.** `loop.pace`, `loop.count`, `wait.duration`, `gap_after`, and `start_offset` are all
parsed as literals. They cannot be expressions, so they cannot reference bindings.

**Where it bit.** Cycle time (`12min`) and cycle count (`120`) are the two parameters a user is
most likely to want to change, and they are the only two that **cannot be operator inputs**.
They must be edited in the document. Worse, cycle time is coupled to the magic slope constant
of #2, so the edit is two fields that must be changed consistently — with nothing enforcing it.

It also rules out adaptive timing: "sample faster while the culture is growing quickly" is not
expressible.

**Suggested feature.** Allow expressions in duration and count slots, resolved at loop entry
(and per-iteration for `pace`). The evaluator and the `_check_kind` coercion machinery already
exist; this is mostly a validator and serializer change.

---

## 7. No abort or assert block — **SHIPPED (2026-07-16)**

**Shipped as the `abort` and `alarm` blocks** (Increment 8). Design:
[`superpowers/specs/2026-07-16-experiment-orchestrator-8-abort-alarm-design.md`](superpowers/specs/2026-07-16-experiment-orchestrator-8-abort-alarm-design.md).
`{abort: {if: "<expr>", message: "..."}}` and `{alarm: {if: "<expr>", message: "..."}}` share the
exact condition-evaluation path `branch.if` already uses — same parser, same type-check, same
freshness/read-before-write path analysis — and differ only in what they do when the condition is
true. `abort` emits `abort_raised` and raises a new `AbortSignalError`: never retried, never
tolerated by any enclosing `on_error: "continue"` (not even inside a `parallel` lane —
`_tolerable`'s never-absorb list and the exception-group flattening both refuse to swallow it),
and it unwinds the block tree so the existing finalizer sweeps every touched device to a safe
state; the run ends with status **`"aborted"`** — the same status an operator-triggered abort
already used, distinguished only by the `AbortSignalError` type and the `abort_raised` event, not
by a new status string. `alarm` is the flag-and-continue sibling: it emits `alarm_raised`, appends
an `AlarmRecord` to `RunReport.alarms`, and returns normally so the run keeps going — deliberately
**stateless** (it fires every cycle its condition holds), with fire-once expressed by composing it
with a `compute`-latched boolean rather than a built-in flag. Both require a non-empty `message`;
`abort` additionally forbids `on_error: "continue"` (tolerating a safety stop is a contradiction),
while `alarm` allows it. `examples/morbidostat.json` now expresses the contamination guard this
section was filed for: a latched `alarm` flags a contaminated tube and drops it from service while
the others run on, and a whole-run `abort` fires once every tube is lost. **Honest gap:** the test
rig's simulated densitometers read absorbance 0.0 on every sample, so the contamination predicate
itself cannot fire on real hardware — that path is proven in FakeLab integration tests, where OD
is scriptable. What *is* proven on real hardware is the operator side: an `emergency_stop`
operator input feeding an `abort` lets the preprod smoke trigger a real abort and watch the
finalizer sweep the thermostats, pumps, and valves safe, end to end. The original problem
statement is kept below as motivation.

**What.** The block vocabulary is `command`, `measure`, `operator_input`, `wait`, `serial`,
`parallel`, `loop`, `branch`, `group_ref`. There is no way for a workflow to *fail itself* on a
condition.

**Where it bit.** A three-week morbidostat run's most likely ending is contamination or
biofilm, which show up as an OD that climbs and never comes down no matter how much drug is
injected. The workflow can detect this — the expression is easy — but it cannot *act* on it. It
cannot stop, and it cannot flag. It will keep cheerfully pumping drug into a contaminated vial
for a fortnight.

**Workaround used.** None. Documented as an operator responsibility.

**Suggested feature.** An `assert`/`abort` block: `{abort: {if: "<expr>", message: "..."}}`,
raising a run failure through the existing finalizer (which already sweeps devices to a safe
state). A softer `alarm` variant that logs an event and notifies without ending the run would
suit multi-vial experiments better, where one bad vial should not kill the other fourteen.

---

## 8. No clock in expressions

**What.** Stat windows accept durations (`mean(od, last=30min)`), so relative-time *windows*
exist — but there is no `elapsed()` or `now()`. An expression cannot ask how long the run has
been going.

**Where it bit.** Mildly. The daily loop is "run 24 h, then pause for the manual transfer",
which is expressed as a cycle count (`120 × 12min`) — correct only as long as no cycle
overruns its `pace`. `count(od_1)` works as a cycle counter proxy.

**Suggested feature.** `elapsed()` in seconds since run start. Small, and it makes
time-bounded conditions (`until: "elapsed() > 24h"`) direct rather than inferred.

---

## Smaller sharp edges

- **Division by zero is a hard error,** not a fail-safe. The morbidostat's `r = m/OD` is only
  safe because an enclosing branch guarantees `OD ≥ od_min`. A user who reorders those branches
  gets a run-killing `EvaluationError` at cycle 1. Worth a validator warning when a division's
  denominator is a stat that is not provably non-zero.
- **String-kind params are opaque.** `direction`, `rotation`, and `default_rotation` are passed
  through literally and never evaluated — correct, but it means a param's behaviour depends on
  its registry kind in a way that is invisible in the document. Related to #5.
- **Stream `units` are declarative only.** Nothing checks them; `blank_1` (an AU/s slope) and
  `od_1` (AU) can be freely mixed in one expression.
- **No per-sample tagging.** A stream sample carries a value and a timestamp. There is no way
  to mark *which branch fired* on a given cycle, so the decision history cannot be overlaid on
  the OD chart — it lives only in the run log.

---

---

## Not the engine: duplicate device serials collide in the agent's state store

Filed here because it **changed the example**, but it is not an engine limitation — and the root
cause is narrower and more specific than "the store isn't thread-safe", which is what it looked
like at first.

**Root cause.** The SerialHop agent persists device state to a file keyed by
**`<type>-<serial>`** under `C:\ProgramData\SerialHop\devicestate\`. The test client's simulated
devices are *clones*: `identify` reports the **same serial for every device of a type**.

| Device | Serial |
|---|---|
| `densitometer_1`, `_2`, `_3` | all `25-006` |
| `pump_1`, `_2`, `_3` | all `26-025` |
| `valve_1`, `_2`, `_3` | none (the valve has no serial command) |

So three logically distinct densitometers **alias onto one state file**,
`densitometer-25-006.json`. A state-persisting command (`set_thermostat`, `home`, `configure`,
`set_calibration`) issued to all three at once becomes three concurrent writers to a single
file — and the agent's save is a non-atomic write-temp-then-rename, which on Windows raises a
sharing violation when another handle is open:

```
persist thermostat: device store rename:
  rename ...\densitometer-25-006.json.tmp  ...\densitometer-25-006.json
  The process cannot access the file because it is being used by another process.

persist thermostat: device store write:
  open ...\densitometer-25-006.json.tmp
  The process cannot access the file because it is being used by another process.
```

**Measured on `windows_arm64_test_client`** (25 trials each, 3 devices):

| Command | Parallel | Serial |
|---|---|---|
| `set_thermostat` (persists, shared serial) | **23/25 failed** | **0/25 failed** |
| valve `configure` (persists, *no* serial → no shared file) | 0/25 failed | — |
| `measure` (pure read; 90 concurrent calls via the engine) | 0 failed | — |

Every single failure named the *same* file. Valves never collide precisely because they have no
serial and so are not keyed onto a shared one — which is itself the confirmation of the
mechanism.

**Re-measured 2026-07-14, same hardware, same fault, same file, same two sharing-violation
variants (temp-open and rename).** A dedicated baseline of `set_thermostat` in parallel (no
retry) failed **8/25 (32%)**, not 23/25 (92%) — measured under Task 11's real-hardware
validation, through the engine's executor rather than raw parallel client calls. Across all
thermostat trials that day (three batches under different retry/on_error configurations), the
rate held consistent with itself: **29/75 (38.7%)**. The fault is real, reproduces reliably, and
names the identical file and error text above — it is just roughly a third as frequent as first
recorded. I did not determine why the rate differs; the duplicate serials are intact and the
fault source is unchanged, so the likely explanation is the harness or ambient load on the
Windows box at the time of the original measurement. Take **32%** as the current number for this
roster.

**What is NOT broken (tested, so the alarming version can be ruled out).** Runtime device state
is per-device, not shared: setting `pump_1`'s calibration to 0.002 left `pump_2` and `pump_3` at
0.001. So the aliasing does **not** cause silent cross-talk during a run — three pumps do not
share one live calibration. The damage is confined to the persist path, where it is loud (the
command fails) rather than quiet. Persisted state presumably *is* last-writer-wins across an
agent restart, but that was not tested.

**Also not broken — in fact aliased in exactly the direction you'd expect, and a direct
consequence of this same root cause.** The blank calibration (`measure_blank`) persists to the
same shared `densitometer-25-006.json` this whole section is about, so blanking any one of the
three densitometers blanks all three. Measured 2026-07-14: withholding `measure_blank` from
`densitometer_3` and calling `measure` on it anyway returned a full 5/5 samples across 3 trials,
identical to the blanked lanes. **`measure` does not require a prior `measure_blank` on this
roster** — the requirement is real in principle (an unblanked read is meaningless) and
unenforceable in practice, for the same aliasing reason as everything else here.

**Where it bit.** The example originally set all three thermostats in one `parallel` block —
legal, validator-approved, three distinct devices. It killed the first live run 26 s in.

**Workaround used.** Originally: make the example's one-time setup (thermostats, blanks, valve
home/configure) **serial**, at a cost of ~2 s. The monitor loop's three simultaneous `measure`
calls stayed parallel: a pure read, what the science requires, verified over 90 concurrent calls.

**Superseded, 2026-07-14 (§0 shipped).** The thermostat block is `parallel` again, with
`retry: {attempts: 6, backoff: "1s"}` on each lane — the race is transient and
`set_thermostat` is an absolute setter, so a retry is safe and lands the same state. The 6
attempts were originally justified by a convergence story: the three lanes fail *together* and
the back-off has **no jitter**, so they retry together too, and the contenders only thin out as
each round's winner drops out (3 → 2 → 1), leaving 3 attempts exactly zero headroom. **Measured
on real hardware the same day, that story is wrong:** across 25 trials the fault fired 9 times,
produced 10 `block_retried` events, and every single one was `attempt: 1 of 6` — no block ever
reached attempt 2. A collision costs exactly one loser one extra second, not several rounds;
`attempts: 2` would have covered every observed case. **6 stays anyway** — it is nearly free
headroom on a one-time block — but the rationale is corrected, not the number. It is
deliberately **not** tolerated — a silently-unset thermostat is a scientific defect, not a
dropped sample. The blanks and the valve `home`/`configure` remain serial: they are equally
one-time and there was nothing to buy back.

Retry papers over the defect; it does not fix it. Everything below still stands.

**Fixes, in order of value:**

1. **Give the simulated test devices distinct serials.** This is a test-client configuration
   defect and fixing it removes the symptom entirely — parallel setup would then just work. Real
   hardware presumably has unique serials, so a production lab is likely unaffected today, which
   is why this never surfaced before.
2. **Key the agent's state file by something actually unique** — device id or port — rather than
   by serial, which is not guaranteed unique and is empirically not unique. A duplicate serial
   should not be able to make two devices share a file.
3. **Make the save robust**: retry the rename, or use an atomic replace with proper sharing
   flags. Even with unique keys, an antivirus or indexer holding a handle can lose this race.

Worth a `lab-bridge` issue. Note that nothing in the engine or the validator warns an author
that a `parallel` block of state-persisting verbs is unsafe on such a roster.

---

## Summary

| # | Limitation | Blocks | Suggested feature |
|---|---|---|---|
| 0 | ~~No retry / no fault tolerance~~ | ~~Any unattended run~~ | **SHIPPED 2026-07-14** — `retry`, `on_error`, `defaults.retry`, resilient job polling |
| 1 | ~~No computed bindings~~ | ~~Any stateful controller; drug tracking; escalation rules~~ | **SHIPPED 2026-07-15** — `compute` block (number or boolean; seeded accumulator) |
| 2 | No math functions | `ln`-based growth rate; median filtering | `slope`, `median`, `stddev`, `ln`, `abs` |
| 3 | ~~Streams can't hold computed values~~ | ~~Charting growth rate / drug concentration~~ | **SHIPPED 2026-07-15** — `record` block (computed sample into a declared stream) |
| 4 | ~~Groups not parametrized~~ | ~~Scaling past ~3 vials~~ | **SHIPPED 2026-07-15**, typed 2026-07-20 — `for_each` (typed row table) + typed group params, `locals`, engine-owned roles; see [`workflow-schema.md`](workflow-schema.md) |
| 5 | `enum` inputs unusable in expressions | Operator-selectable modes | String comparison in expressions |
| 6 | Durations/counts are literals | Cycle time as an operator input; adaptive timing | Expressions in duration/count slots |
| 7 | ~~No abort/assert block~~ | ~~Contamination guards on long runs~~ | **SHIPPED 2026-07-16** — `abort` (hard stop, `AbortSignalError`, status `"aborted"`) / `alarm` (flag-and-continue, `RunReport.alarms`) |
| 8 | No clock in expressions | Time-bounded conditions | `elapsed()` |

**#0 is done**, and it is the one that had to be: it is the difference between a workflow you
can express and a workflow you can *run*. The morbidostat now survives the fault that killed it
— but survival is where the engine's help stops. It will carry a run through a dead sensor
without ever telling anyone the sensor is dead, and the only thing standing between that and a
sterilized vial is a freshness constant the author had to compute by hand and the validator
cannot check. That is not a complaint about the feature; it is the honest shape of what
tolerance buys you, and it is why **#7 (abort/alarm)** now reads to me as the natural sequel to
#0 rather than a nice-to-have.

**#1 (computed bindings) and #3 (computed streams) are now done too** (Increment 6, 2026-07-15).
Together they turned the engine from a sequencer that reacts into a controller that reasons: the
morbidostat now runs its drug-concentration recursion inside the workflow, records the sawtooth
as a first-class stream, and names its growth rate once instead of inlining a magic constant in
every branch — which is exactly why they **made #2's `slope` optional rather than essential**, as
predicted. `record` also collapsed part of #2: the growth rate is a named `compute`, so the unit
constant lives in one place.

**#4 (parametrized groups) is now done too** (Increment 7, 2026-07-15). `for_each` (a splicing
macro over an item list) and parametrized groups (`params`/`args`, inlined as a `Serial`) share
one substitution engine, and together they make the 15-vial version of this experiment expressible
for the first time: the tube-service control law is written once, as a `service(tube)` group, and
`for_each` invokes it per tube, seeds its accumulators, and lanes its OD reads. `defaults.retry`
had already bought this example its scale for *retry policy* — one clause instead of ~60
hand-copied ones; **#4 now buys that same scale for the *control law* itself** — one law instead
of fifteen hand-copied, byte-identical subtrees.

**#4 was re-shipped typed** (Increment 9, 2026-07-20). The 2026-07-15 version bought the scale;
it did not buy the safety, because an untyped hole is not a name until expansion makes one, and
nothing can be checked before that. Kinds, group locals, and engine-owned roles close that gap:
the four distinct things `{tube}` used to mean are now four declarations, each checked against
the role, stream, and binding namespaces before a single copy is spliced. It also produced the
repo's first maintained schema reference, [`workflow-schema.md`](workflow-schema.md) — until
now the format was documented only inside dated design specs, which are records of decisions and
go stale by design.

**#7 (abort/alarm) is now done too** (Increment 8, 2026-07-16). `abort` and `alarm` share one
condition-evaluation path with `branch`, so the freshness/read-before-write guarantees documented
under #0 apply to them for free — zero new analysis logic, the same payoff Increment 7 already
banked for `for_each`. #7 was named the natural sequel to #0 throughout this document, and it now
closes the loop: a run can both *survive* a dead sensor (#0 — `retry`/`on_error`) and *flag or
halt* on one (#7 — `alarm`/`abort`). The morbidostat's contamination guard is the concrete
demonstration: a latched `alarm` drops one bad vial from service while the other fourteen run on,
and a whole-run `abort` sweeps every device safe when every vial is lost. The one honest gap is
where it was always going to be — the test rig's simulated densitometers read OD 0.0, so the
contamination predicate itself cannot fire on real hardware; that path is proven in FakeLab
integration tests, and the operator's own `emergency_stop` → `abort` is what is proven end to end
on real hardware instead.

Separately, the **duplicate-serial collision** above is not an engine issue at all, and it has a
one-line fix: give the simulated test devices distinct serials. Until then, a `parallel` block of
state-persisting verbs fails **~32%** of the time on that roster (measured 2026-07-14; 29/75 =
38.7% across all thermostat trials that day) and nothing warns the author — retry now rides the
race out (the example asks for 6 attempts), which makes it survivable, not fixed.
