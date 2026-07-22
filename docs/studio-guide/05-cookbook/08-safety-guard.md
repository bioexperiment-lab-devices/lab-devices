# Recipe 8 — Stop safely on contamination

**Goal:** watch each cycle for a contamination signal. Flag a warning the first time it
appears, and abort the run if it gets worse — with the flag firing **once**, not every pass.

**Blocks used:** [Loop](../04-blocks/flow.md) · [Measure](../04-blocks/device-actions.md)
(measure) · [Compute](../04-blocks/data.md) (latch) · [Alarm](../04-blocks/safety.md) ·
[Abort](../04-blocks/safety.md).

**Roles:** `od_meter` (densitometer).

## Build it

1. Create a [role](../03-concepts/roles.md) `od_meter` (densitometer). Optionally declare a
   [constant](../03-concepts/bindings-and-constants.md) `warn_od = 0.05` and `abort_od =
   0.02`.
2. Drag a **[Loop](../04-blocks/flow.md)**; set **Repeat:** `Count`, **Count:** `60`.
3. Inside the loop, in order:
   - **`measure`** verb of `od_meter`, **Into stream:** `od` (unit `AU`).
   - A **[Compute](../04-blocks/data.md)** to **latch** a warning flag:
     - **Into (binding):** `warned`
     - **Value:** `warned or last(od) < warn_od`
   - An **[Alarm](../04-blocks/safety.md)**:
     - **If:** `warned`
     - **Message:** `Possible contamination — OD dropping`
   - An **[Abort](../04-blocks/safety.md)**:
     - **If:** `last(od) < abort_od`
     - **Message:** `Contamination confirmed — aborting run`
4. Save and run.

![](../images/cb-08-safety-guard.png)
> *Screenshot: a Loop containing measure→od, a Compute latching `warned`, an Alarm on
> `warned`, and an Abort on `last(od) < abort_od`.*

## Why it's built this way

- **Abort** is the hard stop: when `last(od)` falls below the abort threshold, the run ends
  and devices are swept safe. Reserve it for the point of no return.
- **Alarm** flags a softer warning and lets the run continue — but on its own it would fire on
  **every** loop pass while the condition holds. The **[Compute](../04-blocks/data.md)**
  latch fixes that: `warned` becomes true the first time OD dips and **stays** true
  (`warned or …`), so the alarm records the concern once and doesn't spam the record.
- Putting the thresholds in **[constants](../03-concepts/bindings-and-constants.md)** keeps
  the two limits — warn and abort — tunable from one place.

## You've finished the cookbook

You've built sequences, loops, decisions, parallel lanes, operator input, reusable groups,
and safety guards. Combine these and you can express most real experiments. For inspiration,
look at the full worked examples that ship with the platform (the morbidostat and the adaptive
bioreactor) — they use exactly these blocks at a larger scale.
