# Quickstart B — one pump and one densitometer

Now a real little experiment. You'll add dye to a tube of water and watch its **optical
density (OD)** climb, while the densitometer **holds a temperature** and you log it too — all
with just **two devices**: a pump and a densitometer.

> **The densitometer holds the temperature.** There is no separate thermostat device — the
> densitometer both reads OD and controls/reports temperature. So this experiment needs only
> a pump and a densitometer.

**You'll learn:** creating [roles](../03-concepts/roles.md), turning a role's verb into a
step, reading into a [stream](../03-concepts/streams.md), **mapping roles to real devices**,
watching the live chart, and opening the record.

**Before you start:** have a connected lab with at least one pump and one densitometer (a
simulated lab is fine).

---

## 1. Create the roles

A [role](../03-concepts/roles.md) is a labeled slot for a device. Create two:

1. In the **Palette**, find the **Roles** section.
2. In the **pump** group, use **+ add role** and name it `dye_pump`.
3. In the **densitometer** group, use **+ add role** and name it `od_meter`.

![](../images/qs-b-roles.png)
> *Screenshot: the Roles panel with `dye_pump` under pump and `od_meter` under densitometer,
> each with a colored swatch.*

---

## 2. Hold the temperature

Start by turning on the thermostat so the tube warms while everything else runs.

1. Click the **`od_meter`** role to reveal its verb chips.
2. Drag the **`set_thermostat`** chip onto the canvas.
3. In the block's Inspector, set the params:
   - **enabled:** `true`
   - **target_c:** `37`

This is a [Command](../04-blocks/device-actions.md) — it tells the device to do something.

---

## 3. Add the dye

1. Click the **`dye_pump`** role to reveal its verbs.
2. Drag the **`dispense`** chip onto the canvas, **below** the thermostat step.
3. In the Inspector, set **volume_ml:** `0.2`.

---

## 4. Repeat: read OD and temperature every minute

Now a loop that takes readings over time.

1. From the Palette, under **Flow**, drag a **Loop** onto the canvas, below the dispense.
2. In the Loop's Inspector, set **Repeat:** `Count`, **Count:** `20`.
3. **Inside** the Loop, add three steps in order:
   - Drag the **`measure`** verb of **`od_meter`** into the loop body. Set **Into stream:** a
     new stream named `od`, unit `AU`. This reads optical density into `od`.
   - Drag the **`read_temperature`** verb of **`od_meter`** into the loop body. Set **Into
     stream:** a new stream named `temp_c`, unit `°C`.
   - From the Palette under **Pause**, drag a **Wait** into the loop body. Set **Duration:**
     `1min`.

Both readings are [Measure](../04-blocks/device-actions.md) blocks — they capture a device
reading into a stream.

![](../images/qs-b-finished-canvas.png)
> *Screenshot: the finished canvas — set_thermostat, dispense, then a Loop (×20) containing
> measure→`od`, read_temperature→`temp_c`, and Wait 1min. Validation chip "valid".*

> **Optional:** add a [Branch](../04-blocks/flow.md) inside the loop with **If** `last(od) >
> 1.0` that does something when the culture gets dense — good practice once the basics work.

---

## 5. Save

Give it a name (e.g. `Dye and OD`) and click **Save**.

---

## 6. Map roles to devices, then run

This is the new step compared with Quickstart A.

1. Switch to the **Run** tab and select `Dye and OD`.
2. Studio lists your two roles and asks you to **map** each to a connected device:
   - **`dye_pump`** → choose a real pump.
   - **`od_meter`** → choose a real densitometer.
3. Start the run.

![](../images/qs-b-role-mapping.png)
> *Screenshot: the Run tab's role-mapping step — `dye_pump` and `od_meter` each with a device
> dropdown, and the Start button.*

---

## 7. Watch the live chart

As the loop runs, each reading appears on the **live chart**. Watch the `od` stream climb
after the dye goes in, and `temp_c` settle near 37 °C.

![](../images/qs-b-live-chart.png)
> *Screenshot: the running experiment with the live chart plotting the `od` stream rising
> over time.*

---

## 8. Open the record

When the run finishes, switch to the **Records** tab and open it. You'll find both streams
(`od` and `temp_c`), the full timeline, and the run's outcome — everything the experiment
collected.

![](../images/qs-b-record.png)
> *Screenshot: the Records tab with the finished run open, showing the `od` and `temp_c`
> streams charted.*

---

## What you learned

You designed an experiment around **roles**, turned a role's verbs into device steps,
collected readings into **streams**, **mapped roles to real devices**, watched data arrive
live, and reviewed the record.

**Next:**

- Read the [Concepts](../03-concepts/index.md) pages to deepen the ideas you just used.
- Browse the [Cookbook](../05-cookbook/index.md) for ready-to-build patterns — dosing loops,
  dilution decisions, running several vials at once, and more.
