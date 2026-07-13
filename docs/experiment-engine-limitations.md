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
