# Expression editing upgrade: clickable help, autocomplete, highlighting, instant validation

**Date:** 2026-07-21
**Status:** Approved
**Scope:** Webapp frontend (one new Python golden-generator + one engine-side parity test; no engine behavior changes)

## 1. Problem

Expression editing in the Studio is a bare mono textarea. The help popover
(`fields.tsx` `ExpressionInput`, content from `exprHelp.ts`) lists streams,
bindings, functions, and window forms as plain text — nothing is clickable.
There is no autocomplete and no syntax highlighting. Validation is whole-doc
only: a 500 ms debounced POST to `/api/validate` whose diagnostics land on
canvas cards and the ProblemsPanel — never inline under the field being edited,
and never on a *draft*, because fields commit on blur/Enter and the store (and
therefore the validator) only ever sees committed values.

Separately, the engine has accepted expressions in duration/count slots since
schema v3 (#58: `wait.duration`, `loop.count`, `loop.pace`, retry `backoff`,
`gap_after`, `start_offset` all take a `number<s>`/`int` expression), but the
Studio still gates those fields on the literal `DURATION_RE` / a numeric input.

## 2. Decisions (settled forks)

| Fork | Decision |
|---|---|
| Editor foundation | Hand-rolled overlay on the native textarea. No CodeMirror: ~150KB+ dep, fights the 24px `controlClass` system, untestable in vitest (node-env only). |
| Instant validation | Client-side TS port of the engine tokenizer+parser (syntax + known-name checks), advisory only; types/units stay server-side. Golden parity corpus pins the port to the engine grammar. |
| Scope | All expression surfaces **including** duration/count slots (Studio catches up with engine #58). |

## 3. Architecture

### 3.1 `ExpressionEditor` component (replaces `ExpressionInput`'s guts)

One shared component used by conditions, compute/record expressions, param
expression-mode, and the newly expression-capable duration/count slots.

- The native `AutoGrowTextArea` remains the input surface. Commit-on-blur/
  Enter, Escape-revert, `singleLine` soft-wrap, `maxLines` — all unchanged.
- Behind it, an `aria-hidden` **highlight layer**: absolutely positioned div
  with identical font/padding/width/wrap classes rendering the token stream as
  colored spans. The textarea's text becomes transparent (`text-transparent`
  + explicit `caret-color`) so the colored layer shows through. Identical
  styles ⇒ identical wrap geometry. Scroll offset synced (`onScroll` →
  transform) for the max-lines overflow case.
- Prop `expected: 'bool' | 'number' | 'int' | 'duration' | 'any'` drives the
  placeholder, literal fast-paths, and slot-specific heuristics (§3.4).
- The trailing help IconButton and popover stay (now clickable, §3.6).

### 3.2 Client grammar module `src/builder/expr/`

TS port of `expr.py` + the duration fragment of `durations.py`:

- `tokenize.ts` — port of the single-regex named-group tokenizer. Token kinds
  `DURATION | NUMBER | STRING | NAME | OP` plus positions; whitespace skipped;
  unexpected characters produce an error token (position + char) instead of a
  throw, so highlighting still renders everything before the bad char. Duration
  fragment: `\d+(\.\d+)?(ms|s|min|h)\b` (longest-unit-first, `\b` guard).
- `parse.ts` — port of the recursive-descent parser (`_or_expr` → `_and_expr`
  → `_not_expr` → `_comparison` (no chaining) → `_additive` →
  `_multiplicative` → `_unary` → `_atom` / `_stat_call` / `_window`), the
  keyword set, `STAT_FNS`, the 64-deep nesting guard, and the same error
  messages with positions. Produces `{ ok: true, ast } | { ok: false, error:
  { message, pos } }` — no exceptions.
- `analyze.ts` — semantic pass over the AST: stat-call stream names checked
  against scope streams, `BindingRef`s against scope bindings (same sources
  `exprHelp` uses today: `scopeStreamNames`/`collectBindings`/
  `scopeBindingNames`); plus per-slot heuristics (§3.4). Unknown names carry
  their token span so the highlight layer can underline them.
- `highlight.ts` — token stream → span classification: `fn` (a NAME in
  `STAT_FNS` position), `name` (stream/binding), `number`, `duration`,
  `string`, `keyword` (`and or not true false`), `op`, `error`.

The client never grows a copy of the type lattice: types and units remain
engine-only, surfaced through the existing whole-doc validation.

### 3.3 Grammar-drift control (golden parity)

- `webapp/backend/tools/gen_expr_golden.py` runs the **engine's** `tokenize`
  and `parse_expression` over a shared corpus (valid + invalid expressions,
  covering every token kind, operator, window form, error branch) and writes
  `webapp/frontend/src/builder/expr/__goldens__/expr-parity.json`: per case,
  the token stream (kind/text/pos) and `ok`/error-substring+position.
- vitest (`parity.test.ts`) replays the corpus through the TS port and asserts
  identical token streams and identical ok/error outcomes (error position
  exact; message compared on the stable leading clause).
- An engine-side test (`webapp/backend/tests/test_expr_golden.py`) regenerates
  the golden in-memory and diffs it against the committed file — any engine
  grammar change breaks CI until the corpus is regenerated and the TS port
  re-synced.

### 3.4 Instant validation UX

- The draft is analyzed on a ~300 ms idle debounce (tokenize+parse+analyze —
  microseconds at these sizes; the debounce is purely to avoid flashing
  mid-word errors).
- Draft problems render under the field in **amber-700** (existing
  DurationField precedent): amber = "this draft won't parse / names unknown".
- Committed-value diagnostics from the server render under the owning field in
  **red-600**: red = "the engine rejected what's saved". Attribution via §3.5.
