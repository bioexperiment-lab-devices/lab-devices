# Experiment Studio — engine parity (W8 + W9)

**Status:** design, user-settled 2026-07-16.
**Parent spec:** [`2026-07-11-experiment-studio-webapp-design.md`](2026-07-11-experiment-studio-webapp-design.md) (S1–S10).
**Engine specs this delivers:** [fault tolerance](2026-07-14-engine-fault-tolerance-design.md) (#21),
[computed values](2026-07-15-experiment-orchestrator-6-computed-values-design.md) (#22),
[parametrized repetition](2026-07-15-experiment-orchestrator-7-parametrized-repetition-design.md) (#24),
[abort/alarm](2026-07-16-experiment-orchestrator-8-abort-alarm-design.md) (#25).

---

## 1. Problem

Since PR #21 the engine gained six new block types and one new workflow-level construct.
Studio's **observe** path kept pace with every one of them; Studio's **author** path never
moved. The result is a UI that can *run and chart* a document it cannot *open*.

| Engine surface | Shipped | Studio observe | Studio author |
|---|---|---|---|
| `retry` / `on_error` | #21 | ✅ events, `tolerated_errors` | ✅ Inspector |
| `compute` | #22 | ✅ `binding_computed` | ❌ |
| `record` | #22 | ⚠️ event log only — **not on the live chart** | ❌ |
| `for_each` | #24 | ✅ (runs expanded) | ❌ |
| parametrized `groups` / `group_ref` | #24 | ✅ (runs inlined) | ❌ |
| `abort` | #25 | ✅ `abort_raised`, status `aborted` | ❌ |
| `alarm` | #25 | ✅ `alarm_raised`, `RunReport.alarms` | ❌ |

Concretely: `webapp/frontend/src/builder/convert.ts` throws `DocConvertError` on every
newer block (`:52` groups, `:147` `for_each`, `:151` `abort`/`alarm`, `:156` the generic
default that catches `compute`, `record`, `group_ref`). The flagship
`examples/morbidostat.json` — which uses `groups` **and** `for_each` — imports, saves, lists,
runs, and charts, but **cannot be opened in the builder at all**. That is the W7 §7 contract:
an emerald "this success isn't a failure" note, deliberately never a red error.

**The backend is already at full grammar parity** and is not the problem.
`roles.py:15-23` names every newer block in `_CHILD_LISTS`/`_LEAF_BLOCKS` (with a parity test
at `tests/test_roles.py:166`), and both `docs_store.validate_doc` and `runner` call
`expand_dict` before substitution. This work is therefore **almost entirely frontend**, with
one narrow, well-motivated engine addition (§5.3).

### 1.1 The bug this uncovered

`webapp/frontend/src/run/reducer.ts:46` folds **only** `measure_recorded` into `feed.samples`:

```ts
if (msg.kind === 'measure_recorded') {
```

A `record` block emits `sample_recorded` (`execute.py:691`), which is pushed to `events` and
never into `samples`. `RunView.tsx:29-42` charts `feed.samples`, so **a computed stream never
appears on the live chart**. Post-run it charts correctly, because `records.py:193-211` reads
declared streams from CSV — a different code path.

This silently negates Increment 6's headline payoff. The morbidostat's drug-concentration
sawtooth — the whole reason `record` exists — is invisible for the three weeks the run is
live, and appears only once the run is over. It is a one-line fold with a large blast radius,
and it ships in W8.

---

## 2. Scope

**In scope (W8):** `compute`, `record`, `abort`, `alarm` canvas authoring; the live-chart
fold; `refs.ts`/`exprHelp.ts` plumbing for computed bindings and recorded streams.

**In scope (W9):** `for_each` and parametrized `groups`/`group_ref` canvas authoring; the
diagnostic source map; `paths.ts` group-scope resolution.

**Non-goals.**

- Engine limitations #2 (math functions), #5 (enum in expressions), #6 (durations as
  expressions), #8 (`elapsed()`) — still open, unaffected by this work.
- A validator **warning tier** (the `count(S) > 0` latch hazard, tolerated-actuation hazard).
  These are engine-side and documented in `docs/experiment-engine-limitations.md`; the builder
  will not grow a second, divergent opinion about them. See §7.
- Stream-declaration templating (`od_{tube}` in `workflow.streams`) — explicitly out of scope
  in Increment 7 and still is.
- Per-stream `persistence` UI. It stays carried opaquely (`convert.ts:22-26`).

---

## 3. Settled decisions

| # | Fork | Decision |
|---|---|---|
| **P1** | Slicing | **Two PRs.** W8 = leaf blocks + chart fix + plumbing. W9 = repetition + source map. W8 is ~70% of the value and ships on a clean review surface. |
| **P2** | `groups` depth | **Full.** Canvas scope switcher (Main / each group), editable bodies and `params`, `group_ref` with `args`. The payoff is that `examples/morbidostat.json` becomes canvas-editable. |
| **P3** | Macro diagnostics | **Source map from `expand.py`.** Expanded-path → authored-path provenance, applied by `docs_store` before diagnostics leave the backend. |
| **P4** | `for_each` rendering | **Authored view only.** One card, body nested once. No expansion preview (YAGNI); matches the engine's DRY-source model. |

**P3 rationale.** The backend validates the *expanded* workflow, so its diagnostic paths use
expanded indices. An authored `for_each` at `blocks[0]` producing 3 siblings makes expanded
`blocks[2]` a copy of its body, while authored `blocks[2]` is an unrelated block. Without a
source map, `paths.ts` resolves the diagnostic onto the **wrong block** and highlights it —
strictly worse than not resolving it. Mapping is many-to-one by nature (all three copies trace
to the one authored body block), which is exactly the behaviour an author wants.

---

## 4. W8 — leaf blocks and the observe-path fix

### 4.1 Grammar

Four leaf blocks, two shapes, no children, no device:

```json
{"compute": {"into": "c_1",  "value": "c_1 * V / (V + dV)"}}
{"record":  {"into": "c_series_1", "value": "c_1"}}
{"abort":   {"if": "emergency_stop", "message": "operator emergency stop"}}
{"alarm":   {"if": "contaminated_1", "message": "tube 1 contaminated"}}
```

`types/doc.ts` gains `ComputeBody`, `RecordBody`, `AbortBody`, `AlarmBody` and the
corresponding optional keys on `BlockJson`. `tree.ts` gains `ComputeNode`, `RecordNode`,
`AbortNode`, `AlarmNode` on the `BlockNode` union, each extending `NodeBase` — so `label`,
`gap_after`, `start_offset` come free. All four have **no child slots**, so `childSlots`,
`replaceSlot`, drag/drop, duplicate, and undo need no change.

`abort`/`alarm` use `if` in JSON but `condition` on the node, mirroring the existing
`BranchNode.condition` ↔ `branch.if` convention (`convert.ts:141`).

### 4.2 Canvas and Inspector

Palette chips, under a new **Control** section (Structure stays containers + wait + input):

| Kind | Glyph | Summary line |
|---|---|---|
| `compute` | `ƒ` | `ƒ c_1 = c_1 * V / (V + dV)` |
| `record` | `✎` | `✎ c_series_1 ← c_1` |
| `abort` | `⛔` | `⛔ Abort if emergency_stop` |
| `alarm` | `⚠` | `⚠ Alarm if contaminated_1` |

Glyphs deliberately avoid arrows: `summary.ts:13-20` records that `↻` (loop) next to a
retry marker was already unreadable, and `R×N` was chosen to break that collision. No new
glyph may reintroduce it.

Inspector editors:

- **compute** — `into` (`TextField`, binding name), `value` (`ExpressionInput`).
- **record** — `into` (**picker over declared streams**, not free text — the engine requires a
  declared stream), `value` (`ExpressionInput`).
- **abort** — `condition` (`ExpressionInput`), `message` (`TextField`, required non-empty).
- **alarm** — same as abort.

**Retry** stays gated to `command`/`measure` (`Inspector.tsx:121` already does this, and it is
correct: `retry` is command/measure-only per the #21 design §2.1). None of the four new leaves
gets a retry section.

**On-error** is shown for `compute`, `record`, `alarm` — and **omitted for `abort`**. The
engine forbids `on_error: "continue"` on an abort, because tolerating a safety stop is a
contradiction; offering a control whose only non-default value always produces an invalid
document is a UX defect, not flexibility. The related rule — an `abort` may not have *any*
tolerant ancestor (#25, review finding I1) — is **not** duplicated in the frontend: the
backend validator owns it and reports it as a diagnostic. One opinion, one place.

### 4.3 The live-chart fold

`reducer.ts` folds `sample_recorded` into `samples` identically to `measure_recorded`; both
carry `{stream, value}`. Computed streams get **no visual distinction** in the chart legend —
a stream is a stream, the declaration is where the difference lives, and the engine's own
disjointness rule (a stream is `measure` XOR `record`) means the two can never collide on one
series.

### 4.4 Reference plumbing

Two latent bugs that go live the moment `compute`/`record` can be authored:

- `refs.ts:45-55` `collectBindings` collects only `operator_input` names. A `compute.into` is
  a binding readable by later expressions (`blocks.py:96`), so it must be collected too —
  otherwise `exprHelp.ts` omits from its help exactly the bindings the author just created.
- `refs.ts:31-37` `countStreamRefs` counts only `measure` blocks. Once a stream can be fed by
  `record`, deleting a record-only stream reports **0 references** and is silently allowed,
  orphaning the block. It must count `record.into` as well.

`StreamsPanel` gains a per-stream source tag (`measure` / `record` / unused) — cheap, and it
makes the engine's XOR rule visible at the point of authoring rather than at validation.

### 4.5 Testing

- `convert.test.ts` — round-trip each new block; the existing golden-fixture byte-equality
  test extends to a fixture using all four.
- `tree.test.ts` — construction; `childSlots` returns `[]`.
- `summary.test.ts` — one arm per kind.
- `refs.test.ts` — compute binding collected; record-only stream counts 1 reference.
- `reducer.test.ts` — **a `sample_recorded` message lands in `samples`.** This is the
  regression test for §1.1 and must fail against today's reducer.
- Node-level Inspector tests follow the existing pattern (pure helpers tested; React glue not).

---

## 5. W9 — repetition

### 5.1 `for_each`

```json
{"for_each": {"var": "tube", "in": [1, 2, 3], "body": [ ... ]}}
{"for_each": {"in": [{"tube": 1, "port": 2}, {"tube": 2, "port": 3}], "body": [ ... ]}}
```

`ForEachNode` = `{kind, var: string | null, items: ValueExpr[] | Record<string,ValueExpr>[], body: BlockNode[]}`.
`childSlots` gains `['body', node.body]`; `replaceSlot` handles it; drag/drop, duplicate, and
undo then work with no further change. `Canvas.tsx`'s container test and `ContainerBody` gain
the kind, or `for_each` renders as a childless leaf.

Card: `∀ For each tube in [1, 2, 3]` — `∀` is unique and, unlike `⟳`, cannot be confused with
the loop's `↻`.

**The Inspector must omit `retry`, `on_error`, `gap_after`, and `start_offset` for a
`for_each`.** `expand.py:26` `_FOR_EACH_FORBIDDEN` rejects all four with
`"for_each may not carry block-level {k!r}; put it on the body blocks"` — the macro is a
splice, so there is no single runtime block for such a key to attach to. `label` is allowed.

`items` are edited as a JSON array in a `TextAreaField`, validated client-side against the
engine's own rules (`expand.py:95-118`): non-empty list; all scalars when `var` is set; all
objects sharing one key set when it is not. Client-side validation here is a fast-feedback
mirror, not a second opinion — the backend remains authoritative.

### 5.2 `groups` and the scope switcher

`DocSnapshot` gains `groups: Record<string, {params: string[]; body: BlockNode[]}>`, and the
store gains `scope: string | null` (`null` = main workflow). The canvas renders the active
scope's block list; the Palette, Inspector, and drag/drop are unchanged — they operate on
"the current tree", which becomes a selector rather than a field.

```
Editing: [ Main workflow ▾ ]
         ├ Main workflow
         ├ service(tube)
         └ + New group…
```

`GroupRefNode` = `{kind, name, args: Record<string, ValueExpr>}`. `types/doc.ts:55-57`
`GroupRefBody` is **missing `args`** today (engine `blocks.py:91` has it) — that gets fixed.
`WorkflowJson.groups` is `Record<string, unknown>`; it becomes a typed
`{params?: string[]; body: BlockJson[]}`.

Card: `⧉ service(tube=1)`.

**Undo/redo:** `groups` and `tree` are both document fields, so both belong in the zundo
snapshot; `scope` is view state and must **not** be (same rule that already excludes
`selectedUid`). Undoing an edit made in another scope while viewing a different one is
therefore possible — the store switches scope to follow the undone edit rather than applying
it invisibly.

**Deleting a group** whose name a `group_ref` still cites is refused, reusing the
`countRoleRefs`/`countStreamRefs` pattern in `refs.ts`.

### 5.3 The diagnostic source map (engine change)

`expand_dict` gains a traced sibling; the existing signature stays for every current caller:

```python
def expand_dict(workflow_dict: dict[str, Any]) -> dict[str, Any]: ...
def expand_dict_traced(workflow_dict: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]: ...
```

The trace maps **expanded structural path → authored structural path**, in the exact grammar
the validator emits (`validate.py:44-64`): `blocks[i]`, `.children[j]`, `.body[k]`,
`.then[k]`, `.else[k]`, plus `groups['name'].body[i]` for group bodies — `_iter_all_blocks`
already walks groups under exactly that prefix (`validate.py:63-64`), and `roles.py:71` emits
the identical form, so the map speaks a grammar both halves of the backend already produce.

Note the type key never appears in a path: a `for_each` body block is `blocks[0].body[0]`
(`validate.py:58` yields `f"{path}.body"`), the same slot spelling a `loop` body uses.

`_expand_blocks`/`_expand_block` already thread `groups`, `counter`, `depth`; they gain a
source prefix and a destination prefix. `_expand_blocks` knows each output block's expanded
index as it splices, and `_expand_block` knows the authored path it came from, so the trace is
built during the existing single walk — no second pass, no provenance stamped into the JSON
(which `workflow_from_dict` would reject anyway).

Two cases carry the meaning:

- **`for_each`** — every copy traces to the one authored body block:
  `blocks[0]`, `blocks[1]`, `blocks[2]` → `blocks[0].body[0]`.
- **`group_ref`** — an inlined body traces *into the groups dict*:
  `blocks[5].children[0]` → `groups['service'].body[0]`. This is precisely why `paths.ts`
  needs group-scope resolution and why P2 (editable group bodies) and P3 are one design: a
  diagnostic on the control law must be able to jump to where the control law is authored.

`docs_store.validate_doc` switches to `expand_dict_traced` and rewrites each diagnostic's
**structural prefix** through the trace before returning, leaving the context suffix
(`" branch if"`, `" param 'x'"`, `" abort if"`) untouched. Diagnostics from
`roles_mod.substitute` are remapped the same way — they too walk the expanded doc. An
unmapped path passes through unchanged rather than being dropped.

**Why this is clean here:** `validate_doc` expands *before* validating (`docs_store.py:164`),
so `validate()` sees a macro-free workflow, takes the legacy `_validate_workflow` path, and
**every** structural path it emits is an expanded path. There is no mixture with the
pre-expansion macro gates (`_validate_macro_workflow`), whose paths are authored — that
mixture would exist if Studio called `validate()` on the authored workflow, and it does not.

`runner.py` keeps calling plain `expand_dict`; run-time block paths are engine-side and out of
scope.

### 5.4 `paths.ts`

`ResolvedPath` gains `scope: string | null`. The structural regex gains a
`groups['name'].body[i]` prefix form alongside `blocks[i]`, and `for_each`'s `body` slot joins
`children|body|then|else` (`body` is already accepted, so this is a `childSlots` change only).
Clicking a diagnostic switches scope when needed, then selects the block.

`MappedDiagnostic.role` is currently written by `paths.ts:22-23` and **read by nothing** —
role diagnostics reach `ProblemsPanel.tsx:29-47` with `uid === null`, which disables the row's
button (`:32`), so they are unclickable. W9 wires `role` to focus the offending role in
`RolesPanel`, since the same click-to-source machinery is being touched anyway.

### 5.5 Testing

- `expand` trace tests (pytest) — `for_each` many-to-one; nested `for_each`; `group_ref`
  inline tracing into `groups['x'].body[i]`; plain-group bodies whose indices shift because a
  `for_each` inside them spliced.
- `test_docs_store` — a diagnostic inside a `for_each` body returns an **authored** path.
- `paths.test.ts` — group-scope resolution; a `for_each` body path resolves to the authored
  body block.
- `convert.test.ts` — `examples/morbidostat.json` round-trips through
  `docToTree`/`treeToDoc` byte-for-byte via `json.dumps`-style key-order-sensitive comparison
  (the W7 trap: deep-equal is blind to `6.0` vs `6` and to key order).

---

## 6. Error handling and graceful degradation

The W7 §7 contract **stays**, and stays emerald. After W9, `examples/morbidostat.json` opens
in the builder, so its note disappears — but the mechanism remains for genuinely unopenable
documents (`doc_version`/`schema_version` mismatch, malformed blocks). A document that fails
to convert must still import, list, run, and chart; only the block-tree render degrades, and
it degrades as a note, never as a red error.

`convert.ts:156`'s generic `unsupported block type '${kind}'` default remains as the
catch-all for a future engine block Studio has not learned yet — which is exactly the state
`compute`/`record`/`group_ref` were in, and the reason this spec exists.

`nodeToBlock` (`convert.ts:190-241`) is a `switch` over the node union with no `default`. It is
safe today only because `BlockNode` cannot represent the newer kinds; a kind added to the union
without an arm here silently emits a block with **zero type keys**, which the engine rejects at
`serialize.py:277` with a message pointing at the document rather than at the builder. Both
increments add arms; W8 additionally makes the switch exhaustive via a `never` check so the
next omission is a **compile** error.

---

## 7. Sharp edges this does not fix

Recorded so the omissions are deliberate, not forgotten.

- **The freshness-guard latch.** A bare `count(S) > 0` guard over a tolerated `measure` is a
  well-formed workflow that becomes an open-loop drug injector on a dead sensor (measured:
  1,600× OD collapse, run reports `completed`). The validator cannot catch it and neither can
  the builder. `docs/experiment-engine-limitations.md` §0 is the authority; a warning tier is
  engine work and stays on the backlog.
- **Tolerated actuation.** `on_error: "continue"` on a `valve.set_position` silently doses the
  wrong vial. The builder now makes `on_error` easy to set on more block kinds, which does not
  make this worse — it was already one dropdown away on every command — but it is why the
  On-error control keeps its explicit `fail (stop the run)` / `continue (tolerate the failure)`
  labels rather than a bare toggle.
- **`for_each` `var` shadowing a group `param`** — `expand.py:176-177` documents that a param
  shadows an inner loop var with no enforcement. Unchanged here.
- **Reserved `{identifier}` syntax.** Once any macro fires, a stray literal `{foo}` anywhere in
  the document is a post-expansion residual-hole error. Authoring a `for_each` in the builder
  therefore changes the meaning of brace text elsewhere in the same document. The residual-hole
  message names the offending hole, which is the mitigation.

---

## 8. Acceptance

**W8.** A document authored entirely in the canvas containing `compute`, `record`, `abort`,
and `alarm` saves, validates, runs, and round-trips byte-for-byte. A `record` stream appears
on the **live** chart while the run is in progress.

**W9.** `examples/morbidostat.json` — `groups` + `for_each`, the flagship — **opens in the
builder**, renders its `service(tube)` group in the scope switcher, round-trips byte-for-byte,
and a deliberately broken expression inside the group body produces a diagnostic that clicks
through to the authored block in the group scope.

**Both.** Gates green: engine `pytest`/`mypy src/lab_devices`/`ruff`/`awk 'length>100'`;
backend `pytest`/`mypy` (no path arg)/`ruff`; frontend `lint`/`typecheck`/`test --run`/`build`.
Real-hardware validation on preprod (`windows_arm64_test_client`) per §9.

## 9. Real-hardware validation

Per the established recipe: overlay the branch onto the preprod container, then drive a
purpose-built document via `ssh khamit@111.88.145.138 docker exec -i lab-bridge-jupyter-1`.

The honest gap carries forward unchanged: the rig's simulated densitometers read absorbance
**0.0**, so contamination-style predicates cannot fire on real hardware. W8's hardware proof is
therefore an **operator-input-driven** `abort` plus a `compute`/`record` accumulator on real
densitometers (the Increment-7 preprod run already proved per-tube accumulators drive real
devices); W9's is a canvas-authored `for_each` + `service(tube)` group running three real
tubes. Contamination-predicate coverage stays in FakeLab, where OD is scriptable.
