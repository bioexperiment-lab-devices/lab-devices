# Experiment engine — parametrized repetition (`for_each` + parametrized groups)

- **Date:** 2026-07-15
- **Status:** Design. Approved forks settled in §2 (both primitives), §3 (item + substitution
  model), §4 (first-class + expand-internally), §9 (Studio at the Increment-6 boundary).
- **Implements:** `docs/experiment-engine-limitations.md` **#4** ("Groups are not
  parametrized"). The limitations doc's own recommendation: *"A `for_each` block over a list of
  parameter bindings would subsume [parametrized groups] and is what the 15-vial case really
  wants."* We ship **both**, unified under one substitution engine.
- **Depends on:** Increments 1–6 (`lab_devices.experiment`), the fault-tolerance increment, and
  the computed-values increment (`compute`/`record`) — all on main.
- **This is Increment 7.**

## 1. The problem

`groups` + `group_ref` exist, but a group takes **no arguments**: its body hard-codes its device
roles and stream names. The morbidostat's three tube-service subtrees
(`examples/morbidostat.json`, the three `branch` blocks) are near-identical — they differ only by
a tube index `N` that threads through:

- a **device role** — `od_meter_N`;
- **stream names** — `od_N`, `blank_N`, `c_series_N`, `r_series_N`;
- **binding names** — `c_N`, `r_N`;
- a **scalar param** — the valve `position: N`.

The control law is therefore copied three times. Edit it and you must edit it three times,
identically, by hand. The published experiment runs **15 vials**; at 15 copies this stops being an
inconvenience and becomes a correctness hazard, and it is the single reason the example is capped
at three tubes. Nothing in the engine can *abstract over the repetition*.

## 2. What we are building (settled fork: both primitives, one engine)

Two authoring surfaces over **one** primitive — a deep substitution of `{name}` holes into a
copied block subtree (§3). Neither adds a runtime execution mode: both are **macros** that expand,
before validation and execution, into ordinary blocks (§4).

### 2.1 `for_each` — inline, iterated, spliced

```json
{ "for_each": {
    "var": "tube", "in": [1, 2, 3],
    "body": [ { "group_ref": {"name": "service", "args": {"tube": "{tube}"}} } ]
} }
```

For each item in `in`, the `body` is copied with the item's fields substituted, and the copies are
**spliced into the enclosing block-list** in place. `for_each` contributes `len(in) × len(body)`
siblings; it is **not** itself a container node at runtime. Mode is therefore inherited from the
enclosing container:

- `for_each` as the sole child of a **`parallel`** → N concurrent lanes;
- `for_each` in a **`serial`** / loop `body` → N blocks in sequence.

This is exactly what writing the blocks out by hand produces today — `for_each` is sugar for it.

### 2.2 Parametrized groups — named, reusable, substituted

```json
"groups": { "service": { "params": ["tube"], "body": [ ...uses {tube}... ] } }
```

Invoked by a `group_ref` carrying `args`:

```json
{ "group_ref": {"name": "service", "args": {"tube": 2}} }
```

The group body is copied with `args` substituted and inlined as a **single** `Serial`-wrapped
instance (one invocation, not iteration) that carries the `group_ref`'s own block-level keys
(`label`, `on_error`, timing). A `group_ref` with `args` therefore behaves like a call.

- **Plain (param-less) groups are unchanged.** A group with no `params`, referenced by a
  `group_ref` with no `args`, keeps today's exact lazy-inline semantics and today's `group[...]`
  block ids (§4.4). This increment adds behavior only for the new `args` case — **zero back-compat
  change** for existing group docs.
- **Arity is checked** (§6): a `group_ref`'s `args` keys must equal the group's declared `params`
  exactly — no missing, no extra. A group with `params` referenced without `args` (and vice versa)
  is an error.

### 2.3 They compose

`for_each` supplies the *iteration*; parametrized groups supply the *named reusable body*. The
canonical composition — and how the example is written (§8) — is a `for_each` whose body is a
single `group_ref(args)`, passing the loop variable through the args (`{"tube": "{tube}"}`). The
`for_each` splices N calls; each call inlines the substituted `service` body. This exercises both
features and their composition end to end.

## 3. The substitution engine (settled fork: objects + scalar shorthand, `{name}` interpolation)

One primitive underneath both surfaces: **`substitute(subtree, env)`** — deep-copy a block
subtree, replacing every `{name}` occurrence in **every string** it contains with `env[name]`.

