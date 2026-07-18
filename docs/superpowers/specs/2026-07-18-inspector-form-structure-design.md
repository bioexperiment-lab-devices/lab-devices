# Inspector form structure (W15)

**Status:** user-settled 2026-07-18. Sequel to W13 (UI improvements round 2) and W14
(lab-independent Builder).

## 1. Problem

The Inspector's per-block settings form groups and orders its fields the way the code was
written, not the way an author thinks. Every block renders:

```
<h2> kind title
<KindBody>                       — the kind's own fields, no header
<h3> Timing & label
  Label
  Gap after      (conditional)
  Start offset   (conditional)
  On error       (conditional)   ← no header of its own
  Retry + hazard box (command/measure only)  ← no header of its own
```

That `<h3>` was written in W3, when the section held exactly what it names. W8 appended
`On error` and the entire retry sub-form *beneath it without introducing a new header*, so
today failure handling is filed under a heading that reads "Timing & label". Six defects
follow, five of them from that same cause:

- **D1 — the header lies.** "Timing & label" roofs label, timing, error policy and retry.
- **D2 — timing is split by serialization shape, not meaning.** `gap_after` and
  `start_offset` are block-level keys, so they land in the common tail; a Loop's `pace` and
  a Wait's `duration` are kind keys, so they land in the body. A Loop author edits two
  timing controls in two sections, divided by which side of the JSON schema the key sits
  on — a distinction with no meaning to them.
- **D3 — header depth is inconsistent.** The kind's own fields (Role, Verb) carry no header,
  but their sub-list does (`Params`, `Args`), so the hierarchy implies `Params` is
  subordinate to nothing and `Role` is superordinate to nothing.
- **D4 — the label is buried.** The one field that means the same thing for all fourteen
  kinds renders roughly sixth, below every param, under the timing heading.
- **D5 — related fields are separated by unrelated ones.** `On error` and `Retry` are both
  "what happens when this fails" with `Gap after`/`Start offset` wedged between them. In
  `OperatorInputForm`, `Type` is separated from its own constraints (`Min`/`Max`/`Choices`)
  by the operator-facing `Prompt`. In `ActionForm`, a measure's `Into stream` sits between
  the verb and the verb's own params.
- **D6 — no progressive disclosure.** A Wait block has one required field and presents five
  rows. Serial and Parallel say "drag blocks on the canvas" and then show a full timing and
  error tail.

## 2. Settled forks

Four forks were put to the user as batched multiple choice on 2026-07-18. All four
recommendations were accepted.

| Fork | Decision |
|---|---|
| Organizing principle | Body + named tail sections (not four uniform intent sections, not a single "More") |
| Kind-specific timing | Only block-level keys move to Timing; `pace`/`duration`/`backoff` stay in the body |
| Disclosure | Tail sections collapsed by default, auto-open when they hold a non-default value |
| Label placement | First row of the form; the `h2` keeps showing the kind |

The user additionally asked for a UI-consistency sweep over control sizing — "input fields
sizes, sizes of input and button in one row" — which §6 covers.

## 3. Target structure

Three regions, fixed order, for every kind:

```
Command                          ← h2, the kind (unchanged)

  Label     [feed pump A      ]  ← identity row, always present, always first
  Role      [pump_1          ▾]  ← body: the kind's own fields, unheaded
  Verb      [dispense        ▾]
  PARAMS                         ← body sub-label (plain caption, no chevron)
    volume_ml *  [5.0         ]
  ────────────────────────────
  ▸ Timing · gap after 30s       ← tail: disclosure button, summary when collapsed
  ▸ On failure · continue
```

### 3.1 Identity row

`Label` renders first for every kind, with no conditional. The panel `h2` continues to show
the kind name from `KIND_TITLES`, so nothing about kind legibility regresses; the canvas
card already displays the label, and this makes the field that drives it easy to reach.

### 3.2 Body

Unchanged in principle: `KindBody` renders the kind's own fields with no section header.
`PARAMS` and `ARGS` remain as sub-labels within the body. Two orderings change (§5).

