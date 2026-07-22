# Experiment Studio User Guide — design spec

**Date:** 2026-07-22
**Status:** approved, ready for implementation
**Scope of this effort:** author comprehensive end-user documentation that teaches
**lab staff** how to **create and run experiment workflows** in the Experiment Studio
web UI. This session focuses on *creating* workflows; running/analysis is covered only
to the depth the quickstart needs (a full Run/Records reference is a later effort).

The deliverable is a nested folder of portable Markdown under `docs/studio-guide/`,
authored so it can be dropped into lab-bridge's MkDocs-like docs engine (nested folders
of `.md` files). Screenshots are left as annotated placeholders for the user to fill.

---

## 1. Decisions (locked)

| Question | Decision |
|----------|----------|
| Format / location | Nested Markdown folders under `docs/studio-guide/`; portable to lab-bridge's docs engine. Standard headings, relative image links, `<details>` for optional deep-dives. |
| Audience | **Non-programmer lab scientists.** Explain roles, streams, bindings, expressions from first principles. Second person, plain language, analogies to lab work, define every term on first use. |
| Run/analysis scope | **Quickstart depth only.** Role mapping, starting a run, watching the live chart, opening a run record — as far as the quickstart needs. No full Run-tab / Records-tab reference this round. |
| Cookbook | **New, escalating, hand-recreatable recipes** (8), distinct from the shipped `examples/` — those are too complex to recreate by hand. |
| Worktree | Authored on worktree `docs/studio-guide` branched from `main`. Spec + docs committed there; PR → CI → merge. |

### Non-goals (explicitly out of scope this round)

- Full **Run tab** reference (preflight internals, execution controls, event-log
  semantics, live-stream plumbing) beyond what the quickstart demonstrates.
- Full **Records tab** reference (run history browsing, record viewer, workflow
  snapshot diffing) beyond opening one record in the quickstart.
- **Devices tab** and **Labs tab** deep-dives (manual device control, lab roster).
  They get a one-line mention in the overview only.
- Administration, deployment, lab-bridge setup, device calibration.
- Screenshots themselves (placeholders only).

---

## 2. Documentation structure

```
docs/studio-guide/
  index.md                     — what this guide is, who it's for, reading order
  01-overview.md               — What Studio is; the 5 tabs at a glance; Builder anatomy
  02-quickstart/
    index.md                   — how the two walkthroughs build on each other
    a-no-lab.md                — simplest possible run, NO lab needed (learn the flow)
    b-pump-densitometer.md     — dye + OD monitor + thermostat; role-map → run →
                                 watch chart → open record
  03-concepts/
    index.md                   — why these four concepts, and how they relate
    roles.md                   — roles, device types, run-time mapping, colors
    streams.md                 — streams, units, measure-vs-record writers
    bindings-and-constants.md  — bindings (operator input / compute) vs constants
    expressions.md             — the expression language + where expressions appear
  04-blocks/
    index.md                   — how to read an entry; common settings (Label · Timing ·
                                 On-failure); the block map
    device-actions.md          — command & measure
    flow.md                    — serial · parallel · branch · loop · for_each
    data.md                    — compute · record
    pause.md                   — wait · operator_input
    safety.md                  — alarm · abort
    groups.md                  — groups & group_ref (reusable subroutines)
  05-cookbook/
    index.md                   — how to use recipes; index of the 8
    01-add-dye-read-od.md
    02-hold-temperature-log.md
    03-timed-dosing.md
    04-dilute-when-high.md
    05-operator-dose.md
    06-parallel-vials.md
    07-service-group.md
    08-safety-guard.md
  images/                      — screenshot placeholders (referenced, not created)
```

Rationale: **Concepts precede the block reference** because a non-programmer needs
"what is a role / stream / binding / expression" before `command` / `record` / `branch`
blocks are meaningful. **Groups** sits in the block reference (advanced); the quickstarts
never use it. Each folder carries an `index.md` so the tree maps to a docs-site nav.

