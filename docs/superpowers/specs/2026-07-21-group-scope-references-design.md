# Scope-aware references: surface a group's own params & locals while editing it

Date: 2026-07-21
Status: design, awaiting review
Depends on: `2026-07-20-typed-group-parameters-design.md` (engine schema 2, PR #50),
`2026-07-21-typed-group-parameters-studio.md` (Studio schema 2, PR #51)

## Problem

Increment 9 gave groups typed `params` (value/`role`/`stream`/`binding`) and named `locals`
(`stream`/`binding`), edited in the Inspector's `GroupProperties` panel. But the Builder's
reference surfaces were never made scope-aware. While the canvas is switched into a group's
body (`docStore.scope === "service"`), the left-menu **Streams** (`StreamsPanel`) and **Roles**
(`RolesSection`) sections — and every reference picker (`ActionForm`'s Role dropdown,
`StreamIntoPicker`, `ExpressionInput`'s help panel) — still read **only** the top-level
`s.roles` / `s.streams`. So the group's own typed references are invisible and undraggable
exactly where you'd use them.

Concretely, for a group `service` with `params: [param_pump: role<pump>, param_stream: stream]`
and `locals: { local_stream: stream }`:

- `param_stream` and `local_stream` do not appear in the **Streams** section, so a measure/
  record inside the body can't pick them as an `into` target and expression help doesn't list
  them.
- `param_pump` does not appear in the **Roles** section, so it can't be dragged onto the
  canvas to place a command/measure, and a block that does reference it reads as
  `unknown role '{param_pump}'`.

## Engine model this must match

Inside a group body, references come in two forms and **both are legal at once**
(`expand.py`, `_HOLE_RE`, "a reference must occupy a whole identifier"):

1. **Top-level roles/streams**, written as **bare names** (`drug_pump`, `od_1`). Morbidostat's
   `service` group references top-level pumps/valves this way.
2. **The group's own params + locals**, written as **`{name}` holes** (`{param_pump}`,
   `{param_stream}`, `{local_stream}`), substituted per call site at expansion. `service`
   reads `{od}` (stream param) and writes `{r_series}`/`{c_series}` (stream locals) this way.

Therefore the display model is **additive**: while editing a group, show the group's own refs
*in addition to* the top-level ones, rendered as `{name}` holes and shown only in that group's
scope. Replacing top-level refs would break form (1), a real engine-supported pattern.

## Approach

One small **pure** module, `builder/scopeRefs.ts`, derives "the references available in the
current scope" (top-level ∪ the active group's typed params/locals). Every consumer reads it
instead of re-reading `s.roles`/`s.streams`, so the Streams list, Roles list, drag-drop, the
Inspector pickers, and expression help can never disagree. At the workflow scope
(`scope === null`) every derivation collapses to exactly today's top-level behavior, so nothing
outside a group scope changes.

### `builder/scopeRefs.ts` (new, pure, unit-tested)

```ts
export const hole = (name: string): string => `{${name}}`

// The group being edited, or null at the workflow scope.
activeGroup(scope: string | null, groups: Record<string, GroupDef>): GroupDef | null

// Role refs usable in scope: every top-level role, PLUS the active group's role-kind params
// keyed by their {hole} form -> { type: device_type }. Shaped like s.roles so ActionForm,
// RetrySection and roleGroups consume it unchanged.
rolesInScope(roles: Record<string, RoleDeclJson>, group: GroupDef | null): Record<string, RoleDeclJson>

// The {hole} names that are the active group's role params — lets a consumer partition a
// rolesInScope map into top-level vs. this-group entries for the additive Roles display.
groupRoleParamNames(group: GroupDef | null): Set<string>

interface ScopeStreamRef { ref: string; origin: 'top' | 'param' | 'local'; units: string | null }
// Top streams (bare) first, then the group's stream params, then its stream locals (as holes).
streamRefsInScope(streams, group): ScopeStreamRef[]

// For expression help / the Into picker: bare top names + the group's stream params & locals as holes.
scopeStreamNames(streams, group): string[]

// Scalar names usable in expressions: the group's VALUE params (int/number/bool/string) and
// binding params/locals, all as holes. role/stream excluded (not scalars). Callers union this
// with collectBindings(activeTree).
scopeBindingNames(group): string[]
```

A hook `useRolesInScope()` lives in `scopeRefs.ts` (it imports `useDocStore`; `docStore.ts`
does not import `scopeRefs`, so there is no cycle) and returns
`rolesInScope(s.roles, activeGroup(s.scope, s.groups))` for the React call sites, subscribing to
`roles`/`scope`/`groups` as separate slices the same way `useActiveTree` does.

### Consumer changes

- **`RolesSection.tsx`** — build `roleGroups(useRolesInScope(), catalog)` and thread
  `groupRoleParamNames` down. `RoleTypeBlock` splits its `roles` into top-level (not a param
  name) and group params (a param name); renders top badges, then — when the group contributes
  params of this device type — a `── In this group ──` divider and the param badges, styled as
  `{name}` holes (font-mono). Selection and the selected role's draggable verb chips work
  identically for both.

- **`dnd.ts`** — the `palette-verb` payload gains `deviceType: string` (the role's device type,
  set on every verb chip). This removes the drop handler's dependency on `s.roles` and lets a
  role-param chip carry its type even though `{param_pump}` is not in `s.roles`.

- **`BuilderTab.tsx`** (`onDragEnd`) — resolve the verb spec via
  `const roleType = payload.deviceType ?? s.roles[payload.role]?.type`. `newVerbNode(payload.role, …)`
  then sets `device` to `payload.role`, which is the bare name for a top-level role and the
  `{param_pump}` hole for a role param — no other change needed.

- **`StreamsPanel.tsx`** — unchanged for the editable top-level list. When `scope !== null` and
  the group contributes stream refs, append a read-only `── In this group ──` subsection listing
  the `param`/`local` entries from `streamRefsInScope` (name as `{hole}`, a `param`/`local` tag,
  units for locals, and the measure/record/unused source tag computed via
  `streamSources(activeGroupBody)`). Editing of these lives in the group's Inspector
  (`Params`/`Locals`), so this subsection is display-only, not another edit surface. The `query`
  filter applies to both lists.

- **`Inspector.tsx`**
  - `ActionForm` + `RetrySection` read `useRolesInScope()` instead of `s.roles`, so the Role
    dropdown offers `{param_pump}`, verbs populate, params become editable, and the
    `unknown role` banner clears for a valid role-param reference.
  - `IntoPicker` (Measure) and `ValueForm` (Record) pass the group's stream holes to
    `StreamIntoPicker` via a new `extraOptions?: string[]` prop.
  - `ArgField`'s role picker uses `useRolesInScope()` so a nested `group_ref`/`for_each` arg can
    pick a hole from the enclosing group's role params.

- **`StreamIntoPicker.tsx`** — accept `extraOptions?: string[]` (default `[]`); render them as
  `<option>`s after the real streams and before `+ new stream…`. Picking one calls `onPick(hole)`.
  The `+ new stream` flow (creates a top-level stream) is unchanged.

- **`fields.tsx`** (`ExpressionInput`) — feed `buildExpressionHelp` the scope-aware lists:
  streams = `scopeStreamNames(streams, group)`; bindings =
  `dedupe([...collectBindings(activeTree), ...scopeBindingNames(group)])`.

## Data flow

```
docStore { scope, groups, roles, streams }
        │
        ▼  scopeRefs (pure)
 rolesInScope / streamRefsInScope / scopeStreamNames / scopeBindingNames / groupRoleParamNames
        │                    │                     │                    │
        ▼                    ▼                     ▼                    ▼
  RolesSection         StreamsPanel        StreamIntoPicker      ExpressionInput
  ActionForm           (In-group          (Measure/Record        (help panel)
  RetrySection          subsection)         Into pickers)
  ArgField(role)
        │
        ▼  drag verb chip (payload.deviceType, role={param_pump})
   BuilderTab.onDragEnd → newVerbNode → command/measure device="{param_pump}"
```

## Testing

- **Unit (vitest, pure)** — `scopeRefs.test.ts`: `activeGroup` (null scope, missing key,
  present); `rolesInScope` (adds only role-kind params as holes with the right type; ignores
  stream/binding/value params; null group is identity); `groupRoleParamNames`;
  `streamRefsInScope` (origin tags + ordering; only stream-kind params/locals; units carried);
  `scopeStreamNames`/`scopeBindingNames` (value + binding params/locals as holes; role/stream
  excluded from bindings; stream params/locals included in streams).
- **DOM (probe harness, `npm run capture`)** — per `frontend/CLAUDE.md`, add a capture state
  "editing a group with typed params + locals" (scope into a group; role/stream params + a
  stream local + a binding local) so R4 sibling-height, R5 text-contrast, and the truncate-with-
  title rules cover the new subsections and hole badges. Verify no horizontal overflow of the
  256px palette from long `{hole}` names (truncate + title, as role badges already do).
- **Backend** — no backend change; the webapp already speaks schema 2. Confirm on preprod that a
  mid-authoring group whose body cites `{param_pump}` does not raise spurious diagnostics
  (validation behavior is pre-existing and unchanged by this UI-only work).

## Out of scope / non-goals

- No new authoring of params/locals here — that stays in the group's Inspector panel; the
  Streams "In this group" subsection is read-only.
- No change to the workflow scope (`scope === null`): every derivation collapses to today's
  top-level behavior.
- Nested-scope arg holes beyond the role picker (e.g. a for_each var threaded through a
  `group_ref` value arg) already work via `ArgField`'s `ƒ` toggle and are untouched.
```
