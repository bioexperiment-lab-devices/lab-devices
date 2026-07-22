# Experiment Studio User Guide — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author comprehensive, non-programmer-friendly documentation that teaches lab staff to create and run experiment workflows in Experiment Studio.

**Architecture:** A nested folder of portable Markdown under `docs/studio-guide/`, structured for lab-bridge's MkDocs-like docs engine (folders + `index.md`). Reference sections (overview, concepts, block reference) come first in writing order because the guided paths (quickstarts, cookbook) link back to them. Screenshots are annotated placeholders; a shot list lives in `images/README.md`.

**Tech Stack:** Markdown only. `<details>` for optional deep-dives. Relative links, relative image paths. No MkDocs-specific admonition syntax.

**This is a documentation deliverable, not code.** There are no unit tests. Each task's verification step is a *coverage + consistency check*: the spec's §4 checklist boxes the task covers, the per-block template (spec §3.1) is followed, every screenshot placeholder has a caption and a matching `images/README.md` entry, and links are relative.

## Global Constraints

- Location: `docs/studio-guide/` in the `lab-devices` repo (authored on worktree `docs/studio-guide`).
- Audience: **non-programmer lab scientists**. Second person, plain language, define every term on first use, lab analogies over code analogies (spec §3.3).
- Portability: no `!!! note` admonitions; `<details>` is the only HTML; all links/images relative (spec §3.4).
- Per-block entries use the spec §3.1 template: **What it does / When to use it / Settings** always visible; **Details & gotchas** inside `<details>`.
- Screenshot placeholders: image link + blockquote caption saying what to capture/annotate (spec §3.2). Every placeholder is also listed in `images/README.md`.
- Device facts come from the engine registry, verbatim from spec §7. **Three device types: pump, valve, densitometer. No thermostat type.** Only the densitometer has measure verbs (`measure`, `measure_blank`, `read_temperature`); everything else is a command verb. `dispense`/`rotate`/`calibrate_tube` are the non-retry-safe verbs.
- Run/analysis coverage is quickstart-depth only (spec §1 non-goals). Devices/Labs tabs get a one-line mention in the overview.
- Commit after each task with a `docs(studio):` message.

---

### Task 1: Scaffold — top index, folder tree, shot-list stub

**Files:**
- Create: `docs/studio-guide/index.md`
- Create: `docs/studio-guide/images/README.md`

**Covers (spec §4):** the entry point + reading order; establishes the `images/` shot-list mechanism.

- [ ] **Step 1: Write `docs/studio-guide/index.md`** — title, one-paragraph "what this guide is / who it's for" (lab staff, no coding needed), and a **reading order** list linking (relative) to: `01-overview.md`, `02-quickstart/`, `03-concepts/`, `04-blocks/`, `05-cookbook/`. Add a short "how to use this guide" note (start with a quickstart, keep the block reference open as you build).
- [ ] **Step 2: Write `docs/studio-guide/images/README.md`** — explain these are placeholders; a table with columns *file · used in · what to capture*. Seed the header row; each later task appends its shots.
- [ ] **Step 3: Verify** — both files exist; all links in `index.md` are relative and point to paths this plan will create.
- [ ] **Step 4: Commit** — `docs(studio): scaffold user guide (index + shot list)`

---

### Task 2: Platform overview

**Files:**
- Create: `docs/studio-guide/01-overview.md`

**Covers (spec §4):** 4.1 (what Studio is, five tabs, Builder anatomy, theme toggle), 4.2 (canvas & toolbar: drag chips/drop slots, select→Inspector, block card controls, toolbar name/dirty-dot/validation chip, undo/redo, New/Load/Save/Save-as/Duplicate, Export/Import), 4.15 (validation chip + Problems strip — introduced here, detailed later).