---

## 3. Writing conventions

### 3.1 Per-block entry template

Every block in `04-blocks/` uses this shape so entries are scannable and detail is opt-in:

```markdown
### Loop
**What it does** — one plain sentence.
**When to use it** — the lab situation that calls for it.

![](../images/block-loop.png)
> *Screenshot: the Loop block on the canvas, Inspector open, Repeat = Until.*

**Settings**
- **Repeat** — Count (a fixed number of passes) or Until (a condition).
- **Count / Until** — depending on Repeat.
- **Check condition** — after each pass / before each pass.
- **Pace (min. loop period)** — the minimum time each pass should take.

<details><summary>Details &amp; gotchas</summary>

Deeper mechanics, e.g. "Until with check = before can run zero times;
pace makes a fast loop wait so cycles line up on a clock."
</details>
```

- **What it does / When to use it / Settings** are always visible.
- **Details & gotchas** go inside `<details>` (the "hidden behind a dropdown" ask).
- Settings bullets name the field exactly as it reads in the Inspector, then a plain gloss.

### 3.2 Screenshot placeholders

Every screenshot is an image link plus a blockquote caption that says exactly what to
capture and annotate:

```markdown
![](images/overview-builder-anatomy.png)
> *Screenshot: the Builder tab. Annotate the five regions — Palette (left),
> Canvas (center), Inspector (right), Toolbar (top), Problems strip (bottom).*
```

Placeholders reference `images/…` (or `../images/…` from a subfolder). The `images/`
folder is created with a short `README.md` listing every expected shot, so the user has a
shot list. No binary images are committed.

### 3.3 Tone & vocabulary

- Second person ("you"), present tense, plain language.
- Define every Studio term on first use, in lab terms. Example: *"A **role** is a
  labeled slot for a device — like 'the pump that adds medium'. You design the experiment
  with roles, then pick the real device for each role right before you run."*
- Prefer lab analogies over code analogies. No assumption of programming background.
- Cross-link generously (relative links) between concepts, blocks, and recipes.

### 3.4 Portability constraints

- No MkDocs-specific admonition syntax (`!!! note`). Use blockquotes and bold "Note:".
- `<details>` is the only HTML used, for the deep-dive dropdowns.
- All links relative; all images under `images/`.

---

## 4. Complete feature-coverage checklist

This is the "structured list of all Experiment Studio features" that guarantees coverage.
Every feature maps to the doc section that teaches it. Source of truth: the Builder
feature inventory (frontend `src/builder/*`, `types/doc.ts`, `types/catalog.ts`).

### 4.1 Platform / shell
- [ ] What Experiment Studio is; the workflow-authoring model → `01-overview`
- [ ] The five tabs (Builder, Run, Records, Devices, Labs) at a glance → `01-overview`
- [ ] Builder anatomy: Palette · Canvas · Inspector · Toolbar · Problems strip → `01-overview`
- [ ] Theme toggle (System/Light/Dark) — one-line mention → `01-overview`

### 4.2 Canvas & Toolbar
- [ ] Drag a palette chip onto the canvas; drop slots between blocks → `01-overview`, `04-blocks/index`
- [ ] Select a block → its Inspector; deselect on empty canvas → `01-overview`
- [ ] Block card: collapse/expand, role swatch, kind icon, summary, diagnostics badge, Duplicate, Delete → `01-overview`, `04-blocks/index`
- [ ] Scope switcher ("Editing: Main workflow ▾" / "+ New group…") → `04-blocks/groups`
- [ ] Toolbar: experiment name, unsaved `●` dot, validation chip → `01-overview`
- [ ] Undo / Redo (⌘Z / ⇧⌘Z / ⌘Y); Delete/Backspace removes selected → `01-overview`
- [ ] New · Load · Save · Save as · Duplicate → `01-overview`, `02-quickstart`
- [ ] Export (download JSON) · Import (upload JSON) → `01-overview`

