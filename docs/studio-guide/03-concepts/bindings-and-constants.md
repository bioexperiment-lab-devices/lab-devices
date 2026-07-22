# Bindings & constants

Sometimes you need a **single named value** rather than a whole series. Studio has two kinds:

- A **binding** is a value that appears **during the run** — an operator types it in, or the
  workflow calculates it.
- A **constant** is a value you set **at design time**, before the run, and it never changes.

Both are the opposite of a [stream](streams.md): one number, not a growing series.

## Bindings

A binding is created by one of two blocks:

- **[Operator input](../04-blocks/pause.md)** — the run pauses and asks a person for a
  value (e.g. "how many ml of drug?"). Their answer becomes the binding.
- **[Compute](../04-blocks/data.md)** — the workflow calculates a value from an
  [expression](expressions.md) (e.g. `target = od_setpoint * 2`) and stores it under a name.

Once a binding exists, you can use its name in any later [expression](expressions.md).

### The Bindings panel

The **Bindings panel** in the Palette is a **read-only** overview — you don't create
bindings here, you create them with the blocks above. For each binding it shows:

- a **type badge** — the value's type and unit (see below),
- who **writes** it (which operator-input or compute block),
- who **reads** it (which blocks use it) — click to jump straight to that block.

![](../images/concept-bindings-panel.png)
> *Screenshot: the Bindings panel with one binding expanded to show its type badge, its
> writer, and its readers.*

## Constants

A **constant** is a workflow-global value you fix once. Declare it in the **Constants
panel**: give it a name, a value (a number, `true`/`false`, or a short
[expression](expressions.md)), and optionally a **unit**. It is **write-once** — you set it
at design time and every part of the workflow reads the same value.

Constants are perfect for the numbers you'd otherwise repeat everywhere: a target OD, a
cycle length, a dose volume. Change the constant in one place and the whole experiment
follows.

![](../images/concept-constants-panel.png)
> *Screenshot: the Constants panel with two constants (e.g. `target_od = 0.6`,
> `cycle_min = 60`), each showing its value, unit, and type badge.*

## Types and units

Both bindings and constants show a **type badge** — the value's base type (a whole number,
a decimal number, true/false, or text) plus a **unit** when it has one.

You can attach a unit to a computed value with a **cast**, written as `as`. For example, a
[Compute](../04-blocks/data.md) block that works out a rate can cast the result `as
per_hour`, and a [Record](../04-blocks/data.md) into a stream must cast to match that
stream's unit. Units are checked for you: if you try to record a value in the wrong unit,
Studio flags it. You don't have to use units, but they catch real mistakes.

## Which one do I want?

| You need… | Use… |
|-----------|------|
| A number the operator provides at run start | **Operator input** → binding |
| A number the workflow calculates mid-run | **Compute** → binding |
| A fixed number reused across the workflow | **Constant** |
| A series of readings over time | **[Stream](streams.md)** |

---

**Related:** [Expressions](expressions.md) · [Compute & Record](../04-blocks/data.md) · [Operator input](../04-blocks/pause.md)
