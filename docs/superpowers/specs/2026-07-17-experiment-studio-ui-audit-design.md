# Experiment Studio — UI audit workflow

**Status:** design, user-settled 2026-07-17
**Target:** `experiment-studio` 0.7.0 (`main` @ `d3b022f`), W1–W9 shipped
**Predecessors:** `2026-07-11-experiment-studio-webapp-design.md` (S1–S10),
`2026-07-16-experiment-studio-export-import-design.md` (W7),
`2026-07-16-experiment-studio-engine-parity-design.md` (W8/W9, P1–P4)

---

## 1. Problem

Nine increments built the Studio's UI and not one of them looked at it. Every gate was a unit
test, a type check, or a scripted walkthrough that asserted *text content* — `hasText`, a class
name, an event kind. None asserted that a human can read the screen. The one visual defect the
project did catch, it caught by accident, and only after shipping: W7's §7 note used `truncate`
with no `title`, so the 127-character message explaining "this success isn't a failure" was
itself unreadable below 1920px. That bug passed every gate the repo had.

This spec defines a repeatable workflow for finding that class of defect deliberately.

### 1.1 Why "take screenshots and look at them" is not enough

Screenshots plus model judgment is an unreliable oracle. Left to assess pictures freehand, the
reviewer invents nitpicks, misses real breakage, and produces findings indistinguishable from
taste — which the reader then correctly discards, taking the true findings with them.

The fix is to notice that most genuine visual bugs are **boundary** bugs, and boundaries are
mechanically checkable in the DOM with no judgment at all. `scrollWidth > clientWidth` under
`overflow: hidden` means content is unreachable — that is a fact, not an opinion. So the audit
splits into two tracks with different evidence standards, and judgment is spent only where
measurement cannot reach.

---

## 2. Scope

**In:** all four tabs (Devices, Builder, Run, Records), including a live run and a finished
record. Desktop widths 1024–1920. Static, transient, empty, and error states.

**Out:** tablet and phone widths — Studio is a desktop lab tool behind Authelia, and treating
390px as supported would generate a large volume of findings that are really feature requests.
Fixes are out: this workflow ends at a triaged report (§3, D4).

---

## 3. Settled decisions

| # | Fork | Decision |
|---|---|---|
| **D1** | Surfaces | **All four tabs + a live run + a finished record.** The devserver's FakeLab makes a run cheap, and Run/Records hold the states that exist nowhere else: `InputDialog`, `PreflightPanel`, `EventLog`, the live WS chart. They are also the least-reviewed components in the app. |
| **D2** | Viewports | **Desktop only.** Probes sweep 1024×720 / 1280×800 / 1920×1080; judgment screenshots at 1440×900, with the extremes shot only where probes point. 1024×720 is not hypothetical — it stresses `BuilderTab`'s hardcoded `h-[calc(100vh-9rem)]`, which assumes the header never wraps. |
| **D3** | Harness permanence | **Fixture committed, script scratchpad.** The torture doc is the expensive artifact and is reusable; the playwright script is cheap to rewrite and stays out of `package.json` (no browser download in the frontend gates). Matches the W3/W5 precedent — *"scratchpad only, not committed"*. The recipe lives in §11 of this doc. |
| **D4** | Fix boundary | **Audit only, severity-triaged.** Fixes land as a separate increment. If the auditor may also fix, findings drift toward whatever is cheap to fix and the expensive layout problems get quietly downgraded. |
| **D5** | Screenshot storage | **Only cited screenshots are committed**, under `docs/ui-audit/2026-07-17/`. The full ≈42-state × 3-viewport capture set stays in scratchpad. A report whose evidence is a dead scratchpad path is unreadable in a month; committing all ~126 captures is megabytes of noise. |
| **D6** | Settled list | **Re-examined, not muted** (§8). |

---

## 4. Targets

Two environments, each doing the job the other cannot.

**Local (primary).** `webapp/backend/tests/devserver.py` (FakeLab) on :8000 + `npm run dev` on
:5173. This is where state is controllable: seed the torture doc, force an empty database, kill
the backend to photograph the error path, reset between captures, iterate in seconds.

**Preprod (secondary).** `https://111.88.145.138/studio/`, verified 0.7.0 this session —
`{"status":"ok","library":"0.7.0","studio":"0.7.0"}` — identical to local HEAD. It gets the
three jobs local cannot fake: the **real 7-device roster** on the Devices tab (real names, real
types, real widths), a **real-hardware run**, and the **`/studio/` sub-path proxy**.