### 4.3 Block-level common settings (every block)
- [ ] **Label** (display nickname) → `04-blocks/index`
- [ ] **Timing → Gap after** (delay inserted after the block; not on for_each / parallel-child) → `04-blocks/index`
- [ ] **Timing → Start offset** (parallel-lane offset; parallel-child only) → `04-blocks/index`, `flow`
- [ ] **On failure → On error** (fail / continue; absent on abort & for_each) → `04-blocks/index`
- [ ] **On failure → Retry** (command/measure only) → `04-blocks/device-actions`

### 4.4 Device actions
- [ ] **command** block: Role, Verb, Params → `04-blocks/device-actions`
- [ ] **measure** block: Role, Verb, Params, **Into stream** → `04-blocks/device-actions`
- [ ] Verb chips dragged from a role in the Roles section create command/measure → `04-blocks/device-actions`, `03-concepts/roles`
- [ ] Catalog drives verb list & params (enum selects, defaults, required) → `04-blocks/device-actions`
- [ ] Params in expression mode ("ƒ" escape for bool/numeric) → `04-blocks/device-actions`, `03-concepts/expressions`
- [ ] **Retry**: on-failure checkbox, `attempts` (total tries), `backoff`, `allow_repeat` hazard opt-in for non-idempotent verbs → `04-blocks/device-actions`

### 4.5 Flow blocks
- [ ] **Serial** — run children in order → `04-blocks/flow`
- [ ] **Parallel** — lanes run at once; "+ lane"; per-lane start offset → `04-blocks/flow`
- [ ] **Branch** — If / then / else (add/remove else lane) → `04-blocks/flow`
- [ ] **Loop** — Repeat Count|Until, Count expr, Until expr, Check before/after, Pace → `04-blocks/flow`
- [ ] **For each** — typed Loop variables, Rows grid, splicing-into-enclosing-list semantics → `04-blocks/flow`

### 4.6 Data blocks
- [ ] **Compute** — Into (binding), Value (expr), Units → Cast (as) → `04-blocks/data`
- [ ] **Record** — Into stream (picker + inline new stream), Value, Cast (as) → `04-blocks/data`

### 4.7 Pause blocks
- [ ] **Wait** — Duration (literal or expression) → `04-blocks/pause`
- [ ] **Operator input** — Binding name, Type (int/float/bool/enum), Min/Max, Choices, Prompt → `04-blocks/pause`

### 4.8 Safety blocks
- [ ] **Alarm** — If, Message; flags & continues; latch-once idiom → `04-blocks/safety`
- [ ] **Abort** — If, Message; sweeps devices safe, ends run "aborted" → `04-blocks/safety`

### 4.9 Groups
- [ ] **Group** — reusable subroutine: Params (typed), Locals (binding/stream), Body → `04-blocks/groups`
- [ ] **group_ref** — Group, As (call-site prefix; required with locals), Args (one per param) → `04-blocks/groups`
- [ ] `{hole}` args threaded from a for_each var → `04-blocks/groups`, `flow`

### 4.10 Roles (concept)
- [ ] Roles are symbolic; bound to real devices at run start → `03-concepts/roles`
- [ ] Grouped by device type (pump / valve / densitometer) → `03-concepts/roles`
- [ ] Add / rename / delete a role; naming rule `[a-z][a-z0-9_]*` → `03-concepts/roles`
- [ ] Role colors (8-swatch ramp, auto/positional, no-color) → `03-concepts/roles`
- [ ] Role → verb chips → command/measure → `03-concepts/roles`

### 4.11 Streams (concept)
- [ ] A stream is an append-only numeric series → `03-concepts/streams`
- [ ] Declared with a name + units; source tag (measure / record / unused) → `03-concepts/streams`
- [ ] measure writes a stream; record appends a computed sample → `03-concepts/streams`
- [ ] Naming rule `[A-Za-z_][A-Za-z0-9_]*` → `03-concepts/streams`