- **Slots reached:** uniformly, *all* string values in the copied subtree — `device`, `into`,
  `value`, `if`, `until`, `duration`, `pace`, `gap_after`, `start_offset`, `retry.backoff`,
  `label`, every string `params` value, and every `group_ref.args` value (so a `for_each` can pass
  its variable into a group). Non-string slots (`count`) are untouched. The rule is deliberately
  uniform — "interpolate every string" — so it is predictable and needs no per-slot table.
- **`env` shape.** Items are **objects** whose fields become holes: `in: [{tube:1}, {tube:2}]`,
  interpolate `{tube}`. A **scalar shorthand** desugars to single-field objects:
  `var: "tube", in: [1, 2, 3]` ≡ `in: [{tube:1}, {tube:2}, {tube:3}]`. `var` is required with
  scalar items and forbidden with object items (mixing is an error).
- **Value formatting.** Item field values are JSON number / string / bool. A number renders
  canonically (`1` → `"1"`, `1.5` → `"1.5"`), a bool as `true`/`false`, a string verbatim.
- **The expansion is fully re-validated (§4.3), so substitution itself is untrusted.** A hole that
  lands in a name position and yields a non-identifier (`od_{tube}` with `tube = 1.5` → `od_1.5`)
  is caught by the ordinary `_IDENT_RE` / stream-declaration checks at the expanded position — no
  bespoke pre-check is required, though a targeted "interpolation into a name must be an
  identifier" diagnostic is a cheap nicety we include.
- **Delimiter safety.** The expression grammar never uses `{` or `}` (`expr.py` — verified), so
  `{name}` is unambiguous inside expression text: `mean(od_{tube}, last=5)` → `mean(od_1, last=5)`
  parses only after substitution.

## 4. Expand-then-everything (settled fork: first-class AST, expand internally)

`for_each` and parametrized `group_ref`s are **first-class in the authored AST** — they serialize
back **unchanged**, so the source document stays DRY across a save/reload (`workflow_to_dict ∘
workflow_from_dict` is identity on them). But `validate()` and `ExperimentRun` operate on an
**internally expanded copy**. This is the whole architectural payoff: once `for_each tube in
[1,2,3]` becomes concrete `od_1/od_2/od_3`, `c_1/c_2/c_3`, every existing path-sensitive analysis
runs on real names with **no new analysis logic** (§4.3).

### 4.1 The expander (`expand.py`)

Two entry points over one workhorse:

- **`expand_dict(workflow_dict) -> workflow_dict`** — the workhorse. Pure JSON manipulation: it
  splices `for_each`, inlines parametrized `group_ref`s (as `Serial` instances), interpolates
  `{name}`, expands `group` bodies, and enforces the expansion cap (§4.5). It **never calls
  `lookup`**, so it runs on role-named or templated device strings before they are concrete. This
  is the entry point the role pipeline uses (§4.4, §9).
- **`expand_workflow(w: Workflow) -> Workflow`** = `workflow_from_dict(expand_dict(
  workflow_to_dict(w)))`. Used by `validate()` and `ExperimentRun`. Only ever invoked on
  concrete-typed ASTs (role-named ASTs never reach it — they are dict-expanded and role-substituted
  before load, §4.4).

Expansion rules:

1. **`for_each`** → for each item, `substitute(body, env)`; concatenate; splice into the parent
   list. Block-level keys (`retry`, `on_error`, `gap_after`, `start_offset`) are **not allowed on
   a `for_each`** — it has no single runtime identity to attach them to; put them on the body
   blocks. `label` is allowed (documentation only; discarded on expansion). `retry` is already
   rejected by `_check_retry` (command/measure only); the others get a targeted diagnostic (§6).
2. **Parametrized `group_ref`** (group has `params`) → `Serial(children=substitute(expand(
   group.body), args), label=ref.label, on_error=ref.on_error, gap_after=ref.gap_after,
   start_offset=ref.start_offset)`. A `Serial` wrapper is transparent to `_footprint` and path
   analysis, and it preserves the call's block-level semantics.
