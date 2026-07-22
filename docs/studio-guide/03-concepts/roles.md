# Roles

A **role** is a labeled slot for a device — like *"the pump that adds medium"* or *"the OD
meter for vial 1"*. You design the whole experiment using roles, and then pick the real
device for each role right before you run.

This is the single most important idea in Studio. Because your workflow talks about
`medium_pump` (a role) instead of a specific serial-numbered pump, the same experiment runs
on any lab that has a pump — you just point the role at whatever pump is plugged in that day.

> **Roles are symbolic.** Nothing in the Builder is tied to physical hardware. The
> connection happens at run time, in the Run tab, when you **map** each role to a device.

## Device types

Every role has a **device type**. There are three:

- **pump** — moves liquid (dispense a volume, run continuously).
- **valve** — selects a position (route tubing to one of several ports).
- **densitometer** — reads optical density (OD), and also holds a temperature and reports it.

The Roles panel groups your roles by type, so all your pumps sit together, all your
densitometers together, and so on.

![](../images/concept-roles-panel.png)
> *Screenshot: the Roles panel in the Palette, grouped by device type, with one role
> selected so its color swatch and verb chips are visible.*

## Creating and naming roles

In the Roles panel:

- **Add a role** — use the "+ add role" form inside the device-type group. You give it a
  name; the type is decided by which group you add it to.
- **Rename** or **delete** the selected role with the pencil and ✕ controls.

A role name must be **lowercase**, start with a letter, and use only letters, digits, and
underscores — for example `medium_pump`, `od_meter_1`, `waste_valve`. Studio won't let you
create a name that breaks this rule or one that's already taken.

## Role colors

Each role gets a **color** from a fixed palette, assigned automatically in the order you
create roles. Every device action for that role — every dispense, every reading — carries
the same colored swatch on its canvas card, so you can see at a glance which device a step
touches. You can override a role's color, set it back to **auto**, or choose **no color**.

## From a role to a device action

Selecting a role reveals its **verb chips** — the things that device can do (a pump shows
*dispense*, *rotate*, …; a densitometer shows *measure*, *read temperature*, …). **Drag a
verb chip onto the canvas** to create a step that commands or reads that device. That step
is a **command** or **measure** block — see [Device actions](../04-blocks/device-actions.md).

## What you'll do with roles later

When you press run, Studio shows every role and asks you to **map** it to a connected
device. Until then, roles are just names and colors. See
[Quickstart B](../02-quickstart/b-pump-densitometer.md) for role mapping in action.

---

**Related:** [Streams](streams.md) · [Device actions](../04-blocks/device-actions.md)