### 4.12 Bindings & Constants (concept)
- [ ] Bindings are scalar values written by operator_input and compute → `03-concepts/bindings-and-constants`
- [ ] Bindings panel is read-only; writers/readers, type badges → `03-concepts/bindings-and-constants`
- [ ] Constants: workflow-global, write-once, typed, optional unit → `03-concepts/bindings-and-constants`
- [ ] Binding/constant vs stream: scalar vs series → `03-concepts/bindings-and-constants`

### 4.13 Expressions (concept)
- [ ] Literals: numbers, durations (ms/s/min/h), strings, true/false → `03-concepts/expressions`
- [ ] Operators: `and or not`, comparisons (no chaining), arithmetic, parentheses → `03-concepts/expressions`
- [ ] Stat functions: `last mean min max count` over a stream → `03-concepts/expressions`
- [ ] Windows: all samples / `last=N` / `last=<duration>` → `03-concepts/expressions`
- [ ] The editor: highlighting, autocomplete (Ctrl-Space), help popover, live advisory checks → `03-concepts/expressions`
- [ ] Everywhere expressions appear (branch/abort/alarm if, loop count/until, compute/record value, durations, params) → `03-concepts/expressions`

### 4.14 Type system / units
- [ ] Typed kinds: int, number, bool, string, role, stream, binding (group params / for_each vars) → `04-blocks/groups`, `flow`
- [ ] Device param types (number/int/string/bool, enums) → `04-blocks/device-actions`
- [ ] `as` unit cast on compute/record/constants; inferred binding types (base + unit badge) → `03-concepts/bindings-and-constants`, `04-blocks/data`

### 4.15 Validation & Problems
- [ ] Live validation (debounced); the validation chip states → `01-overview`, `04-blocks/index`
- [ ] Problems strip: click a problem → jump to the block/role → `01-overview`, `04-blocks/index`
- [ ] In-Inspector field diagnostics (red) vs editor advisory (amber) → `03-concepts/expressions`, `04-blocks/index`

### 4.16 Running (quickstart depth only)
- [ ] Role mapping: bind each role to a real device before a run → `02-quickstart/b`
- [ ] Start a run; the preflight check → `02-quickstart/b`
- [ ] Watch a live stream on the chart → `02-quickstart/b`
- [ ] Operator input prompts during a run → `02-quickstart/a`, `pause`
- [ ] Open a run record afterward → `02-quickstart/b`
- [ ] Run without a lab (no-device flow) → `02-quickstart/a`

---

## 5. Quickstart designs

### 5.1 Quickstart A — "Your first run, no lab needed"
Goal: learn the create→save→run→observe loop with zero hardware. Uses only blocks that
need no device: **Operator input** (ask for a number), **Compute** (derive a value),
**Wait**, **Record** (log the value to a stream), and an **Alarm** guard. Runs against no
lab (or a simulated/empty lab). Teaches: palette→canvas drag, Inspector settings, save,
switch to Run, answer an operator prompt, watch the event log / a recorded stream, open
the record. Deliberately no roles/devices so the *flow* is the only new thing.