> **Version discipline.** Preprod ran 0.6.0 until shortly before this design. 0.6.0 is the cut
> *before* W8 and W9, so an audit there would have missed the Control palette, the group scope
> switcher, and `for_each` rendering, and `morbidostat.json` would not have opened at all.
> **Re-assert `/studio/api/health` before every preprod capture session.** A stale preprod does
> not fail loudly — it silently audits an app that no longer exists.

**Preprod auth recipe** (proven this session). The login portal is **siteapp's**, not
Authelia's own — `compose/Caddyfile.tmpl` mounts Authelia at `/auth/*` with `strip_prefix`, so
`POST /api/firstfactor` hits the SPA catch-all and returns **200 with portal HTML**, which looks
like a success and is not one. The real endpoint:

```
POST https://111.88.145.138/api/auth/firstfactor
     {"username": ..., "password": ..., "targetURL": "/studio/", "keepMeLoggedIn": true}
  → 200 {"redirect": "/studio/"} + authelia_session cookie
```

The cert is self-signed: playwright needs `ignoreHTTPSErrors: true`, curl needs `-k`.

---

## 5. The two tracks

### 5.1 Track A — mechanical probes

A script walks the DOM at each state × viewport and emits violations that need no taste. Output
is JSON, one record per violation:

```json
{"state": "builder/inspector/compute", "viewport": "1280x800",
 "rule": "truncate-no-title", "severity": "violation",
 "selector": "div.truncate", "text": "imported as 'Morbidostat' — saved, but…",
 "detail": {"scrollWidth": 420, "clientWidth": 180}}
```

| Rule | Test | Severity |
|---|---|---|
| `page-h-scroll` | `documentElement.scrollWidth > innerWidth + 1` | violation |
| `clipped-overflow` | computed `overflow-x\|y` ∈ {`hidden`,`clip`} **and** `scrollWidth > clientWidth + 1` — content unreachable | violation |
| `truncate-no-title` | `text-overflow: ellipsis` **and** overflowing **and** no `title` / `aria-label` — the W7 bug | violation |
| `zero-area-control` | interactive, not `display:none`/`visibility:hidden`, rect area 0 — unclickable | violation |
| `low-contrast` | text vs first non-transparent ancestor background, WCAG AA (4.5:1; 3:1 at ≥18.66px or ≥14px bold) | violation |
| `overlap` | two interactive rects intersecting > 25% of the smaller | violation |
| `unexpected-scroll` | `overflow-x: auto\|scroll` **and** overflowing | **suspicion** |
| `tiny-target` | interactive element < 24px on either axis | **suspicion** |

**The false-positive traps, and why the split matters.** A probe that cries wolf is worse than
no probe, because its output stops being read.

- `overflow: auto` that scrolls is usually *intended* — S1 makes Parallel N side-by-side lanes,
  and lanes are supposed to scroll. It is a **suspicion**, resolved by judgment, never an
  automatic finding.
- `overlap` fires on every deliberate overlay. Elements inside `[role=dialog]` and the dnd-kit
  `DragOverlay` are excluded, and the rule is skipped entirely while a dialog is open.
- `low-contrast` is approximate: it cannot resolve gradients or background images. When the
  effective background is an image, downgrade to suspicion.
- `tiny-target` is a suspicion because a 20px icon button in a dense inspector may be a
  considered trade-off, not an accident.

### 5.2 Track B — judgment

Screenshots at 1440×900: full page per state, plus a clipped shot per component. Reviewed only
for what Track A structurally cannot see (§5.3).

### 5.3 The rubric

Findings must be arguable, so judgment is spent against a written standard rather than vibes:

1. **Hierarchy** — is the primary action obvious? Is the selected block visually dominant?
2. **Rhythm** — consistent spacing scale, border weight, radius. Tailwind's scale is the ruler.
3. **Alignment** — label/field alignment across the Inspector's 936 lines of generated forms.
4. **Affordance** — is a drop slot obviously droppable? Is a disabled control obviously
   *disabled*, or just gray?
5. **State legibility** — can you tell running from paused from aborted at a glance?
6. **Error presentation** — does colour match severity? (Note the W7 §7 contract in §8.)
7. **Empty states** — do they say what to do next, or just show nothing?
8. **Cross-tab consistency** — do four tabs feel like one app?

---

## 6. The fixtures

