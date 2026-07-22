# Streams

A **stream** is a named series of numbers collected over the run — for example an `od`
stream that gains one value every time you take a reading. Think of a column in a lab
notebook that grows one row per measurement, time-stamped automatically.

Streams are how your experiment **records data**. When you run the workflow, streams are
what you watch on the live chart and what you find in the run record afterward.

## What a stream has

Every stream you declare has:

- a **name** — an identifier like `od`, `temp_c`, `od_1` (letters, digits, underscores;
  must start with a letter or underscore),
- **units** — free text like `AU`, `°C`, `ml`. Leave it blank for a plain unitless number.
  Units are optional but help you (and Studio) keep readings straight.

You manage streams in the **Streams panel** in the Palette.

![](../images/concept-streams-panel.png)
> *Screenshot: the Streams panel with two streams (e.g. `od` in AU and `temp_c` in °C),
> showing the units field and the source tag on each row.*

Each stream row also shows a **source tag** telling you which block writes into it:

- **measure** — a device reading feeds the stream (see below),
- **record** — a value you calculate is appended to the stream,
- **unused** — nothing writes to it yet (a reminder to wire it up or delete it).

## Two ways a stream gets filled

There are exactly two blocks that write into a stream:

- A **[Measure](../04-blocks/device-actions.md)** block takes a **reading from a device**
  (an OD measurement, a temperature) and stores it in the stream. This is the usual way.
- A **[Record](../04-blocks/data.md)** block appends a **value you compute** — say, a growth
  rate you worked out from other numbers — into the stream. Use this to log derived
  quantities alongside raw readings.

Both add one sample each time they run. Put either inside a loop and the stream fills up
over the course of the experiment.

## Stream vs. a single value

A stream holds **many numbers over time**. When you only need **one** number — an operator's
answer, a target you set once — use a [binding or a constant](bindings-and-constants.md)
instead. The difference matters: you can ask a stream for its `last` value or its `mean`
(see [Expressions](expressions.md)), but a binding is just the one value.

---

**Related:** [Bindings & constants](bindings-and-constants.md) · [Record block](../04-blocks/data.md)