- [ ] **Step 1: Write "What is Experiment Studio"** — a visual workflow builder: you assemble an experiment out of blocks on a canvas, then run it against real lab devices. No coding.
- [ ] **Step 2: Write "The five tabs"** — one line each: **Builder** (design workflows — the focus of this guide), **Run** (map roles to devices and execute — quickstart depth), **Records** (past runs — quickstart depth), **Devices** (manual device control — out of scope here), **Labs** (which lab/devices are connected — out of scope here). Mention the System/Light/Dark theme toggle.
- [ ] **Step 3: Write "Anatomy of the Builder"** — the five regions with a plain gloss each: **Palette** (left: block chips + Roles/Streams/Constants/Bindings/Groups panels), **Canvas** (center: your workflow), **Inspector** (right: settings for the selected block), **Toolbar** (top: name, save, undo/redo, validation), **Problems strip** (bottom: what's wrong, click to jump). One annotated screenshot placeholder of the whole Builder.
- [ ] **Step 4: Write "Working on the canvas"** — drag a chip from the palette to a drop slot; click a block to open its Inspector; block-card controls (collapse/expand, role color swatch, icon, summary, red problem badge, Duplicate, Delete); click empty canvas to deselect. Screenshot placeholder of a block card with its controls labeled.
- [ ] **Step 5: Write "Saving & managing your work"** — experiment name field, the unsaved `●` dot, New/Load/Save/Save as/Duplicate, Export (download JSON) / Import (upload JSON), Undo/Redo (⌘Z / ⇧⌘Z) and Delete to remove a selected block. Note the validation chip states (validating… / N problems / valid) and that the Problems strip is covered where relevant.
- [ ] **Step 6: Verify** — §4.1, §4.2 boxes covered; screenshots added to `images/README.md`; links relative.
- [ ] **Step 7: Commit** — `docs(studio): overview (tabs, Builder anatomy, canvas, saving)`

---

### Task 3: Concepts — roles, streams, bindings/constants, expressions

**Files:**
- Create: `docs/studio-guide/03-concepts/index.md`
- Create: `docs/studio-guide/03-concepts/roles.md`
- Create: `docs/studio-guide/03-concepts/streams.md`
- Create: `docs/studio-guide/03-concepts/bindings-and-constants.md`
- Create: `docs/studio-guide/03-concepts/expressions.md`

**Covers (spec §4):** 4.10 roles, 4.11 streams, 4.12 bindings & constants, 4.13 expressions, 4.14 type/unit casts (the binding-type badge + `as`).

- [ ] **Step 1: `index.md`** — why these four ideas, and the one-line mental model of each; how they relate (roles = devices; streams = series of numbers over time; bindings/constants = single named values; expressions = how you compute/decide from all of them). Link to the four pages.
- [ ] **Step 2: `roles.md`** — a role is a labeled slot for a device ("the pump that adds medium"), symbolic until you bind it to real hardware at run start. Grouped by device type (**pump / valve / densitometer** — the only three). Add/rename/delete a role; naming rule (lowercase, letters/digits/underscore). Role colors (8-swatch ramp, auto/positional, or none) — every command/measure of a role shares its color. Dragging a role's **verb chips** onto the canvas creates command/measure blocks (forward-link to device-actions). Screenshot placeholder of the Roles panel with a role selected and its verb chips.
- [ ] **Step 3: `streams.md`** — a stream is an append-only series of numbers over the run (e.g. OD every minute), with a **name** and **units**. Declared in the Streams panel; a **source tag** shows which block writes it (measure / record / unused). `measure` writes device readings; `record` appends a value you compute. Naming rule. Screenshot placeholder of the Streams panel.
- [ ] **Step 4: `bindings-and-constants.md`** — a **binding** is a single named value produced during the run by **Operator input** (asked at start) or **Compute** (derived). The **Bindings** panel is read-only: it shows each binding's type badge, who writes it, who reads it (click to jump). A **constant** is a workflow-global, write-once value you set at design time (Constants panel), optionally with a unit. Contrast: binding/constant = one value (scalar); stream = many values over time (series). Explain the **type badge** (base + unit) and the **`as` unit cast** on compute/record/constants. Screenshot placeholders of the Constants and Bindings panels.
- [ ] **Step 5: `expressions.md`** — the little language you type into condition/value/duration fields. Cover: literals (numbers; durations `30s`, `5min`, `2h`; text `'forward'`; `true`/`false`); operators (`and`/`or`/`not`, comparisons `< <= > >= == !=` — no chaining, arithmetic `+ - * /`, parentheses); **stat functions** over a stream (`last`, `mean`, `min`, `max`, `count`) with **windows** (all samples, `last=5`, `last=30s`); the editor (color highlighting, autocomplete with Ctrl-Space, the help popover, live amber advisory checks vs red server errors). A "where expressions appear" list (branch/abort/alarm condition; loop count/until; compute/record value; wait/gap/offset/pace/backoff durations; numeric & bool device params via the "ƒ" toggle). Give 3–4 worked examples (`last(od) > 0.5`, `mean(od, last=5) > 0.6`, `cycle_min * 1min`). Screenshot placeholder of the expression editor with autocomplete open.
- [ ] **Step 6: Verify** — §4.10–4.14 boxes covered; every term defined on first use; screenshots in `images/README.md`; cross-links relative.
- [ ] **Step 7: Commit** — `docs(studio): concepts (roles, streams, bindings/constants, expressions)`

---

### Task 4: Block reference — index & common settings

**Files:**
- Create: `docs/studio-guide/04-blocks/index.md`

**Covers (spec §4):** 4.3 (Label, Timing → Gap after / Start offset, On failure → On error / Retry — membership rules), a "how to read an entry" note, and the block map linking to the six block pages.

- [ ] **Step 1: Write "How to read this reference"** — explain the entry template (What it does / When to use it / Settings / Details dropdown) and that every block also has the common settings below.
- [ ] **Step 2: Write "Settings every block has"** — **Label** (a nickname shown on the card). **Timing → Gap after** (a pause inserted after the block; not available on For-each or on a lane inside Parallel). **Timing → Start offset** (only for a lane inside Parallel — delays that lane's start). **On failure → On error** (fail = stop the run, the default; continue = tolerate and keep going; not on Abort or For-each). **On failure → Retry** (only on device actions — command/measure; forward-link).
- [ ] **Step 3: Write "The block map"** — a short table: Flow (Serial, Parallel, Branch, Loop, For each), Data (Compute, Record), Pause (Wait, Operator input), Safety (Alarm, Abort), Device actions (Command, Measure), Groups — each linking to its page.
- [ ] **Step 4: Write "Validation & the Problems strip"** — live validation as you edit; the chip; the Problems strip lists issues, click one to jump to the block; red field errors (server) vs amber advisories (expression editor).
- [ ] **Step 5: Verify** — §4.3 + §4.15 boxes covered; links to all six block pages resolve.
- [ ] **Step 6: Commit** — `docs(studio): block reference index + common settings`

---

### Task 5: Block reference — device actions & flow

**Files:**
- Create: `docs/studio-guide/04-blocks/device-actions.md`
- Create: `docs/studio-guide/04-blocks/flow.md`

**Covers (spec §4):** 4.4 device actions (command/measure, catalog-driven verbs/params, retry/allow_repeat), 4.5 flow (serial, parallel, branch, loop, for_each), and the flow-related type facts of 4.14 (for_each typed vars).

- [ ] **Step 1: `device-actions.md`** — intro: device actions come from a **role**; you create them by dragging a role's verb chip. Then two template entries:
  - **Command** — do something to a device. Settings: Role, Verb, Params (from the catalog: some are enums/dropdowns, some required, numeric/bool params accept expressions via "ƒ"). List the real verbs by type from spec §7 (pump: dispense/rotate/stop/set_calibration; valve: set_position/home/configure/stop; densitometer: set_led/set_thermostat/set_tube_correction/calibrate_tube/stop/stop_monitoring). Details dropdown: mode verbs (set_led/set_thermostat) and the safe-state `stop`.
  - **Measure** — take a reading into a **stream**. Settings: Role, Verb (densitometer only: `measure`→OD/absorbance, `measure_blank`→slope, `read_temperature`→°C), Params, **Into stream**. Details dropdown: `read_temperature` runs even while the thermostat is on.
  - **Retry** section (shared): the on-failure Retry checkbox; **Attempts** (total tries incl. the first); **Backoff**; the amber **allow repeat** hazard for non-idempotent verbs (`dispense`, `rotate`, `calibrate_tube`) — explain *why* retrying a dispense is dangerous (double-dose). Screenshot placeholders: a Command Inspector, a Measure Inspector, the Retry section with the amber hazard.
- [ ] **Step 2: `flow.md`** — five entries with the template:
  - **Serial** — run children top to bottom. Settings: none unique (managed on canvas).
  - **Parallel** — run lanes at the same time. Settings: lanes managed on canvas ("+ lane"); each lane can have a **Start offset**. Details: dropping a block onto a Parallel wraps it as a lane.
  - **Branch** — do one thing or another based on a condition. Settings: **If** (expression), **then** lane, optional **else** lane (add/remove). Example `last(od) > 0.5`.
  - **Loop** — repeat. Settings: **Repeat** (Count | Until); **Count** (a number or int expression) or **Until** (a condition) + **Check** (after/before each pass); **Pace** (minimum period per pass). Details: Until + check=before can run zero times; Pace lines cycles up on a clock.
  - **For each** — stamp out a copy of the body per row. Settings: **Loop variables** (typed: int/number/bool/string/role/stream/binding), **Rows** (one value per variable per row). Details: it *splices* copies into the enclosing list — sole child of a Parallel becomes N lanes; inside a Serial, an N-step sequence. It has no timing/on-failure of its own.
- [ ] **Step 3: Verify** — §4.4, §4.5 boxes covered; verbs match spec §7 exactly; template followed; screenshots logged.
- [ ] **Step 4: Commit** — `docs(studio): block reference — device actions & flow`

---

### Task 6: Block reference — data, pause, safety, groups

**Files:**
- Create: `docs/studio-guide/04-blocks/data.md`
- Create: `docs/studio-guide/04-blocks/pause.md`
- Create: `docs/studio-guide/04-blocks/safety.md`
- Create: `docs/studio-guide/04-blocks/groups.md`

**Covers (spec §4):** 4.6 data (compute, record), 4.7 pause (wait, operator_input), 4.8 safety (alarm, abort), 4.9 groups (group + group_ref, `{hole}` args), plus type-kind facts (4.14).

- [ ] **Step 1: `data.md`** — **Compute** (Into = binding name, Value = expression, Units → Cast `as`) and **Record** (Into stream = picker with inline "new stream", Value, Cast `as` must match the stream's unit). Explain compute writes a scalar binding; record appends a sample to a series. Screenshot placeholders of each Inspector.
- [ ] **Step 2: `pause.md`** — **Wait** (Duration — literal like `30s`/`5min` or an expression). **Operator input** (Binding name; Type = int/float/bool/enum; Min/Max for numbers; Choices for enum; Prompt). Note the operator answers at run start / when reached. Screenshot placeholders.
- [ ] **Step 3: `safety.md`** — **Alarm** (If, Message; flags the run and continues; fires every time it holds — latch it once with a compute). **Abort** (If, Message; sweeps devices safe and ends the run "aborted"). Contrast the two. Screenshot placeholders.
- [ ] **Step 4: `groups.md`** — a **group** is a reusable subroutine you build once and call many times. Editing: the canvas scope switcher / "+ New group". Its Inspector: **Params** (typed inputs — role/stream/binding/int/number/bool/string) and **Locals** (its own private binding/stream). **group_ref** (the call): pick the Group, a **call-site prefix (As)** required when the group has locals, and one **Arg** per param. `{hole}` args let a For-each variable flow into a call (e.g. call `service(tube)` per vial). Note the current limitation area lightly if relevant. Screenshot placeholders of a group scope and a group_ref Inspector.
- [ ] **Step 5: Verify** — §4.6–4.9 boxes covered; template followed; screenshots logged.
- [ ] **Step 6: Commit** — `docs(studio): block reference — data, pause, safety, groups`

---

### Task 7: Quickstarts

**Files:**
- Create: `docs/studio-guide/02-quickstart/index.md`
- Create: `docs/studio-guide/02-quickstart/a-no-lab.md`
- Create: `docs/studio-guide/02-quickstart/b-pump-densitometer.md`

**Covers (spec §4):** 4.16 running (role mapping, start a run, live chart, operator prompts, open a record, no-lab flow) + reinforces earlier concepts by doing.

- [ ] **Step 1: `index.md`** — the two walkthroughs and how they build (A = the flow with no hardware; B = a real two-device experiment). Prereqs (Studio open; for B, a lab with a pump + densitometer, real or simulated).
- [ ] **Step 2: `a-no-lab.md`** — step-by-step (spec §5.1): drag **Operator input** (ask a number, e.g. `dose_ml`), **Compute** (derive something, e.g. `total = dose_ml * 3`), **Record** it to a stream, add a **Wait**, add an **Alarm** guard. Save. Switch to **Run**, start it (no role mapping needed — no devices), answer the operator prompt, watch the event log / recorded value, open the **record**. Each UI step gets a screenshot placeholder. Callout: this teaches the create→run→observe loop with zero hardware.
- [ ] **Step 3: `b-pump-densitometer.md`** — step-by-step (spec §5.2): create roles `dye_pump` (pump) and `od_meter` (densitometer). Build: **command** `od_meter` `set_thermostat` (enabled true, target_c 37) → **command** `dye_pump` `dispense` (volume_ml small) → **Loop** count N doing **measure** `od_meter` `measure` into `od`, **measure** `od_meter` `read_temperature` into `temp_c`, then **Wait** 1 min. Save. Switch to **Run**: **map each role to a real device** (the key new step), start, watch **od** on the live chart, then open the **record** afterward. Screenshot placeholders for role creation, verb-chip drag, role mapping, and the live chart. Close with "what you learned" linking to Concepts and the block reference.
- [ ] **Step 4: Verify** — §4.16 boxes covered; every verb/param matches spec §7; screenshots logged; links relative.
- [ ] **Step 5: Commit** — `docs(studio): quickstarts (no-lab + pump/densitometer)`

---

### Task 8: Cookbook

**Files:**
- Create: `docs/studio-guide/05-cookbook/index.md`
- Create: `docs/studio-guide/05-cookbook/01-add-dye-read-od.md`
- Create: `docs/studio-guide/05-cookbook/02-hold-temperature-log.md`
- Create: `docs/studio-guide/05-cookbook/03-timed-dosing.md`
- Create: `docs/studio-guide/05-cookbook/04-dilute-when-high.md`
- Create: `docs/studio-guide/05-cookbook/05-operator-dose.md`
- Create: `docs/studio-guide/05-cookbook/06-parallel-vials.md`
- Create: `docs/studio-guide/05-cookbook/07-service-group.md`
- Create: `docs/studio-guide/05-cookbook/08-safety-guard.md`

**Covers (spec §6):** the 8 escalating recipes. Each recipe: **Goal / Blocks used / Build it (numbered steps recreatable by hand) / Screenshot of finished canvas / Why it's built this way**.

- [ ] **Step 1: `index.md`** — how to use recipes (recreate by hand — Studio is visual), a difficulty-ordered list linking the 8, and which concept/block each exercises.
- [ ] **Step 2: Write recipes 01–06** (quickstart/concept material only): 01 add dye then read OD (command + measure); 02 hold temperature & log every minute (set_thermostat + Loop + measure/record + Wait); 03 timed repeated dosing (Loop count + Pace); 04 dilute only when OD too high (Branch + `last(od) > X` + dispense); 05 ask operator for a dose at start (Operator input → dispense param references the binding); 06 run three vials in Parallel (three measure lanes). Each with the five-part structure and a finished-canvas screenshot placeholder.
- [ ] **Step 3: Write recipes 07–08** (advanced): 07 reusable `service(tube)` group with a role/stream param called per vial via For-each `{hole}` args; 08 stop safely on contamination (Alarm to flag + Abort to stop, with the latch idiom). Five-part structure + screenshots.
- [ ] **Step 4: Verify** — all 8 present, five-part structure each, verbs match spec §7, screenshots logged; recipes 1–6 use only quickstart/concept blocks, 7–8 pull in groups/safety.
- [ ] **Step 5: Commit** — `docs(studio): cookbook (8 escalating recipes)`

---

### Task 9: Coverage pass, link check, finalize

**Files:**
- Modify: `docs/studio-guide/index.md` (final reading-order polish)
- Modify: `docs/studio-guide/images/README.md` (complete shot list)
- Modify: any file with a broken/inconsistent link found in the sweep.

- [ ] **Step 1: Coverage sweep** — walk spec §4 (all 16 groups) and confirm every box maps to a shipped section. Note the mapping in a short comment at the bottom of `index.md` or a `COVERAGE.md`. Fix any gap by adding the missing content to the owning file.
- [ ] **Step 2: Link & image sweep** — grep for markdown links and image refs; confirm each target file exists and each image is listed in `images/README.md`. Fix mismatches.
- [ ] **Step 3: Consistency sweep** — every block entry follows the §3.1 template; no `!!!` admonitions; `<details>` only for deep-dives; terms defined on first use; device verbs/params match spec §7 everywhere.
- [ ] **Step 4: Commit** — `docs(studio): coverage pass, link check, finalize guide`

---

## Self-Review (run after drafting the plan)

**Spec coverage:** Each spec §4 group (4.1–4.16) is assigned to a task: 4.1/4.2/4.15→T2 & T4; 4.3→T4; 4.4→T5; 4.5→T5; 4.6/4.7/4.8/4.9→T6; 4.10–4.13→T3; 4.14→T3/T5/T6; 4.16→T7. Cookbook (spec §6)→T8. Quickstarts (spec §5)→T7. Structure (spec §2)→T1. Conventions (spec §3)→every task's template + T9 sweep. No gaps.

**Placeholder scan:** No "TBD/TODO/handle edge cases". Each task names exact files and the exact content outline + which §4 boxes it closes. (Full prose is produced at execution — appropriate for a docs deliverable; the plan fixes structure, coverage, and facts.)

**Type consistency:** Device types (pump/valve/densitometer), verb names, and param names are used identically across T5/T6/T7/T8, all sourced from spec §7. Stream names (`od`, `temp_c`) and binding names (`dose_ml`, `total`) are consistent between the quickstarts and cookbook.
