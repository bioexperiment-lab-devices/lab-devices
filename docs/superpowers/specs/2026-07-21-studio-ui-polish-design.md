# Studio UI polish + behavior fixes — design

Date: 2026-07-21. Status: approved (all forks user-settled 2026-07-21).

Thirteen user-reported issues against the current Studio build, landing as **two
stacked PRs**: PR 1 is pure frontend visual polish, PR 2 changes behavior and
contracts (serialization, save flow, device-param enums incl. a backend/engine
change, run gating).

## Settled forks

1. **Palette block defaults: clear all of them.** Not just `for_each` — `wait`,
   `loop`, and `operator_input` also seed empty and show placeholder hints.
   Blocks are invalid-until-filled, exactly like `branch`/`compute` today.
   Parallel keeps its two empty lanes (structure, not data).
2. **Unitless: blank = unitless.** An empty units field serializes as the
   literal `"unitless"`; loading normalizes `"unitless"` back to a blank field.
   No extra widget.
3. **No-roles runs: fix gating only, keep the lab requirement.** The backend
   anchors every run to a lab; that stays.
4. **Two PRs**, PR 2 stacked on PR 1's branch.

## PR 1 — Builder visual polish (frontend only)

### Roles panel (`webapp/frontend/src/builder/RolesSection.tsx`)

1. **Add-role placement.** `AddRoleForm` currently renders as the last child of
   each `RoleTypeBlock`, *below* the role-action cluster and verb chips. Move it
   into the badge row itself (`flex flex-wrap`), rendered as the last chip after
   the last role badge: collapsed = a "+ add role" chip, expanded = the inline
   name input + Add button (wrapping within the row is fine).
2. **Badges show their role color.** Each role badge gets the same small swatch
   the canvas uses (`h-2.5 w-2.5 rounded-sm`), resolved via `assignRoleColors`
   plus the `roleColorStore` overrides — today the badge never reads the color
   at all, so a picked color is only visible after dropping a block on the
   canvas. A role with the explicit "no colour" override renders no dot.
3. **Color-picker clipping.** The picker popover is `absolute` inside the
   palette's `overflow-y-auto` aside (`Palette.tsx:124`), which crops it both
   vertically and horizontally (256px column). Render the popover through
   `createPortal` to `document.body`, positioned `fixed` from the trigger's
   `getBoundingClientRect()` and clamped to the viewport. `useDismissable`'s
   outside-click test must treat clicks inside the portal node as inside.

### Canvas (`builder/tree.ts`, `builder/DropSlot.tsx`, `builder/Canvas.tsx`)