- Slot heuristics: `expected='duration'` flags a bare unitless numeric literal
  ("durations need a unit — 30s, not 30"); `expected='int'` flags a bare float
  literal. Nothing deeper client-side.
- Commit is **never blocked**; everything is advisory.
- Empty drafts show nothing (required-ness is the server's call).

### 3.5 Field attribution of server diagnostics

`paths.ts` already splits a diagnostic's trailing context suffix (" branch
if", " compute value", " param 'x'", …) but only extracts `param`. Extend
`ResolvedPath`/`MappedDiagnostic` with `field: string | null` — the raw suffix
kept whole (param suffixes keep populating `param` as today). The Inspector
gains a small `FieldDiagnostics` hook/component: diagnostics for the selected
uid whose suffix matches the field's known suffix(es) render under that field;
non-matching or suffix-less diagnostics for the uid render once in an
Inspector-level strip under the form header (today they are canvas/panel-only).
Canvas behavior unchanged.

### 3.6 Clickable help + autocomplete (shared insertion core)

`insert.ts`: `insertAtCaret(text, caret, fragment, {replaceRange?}) → { text,
caret }` — pure function, handles token-boundary spacing (no double spaces, no
gluing identifiers).

**Help popover** (kept as the documentation surface, rows become buttons):
- Stream / binding rows insert the name at the caret.
- Function rows insert `name()` with the caret between the parens.
- Window rows insert their fragment (`, last=5` / `, last=30s`) when the caret
  is inside a stat call's parens, else the row's full example.
- After insert: focus returns to the textarea, caret placed, popover **stays
  open** (composition: click `mean` → click `od` → click window in 3 clicks).

**Autocomplete popup** (new, anchored below the field — single-line fields, no
caret-mirror measurement):
- Opens while typing an identifier prefix; Ctrl+Space opens the full list.
- Candidates by token context (`complete.ts`, pure: `(text, caret, scope) →
  { candidates, replaceRange }`): start of an atom → functions + streams +
  bindings + `not`; first argument of a stat call → streams; after `,` inside
  a call → `last=`. Nothing fancier.
- Keyboard: Down/Up navigate, Enter/Tab accept, Escape closes the popup first
  (second Escape reverts the draft — no conflict with existing semantics;
  Enter with the popup open accepts instead of committing).
- Accepting replaces the partial identifier; functions insert `name()` caret-
  inside.
- Popup and help popover are mutually exclusive (opening one closes the other);
  both live inside the existing `useDismissable` wrapper.

### 3.7 Duration/count slots

- `DurationField` → `ExpressionEditor expected='duration'` with a literal
  fast-path: a `DURATION_RE` match is valid with no parse; anything else runs
  the expression pipeline. Doc-model duration fields are already strings —
  no schema/convert change.
- `count`: doc model changes `number` → `number | string`. `convert.ts` emits
  a JSON number for a numeric value and the string for an expression;
  round-trips both (engine schema v3 already accepts either). The count
  `NumberField` swaps to `ExpressionEditor expected='int'`.
- Affected Inspector slots: `wait.duration`, `loop.count`, `loop.pace`, retry
  `backoff`, `gap_after`, `start_offset`.
- These fields get the same help popover, autocomplete, and instant
  validation, scope-aware like every other site.

### 3.8 Highlighting palette

A new, minimal color language, disjoint from the reserved state hues
(blue/red/amber/emerald) and from construct tints / role ramps:

| Token class | Class (complete literal) |
|---|---|
| function names | `text-violet-700` |
| stream/binding names | `text-teal-700` |
| numbers + durations | `text-slate-800` |
| strings | `text-fuchsia-700` |
| keywords + operators | `text-slate-500` |
| unknown name | amber wavy underline (`decoration-amber-600`) |
| lex error char | amber wavy underline (`decoration-amber-600`) |

Unknown names and lex errors are *draft*-detected, so their in-text underline
uses the amber draft language of §3.4, not red — red stays exclusively for
server-confirmed diagnostics on committed values.

All complete literals in source (Tailwind 4 scans text). Verified against the
AA floor with `npm run capture` (probe R5) on a real doc before merge;
adjusted if any measure under 4.5:1. Keywords/operators use `text-slate-500`
deliberately — same weight as `text-hint`; if R5 flags it in context, bump to
`text-slate-600`.

## 4. Testing

- **vitest (pure functions, per project rules):** tokenizer, parser, analyze,
  golden parity, `complete.ts` candidates + replace ranges, `insertAtCaret`,
  highlight classification, count round-trip in `convert.test.ts`, duration
  literal fast-path.
- **Probe/capture:** overlay alignment (R4 sibling heights must not regress),
  R5 contrast on the token palette, popup/popover flows captured on a real doc.
- **Engine-side:** `test_expr_golden.py` regen-and-diff.
- **No component rendering in vitest** — DOM wiring is probe territory.

## 5. Rollout

Feature worktree `expression-editor`; two green→green PRs:

1. **PR 1:** `expr/` module + golden pipeline + `ExpressionEditor` (overlay,
   autocomplete, clickable help, instant validation, field-attributed server
   diagnostics) swapped in at all existing `ExpressionInput` sites.
2. **PR 2:** duration/count slot upgrade (`DurationField`/count swap,
   doc-model `count: number | string`, `convert.ts` round-trip).

Each PR: frontend gates (`npm test`, `typecheck`, `lint`, `capture` probe) +
engine/backend pytest; merge on green CI.

## 6. Out of scope

- Client-side type/unit checking (stays engine-only).
- Multi-line expressions, caret-anchored popup positioning, snippets beyond
  `name()`.
- Any engine grammar change.
- Group-param/`as`-cast editing surfaces beyond what already uses
  `ExpressionInput`.
