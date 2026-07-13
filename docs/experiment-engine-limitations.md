# Experiment engine — known limitations

Found while implementing the morbidostat example (`examples/morbidostat.json`) — a real
closed-loop evolution experiment, and the most demanding workflow the engine has been asked to
express so far. Everything here is a limitation I actually hit, with what it cost and what
would fix it. Nothing is speculative.

The headline: **the morbidostat is fully implementable today.** Every limitation below had a
workaround. But the workarounds cluster, and the cluster has a shape — the engine can *read*
state richly and *act* on it, but it cannot *hold* derived state or *abstract over* repetition.

Ranked by what they would actually unlock.

---

## 0. No retry, and no tolerance for a transient device fault

**This is the one that matters most, and it is the only one that makes the example unusable
for its actual purpose.** It was found by running the example on real hardware, not by reading
the code.

**What.** A block that fails, fails the run. There is no retry, no back-off, no
"tolerate this and carry on", no `on_error` branch. The engine's error model is all-or-nothing:
any device error propagates up and terminates the experiment.

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
weeks. **The morbidostat cannot actually be run to completion on this stack today** — not
because the algorithm is hard to express (it isn't; the rest of this document is a footnote by
comparison) but because the engine treats a flaky sensor read as fatal.

And there is no workaround. A workflow cannot catch, cannot retry, cannot skip a cycle. The
author has no lever at all.

**Suggested features**, in the order I would build them:

1. **Retry policy on `command`/`measure`** — `{retry: {times: 3, backoff: "2s"}}`. Cheapest
   possible fix and it alone would have saved this run: the fault is transient, and the very
   next read succeeds.
2. **`on_error` on a block** — `continue` (log it and move on) vs `fail` (today's behaviour),
   so a workflow can declare that a missed sample is survivable but a missed *injection* is
   not. The morbidostat wants exactly this distinction: a dropped OD reading should cost one
   sample out of ten, not the experiment.
3. **Per-device fault isolation** — one bad vial should not kill the other fourteen. Today a
   `parallel` lane failure takes down the whole `TaskGroup`. This is what a 15-vial run needs.

Until at least (1) exists, any long unattended run on this stack is a lottery.

---

## 1. No computed bindings (no accumulator)

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

## 3. Streams cannot hold computed values

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

## 4. Groups are not parametrized

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

## 5. `enum` operator inputs are unusable in expressions

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

## 7. No abort or assert block

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

**What is NOT broken (tested, so the alarming version can be ruled out).** Runtime device state
is per-device, not shared: setting `pump_1`'s calibration to 0.002 left `pump_2` and `pump_3` at
0.001. So the aliasing does **not** cause silent cross-talk during a run — three pumps do not
share one live calibration. The damage is confined to the persist path, where it is loud (the
command fails) rather than quiet. Persisted state presumably *is* last-writer-wins across an
agent restart, but that was not tested.

**Where it bit.** The example originally set all three thermostats in one `parallel` block —
legal, validator-approved, three distinct devices. It killed the first live run 26 s in.

**Workaround used.** The example's one-time setup (thermostats, blanks, valve home/configure) is
now **serial**, at a cost of ~2 s. The monitor loop's three simultaneous `measure` calls stay
parallel: a pure read, what the science requires, verified over 90 concurrent calls.

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
| 1 | No computed bindings | Any stateful controller; drug tracking; escalation rules | `compute`/`let` block |
| 2 | No math functions | `ln`-based growth rate; median filtering | `slope`, `median`, `stddev`, `ln`, `abs` |
| 3 | Streams can't hold computed values | Charting growth rate / drug concentration | `record` block |
| 4 | Groups not parametrized | Scaling past ~3 vials | Group params / `for_each` |
| 5 | `enum` inputs unusable in expressions | Operator-selectable modes | String comparison in expressions |
| 6 | Durations/counts are literals | Cycle time as an operator input; adaptive timing | Expressions in duration/count slots |
| 7 | No abort/assert block | Contamination guards on long runs | `abort` / `alarm` block |
| 8 | No clock in expressions | Time-bounded conditions | `elapsed()` |

If only two were built, **#1 (computed bindings)** and **#3 (computed streams)** together turn
the engine from a sequencer that reacts into a controller that reasons — and they make #2's
`slope` optional rather than essential. **#4** is what the 15-vial version of this experiment
needs before it can be written at all.

Separately, the **duplicate-serial collision** above is not an engine issue at all, and it has a
one-line fix: give the simulated test devices distinct serials. Until then, a `parallel` block of
state-persisting verbs fails ~92% of the time on that roster, and nothing warns the author.
