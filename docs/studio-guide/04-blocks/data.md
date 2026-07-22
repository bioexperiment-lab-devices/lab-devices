# Data blocks — Compute & Record

Data blocks let your workflow do arithmetic and keep its own numbers, separate from what the
devices report. **Compute** works out a single value; **Record** logs a value into a
[stream](../03-concepts/streams.md).

---

## Compute

**What it does** — calculates a value from an [expression](../03-concepts/expressions.md) and
stores it under a name (a [binding](../03-concepts/bindings-and-constants.md)).

**When to use it** — whenever you need a derived number later: a target, a rate, a running
total, a yes/no flag.

![](../images/block-compute.png)
> *Screenshot: a Compute block selected; Inspector shows Into (binding name), Value
> (an expression), and the Units → Cast field.*

**Settings**

- **Into (binding)** — the name to store the result under (e.g. `target_od`). You can use
  this name in any later expression.
- **Value** — the [expression](../03-concepts/expressions.md) to evaluate (e.g.
  `od_setpoint * 2`, or `last(od) > 0.5`). It can be a plain number, a yes/no, or a formula.
- **Units → Cast (as)** — optional. Attach a unit to the result, e.g. `as per_hour`. Leave
  it blank for a plain number.

<details><summary>Details &amp; gotchas</summary>

- A Compute writes **once** each time it runs, replacing any previous value of that binding.
  Put a Compute inside a loop and it updates every pass.
- Use a Compute to **latch** a one-time flag: `alarm_seen or contaminated` keeps a flag true
  once it has been true, so a later [Alarm](safety.md) fires only once.
</details>

---

## Record

**What it does** — appends a value you supply to a [stream](../03-concepts/streams.md).

**When to use it** — logging a *derived* number over time (a computed growth rate, a running
dose total) alongside your raw device readings.

![](../images/block-record.png)
> *Screenshot: a Record block selected; Inspector shows the "Into stream" picker, Value, and
> the Cast field.*

**Settings**

- **Into stream** — the [stream](../03-concepts/streams.md) to append to. Pick an existing
  one, or create a new stream right from the picker.
- **Value** — the [expression](../03-concepts/expressions.md) whose result is stored.
- **Cast (as)** — optional unit for the value; it **must match the target stream's unit**.

<details><summary>Details &amp; gotchas — Compute vs. Record</summary>

- **Compute** makes **one value** (a binding) you read later.
- **Record** adds **one sample to a series** (a stream) you chart and export.

If you want a number you'll *use in a decision*, Compute it. If you want a number you'll
*plot or review afterward*, Record it. You'll often do both — Compute a rate, then Record it.
</details>

---

**Related:** [Streams](../03-concepts/streams.md) · [Bindings & constants](../03-concepts/bindings-and-constants.md) · [Expressions](../03-concepts/expressions.md)
