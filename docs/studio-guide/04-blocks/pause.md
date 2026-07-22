# Pause blocks — Wait & Operator input

Pause blocks stop the workflow — either for a set time, or until a person answers a question.

---

## Wait

**What it does** — pauses for a set length of time before continuing.

**When to use it** — spacing out steps: settle after dosing, wait a minute between readings,
let a temperature equilibrate.

![](../images/block-wait.png)
> *Screenshot: a Wait block selected; Inspector shows the Duration field with `1min`.*

**Settings**

- **Duration** — how long to wait, a [duration](../03-concepts/expressions.md). A fixed value
  like `30s`, `5min`, `2h`, or an expression like `cycle_min * 1min`.

<details><summary>Details &amp; gotchas</summary>

A Wait always adds its full time. If your goal is "one cycle exactly every minute" no matter
how long the work takes, use a [Loop](flow.md)'s **Pace** instead of a Wait — Pace only waits
for the *remainder* of the period.
</details>

---

## Operator input

**What it does** — pauses the run and asks a person for a value. Their answer becomes a
[binding](../03-concepts/bindings-and-constants.md) you can use later.

**When to use it** — anything the workflow can't know on its own: how much drug to add today,
which culture is in the vial, a yes/no confirmation before a critical step.

![](../images/block-operator-input.png)
> *Screenshot: an Operator input block selected; Inspector shows Binding name, Type, and the
> Prompt field.*

**Settings**

- **Binding name** — the name the answer is stored under (e.g. `dose_ml`).
- **Type** — what kind of answer:
  - **int** — a whole number.
  - **float** — a decimal number.
  - **bool** — yes/no.
  - **enum** — one choice from a list you provide.
- **Min / Max** *(int and float only)* — optional limits on the accepted number.
- **Choices** *(enum only)* — the list of options, one per line.
- **Prompt** — the question shown to the operator (e.g. "How many ml of drug today?").

<details><summary>Details &amp; gotchas</summary>

- The operator answers **when the run reaches this block**, not necessarily at the very
  start — so you can ask a question partway through, after a first reading.
- Set **Min/Max** or use **enum** to stop typos: it's easy to fat-finger `20` instead of `2`.
</details>

---

**Related:** [Bindings & constants](../03-concepts/bindings-and-constants.md) · [Expressions](../03-concepts/expressions.md)