Two documents, because one cannot do both jobs. **This is the load-bearing decision of the
design.** Judge aesthetics on a pathological document and every finding is "nobody would do
that" — the reader discards the report wholesale, including the true findings.

### 6.1 `examples/morbidostat.json` — realistic, feeds Track B

Already 12 streams, 1 group, ~35 blocks across 11 kinds. A real experiment. Judgment findings
here are credible because a user really will see this screen.

### 6.2 `webapp/fixtures/ui-audit-torture.json` — pathological, feeds Track A

Built to hit boundaries, not to be pretty:

- **all 14 block kinds.** `BuilderTab`'s `STRUCTURE_TITLES` lists 12, but that is the *palette*
  set; `tree.ts` has fourteen `BlockNode` kinds. The two extras are `command` and `measure`,
  built by `newVerbNode` from the verb palette rather than the structure list — and they are the
  most common blocks in any real experiment, with Inspector forms **generated from the verb
  registry** (S1). That generated form is where layout defects are most likely and least
  reviewed. Full set: `command`, `measure`, `serial`, `parallel`, `loop`, `branch`, `wait`,
  `operator_input`, `compute`, `record`, `abort`, `alarm`, `for_each`, `group_ref`.
- at least one `command`/`measure` per device type in the catalog, so every generated param form
  shape is photographed — including the widest one
- nesting ~8 deep, to test Canvas indentation
- **8+ parallel lanes** — S1 renders Parallel as N side-by-side lanes, which is a horizontal
  overflow gun aimed at the Canvas
- 80-character role names, stream names, and labels
- 30+ streams and 15+ roles, to overflow `RolesPanel` / `StreamsPanel`
- 5+ groups, to overflow the scope switcher
- empty containers (empty `serial`, empty `loop` body), to render bare drop slots
- 200+ character expressions in `compute` / `branch` / `abort` conditions
- long `alarm` / `abort` messages — the W7 truncate class
- **a group name containing a space** — the compound-path trap that cost W9 three review rounds
- deliberate validation errors, to fill `ProblemsPanel`

**The fixture must open before anything else happens.** If `docToTree` throws `DocConvertError`,
the Builder shows the §7 note and the capture pass photographs 25 screenshots of an error card.
Task 1 is: build the fixture, POST it, and prove it renders in a real browser. Nothing is
captured until it does.

---

## 7. The state matrix

≈42 states. Probes at 3 viewports; screenshots at 1440×900.

| Tab | States |
|---|---|
| **Devices** (4) | no lab selected · lab + roster loaded · discovery in progress · discovery error / backend down |
| **Builder** (≈28) | new/empty doc · morbidostat main scope · morbidostat `service` scope · torture doc · torture deep-nest region · torture 8-lane parallel · LoadDialog · Palette · RolesPanel · StreamsPanel · ProblemsPanel (many diagnostics) · dirty/unsaved · drag in flight (DragOverlay) · drop-slot hover · **Inspector × 14 block kinds** (§6.2) |
| **Run** (6) | preflight unmapped · preflight ready · running + live chart · operator input dialog · paused · finished/aborted |
| **Records** (4) | empty · table with N records · RecordViewer + charts · WorkflowSnapshot |

---

## 8. The settled list — re-examined, not muted

Some things that look like bugs are decisions already made. Reporting them wastes the reader's
attention re-litigating settled forks. But a mute list is also where bad decisions hide, so each
item is **deliberately re-examined against the visual evidence and its original rationale**, and
the report carries a verdict per item: **holds** or **worth revisiting**, each with the
screenshot that argues it. Settled items stay out of the main findings either way; the verdicts
live in their own section.

