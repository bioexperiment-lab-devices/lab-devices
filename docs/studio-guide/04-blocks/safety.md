# Safety blocks — Alarm & Abort

Safety blocks watch for trouble and react. Both check a condition; the difference is what
they do when it's true. **Alarm** flags and keeps going; **Abort** stops the run.

---

## Alarm

**What it does** — when its condition is true, it **flags** the run (records a warning) and
**continues**.

**When to use it** — non-fatal warnings you want on the record: OD dipped unexpectedly, a
reading looks off, a soft limit was crossed.

![](../images/block-alarm.png)
> *Screenshot: an Alarm block selected; Inspector shows the If condition and the Message
> field.*

**Settings**

- **If** — the condition to watch, an [expression](../03-concepts/expressions.md).
- **Message** — what to flag (shown in the run's record).

<details><summary>Details &amp; gotchas — it fires every time it holds</summary>

An Alarm fires **every time** its condition is true. If it sits inside a loop and the
condition stays true, you'll get a flag on every pass. To flag **once**, latch it with a
[Compute](data.md): compute a flag like `seen or contaminated`, then alarm on a condition
that you clear — or gate the alarm so it only checks the freshly-crossed case.
</details>

---

## Abort

**What it does** — when its condition is true, it **stops the run**: devices are swept to a
safe state and the run ends with status **"aborted"**.

**When to use it** — a genuine emergency stop: contamination detected, a value far outside
safe range, a device in an unrecoverable state.

![](../images/block-abort.png)
> *Screenshot: an Abort block selected; Inspector shows the If condition and the Message
> field, with the note that a true condition stops the run.*

**Settings**

- **If** — the condition that triggers the stop.
- **Message** — why the run must stop (recorded with the aborted run).

<details><summary>Details &amp; gotchas</summary>

- Abort is the **hard stop**. Once its condition holds, no further blocks run — the safe-state
  sweep runs and the experiment ends. Reserve it for conditions where continuing would waste
  the experiment or risk the hardware.
- Abort has **no "on error" setting** — it *is* the failure path.
</details>

---

## Alarm or Abort?

| Situation | Use |
|-----------|-----|
| Worth noting, safe to continue | **Alarm** |
| Continuing would ruin the run or risk hardware | **Abort** |

You can use both: an Alarm to flag a soft threshold, and an Abort for the hard limit beyond it.

---

**Related:** [Compute](data.md) (for latching) · [Expressions](../03-concepts/expressions.md)
