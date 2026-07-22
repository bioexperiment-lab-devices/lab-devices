# Block reference

This is the catalog of every block you can place on the canvas, and what its settings mean.
Keep it open in a second tab while you build.

## How to read an entry

Every block below follows the same shape:

- **What it does** — one plain sentence.
- **When to use it** — the lab situation that calls for it.
- **Settings** — the fields you fill in, in the Inspector on the right.
- **Details & gotchas** — a dropdown you can expand for the finer points. Click the
  triangle to open it.

Every block *also* has the **common settings** below, so those aren't repeated in each entry.

## Settings every block has

Select any block and its Inspector always offers these, in addition to the block's own
settings:

- **Label** — an optional nickname shown on the block's canvas card. Purely for you; name a
  step *"prime line"* or *"read vial 1"* so the canvas reads like a protocol.
- **Timing → Gap after** — an optional pause inserted **after** this block finishes, written
  as a [duration](../03-concepts/expressions.md) like `30s`. *(Not available on **For each**,
  and not on a block that is a lane inside a **Parallel** — use Start offset there instead.)*
- **Timing → Start offset** — for a lane **inside a Parallel** only: how long to wait after
  the Parallel starts before this lane begins. Lets you stagger lanes.
- **On failure → On error** — what happens if this block fails:
  - **fail (stop the run)** — the default; a failure ends the run.
  - **continue (tolerate the failure)** — log it and carry on.

  *(Not available on **Abort** or **For each**.)*
- **On failure → Retry** — only on **device actions** ([Command and Measure](device-actions.md)).
  Automatically re-tries a failed device call. See that page for the full details, including
  the safety opt-in for actions like dispensing.

> The Timing and On-failure sections stay collapsed until you use them; they open
> automatically when a block has a non-default value there.

## The block map

| Group | Blocks |
|-------|--------|
| **[Flow](flow.md)** | Serial · Parallel · Branch · Loop · For each |
| **[Data](data.md)** | Compute · Record |
| **[Pause](pause.md)** | Wait · Operator input |
| **[Safety](safety.md)** | Alarm · Abort |
| **[Device actions](device-actions.md)** | Command · Measure |
| **[Groups](groups.md)** | Group · Group call (`group_ref`) |

The Flow, Data, Pause, and Safety blocks are **chips in the Palette** — drag them onto the
canvas. **Device actions** are created by dragging a **verb chip** from a
[role](../03-concepts/roles.md). A **Group call** is dragged from the Groups panel.

## Validation and the Problems strip

Studio checks your workflow continuously as you edit. You'll see the result in three places:

- The **validation chip** in the toolbar: *validating…*, *N problems*, or *valid*.
- The **Problems strip** along the bottom lists each issue with a short message. **Click a
  problem to jump** to the exact block (or role) it's about.
- Inside the Inspector, a **red** message appears under the specific field that's wrong.
  Expression fields may also show an **amber** advisory note as you type — advisory notes
  are hints; red messages must be fixed before the workflow is valid.
