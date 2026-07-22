# Recipe 3 — Timed repeated dosing

**Goal:** dispense a small dose on a fixed schedule — exactly one dose per minute — for a set
number of cycles, no matter how long the pump takes.

**Blocks used:** [Loop](../04-blocks/flow.md) (count + **Pace**) ·
[Command](../04-blocks/device-actions.md) (dispense).

**Roles:** `medium_pump` (pump).

## Build it

1. Create a [role](../03-concepts/roles.md) `medium_pump` (pump).
2. Drag a **[Loop](../04-blocks/flow.md)** onto the canvas. Set **Repeat:** `Count`,
   **Count:** `30`, and **Pace:** `1min`.
3. Inside the loop, drag the **`dispense`** verb of `medium_pump`. Set **volume_ml:** `0.5`.
4. Save and run.

![](../images/cb-03-timed-dosing.png)
> *Screenshot: a Loop×30 with Pace 1min containing a single dispense (medium_pump, 0.5 ml).*

## Why it's built this way

**Pace** makes each pass take **at least** one minute: if the dispense finishes in a few
seconds, the loop waits out the rest of the minute before the next pass. That keeps doses on a
clean clock — thirty doses over thirty minutes — which a plain [Wait](../04-blocks/pause.md)
can't guarantee, because a Wait always adds its full time *on top* of the dispense.

> **Careful with retry here.** `dispense` moves liquid, so it is **not** safe to retry
> automatically (a retry could double-dose). Leave Retry off unless you deliberately opt in —
> see [Device actions → Retry](../04-blocks/device-actions.md).

**Next:** [Recipe 4 — dilute only when OD is too high](04-dilute-when-high.md).