### 3.3 Tail

Two collapsible sections, each rendered **only when it has at least one eligible field**:

- **Timing** — `Gap after` (eligible per the existing `gapAfterEligible`), then
  `Start offset` (when the parent is `parallel`).
- **On failure** — `On error`, then the complete `RetrySection` including the hazard box and
  the attempts/backoff pair.

Consequences that are features, not omissions:

- `for_each` renders **no tail at all**. The engine forbids `gap_after`, `start_offset`,
  `on_error` and retry on a splice (`expand.py:26` `_FOR_EACH_FORBIDDEN`), so both sections
  are empty and both disappear. `Label` plus body is the whole form, which is the truth.
- `abort` loses **On failure** entirely. It already suppresses `on_error` (tolerating a
  safety stop is a contradiction — engine design 2026-07-16 §5.1) and never had retry, so
  the section has nothing in it. Its absence states the rule better than a section
  containing one disabled control would.
- A `serial` **inside a parallel** shows Timing containing only `Start offset`, because
  `gapAfterEligible` is false there (no next-in-list). A `serial` at top level shows Timing
  containing only `Gap after`. The section's membership is genuinely dynamic; that is why
  §4 makes it a computed value rather than a literal.

Retry stays command/measure-only, and the `pending` hazard state stays local to
`RetrySection` exactly as today — this increment moves that component under a correct
header, it does not reopen its logic.

## 4. Disclosure semantics

A tail section is **collapsed by default and auto-opens when it holds a non-default value.**

- Timing holds a non-default value when `gapAfter !== null` or `startOffset !== null`.
- On failure holds a non-default value when `onError === 'continue'` (`'fail'` is the
  engine default) or `retry !== undefined`.

Open/closed state lives in `BlockForm`. `Inspector` already mounts it with
`key={node.uid}`, so the state resets on every selection change and the auto-open
computation re-runs from the newly selected node — no stale disclosure carries between
blocks, and two people looking at the same document see the same panel.

**A configured value is never hidden.** The user may collapse a section that holds a value,
because the collapsed header carries a summary of what is set:
`Timing · gap after 30s`, `On failure · continue, retry ×3`. Closing a section changes how
much room it takes, never whether its content is discoverable. This is what makes
collapsing safe without forbidding it — the alternative (locking a non-default section
open) trades one honest affordance for a control that mysteriously refuses to work.

The summary is a pure function of the node, so it is unit-testable (§4.1) and cannot drift
from the fields it summarises.

### 4.1 Where the logic lives

`builder/inspectorRules.ts` gains, alongside the existing `gapAfterEligible`:

- `timingFields(kind, parentKind): TimingField[]` — `[]` means the section is not rendered.
- `failureFields(kind): FailureField[]` — same contract.
- `timingSummary(node, parentKind)` / `failureSummary(node)` — the collapsed-header text,
  `null` when everything is at its default. Each filters through its own membership function,
  so it can only ever mention a control the section actually renders (a `gapAfter` surviving
  on a block moved into a parallel lane is not advertised there).

There is deliberately **no separate auto-open predicate**: `summary !== null` *is* the rule.
Deriving the disclosure state and the text describing it from one expression is what makes
it impossible for a section to open silently or to close over a value it fails to mention.

This is not incidental placement. vitest here runs in **node env with no component
rendering** (`webapp/frontend/CLAUDE.md`), so any of this logic left inside `Inspector.tsx`
is untestable by construction. The same reasoning produced `builder/paletteSections.ts` in
W12 and `builder/roleGroups.ts` in W13.

Membership is typed as an **exhaustive** map over `BlockNode['kind']`, so adding a
fifteenth kind is a compile error until it declares its section assignment. W12's
`Record<Exclude<PaletteKind,'group_ref'>, string>` test caught precisely this class —
a hand-maintained array of kinds would have passed with a kind silently missing.

## 5. Body ordering fixes

Two orderings inside `KindBody` are development-order artifacts and change in the same pass
(D5):

