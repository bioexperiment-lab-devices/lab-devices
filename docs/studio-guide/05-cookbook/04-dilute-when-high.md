# Recipe 4 — Dilute only when OD is too high

**Goal:** each cycle, read OD; if it's above a threshold, add fresh medium to dilute;
otherwise do nothing. A first taste of feedback control.

**Blocks used:** [Loop](../04-blocks/flow.md) · [Measure](../04-blocks/device-actions.md)
(measure) · [Branch](../04-blocks/flow.md) · [Command](../04-blocks/device-actions.md)
(dispense) · [Wait](../04-blocks/pause.md).

**Roles:** `od_meter` (densitometer), `medium_pump` (pump).

## Build it

1. Create roles `od_meter` (densitometer) and `medium_pump` (pump).
2. Drag a **[Loop](../04-blocks/flow.md)** onto the canvas. Set **Repeat:** `Count`,
   **Count:** `40`.
3. Inside the loop, in order:
   - **`measure`** verb of `od_meter`, **Into stream:** `od` (unit `AU`).
   - A **[Branch](../04-blocks/flow.md)**. Set **If:** `last(od) > 0.5`.
     - In the **then** lane, drag the **`dispense`** verb of `medium_pump`, **volume_ml:**
       `1.0`.
     - Leave the **else** lane out (nothing to do when OD is fine).
   - A **[Wait](../04-blocks/pause.md)**, **Duration:** `1min`.
4. Save and run.

![](../images/cb-04-dilute-when-high.png)
> *Screenshot: a Loop containing measure→od, a Branch (If last(od) > 0.5 → dispense), and
> Wait 1min.*

## Why it's built this way

The [Branch](../04-blocks/flow.md) turns a **reading into a decision**: `last(od)` asks the
`od` stream for its newest value, and the dilution only happens on cycles where it's above
`0.5`. Reading **before** the branch each pass means the decision always uses a fresh number.
Because there's nothing to do when OD is fine, the **else** lane is simply omitted.

> **Make the threshold a [constant](../03-concepts/bindings-and-constants.md).** Declare
> `target_od = 0.5` and write the condition `last(od) > target_od`. Now you can retune the
> whole experiment from one place.

**Next:** [Recipe 5 — ask the operator for a dose](05-operator-dose.md).