| Decision | Source | Rationale on record | Re-examine |
|---|---|---|---|
| Parallel = **N side-by-side lanes** | S1 | parallelism is *spatially* visible; Blockly stacks arms vertically | Does it survive 8 lanes at 1024px, or does spatial visibility become a horizontal scrollbar that hides lanes 5–8? |
| Tabs **stepper-styled but freely navigable** | S6 | Records is its own tab so Run stays focused | `TabShell` renders numbered pills (`1 Devices` …). Does the numbering promise an order that isn't enforced — and does that mislead? |
| **No persistence knobs**; streams panel = name + units | S5 | all streams always recorded | With 30+ streams, does a name+units list stay navigable? |
| `for_each` **authored view only**, no expansion preview | P4 | YAGNI; matches the engine's DRY-source model | Can an author tell what will actually run from `∀ For each tube in [1,2,3]` alone? |
| `for_each` Inspector **omits** `retry`/`on_error`/`gap_after`/`start_offset` | §5.1 | `_FOR_EACH_FORBIDDEN` — a macro is a splice, no runtime block to attach to | Is the absence legible, or does the Inspector just look inconsistent with every other container? |
| `abort` renders **no On-error row** | W8-settled | a control whose only non-default value always yields an invalid doc is a UX defect | Same question: silent absence vs. explained absence. |
| Control glyphs **ƒ ✎ ⚠ ⛔**, non-arrow | W8-settled | `↻ Loop ×3 ↻2` is why retry's marker is `R×N` | Do four glyphs from four visual families read as one palette section? |
| `∀ For each` / `⧉ service(tube=1)` cards | §5.1, §5.2 | `∀` cannot be confused with loop's `↻` | Does `∀` read as anything to a biologist? |
| **Emerald note, never red** for unopenable imports | W7 §7 | leads with what succeeded; "rendering it red would tell users the flagship example failed to import when it imported fine" | Contract **holds** — verify it still renders emerald. No longer reachable via morbidostat (W9 made it open); needs a genuinely unopenable doc to photograph. |
| `record.into` = **picker over declared streams**, not free text | W8-settled | — | Behaviour check only. |

---

## 9. Review fan-out and verification

One context reviewing 40 screenshots gets sloppy around #25. So review fans out to parallel
subagents — one component each, each given the rubric (§5.3), the settled list (§8), and its
screenshots.

Every candidate finding then faces a **skeptic** agent instructed to *refute* it against the
actual DOM and screenshot, defaulting to refuted when uncertain. Only survivors reach the
report. This is what keeps Track B's output from being taste.

---

## 10. The report

`docs/ui-audit/2026-07-17.md`, with cited screenshots alongside it in `docs/ui-audit/2026-07-17/`
(D5). Every finding carries: component, viewport, screenshot, repro
steps, what's wrong, **why it matters**, suggested fix, severity.

| Severity | Meaning |
|---|---|
| **S1 broken** | content unreachable, unreadable, or overlapping — a user cannot complete the task |
| **S2 degraded** | works, but confusing or wrong-looking at a supported viewport |
| **S3 polish** | taste, consistency, rhythm |

Plus a **Settled decisions, re-examined** section (§8) with a verdict per item.

---

## 11. The playwright recipe (scratchpad, per D3)

```
mkdir -p <scratchpad>/uiaudit && cd $_
npm init -y && npm i playwright && npx playwright install chromium
```

Local:
```
cd webapp/backend && .venv/bin/python tests/devserver.py    # :8000, background
cd webapp/frontend && npm run dev                            # :5173, /api + WS proxied
curl -X POST localhost:8000/api/experiments/import -H 'Content-Type: application/json' \
     -d @webapp/fixtures/ui-audit-torture.json
```

Preprod: auth per §4, `ignoreHTTPSErrors: true`, base `https://111.88.145.138/studio/`
(**trailing slash is load-bearing** — W6's relative-URL scheme needs it).

Inherited W5/W3 gotchas: `hasText` is case-insensitive; after `page.reload()` the app lands on
the Devices tab; pause a run before reloading for deterministic replay; dnd needs pointer down →
12px jiggle → glide → 400ms drop-animation wait.

---

## 12. Acceptance

- [ ] `webapp/fixtures/ui-audit-torture.json` imports **and renders** in a real browser — no
      `DocConvertError` — proven before any capture.
- [ ] Probes run clean-or-red across ≈42 states × 3 viewports; output committed as JSON.
- [ ] `/studio/api/health` re-asserted as 0.7.0 at the start of the preprod session.
- [ ] Every finding: component, viewport, screenshot, repro, why-it-matters, fix, severity.
- [ ] Every Track B finding survived a skeptic pass.
- [ ] Every §8 settled item has a verdict with evidence.
- [ ] Report + cited screenshots + fixture committed. No UI code changed (D4).

## 13. Sharp edges this does not fix

- **The probe is not an accessibility audit.** No screen-reader pass, no keyboard-navigation
  graph, no ARIA correctness. Contrast and target size only.
- **1440×900 is one judgment viewport.** A layout that is beautiful at 1440 and ugly at 1600
  goes unseen unless a probe flags it.
- **No baseline.** This is a first audit; it finds defects, not regressions. Turning the probe
  output into a committed baseline is a natural sequel and is explicitly not in scope.
