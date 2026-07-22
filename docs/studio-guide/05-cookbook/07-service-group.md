# Recipe 7 — A reusable `service` group, called per vial

**Goal:** build the "service one vial" steps **once** as a [group](../04-blocks/groups.md),
then call it for three vials with a single [For each](../04-blocks/flow.md). Change the
routine in one place and every vial follows.

**Blocks used:** [Group](../04-blocks/groups.md) + group call ·
[For each](../04-blocks/flow.md) · [Measure](../04-blocks/device-actions.md) ·
[Parallel](../04-blocks/flow.md).

**Roles:** `od_meter_1`, `od_meter_2`, `od_meter_3` (densitometers).

This is the advanced payoff — do [recipe 6](06-parallel-vials.md) first so the goal is
familiar.

## Build it

### a. Define the group

1. On the canvas, use the **scope switcher** ("Editing: Main workflow ▾") → **+ New group**.
   Name it `service`.
2. With the group scope active and nothing selected, open its Inspector and add a **Param**:
   - name `meter`, kind **role**, device type **densitometer**.
   - add a **Param** name `out`, kind **stream**.
3. Inside the group body, drag the **`measure`** verb — but point it at the **`{meter}`**
   role param, and set **Into stream** to the **`{out}`** stream param. (Role/stream params
   appear as `{holes}` you can select.)
4. Switch the scope back to **Main workflow**.

![](../images/cb-07-group-body.png)
> *Screenshot: the `service` group scope (hatched) with params `meter` (role) and `out`
> (stream), body = measure {meter} → {out}.*

### b. Call it per vial with For each

1. From the Palette under **Flow**, drag a **[Parallel](../04-blocks/flow.md)** onto the main
   canvas.
2. Inside it, drag a **[For each](../04-blocks/flow.md)**. Add two **Loop variables**:
   `meter` (kind role, densitometer) and `out` (kind stream). Add three **Rows**:
   - `meter = od_meter_1`, `out = od_1`
   - `meter = od_meter_2`, `out = od_2`
   - `meter = od_meter_3`, `out = od_3`
3. Inside the For each body, drag the **`service`** group's chip from the **Groups** panel to
   create a **group call**. For its **Args**, use the **ƒ** toggle to set `meter = {meter}`
   and `out = {out}` (threading the For-each variables in as `{holes}`).
4. Save and run.

![](../images/cb-07-service-group.png)
> *Screenshot: a Parallel containing a For each (rows for three meters/streams) whose body is
> one `service({meter}, {out})` group call.*

## Why it's built this way

The [group](../04-blocks/groups.md) captures the "service a vial" logic once, with its
devices left as **params**. [For each](../04-blocks/flow.md) then **stamps** the group call
once per row, and because the For each is the only thing in the **Parallel**, its three copies
become three lanes that run together — the same result as [recipe 6](06-parallel-vials.md),
but the servicing logic lives in **one** place. Add a step to `service` and all three vials
get it. That's the whole point of groups: define once, call many.

**Next:** [Recipe 8 — stop safely on contamination](08-safety-guard.md).
