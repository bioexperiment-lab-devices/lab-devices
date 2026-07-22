# Screenshots — shot list

The guide references the images below as **placeholders**. Each is a real screenshot to
capture and drop in here later; until then the image links render broken, which is expected.

Every image reference in the docs also has a **blockquote caption** right beneath it that
says exactly what to capture and what to annotate. Use that caption plus this table when
taking the shot. File names are relative to this `images/` folder.

**Conventions**

- Capture at a comfortable window width (the Builder's three columns all visible).
- Annotate with simple numbered callouts or boxes where the caption asks for it.
- Prefer a small, tidy example workflow over a real, cluttered one.
- Light or dark theme is fine — pick one and stay consistent.

| File | Used in | What to capture |
|------|---------|-----------------|
| `overview-tabs.png` | 01-overview | The top tab bar (Builder/Run/Records/Devices/Labs) + theme toggle; Builder active. |
| `overview-builder-anatomy.png` | 01-overview | Whole Builder with 5 numbered callouts: Palette, Canvas, Inspector, Toolbar, Problems strip. |
| `overview-block-card.png` | 01-overview | One selected block card; label swatch, icon, summary, problem badge, Duplicate, Delete. |

| `concept-roles-panel.png` | 03-concepts/roles | Roles panel grouped by device type, one role selected showing its swatch + verb chips. |
| `concept-streams-panel.png` | 03-concepts/streams | Streams panel with two streams (`od` AU, `temp_c` °C); units field + source tags. |
| `concept-bindings-panel.png` | 03-concepts/bindings-and-constants | Bindings panel, one binding expanded: type badge, writer, readers. |
| `concept-constants-panel.png` | 03-concepts/bindings-and-constants | Constants panel with `target_od = 0.6`, `cycle_min = 60`; value, unit, type badge. |
| `concept-expression-editor.png` | 03-concepts/expressions | Expression field editing `mean(od, last=5) > 0.6` with autocomplete popup + highlighting. |

| `block-command.png` | 04-blocks/device-actions | Command block (pump `dispense`) with Role/Verb/params in the Inspector. |
| `block-measure.png` | 04-blocks/device-actions | Measure block (densitometer `measure`) with Role/Verb/params + "Into stream" picker. |
| `block-retry.png` | 04-blocks/device-actions | Retry section for `dispense` showing the amber "allow repeat" hazard, Attempts, Backoff. |
| `block-serial.png` | 04-blocks/flow | Serial block containing three stacked children. |
| `block-parallel.png` | 04-blocks/flow | Parallel block with 2–3 lanes and the "+ lane" button. |
| `block-branch.png` | 04-blocks/flow | Branch with If, a then lane, and an else lane. |
| `block-loop.png` | 04-blocks/flow | Loop selected; Inspector Repeat=Until, an Until condition, Check dropdown. |
| `block-for-each.png` | 04-blocks/flow | For each with a `tube` variable table and a Rows grid. |

| `block-compute.png` | 04-blocks/data | Compute block; Inspector Into (binding), Value expression, Units→Cast. |
| `block-record.png` | 04-blocks/data | Record block; Inspector "Into stream" picker, Value, Cast. |
| `block-wait.png` | 04-blocks/pause | Wait block; Inspector Duration = `1min`. |
| `block-operator-input.png` | 04-blocks/pause | Operator input block; Inspector Binding name, Type, Prompt. |
| `block-alarm.png` | 04-blocks/safety | Alarm block; Inspector If condition + Message. |
| `block-abort.png` | 04-blocks/safety | Abort block; Inspector If condition + Message + stop note. |
| `block-group-scope.png` | 04-blocks/groups | Scope switcher on a group (hatched bg); Inspector Params/Locals. |
| `block-group-call.png` | 04-blocks/groups | Group-call block; Inspector Group picker, "As" prefix, Arg fields. |

| `qs-a-new.png` | 02-quickstart/a-no-lab | Builder toolbar with name "First run" and empty canvas. |
| `qs-a-operator-input.png` | 02-quickstart/a-no-lab | Operator input block; Inspector: dose_ml, float, min 0 max 50, prompt. |
| `qs-a-finished-canvas.png` | 02-quickstart/a-no-lab | Finished canvas: Operator input, Compute, Record, Wait, Alarm; chip "valid". |
| `qs-a-operator-prompt.png` | 02-quickstart/a-no-lab | Run-time operator prompt dialog "How many ml per dose?" with a number. |
| `qs-a-record.png` | 02-quickstart/a-no-lab | Records tab: finished run, `doses` stream value + alarm (if 40 entered). |
| `qs-b-roles.png` | 02-quickstart/b-pump-densitometer | Roles panel: `dye_pump` (pump), `od_meter` (densitometer) with swatches. |
| `qs-b-finished-canvas.png` | 02-quickstart/b-pump-densitometer | set_thermostat, dispense, Loop×20 (measure→od, read_temperature→temp_c, Wait 1min). |
| `qs-b-role-mapping.png` | 02-quickstart/b-pump-densitometer | Run tab role-mapping: dye_pump & od_meter device dropdowns + Start. |
| `qs-b-live-chart.png` | 02-quickstart/b-pump-densitometer | Running experiment; live chart with `od` rising. |
| `qs-b-record.png` | 02-quickstart/b-pump-densitometer | Records tab: finished run, `od` and `temp_c` charted. |

<!-- SHOT-LIST: entries are appended by each section below this line -->
