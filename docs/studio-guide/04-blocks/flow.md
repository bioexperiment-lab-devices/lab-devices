# Flow blocks

Flow blocks are the **containers** that decide *when* and *in what order* your other blocks
run: one after another, all at once, only if a condition holds, or over and over. They hold
other blocks inside them.

---

## Serial

**What it does** — runs the blocks inside it **one after another**, top to bottom.

**When to use it** — the default for "do this, then this, then this". Most of your workflow
lives inside serials.

![](../images/block-serial.png)
> *Screenshot: a Serial block on the canvas containing three stacked child blocks.*

**Settings** — none of its own. You build the sequence by dragging blocks into it on the
canvas.

---

## Parallel

**What it does** — runs several **lanes at the same time**. Each lane is its own little
sequence.

**When to use it** — independent things that should happen together: reading three vials at
once, holding a temperature while a separate loop doses.

![](../images/block-parallel.png)
> *Screenshot: a Parallel block with two or three lanes side by side, and the "+ lane"
> button.*

**Settings**

- **Lanes** — added, removed, and reordered on the canvas with the **"+ lane"** button.
- **Start offset** (per lane) — a lane can wait a set time after the Parallel starts before
  it begins. Set it in that lane's Inspector under **Timing**. Use it to stagger lanes.

<details><summary>Details &amp; gotchas</summary>

Dropping a block directly onto a Parallel automatically wraps it as a new lane, so you can
build lanes just by dragging.
</details>

---

## Branch

**What it does** — checks a condition and runs **one path or the other**.

**When to use it** — "if OD is too high, dilute; otherwise do nothing" and similar decisions.

![](../images/block-branch.png)
> *Screenshot: a Branch block showing the If condition and a **then** lane, with the
> **else** lane added below.*

**Settings**

- **If** — the condition, an [expression](../03-concepts/expressions.md) that is true or
  false (e.g. `last(od) > 0.5`).
- **then** — the blocks that run when the condition is **true**. Always present.
- **else** — an optional second path that runs when the condition is **false**. Add or
  remove the else lane from the Inspector (you can only remove it when it's empty).

---

## Loop

**What it does** — repeats the blocks inside it.

**When to use it** — cycles: read → wait → read → wait…, or "keep going until the culture
reaches OD 0.6".

![](../images/block-loop.png)
> *Screenshot: a Loop block selected with the Inspector showing Repeat = Until, an Until
> condition, and the Check dropdown.*

**Settings**

- **Repeat** — how the loop decides to keep going:
  - **Count** — a fixed number of passes.
  - **Until** — keep going until a condition becomes true.
- **Count** *(when Repeat = Count)* — the number of passes; a whole number or a whole-number
  [expression](../03-concepts/expressions.md).
- **Until** *(when Repeat = Until)* — the stop condition (e.g. `mean(od, last=5) > 0.6`).
- **Check condition** *(Until only)* — when to test the condition:
  - **after each pass** (the default) — run the body, then check.
  - **before each pass** — check first, then maybe run the body.
- **Pace (min. loop period)** — an optional minimum time for each pass. If a pass finishes
  early, the loop waits so passes line up on a clock (e.g. one reading exactly every minute).

<details><summary>Details &amp; gotchas</summary>

- **Until + "before each pass" can run zero times** — if the condition is already true when
  the loop is reached, the body never runs. Use **after** if you want at least one pass.
- **Pace vs. Wait.** Pace guarantees a *minimum* period per pass regardless of how long the
  work took; a [Wait](pause.md) block always adds its full time on top. For "exactly every
  minute", Pace is usually what you want.
</details>

---

## For each

**What it does** — stamps out a **copy of its body for every row** you give it, filling in
different values each time.

**When to use it** — doing the same thing to several vials, positions, or doses without
building the steps by hand N times.

![](../images/block-for-each.png)
> *Screenshot: a For each block showing the Loop variables table (e.g. a `tube` variable)
> and a Rows grid with several rows.*

**Settings**

- **Loop variables** — one or more named variables, each with a **type**: a whole number
  (int), a decimal (number), yes/no (bool), text (string), a [role](../03-concepts/roles.md),
  a [stream](../03-concepts/streams.md), or a [binding](../03-concepts/bindings-and-constants.md).
- **Rows** — a grid with one value per variable per row. Each row produces one copy of the
  body with those values filled in.

<details><summary>Details &amp; gotchas</summary>

- **For each is a stamp, not a loop that runs at a time.** It **splices** its copies into
  the list around it. If a For each is the only thing inside a **Parallel**, its rows become
  N lanes that run together. Inside a **Serial**, the rows become an N-step sequence that
  runs in order.
- Because it's a stamp, For each has **no timing or on-failure settings of its own** — those
  belong to the blocks in its body.
- For each pairs naturally with **[Groups](groups.md)**: give a variable to a group call as a
  `{hole}` so each row calls the same routine with a different vial or role.
</details>

---

**Related:** [Groups](groups.md) · [Expressions](../03-concepts/expressions.md) · [Common settings](index.md#settings-every-block-has)
