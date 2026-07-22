# Recipe 2 — Hold a temperature and log it every minute

**Goal:** turn on the thermostat at 37 °C, then log the temperature once a minute for twenty
minutes.

**Blocks used:** [Command](../04-blocks/device-actions.md) (set_thermostat) ·
[Loop](../04-blocks/flow.md) · [Measure](../04-blocks/device-actions.md) (read_temperature) ·
[Wait](../04-blocks/pause.md).

**Roles:** `od_meter` (densitometer — it carries the thermostat).

## Build it

1. Create a [role](../03-concepts/roles.md) `od_meter` (densitometer).
2. Drag the **`set_thermostat`** verb of `od_meter` onto the canvas. Set **enabled:** `true`,
   **target_c:** `37`.
3. Drag a **[Loop](../04-blocks/flow.md)** below it. Set **Repeat:** `Count`, **Count:** `20`.
4. Inside the loop, add two steps:
   - The **`read_temperature`** verb of `od_meter`, **Into stream:** new stream `temp_c`
     (unit `°C`).
   - A **[Wait](../04-blocks/pause.md)**, **Duration:** `1min`.
5. Save and run (map `od_meter` to a densitometer).

![](../images/cb-02-hold-temperature-log.png)
> *Screenshot: set_thermostat, then a Loop×20 containing read_temperature→temp_c and Wait
> 1min.*

## Why it's built this way

The thermostat is a **mode** — you turn it on once, before the loop, and it stays on;
Studio closes it safely when the run ends. `read_temperature` reads the temperature **without
running the optics**, so it's cheap to call often and won't interfere with OD readings if you
add them later. Twenty passes of one minute gives a twenty-minute log; change **Count** or the
**Wait** to rescale.

**Next:** [Recipe 3 — timed repeated dosing](03-timed-dosing.md).