4. **Palette defaults** (`newPaletteNode`, `tree.ts:366-404`):
   - `for_each`: one var with empty name (`kind: 'int'` stays), zero rows.
     Inspector placeholders suggest `tube` / `1, 2, 3`.
   - `wait`: `duration: ''`, placeholder `1s`.
   - `loop`: `count: ''`, placeholder `2` (count is an expression slot since #65).
   - `operator_input`: `name: ''`, placeholder `value`. `inputType` stays
     `'float'` — a select must hold some value.
   - The `tree.ts` comment justifying the old seed ("empty `in` is a hard load
     error") is superseded: invalid-until-filled is already the norm for
     `branch`/`compute`/`record`/`abort`/`alarm`, and Save never gates on
     validation.
5. **Drop-zone margins.** The hint-mode `DropSlot` (`DropSlot.tsx:23`) loses its
   `m-1`; block-level spacing comes only from the interleaved `my-0.5` bars,
   same as real block cards (which carry no outer margin).
6. **Empty-canvas message** (`Canvas.tsx:85-97`). Plain centered caption text —
   no dashed border, no rounded box, no shadow. The "drop here" hint slot below
   it remains the only action-styled element (today the two render as twin
   dashed boxes and the message reads as a drop target).
7. **Inner-section boxes → separators.** Parallel lanes (`Canvas.tsx:463,486`)
   and branch then/else arms (`Canvas.tsx:566,570`) lose their bordered boxes.
   Labels ("lane N", "then", "else") stay. Lanes/arms after the first get a
   `border-l` hairline separator. Selection, which currently rides on the lane
   box border (`border-blue-500 ring-2`), becomes a `ring-2 ring-blue-400`
   shown only when selected — no idle chrome. The depth-alternating interior
   fill (`interiorFillClass`) stays.

### Streams panel (`builder/StreamsPanel.tsx`)

8. **"unused" badge.** Moves to the right side of the row (after the units
   input, grouped with the delete button) and goes quiet: neutral caption
   styling instead of `bg-amber-100 text-amber-700`. Amber stays reserved for
   real warnings. Both instances: main list (`:109-121`) and group-scope refs
   (`:173-187`).
9. **Filter removal.** The `filter streams…` input, its local `query` state,
   `filterStreamNames` usage, the "no streams match" hint, `streamFilter.ts`,
   and `streamFilter.test.ts` are deleted.

## PR 2 — Behavior fixes (stacked on PR 1)

10. **Blank = unitless** (`builder/convert.ts`, `StreamsPanel.tsx`).
    `treeToDoc` serializes `units: null` as `"unitless"`; `docToTree`
    normalizes `"unitless"` to `null` (blank field). Units inputs get
    placeholder `unitless`. The frontend expression analyzer already treats
    missing units as unitless, matching the engine's `_UNITLESS_TEXTS`
    (`units.py:20`: `"" | "unitless" | "1"`). Byte no-op contract: documents
    saved by the Studio still carry explicit `"unitless"`, so open+save of the
    examples stays a no-op; goldens/fixtures regenerate if affected.
11. **Save = save-as for new docs** (`builder/Toolbar.tsx`). `save()` with
    `serverId === null` routes into the shared name-prompt flow (default = the
    doc's current name, no "(copy)" suffix); cancel aborts, nothing is created.
    "Save as" keeps its "(copy)" default. Extract the prompt+create+markSaved
    sequence so both paths share it.
12. **Enum device params.**
    - Engine (`src/lab_devices/experiment/registry.py`, `catalog.py`):
      `ParamSpec` gains optional `values: tuple[str, ...] | None = None` (kind
      stays `"string"`). Pump `dispense.direction` / `rotate.direction` →
      `("forward", "reverse")`; valve `set_position.rotation` /
      `configure.default_rotation` → `("shortest", "direct", "wrap")` (per
      `docs/lab-bridge-api-reference.md:508,581`). `verb_catalog()` serializes
      `values` when present. Load-time validation rejects a *literal* string
      param outside the enum; expression-valued params are untouched. No new
      document fields → no schema_version bump.
    - Frontend (`types/catalog.ts`, `builder/Inspector.tsx`): `ParamEntry`
      gains optional `values?: string[]`; `ParamInput` renders a `<select>`
      when `values` is present (literal select, no ƒ toggle — string params are
      literal-only today).
13. **Valve values bug** (`devices/catalog.ts:47`). `ROTATION_OPTIONS` corrected
    from `['cw', 'ccw', 'shortest']` to `['shortest', 'direct', 'wrap']` —
    `cw`/`ccw` are not accepted by the device contract at all.
14. **No-roles run gating** (`run/preflight.ts:38-39`). `mappingComplete` drops
    its `rows.length > 0` clause — an experiment with zero roles is vacuously
    mapped. Lab selection stays required. The backend already starts no-roles
    runs cleanly (`runner.py:100-114` produces zero diagnostics).

## Testing

Component/unit tests where behavior is assertable: add-role chip position,
badge swatch rendering, portal popover not clipped (class-level), palette
defaults seeding (all four kinds), DropSlot class strings, lane/arm separator +
selection ring classes, badge placement/styling in StreamsPanel, filter gone,
units round-trip (null ↔ "unitless"), save routing for new docs (prompt,
cancel), catalog `values` serialization (engine + frontend), ParamInput select
rendering, corrected ROTATION_OPTIONS, `mappingComplete([])` true + PreflightPanel
start-enabled state with zero roles.

Gates per repo standard — frontend: `npm run lint && npm run typecheck &&
npm test -- --run && npm run build`; backend: `pytest -q && mypy && ruff check .`
(mypy takes no path arg); engine: root pytest. Mutation-verify any test that
pins a class string or a vacuous-looking predicate (repo has a 5-strike history
of vacuous tests).

## Out of scope

Lane-strip redesign (parallel = N side-by-side lanes, flagged in the UI audit),
`text-warning` utility, ScopeSwitcher intrinsic width, expression support for
string params.
