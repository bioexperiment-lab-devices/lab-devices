# Recipe 6 — Run three vials in parallel

**Goal:** read three vials' optical density **at the same time**, each into its own stream.

**Blocks used:** [Parallel](../04-blocks/flow.md) ·
[Measure](../04-blocks/device-actions.md) (measure) ×3.

**Roles:** `od_meter_1`, `od_meter_2`, `od_meter_3` (all densitometers).

## Build it

1. Create three [roles](../03-concepts/roles.md) in the **densitometer** group: `od_meter_1`,
   `od_meter_2`, `od_meter_3`.
2. From the Palette under **Flow**, drag a **[Parallel](../04-blocks/flow.md)** onto the
   canvas. It starts with two lanes; click **+ lane** to make a third.
3. Into lane 1, drag the **`measure`** verb of `od_meter_1`, **Into stream:** `od_1` (unit
   `AU`).
4. Into lane 2, `od_meter_2`'s **`measure`** → stream `od_2`.
5. Into lane 3, `od_meter_3`'s **`measure`** → stream `od_3`.
6. Save and run (map each role to a densitometer).

![](../images/cb-06-parallel-vials.png)
> *Screenshot: a Parallel with three lanes, each a measure into od_1 / od_2 / od_3.*

## Why it's built this way

A [Parallel](../04-blocks/flow.md) runs its lanes **together**, so all three vials are read at
the same moment rather than one after another — important when you want readings that line up
in time. Each vial gets its **own stream** (`od_1`, `od_2`, `od_3`) so you can chart and
compare them separately.

> **Doing the same thing to many vials?** When the lanes are identical except for the vial,
> a [For each](../04-blocks/flow.md) inside a Parallel stamps them out for you — see
> [recipe 7](07-service-group.md).

**Next:** [Recipe 7 — a reusable `service` group](07-service-group.md).