3. **Plain `group_ref`** (group has no `params`) → left as a `GroupRef` node (today's lazy inline).
   Its target group's body **is** for_each-expanded in the expanded workflow, so the lazy inline at
   exec/analysis never meets a `for_each`.
4. **Group bodies.** Every `group` body is for_each-expanded. **Parametrized** groups are dropped
   from the expanded workflow's `groups` (fully inlined at call sites), so the templated body is
   never fed to the concrete per-block checks. **Plain** groups are kept, bodies expanded.

### 4.2 Validation flow (`validate.py` refactor)

`validate(w: Workflow)` becomes two phases:

- **Pre-expansion gates on the authored `w`** (authored paths, good errors): the existing
  `_check_groups` (unknown ref / recursion), plus new `_check_for_each_shape` (var/in/body
  well-formedness, disallowed block-level keys) and `_check_group_arity` (`args` ↔ `params`), plus
  the cap feasibility check (§4.5). These gate expansion exactly as the recursive-group guard
  already gates the path phase today.
- **If the gates pass:** `we = expand_workflow(w)`, then run every existing concrete check on
  `we` — `_check_defaults`, `_check_namespaces`, `_collect_binding_types`, the per-block
  `_check_block` sweep over `_iter_all_blocks(we)`, and `_analyze_paths(we)`. Templated bodies are
  never type/stream/name-checked; only concrete expansions are.

### 4.3 Why every subtle analysis keeps working for free

Because the checks run on `we`, whose streams and bindings are concrete:

- **Parallel affinity** sees `od_meter_1/2/3` as distinct devices — the OD-read lanes are legal;
  two lanes touching the same device+channel are still flagged.
- **Accumulator seeding / read-before-write** sees concrete `c_1 = 0` seeds before concrete
  `c_1 = c_1*…` updates — the computed-values #1 machinery validates the expansion unchanged.
- **Freshness guards** see concrete `count(od_1, last=11min) > 0` guarding concrete
  `mean(od_1,…)` — the open-loop-injector proof lattice (`analyze.py`) is untouched.
- **Mode intervals** see concrete per-device thermostat/optics modes.

Not one of these needs a line of new analysis — this is the reason expand-then-validate was
chosen over a param-aware symbolic analysis.

### 4.4 Execution (`run.py`) — and why `execute.py` barely changes

`ExperimentRun.__init__`:

```python
validate(workflow)                      # expands internally to check
expanded = expand_workflow(workflow)    # the tree we actually run
assign_block_ids(expanded)
self._workflow = expanded
# workflow.streams == expanded.streams — stream declarations are unchanged by expansion
```

The executor runs `expanded`, which contains **no `for_each`** and **no parametrized `group_ref`**
— only plain `group_ref`s remain, handled exactly as today. So `execute.py` needs **no new arm**;
`assign_block_ids` numbers the expanded tree (parametrized-group instances get positional ids;
plain groups keep `groups[...]` ids). The authored document is never re-serialized by the run, so
it stays DRY on disk.

### 4.5 Resource cap (the deferred "group-DAG expansion" bound)

Expansion is bounded to fail loud rather than blow up: a **total expanded-block cap** (default
10,000) raises a `ValidationError` naming the offending `for_each`/group when the product of nested
`in` lengths and body sizes would exceed it. This closes the resource-bounds item deferred since
Increment 5.

### 4.6 Diagnostics traceability (known limitation)

Post-expansion diagnostics reference **positions in the expanded tree** (e.g. `…loop.body[2]…`).
Positions remain traceable to the source `for_each` / item index, but they do not name the item
symbolically. A provenance map (`{tube=2}` in the path) is a possible future polish; for v1 the
pre-expansion gates catch the common authoring mistakes at authored paths, and expanded positions
are accepted for the semantic checks.

## 5. Schema & serialization (`blocks.py`, `serialize.py`)

- **`blocks.py`:** a `ForEach` dataclass (`var: str | None`, `items: list[...]`, `body: list[Block]`);
  `Group` gains `params: list[str]`; `GroupRef` gains `args: dict[str, ValueExpr]`.
- **`serialize.py`:** a `_for_each` builder + `_dump_body` arm (round-trip: `var`/`in`/`body`);
  `group_ref` dump/load carries `args`; the `groups` section dump/load carries `params`.
  `for_each` is added to `_BUILDERS`. `_no_misplaced_block_keys` works unchanged.
- **Load tolerance (defensive):** `workflow_from_dict` skips the eager `lookup` for a device
  string containing `{` (a template), so an authored for_each doc whose device holes do not resolve
  to a real type prefix still loads to a first-class AST and round-trips; the concrete device is
  verified post-expansion. (The engine's canonical templated form keeps a real type prefix —
  `densitometer_{tube}` has type `densitometer` — so this is belt-and-suspenders.)

## 6. Validation rules (new)

Collected as `Diagnostic`s like every existing rule:

- **`for_each` shape:** `body` is a non-empty list; exactly one of {`var` + scalar `in`} or
  {object `in`} (mixing → error); `in` is a non-empty list; object items share one key set;
  scalar items require `var`; item field values are number/string/bool.
- **`for_each` block-level keys:** `retry` (already via `_check_retry`), `on_error`, `gap_after`,
  `start_offset` on a `for_each` → error with a "put it on the body blocks" message.
- **Group arity:** `group_ref.args` keys == `group.params` (exact); a parametrized group referenced
  without matching `args`, or a plain group referenced with `args`, → error. Duplicate `params`,
  non-identifier `params` → error.
- **Everything else is inherited** from the concrete expansion (§4.2): undeclared streams, name
  disjointness, read-before-write, freshness, affinity, modes, types.

## 7. Testing (TDD throughout)

**Unit — substitution & expansion (`expand.py`).**
- `{name}` interpolation into device / into / expression / param / label / duration slots.
- Scalar shorthand desugars to object items; object items with multiple fields.
- `for_each` splices into a `parallel` (→ N lanes) and into a `serial` (→ N sequence).
- Parametrized `group_ref` inlines as a `Serial` carrying `on_error`/`label`.
- `for_each` over a `group_ref(args)` (the composition) expands to N Serial-wrapped bodies.
- Nested `for_each`; expansion cap trips with a clear error.

**Unit — serialization.** `workflow_to_dict(workflow_from_dict(d)) == d` for docs containing
`for_each`, parametrized groups, and `group_ref` args (round-trip stability = the DRY guarantee).

**Validator.**
- Arity: missing/extra `args`; plain group with `args`; parametrized group without `args`.
- `for_each` shape errors (empty body, var+object mix, empty `in`, ragged object keys).
- Disallowed block-level keys on `for_each`.
- **Expansion soundness (the load-bearing tests):** a `for_each` of OD-read lanes over one shared
  device → affinity error; distinct devices → clean. A `for_each`-seeded accumulator
  (`for_each: compute c_{tube}=0` before the loop, update inside) validates clean; **without** the
  seed → read-before-write error at the expanded position. A tolerated `measure` in a `for_each`
  lane whose windowed read is unguarded → freshness diagnosed; guarded → clean.
- Recursion still caught pre-expansion (a parametrized group referencing itself).

**Executor (FakeClock / FakeLab, zero wall-clock).**
- A `for_each` over `[1,2,3]` drives three distinct devices; parallel splice reads concurrently,
  serial splice runs in order.
- A parametrized `service(tube)` group invoked per tube produces per-tube stream writes and
  per-tube accumulator state that do not cross-contaminate.
- Block ids of expanded instances are positional and stable; plain group ids unchanged.

**Regression.** An existing plain-group doc (no `params`, no `args`) validates, runs, and yields
**identical** block ids and behavior — the back-compat guarantee (§2.2).

**Gates (every task):** `.venv/bin/python -m pytest`, `mypy` (scope `src/lab_devices` only),
`ruff check .`, and `awk 'length>100'` over experiment src + tests.

## 8. The example — the demonstrator (settled fork: rewrite + preprod)

`examples/morbidostat.json` and `morbidostat-demo-speed.json` are rewritten to close #4 and to be
the scaffolding that reaches 15 vials:

- **The tube-service subtree becomes a parametrized group `service(tube)`** — defined once, using
  `{tube}` for the device role (`od_meter_{tube}`), streams (`od_{tube}`, `c_series_{tube}`,
  `r_series_{tube}`), bindings (`c_{tube}`, `r_{tube}`), and the valve `position: "{tube}"`.
- **Repetition becomes `for_each tube in [1,2,3]`** in three places: the accumulator seeds
  (`for_each … compute c_{tube} = 0`), the OD-read lanes (a `for_each` inside the reads `parallel`
  → three lanes), and the per-cycle service invocation (`for_each … group_ref service(tube={tube})`
  in the loop body). The control law now lives in **one** place.
- **Stream declarations stay explicit** (`od_1/2/3`, `c_series_1/2/3`, …). They are flat data, not
  the duplicated control *law* #4 is about; templating them is out of scope (§10).
- The freshness guard, accumulator recursion, fault tolerance, and every pace-coupled constant are
  unchanged — they are simply written once and expanded per tube. Two guarantees prove the rewrite
  is behavior-preserving: (a) a **golden test** asserting `expand_dict(new_workflow)` equals a
  committed expected-expansion fixture (which differs from the old hand-copied tree only by the
  transparent `Serial` wrappers that a parametrized `group_ref` inlines as, §4.1); and (b) the
  existing **integration test** (`test_examples_morbidostat.py` — the control loop must pin each
  culture at its IC50) passing **unchanged** against the rewritten doc, which is the real proof the
  expanded behavior is identical.
- `test_examples_morbidostat.py` is updated to **expand before role substitution** (`expand_dict`
  → `_substitute` → `workflow_from_dict`); `examples/README.md` prose describes the `service`
  macro and the `for_each` scaffolding and notes the 15-vial path.

## 9. Studio — the Increment-6 boundary (settled fork)

Matches exactly what `compute`/`record` shipped last increment: **runnable and viewable, not
canvas-editable.**

- **Backend grammar parity (`webapp/backend/experiment_studio/roles.py`).** Add `for_each` to
  `_CHILD_LISTS` (`("body",)`) so the role walker recurses into it; `group_ref` stays in
  `_LEAF_BLOCKS` (its `args` are data, not a child list). The parity test
  `test_walker_grammar_matches_engine_serializer` (`_DEVICE_BLOCKS ∪ _CHILD_LISTS ∪ _LEAF_BLOCKS
  == set(serialize._BUILDERS)`) stays green with `for_each` added on both sides.
- **Expand before role substitution.** The Studio validate/run pipeline calls the engine's
  `expand_dict` on the workflow dict **before** `roles.substitute`, so templated roles
  (`od_meter_{tube}`) become concrete (`od_meter_1`) and map to real device ids. Diagnostics for a
  for_each doc reference expanded positions (acceptable — such docs are not canvas-editable).
- **Frontend degrades gracefully, no crash.** `convert.ts` already throws `DocConvertError` on
  `groups` (`convert.ts:53`) and on any unhandled block type (`convert.ts:148`), and
  `WorkflowSnapshot.tsx` catches it and renders the "cannot render the snapshot" message — the same
  status a group/`compute`/`record` doc has today. A `for_each` doc therefore **imports, runs on
  hardware, charts its (concrete, post-expansion) streams from `/streams`, and shows in the event
  log**; it is just not editable on the builder canvas. `for_each` is added to the explicit
  "known-but-unsupported-in-builder" set so the message is specific, not a generic throw.
- **Backend tests:** `roles.substitute` recurses `for_each` bodies; a role-mapped for_each doc,
  expanded then substituted, validates and runs; a parametrized-group doc round-trips.

## 10. Out of scope

- **Full builder authoring UI** for `for_each` / groups / `group_ref` / `compute` / `record` —
  the canvas has no group support at all today (`convert.ts:53`), so this is a separate,
  larger frontend increment (bring the builder to grammar parity, then add visual for_each/group
  editing). Deferred; the JSON-authored example is sufficient.
- **Stream-declaration templating.** 15 vials still hand-declare 15×N streams. Streams are flat
  data; a future `streams` template could help, but the control-law duplication #4 targets is what
  `for_each` fixes.
- **`count` / `pace` as expressions or holes** — that is limitation #6. `for_each` interpolates
  strings (durations included), but `count` stays an integer literal.
- **Cross-item dependencies, dynamic `in` lists, `elapsed()`-driven iteration** — `in` is a static
  literal list.
- **Symbolic item provenance in diagnostic paths** (§4.6) — expanded positions are accepted for
  v1.

## 11. Documentation

- `docs/experiment-engine-limitations.md` — **#4** rewritten from "what is missing" to "what
  shipped", keeping the motivation; the summary table row for #4 and the closing paragraph updated
  (the 15-vial version is now expressible). Note that `defaults.retry` had already bought *retry
  policy* at scale; #4 now buys the *control law* at scale.
- `docs/superpowers/specs/2026-07-07-experiment-orchestrator-design.md` — §5 (block taxonomy)
  gains `for_each`; §12 (groups) gains `params`/`args` and the expansion model; §15
  (serialization) gains the three new forms.
