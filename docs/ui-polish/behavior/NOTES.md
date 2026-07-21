# Behavior-fix verification evidence (Task 7)

End-to-end browser verification of the five behavior changes on
`feat/studio-ui-behavior`. Driven with Playwright against the worktree's isolated
devserver stack (FakeLab backend on :8150 with an added `valve_1`, vite dev on :5350).

All three gates were green before this pass:

- frontend: `oxlint` (4 pre-existing fast-refresh warnings, exit 0), `tsc -b`,
  733 vitest tests, `vite build` — all pass.
- webapp backend: 170 pytest, `mypy` (21 files) clean, `ruff` clean.
- engine: 1010 pytest, `mypy` (41 files) clean, `ruff` clean, no line > 100 cols in
  `src/lab_devices/experiment/*.py`.

The native `<select>` option lists are real DOM nodes, so each enum scenario asserts
the exact option set programmatically; for the screenshots the collapsed control was
momentarily expanded (`select.size = optionCount`, display-only) so the options render
inline.

| # | Scenario | Verdict | Screenshot | Key evidence |
|---|----------|---------|------------|--------------|
| a | New doc → Save → prompt (cancel creates nothing; accept creates + toolbar reflects saved) | PASS | `a1-toolbar-after-cancel.png`, `a2-toolbar-saved.png` | prompt title `Save…`, default `Untitled experiment`; experiment count 0→0 on cancel, 0→1 on accept; name adopts `task7-save-a`, no dirty dot, Duplicate enabled |
| b | Existing doc → Save silently PUTs (no prompt) | PASS | `b-toolbar-silent-put.png` | 0 dialogs, `PUT /api/experiments/<id>`, count unchanged |
| c | Command block on pump role → `rotate` → direction select forward/reverse; valve `set_position` → rotation select shortest/direct/wrap | PASS | `c1-inspector-pump-direction.png`, `c2-inspector-valve-rotation.png` | direction options `['', 'forward', 'reverse']`; rotation options `['', 'shortest', 'direct', 'wrap']` (leading `''` = "— unset —") |
| d | Devices tab → valve `set_position` rotation options shortest/direct/wrap | PASS | `d-devices-valve-rotation.png` | ParamForm rotation options `['', 'shortest', 'direct', 'wrap']` |
| e | Zero-role experiment + FakeLab selected → Start enabled → run starts and completes | PASS | `e1-start-enabled.png`, `e2-run-terminal.png` | "this experiment defines no roles", "workflow valid", Start enabled; run finished: `completed` |
| f | Stream left with blank units → save → reopen → still blank; exported JSON carries `"unitless"` | PASS | `f1-streams-blank-units.png`, `f2-streams-reloaded-blank.png` | units input placeholder `unitless`; server doc `streams.od.units == "unitless"`; reloaded `od` row units value `''` |

Engine-side (task 1) confirmed at the API: an out-of-enum literal
`direction: "sideways"` fails validation with
`expected one of ['forward', 'reverse'], got 'sideways'`; the catalog serves the
enum `values` for `pump.rotate.direction`, `pump.dispense.direction`,
`valve.set_position.rotation`, `valve.configure.default_rotation`.
