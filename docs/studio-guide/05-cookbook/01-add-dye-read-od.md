# Recipe 1 — Add dye, then read OD

**Goal:** dispense a small volume of dye, then take a single optical-density reading. The
"hello world" of a device workflow.

**Blocks used:** [Command](../04-blocks/device-actions.md) (dispense) ·
[Measure](../04-blocks/device-actions.md) (measure) — inside a [Serial](../04-blocks/flow.md).

**Roles:** `dye_pump` (pump), `od_meter` (densitometer).

## Build it

1. Create two [roles](../03-concepts/roles.md): `dye_pump` (pump) and `od_meter`
   (densitometer).
2. Drag the **`dispense`** verb of `dye_pump` onto the canvas. Set **volume_ml:** `0.2`.
3. Drag the **`measure`** verb of `od_meter` onto the canvas, **below** the dispense. Set
   **Into stream:** a new stream `od` (unit `AU`).
4. Save. The two steps sit in a Serial, so they run in order: dispense, then read.

![](../images/cb-01-add-dye-read-od.png)
> *Screenshot: canvas with a dispense (dye_pump) followed by a measure (od_meter → od).*

## Why it's built this way

A plain [Serial](../04-blocks/flow.md) is the default container, so two blocks stacked on the
canvas already run one after the other — dispense **then** read. The reading goes **into a
stream** rather than a binding because OD is something you'll want to see over time once you
wrap this in a loop (recipe 2). Keep the dispense volume small while testing.

**Next:** [Recipe 2 — hold a temperature and log it](02-hold-temperature-log.md).