- **`ActionForm` (measure)** — today `Role → Verb → Into stream → Params`, which wedges the
  result destination between a verb and the verb's own params. Becomes
  `Role → Verb → Params → Into stream`: configure the action, then say where the result
  goes. Command is unaffected (it has no `into`).
- **`OperatorInputForm`** — today `Binding name → Type → Prompt → Min/Max/Choices`, which
  separates the type from its own constraints with operator-facing prose. Becomes
  `Binding name → Type → Min/Max/Choices → Prompt`. `setType`'s existing clearing behaviour
  (`choices` cleared when leaving enum; `min`/`max` cleared for enum/bool) is untouched.

Deliberately **not** reordered: `ValueForm` (`Into → Value` reads as the assignment it
compiles to), `ForEachForm` (`var` before `items` matches the canvas summary
`∀ For each tube in [1,2,3]`), `LoopForm`, `GroupRefForm`, `BranchForm`, `ConditionForm`.

## 6. UI consistency sweep

User-requested, and the reason it is scoped here rather than deferred: this increment adds
a new control type (the disclosure header) to a panel full of existing ones, which is
exactly when height and width drift re-enters.

- The disclosure header is a full-width button and therefore takes
  `inlineButtonClass({ width: 'w-full' })`. **Never a concatenated `w-full`** — `w-full`
  and fixed widths are equal-specificity utilities in the same `@layer utilities` block, so
  an appended width loses to declaration order silently (`webapp/frontend/CLAUDE.md`,
  control-token rules; the W11 and W12 cascade traps). Any class baked into a helper is
  un-overridable by concatenation, for every property.
- Every text input, select and inline button in the Inspector renders at the 24px
  `CONTROL_H` token from `src/ui/controls.ts`. Rows mixing a control with an `IconButton`
  (the unknown-param remove button, `ExpressionInput`'s help button, the bool-param
  expression toggle) must measure flush.
- Verification is `npm run capture`, whose **R4 `sibling-height-mismatch`** rule flags
  sibling controls on a shared visual line disagreeing by more than 1px. R4 is the rule
  that exists because twelve crooked rows shipped in 0.8.0.

### 6.1 The vacuous-verification hazard

A probe rule reports clean on rows that **never mounted**. W12 shipped a plan that read as
verified because `capture.mjs`'s states never opened the Groups panel. Collapsed-by-default
tail sections are the identical trap: with both sections closed, R4 has nothing to measure
and passes vacuously.

`tools/capture.mjs` therefore gains states that **open** the tail:

- a block whose Timing and On failure are auto-opened by non-default values (a command with
  `gap_after` set and `on_error: continue`),
- a block with both sections manually expanded from their collapsed default,
- a `command` with an unsafe verb and the retry hazard box open (the densest mixed row in
  the panel),
- the existing `inspector-operator-input` state, updated for the §5 reorder.

## 7. Non-goals

- No change to `DocProperties` / `GroupProperties` (the no-selection panels). They have no
  tail and their `mt-auto` bottom-pinning is a settled W11 fix.
- No change to `convert.ts`, `tree.ts` or any document shape. This increment moves and
  groups controls; **open-then-save stays a byte no-op**, which the existing round-trip
  tests already pin.
- No change to retry semantics, `gapAfterEligible`'s eligibility rule, or the
  backend-only tolerant-ancestor rule.
- The `BlockNode.device` → `role` rename stays deferred (W14-settled).

## 8. Verification

- Frontend gate: `cd webapp/frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build`.
- New pure-function tests in `builder/inspectorRules.test.ts` covering: section membership
  per kind (exhaustive map), the empty-section cases (`for_each`, `abort`, serial-in-
  parallel), summary text, and the auto-open predicate.
- `npm run capture` across the existing viewports with the §6.1 states added; R4 at zero
  violations with the tail sections **open**.
- Real-browser check of the auto-open behaviour against a doc with `gap_after` and
  `on_error: continue` set — the fixtures in `webapp/fixtures/` already carry both.