### 5.2 Quickstart B — "One pump and one densitometer"
Goal: a real (or simulated) small experiment. Add dye to a tube of water, monitor OD, and
hold + log the temperature — all with just **two devices**. The densitometer carries the
thermostat (there is no separate thermostat device type; see §7, resolved).
- Roles: `dye_pump` (pump), `od_meter` (densitometer).
- Workflow sketch: **command** `od_meter` `set_thermostat` (enabled = true, target_c = 37)
  to hold temperature → **command** `dye_pump` `dispense` a small volume → **Loop** (count)
  that each pass does **measure** `od_meter` `measure` into stream `od`, **measure**
  `od_meter` `read_temperature` into stream `temp_c`, then **Wait**s. Optionally a
  **Branch**/**Alarm** if OD climbs past a threshold.
- Teaches: creating roles, dragging verb chips (command vs measure), measure→stream, the
  live chart, role mapping at run start, managing the run, reading the record.

Both quickstarts end with "what you learned / where to go next" linking to Concepts and
the block reference.

---

## 6. Cookbook lineup (8 recipes, escalating)

Each recipe: goal → blocks used → step-by-step build (recreatable by hand) → screenshot
placeholder of the finished canvas → "why it's built this way" note.

1. **Add dye, then read OD once** — command + measure. (Sequential basics.)
2. **Hold a temperature and log it every minute** — Loop (count) + measure/record + Wait.
3. **Timed repeated dosing** — Loop with count + Pace so doses land on a clock.
4. **Dilute only when OD is too high** — Branch + a `last(od) > X` guard.
5. **Ask the operator for a dose at start** — Operator input → command param uses the binding.
6. **Run three vials in Parallel** — Parallel lanes, one measure each.
7. **A reusable `service(tube)` group** — group with a role/stream param, called per vial
   via for_each `{hole}` args. (The advanced payoff.)
8. **Stop safely on contamination** — Alarm to flag + Abort to stop, with a latch idiom.

Recipes 1–6 use only quickstart/concept material; 7–8 pull in Groups and Safety.

---

## 7. Resolved authoring facts (from the engine registry)

Source of truth for Builder verbs: `src/lab_devices/experiment/registry.py` (the trait
registry `/api/catalog` is built from). **Three device types only:** `pump`, `valve`,
`densitometer`. There is **no thermostat device type** — the densitometer carries it.

Builder verbs by device type (kind = **measure** iff `measurement=True`, else **command**):

- **pump** (all command): `dispense` (volume_ml req, speed_ml_min, direction fwd/rev,
  drop_suckback_ml; **not** retry-safe — relative dose), `rotate` (direction req,
  speed_ml_min req; not retry-safe), `stop` (retry-safe), `set_calibration` (retry-safe).
- **valve** (all command, all retry-safe): `set_position` (position int req, rotation
  shortest/direct/wrap), `home` (position int req), `configure` (default_rotation,
  hold_torque), `stop`.
- **densitometer**:
  - measure: `measure` → `absorbance`/OD (include_raw bool), `measure_blank` → `slope`,
    `read_temperature` → `temperature_c` (immediate, no subsystem — runs even while the
    thermostat mode is open). All retry-safe.
  - command: `set_led` (level int req), `set_thermostat` (enabled bool req default true,
    target_c number), `set_tube_correction` (factor req), `calibrate_tube`
    (reference_absorbance req; **not** retry-safe), `stop`, `stop_monitoring`.

Consequence for docs: only the densitometer has measure verbs; pump/valve are command-only.
This is what makes retry / `allow_repeat` (§4.4) matter — `dispense` and `rotate` are the
non-idempotent verbs that trigger the amber hazard opt-in.

> **NOTE:** `webapp/frontend/src/devices/catalog.ts` is the *Devices-tab* manual catalog and
> lists extra convenience commands (e.g. `start_monitoring`, `get_readings`, `read_raw`,
> `measure_blank`, `get_calibration`) plus a `status`→"Read temperature" alias. It does **not**
> drive the Builder. Document Builder verbs from the registry above; the Devices tab is out of
> scope.

Remaining during writing (no user input needed):
- **Screenshot shot list**: compile into `images/README.md` as the docs are written.

---

## 8. Definition of done

- All 16 checklist groups in §4 have their boxes covered by shipped sections.
- Every block in the palette (14 kinds) has a reference entry using the §3.1 template.
- Both quickstarts are complete and internally consistent with the block reference.
- All 8 cookbook recipes written.
- Every screenshot placeholder has a descriptive caption; `images/README.md` lists them all.
- Links resolve (relative), no MkDocs-specific syntax, `<details>` used only for deep-dives.
- Spec + docs committed on `docs/studio-guide`; PR opened, CI green, merged.
