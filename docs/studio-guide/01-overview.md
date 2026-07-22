# Overview

## What is Experiment Studio?

Experiment Studio is a **visual builder for experiments**. Instead of writing a script,
you assemble your experiment out of **blocks** — "dispense 1 ml", "read optical density",
"repeat 20 times", "if OD is too high, dilute" — by dragging them onto a **canvas**. When
the experiment is ready, you connect each step to a real device and press run.

Think of it as a recipe card that the lab devices follow exactly, every time.

You do two things in Studio:

1. **Build** the workflow — the focus of this guide.
2. **Run** it against your devices and watch what happens.

## The five tabs

Across the top of Studio are five tabs. This guide lives mostly in **Builder**.

| Tab | What it's for |
|-----|---------------|
| **Builder** | Design your experiment workflow. **This is where you'll spend your time.** |
| **Run** | Connect each step to a real device and execute the experiment. Covered here only as far as the quickstarts need. |
| **Records** | Look back at past runs and their data. Covered here only at quickstart depth. |
| **Devices** | Control a single device by hand (jog a pump, take one reading). Not covered in this guide. |
| **Labs** | See which lab and which devices are currently connected. Not covered in this guide. |

There is also a **theme toggle** (System / Light / Dark) if you prefer a darker screen — it
only changes appearance, nothing about your experiment.

![](images/overview-tabs.png)
> *Screenshot: the top tab bar with Builder, Run, Records, Devices, Labs, and the theme
> toggle. Highlight the Builder tab as the active one.*

## Anatomy of the Builder

The Builder has five regions. Learn these names — the rest of the guide uses them.

![](images/overview-builder-anatomy.png)
> *Screenshot: the whole Builder tab. Add numbered callouts for the five regions —
> 1 Palette (left), 2 Canvas (center), 3 Inspector (right), 4 Toolbar (top),
> 5 Problems strip (bottom).*

- **Palette** (left) — the parts bin. The top holds **block chips** you drag onto the
  canvas, grouped into Flow, Data, Pause, and Safety. Below them are panels for the
  workflow's **Roles, Streams, Constants, Bindings, and Groups** (all explained in
  [Concepts](03-concepts/index.md)).
- **Canvas** (center) — your workflow. Blocks stack top to bottom and nest inside one
  another. This is the experiment.
- **Inspector** (right) — the settings for whatever block you've selected. Click a block on
  the canvas and its settings appear here.
- **Toolbar** (top) — the experiment's name, save/load buttons, undo/redo, and a chip that
  tells you whether the workflow is valid.
- **Problems strip** (bottom) — a list of anything that needs fixing. It only appears when
  there's something to report.

## Working on the canvas

- **Add a block** — drag a chip from the Palette onto a **drop slot** (the gaps that
  appear between blocks and inside containers as you drag).
- **Edit a block** — click it once. It highlights, and its settings open in the Inspector
  on the right. Click an empty part of the canvas to deselect.
- **Each block on the canvas is a card** with a few controls:

![](images/overview-block-card.png)
> *Screenshot: a single block card selected. Label these controls — the colored role
> swatch, the block icon, the one-line summary, the red problem-count badge (if any), and
> the Duplicate and Delete buttons.*

  - a small **color swatch** if the block acts on a device (the role's color — see
    [Roles](03-concepts/roles.md)),
  - an **icon** for the block kind and a one-line **summary** of its settings,
  - a red **badge** with a number if the block has problems,
  - **Duplicate** and **Delete** buttons,
  - a collapse/expand toggle for blocks that contain other blocks.

## Saving and managing your work

Everything here lives in the **Toolbar**.

- **Name** — type your experiment's name in the field at the top left. A filled dot **●**
  next to it means you have **unsaved changes**.
- **New / Load / Save / Save as / Duplicate** — start fresh, open a saved experiment, save
  the current one, save a copy under a new name, or duplicate on the server.
- **Export / Import** — download the experiment as a `.json` file, or upload one. Handy for
  sharing an experiment or backing it up outside Studio.
- **Undo / Redo** — ⌘Z and ⇧⌘Z (Ctrl on Windows/Linux). You can also press **Delete** or
  **Backspace** to remove the selected block.

As you edit, Studio continuously checks your workflow. The **validation chip** in the
toolbar shows the result: *validating…*, *N problems*, or *valid*. When there are problems,
the **Problems strip** at the bottom lists them — click any one to jump straight to the
block that needs fixing. (More on this in the [block reference](04-blocks/index.md).)

---

**Next:** try [Quickstart A — your first run, no lab needed](02-quickstart/a-no-lab.md).
