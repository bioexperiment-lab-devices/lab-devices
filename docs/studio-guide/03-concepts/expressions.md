# Expressions

An **expression** is a small formula you type into Studio — a condition like *"is the last
OD above 0.5?"* or a value like *"the cycle length times one minute"*. Expressions are how
your workflow **decides** and **calculates**. You already know the ingredients:
[streams](streams.md), [bindings and constants](bindings-and-constants.md).

You don't need to be a programmer. Most expressions are one short line.

## What you can write

**Values (literals)**

- **Numbers** — `1`, `0.5`, `37`.
- **Durations** — a number with a time unit: `500ms`, `30s`, `5min`, `2h`. Use these
  anywhere Studio asks for a length of time.
- **Text** — in single quotes: `'forward'`, `'reverse'`.
- **Yes/no** — `true` and `false`.

**Names** — the name of any [stream](streams.md),
[binding, or constant](bindings-and-constants.md) in scope: `od`, `target_od`, `dose_ml`.

**Operators**

- **Comparisons** — `<`, `<=`, `>`, `>=`, `==` (equal), `!=` (not equal). Compare one thing
  at a time — you can't chain them (write `a > 1 and a < 5`, not `1 < a < 5`).
- **Logic** — `and`, `or`, `not`, and parentheses `( )` to group.
- **Arithmetic** — `+`, `-`, `*`, `/`.

**Stream functions** — ask a [stream](streams.md) a question about its numbers:

| Function | Meaning |
|----------|---------|
| `last(od)` | the most recent value |
| `mean(od)` | the average |
| `min(od)` | the smallest |
| `max(od)` | the largest |
| `count(od)` | how many values so far |

**Windows** — by default a function looks at **all** samples. Narrow it with `last=`:

- `mean(od)` — the average of every reading.
- `mean(od, last=5)` — the average of the **last 5 readings**.
- `mean(od, last=30s)` — the average of readings from the **last 30 seconds**.

## Worked examples

- `last(od) > 0.5` — true when the newest OD reading is above 0.5.
- `mean(od, last=5) > 0.6` — true when the last five readings average above 0.6.
- `count(od) >= 10` — true once you have at least ten readings.
- `cycle_min * 1min` — a duration: the number in `cycle_min`, in minutes.
- `contaminated and last(od) < 0.1` — combine a yes/no binding with a reading.

## Where expressions appear

You'll type expressions into many fields. The common ones:

- **[Branch](../04-blocks/flow.md)**, **[Alarm and Abort](../04-blocks/safety.md)** — the
  **If** condition.
- **[Loop](../04-blocks/flow.md)** — the **Count** (how many times) or the **Until**
  condition.
- **[Compute](../04-blocks/data.md)** and **[Record](../04-blocks/data.md)** — the **Value**.
- **Durations** — a **[Wait](../04-blocks/pause.md)**, a block's **Gap after** /
  **Start offset**, a Loop's **Pace**, a retry **Backoff**.
- **Device parameters** — numeric and yes/no parameters on
  [command/measure](../04-blocks/device-actions.md) blocks can take an expression instead of
  a fixed number (click the small **ƒ** toggle on the field).

## The expression editor

Wherever you type an expression, you get help:

- **Color highlighting** so names, numbers, and functions stand out.
- **Autocomplete** — as you type, a list of matching streams, bindings, and functions pops
  up. Press **Ctrl-Space** to force it open.
- A **help popover** listing the streams, bindings, and functions available right here —
  click any item to insert it.
- **Live checks** — Studio underlines problems as you type. **Amber** notes are advisory
  (e.g. "durations need a unit — `30s`, not `30`"); **red** errors come from the full
  validation and must be fixed.

![](../images/concept-expression-editor.png)
> *Screenshot: an expression field being edited (e.g. `mean(od, last=5) > 0.6`) with the
> autocomplete popup open and the highlighting visible.*

---

**Related:** [Streams](streams.md) · [Bindings & constants](bindings-and-constants.md) · [Block reference](../04-blocks/index.md)
