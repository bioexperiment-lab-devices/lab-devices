# Experiment engine — typed group parameters, group-locals, and engine-owned roles

- **Date:** 2026-07-20
- **Status:** Approved (brainstorming complete 2026-07-20). Seven forks user-settled: §2
  (kind system + group-locals), §3 (concatenation splits by kind), §4 (one type system, covering
  `for_each`), §5 (roles move fully into the engine), §6 (required `as:` on `group_ref`), §7
  (hard break, `schema_version: 2`), §9 (one spec, two PRs). Two decisions settled by the author
  and explicitly approved: **mapping injectivity** (§5.4) and **constant-only `init`** (§2.3).
- **Supersedes:** the untyped `Group.params: list[str]` shipped in Increment 7
  (`2026-07-15-experiment-orchestrator-7-parametrized-repetition-design.md`). That design's own
  §1 already names the four distinct things a single index threads through; this increment gives
  each of them a type instead of a shared textual hole.
- **Depends on:** Increments 1–8 and the Studio increments W1–W16 — all on main (v0.11.0).
- **This is Increment 9 (engine) + W17 (Studio).**

## 1. The problem

`Group.params` is `list[str]` (`workflow.py:33`) — a bare textual macro. `expand.py::_substitute`
interpolates `{name}` into **every string anywhere in the body** (`expand.py:47-55`), and the only
check before that happens is set equality of names, `set(args) == set(params)`
(`expand.py:232-235`). `for_each` vars work identically.

In `examples/morbidostat.json` the single param `tube` of `service(tube)` is simultaneously:

| use | example | what it really is |
|---|---|---|
| stream-name suffix | `od_{tube}`, `r_series_{tube}` | a stream reference |
| binding-name suffix | `c_{tube}`, `contaminated_{tube}` | a binding reference |
| verb param literal | `position: "{tube}"` | an `int` value |
| device-role suffix | `od_meter_{tube}` (`:550`) | a role, spelled as string surgery |

Four kinds of thing behind one untyped hole. **Nothing can be checked before expansion**, because
`od_{tube}` is not a name until expansion produces one. Two consequences:

1. **Safety.** A typo in a group body is not a load error; it is a residual-hole error, an
   undeclared-stream error at some expanded index, or — worst — a silently valid name that reads
   as a different tube's data.
2. **Authoring.** Experiment Studio already renders typed dropdowns for device params, roles, and
   streams (`Inspector.tsx:379-409`, `StreamIntoPicker.tsx`), driven by the verb registry. Group
   params are the one place it must fall back to free text (`Inspector.tsx:898-907`), because a
   `string` is all the schema records. Studio cannot offer "pick a densitometer role, then call
   its measurements" for a group param, since it has no way to know that is what the param is.

## 2. The kind system

One kind set, used identically by group params, group locals, and `for_each` vars.

| kind | the arg is | checked pre-expansion |
|---|---|---|
| `int`, `number`, `bool`, `string` | a literal value | JSON type matches the kind |
| `role` (requires `device_type`) | a declared role name | role exists; `roles[r].type == device_type` |
| `stream` | a declared stream name | stream exists in `workflow.streams` |
| `binding` | a binding name | identifier shape; namespace disjointness (`validate.py:520`) |

`binding` is deliberately the weakest of the three references, and it has to be: bindings have no
declaration section — they are created implicitly by their writer, `operator_input.name` or
`compute.into` (`validate.py:864-865,882-883`). So a `binding` arg cannot be checked for
existence, only for shape and for not colliding with a stream. Existence remains the job of the
existing path-sensitive rule, which reports a binding *"may be read before it is written"*
(`validate.py:679-680`). Group locals (§2.2) are the way to get a *declared* binding.

Value kinds deliberately mirror `registry.ParamSpec.kind` (`registry.py:20`) so a value param
bound to a verb param can be checked kind-against-kind. Reference kinds are new.

### 2.1 Declaration syntax

`params` becomes an **ordered list of objects** (order is the authoring order Studio renders):

```json
"service": {
  "params": [
    {"name": "tube", "kind": "int"},
    {"name": "od",   "kind": "stream"}
  ],
  "locals": { ... },
  "body": [ ... ]
}
```

A `role` param carries its device type, which is what makes role-specific verb offering possible:

```json
{"name": "meter", "kind": "role", "device_type": "densitometer"}
```

`device_type` is **required** on `role` and forbidden on every other kind. An unknown
`device_type` (not a key of the verb registry's device types) is a load error.

### 2.2 Group locals

A group declares the streams and bindings it owns. This is what keeps typing from becoming
verbose: without it, `service` needs ~9 explicit reference params — every stream and binding it
touches — and each call site must thread all of them.

```json
"locals": {
  "c":            {"kind": "binding", "init": "0"},
  "contaminated": {"kind": "binding", "init": "false"},
  "alarmed":      {"kind": "binding", "init": "false"},
  "r":            {"kind": "binding"},
  "od_high":      {"kind": "binding"},
  "c_series":     {"kind": "stream", "units": "ug/mL"},
  "r_series":     {"kind": "stream", "units": "1/h"}
}
```

Only `stream` and `binding` kinds are legal in `locals` — a local value would just be a constant,
which `compute` already expresses. A `stream` local may carry `units` and `persistence`, matching
`StreamDecl` (`workflow.py:23-26`); the expander copies them into the emitted declaration.

**Locals are namespaced, not private.** They expand into ordinary top-level streams and bindings
under a qualified name (§6), and any expression anywhere in the workflow may read that qualified
name. This is required, not merely permitted: `examples/morbidostat.json` gates a top-level abort
on `contaminated_1 and contaminated_2 and contaminated_3`, reading three per-tube latches from
outside the group that owns them. Under this design that abort reads
`tube_1_contaminated and tube_2_contaminated and tube_3_contaminated`.

Introducing a private scope would break that pattern and buy nothing the namespace does not
already give: the point of locals is to stop the *author* from doing name surgery, not to hide
the resulting names from the rest of the document.

### 2.3 `init` — settled: constant expressions only

A local may declare `init`, an expression evaluated once before the run. The expander hoists one
`compute` per initialized local to the **front of `workflow.blocks`**, in deterministic expansion
order. That is exactly where the seeds live today — `examples/morbidostat.json:484-506` is a
`for_each` of three `compute` blocks sitting before the outer loop — so this replaces an
authoring pattern rather than inventing one.

`init` **must be a constant expression**: numeric/boolean literals and operators over them, with
no `stat` calls, no stream references, and no binding references. Rationale: a hoisted initializer
runs before every other block in the document, so any data dependency it could express is
guaranteed unwritten at that point. Permitting them would produce a read-before-write diagnostic
at best and a confusing one at worst — the analysis would blame a block the author never wrote at
a position they never chose. Restricting `init` makes the hoist total and order-insensitive.

A local without `init` is merely declared. Existing path-sensitive analysis
(`validate.py:679-680`) already reports it if it is read before written, so no new check is
needed.

### 2.4 Name rules

- A group's **param names and local names share one namespace** and may not collide. Both become
  holes in the same body, so a collision has no meaningful resolution.
- A param or local name must match `_IDENT_RE` (`validate.py:256`) and must not be a reserved
  name (`_RESERVED_NAMES`).
- `group_ref.args` must supply **exactly** the declared param names — no missing, no extra. This
  keeps the existing arity rule (`expand.py:232-235`), now checked against typed declarations and
  reported per-param rather than as a set-difference message.
- The **param-shadows-`for_each`-var hazard is now caught.** `expand.py:216-217` documents it as a
  known, unenforced caveat: a group param silently shadows an enclosing loop var of the same
  name. With both sides declared, the expander detects the shadow and reports it.

## 3. Substitution — uniform holes, concatenation split by kind

**Everything is a hole.** Inside a group body, params and locals are referenced as `{name}` in
every position, including inside expression strings:

```json
{"compute": {"into": "{od_high}",
             "value": "count({od}, last=11min) > 0 and mean({od}, last=11min) > 2.0"}}
```

There is no bare-name-in-expressions special case. Uniformity is what makes the residual-hole scan
(`expand.py:284-293`) a complete check: any name that is neither substituted nor a real
post-expansion identifier is caught by construction. Expressions containing holes are unparseable
until expansion, which is already the established behaviour — `serialize._checked_expr` skips
eager parsing when `'{' in text` (Increment 7, §4.1) — so this adds no new deferral.

**Concatenation splits by kind:**

- **Reference kinds** (`role`, `stream`, `binding`) — the hole must occupy a **whole identifier**:
  it may not sit adjacent to identifier characters (`[A-Za-z0-9_]`) on either side.

  ```
  "{od}"                                legal — the entire string (a name field)
  "count({od}, last=11min) > 0"         legal — delimited by "(" and ","
  "od_{od}"                             load error — glued to a leading "od_"
  "{od}_raw"                            load error — glued to a trailing "_raw"
  "{od}{other}"                         load error — glued to an adjacent hole
  ```

  **Adjacency is judged after substitution, not before.** A neighbouring hole counts as glue:
  in the authored text the character beside `{od}` is `{` or `}`, never an identifier character,
  so a rule that only inspected the authored string would let `"{od}{other}"` through and
  manufacture `od_1od_2` — precisely the name-surgery this forbids. For a reference-kind hole,
  treat `{` and `}` as identifier characters too.

  Stating the rule as "the entire string" would be wrong: a reference legitimately appears
  *inside* a larger expression string, which is exactly where most stream references live. What
  must be forbidden is **concatenation with adjacent identifier text**, because that is what
  manufactures a new name instead of referring to a declared one. In a plain name field
  (`device`, `into`, an `args` value) the two formulations coincide — the whole string is the
  identifier — so the rule reads as "must be the entire string" there.

  A reference hole always substitutes as the name string; the typed-JSON-value rule of §3.1
  applies to value kinds only.
- **Value kinds** (`int`, `number`, `bool`, `string`) — interpolate anywhere. `"position": "{tube}"`
  and `"label": "tube {tube}: service"` both keep working unchanged.

### 3.1 Typed substitution of value kinds

A **whole-string hole of a value kind substitutes as a typed JSON value**, not a string. So
`{"position": "{tube}"}` with `tube: int = 1` yields `{"position": 1}`, where today it yields
`{"position": "1"}` — a string that survives only because `_check_param_value` (`validate.py:200`)
re-parses a string in an `int`-kinded slot as an expression. Embedded holes still stringify via
`_fmt` (`expand.py:29-34`), since the result is by definition a larger string.

This removes a real class of confusion: the `position: "{tube}"` → `"1"` → parsed-as-expression →
`int` path is three coincidences deep, and it is the reason Increment 7's own notes record
`valve position:"{tube}" = string expr → int` as a thing to remember.

## 4. `for_each` — a typed table

`for_each` vars take the same declarations, and `in` becomes a table of typed rows:

```json
{"for_each": {
  "vars": [{"name": "tube",  "kind": "int"},
           {"name": "meter", "kind": "role", "device_type": "densitometer"},
           {"name": "od",    "kind": "stream"}],
  "in": [{"tube": 1, "meter": "od_meter_1", "od": "od_1"},
         {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
         {"tube": 3, "meter": "od_meter_3", "od": "od_3"}],
  "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}]}}
```

This is where the role case lands. `od_meter_{tube}` — string surgery whose result is expected to
be a role name — becomes a `role<densitometer>` column, checkable before expansion against the
role declarations.

The old scalar shorthand (`"var": "tube", "in": [1, 2, 3]`) is **removed**. It cannot carry a kind,
and keeping it would leave the untyped path alive next to the typed one. Every row must supply
exactly the declared var names; a missing or extra key is a load error, replacing the weaker
"object items must share one key set" check (`expand.py:109-117`) which only enforced mutual
consistency, not agreement with a declaration.

Every cell being typed is what lets Studio render `in` as a grid with a role dropdown filtered by
device type, a stream picker, and a typed value field per column (§9.2).

## 5. Roles move into the engine

Settled fork: the **full move**. Today `grep -rni '\brole' src/` returns zero hits — roles are a
Studio-only concept, and role→type resolution is `device_id.rsplit("_", 1)[0]`
(`registry.py:200`) round-tripped through synthetic placeholder ids that exist only to be decoded
back by that same hack (`roles.py:42-50`).

### 5.1 Declaration

```json
"roles": {
  "od_meter_1":  {"type": "densitometer"},
  "medium_pump": {"type": "pump", "device": "pump_2"}
}
```

`type` must be a device type known to the verb registry. `device` is optional and binds the role
directly, so a standalone (non-Studio) user of the published `bioexperiment-lab-devices` package
is not forced to supply a mapping for a fixed rig.

### 5.2 `device:` fields hold role names, end to end

`Command.device` and `Measure.device` (`blocks.py:32-45`) carry role names throughout load,
validation, expansion, and execution. **Role names stay the key everywhere inside the engine** —
`ctx.lock()` (`context.py:82-92`), `Occupancy._slots`, `ctx.touched`, `ctx.in_flight`, and event
payloads all key on the role name, unchanged in shape. Injectivity (§5.4) makes that sound:
role names and device ids are in bijection, so keying by either yields identical behaviour.

Exactly **one** site resolves to a physical device id: `ctx.device(role)`, which looks up the
mapping and returns the `LabClient` handle. Keeping resolution to a single point is the whole
benefit of the move — the wire boundary is the only place a physical id is meaningful.

Events therefore carry role names, which is what the author wrote and what diagnostics should
name. The role→device mapping is recorded **once** on `RunReport`, rather than duplicated into
every event payload.

Every **type** site instead reads `workflow.roles[name].type`:

- `registry.lookup()` changes signature to take a device **type**, not a device id.
- **`registry.device_type()` is deleted.** With it go all three copies of the `rsplit("_", 1)`
  convention: `registry.py:200`, `runner.py:110`, and its inverse `placeholder_ids`
  (`roles.py:42`).
- `finalize.py:58` needs both: the type to select sweep verbs, the role name to address the
  device. It reads the type from the declaration and keeps iterating `ctx.touched` by role.

### 5.3 Parse ordering

`workflow_from_dict` currently parses `blocks` *inside* the `Workflow(...)` constructor call
(`serialize.py:420`), and `_command`/`_measure` call `lookup(device, verb)` at parse time
(`serialize.py:131,139`). With role names in `device:`, `lookup` would need a type it cannot
derive, so **`roles` must be parsed before `blocks`** and threaded into `_command`/`_measure`. The
existing `if "{" not in device` escape for unexpanded holes stays.

### 5.4 Mapping injectivity — settled

**The role→device mapping must be injective**, checked at run start; a duplicate device id across
two roles is a load-time error.

This is load-bearing, not hygiene. The affinity and mode analyses intersect raw device strings
(`_footprint`, `validate.py:783-820`; mode keying, `validate.py:729-745`) and `Occupancy._slots`
keys raw device strings (`occupancy.py:48`). Today they agree only because Studio hands the engine
already-substituted physical ids and re-validates against them — `runner.py:336-339`, whose
comment states the purpose exactly: *"construction runs the engine validator against the REAL
device ids — this is the real-mapping re-validation (two roles on one device etc.)"*.

If the engine validated on role names with a non-injective mapping, two roles aliasing onto one
device would pass every static check and then collide at run time on one `(device, channel)` slot,
raising `InvariantViolationError` from `occupancy.py:82` — which `_NEVER_RETRY` refuses to retry
(`execute.py:38-44`) and `_tolerable` refuses to absorb (`execute.py:483-493`). A statically clean
workflow would die mid-run, unrecoverably.

With injectivity, role names are in bijection with device ids, so footprint intersection over role
names is **provably equivalent** to intersection over device ids. The static proof becomes sound
by construction rather than sound by Studio's convention. Two payoffs follow:

- Studio validates **once**, on the unbound document, with no mapping and no placeholder ids.
- `roles.py` loses `substitute` and `placeholder_ids`, and with them the hand-copied
  `_BLOCK_KEYS`/`_CHILD_LISTS` block-grammar mirror carrying the standing warning *"Keep in sync
  or blocks are silently skipped in `_walk`"* (`roles.py:11-23`).

The cost is a genuine new restriction — a previously legal mapping becomes an error. It is the
right one: a role denotes a distinct physical instrument, and the alternative is a runtime failure
mode the validator cannot see.

## 6. Instance naming — required `as:`

A `group_ref` calling a group that declares `locals` **must** supply `as`, the instance name:

```json
{"group_ref": {"name": "service", "as": "tube_{tube}",
               "args": {"tube": "{tube}", "od": "{od}"}}}
```

Locals qualify as `{as}_{local}` — `tube_1_c`, `tube_1_c_series`. `as` is an ordinary string
field, so value-kind holes interpolate into it (§3), which is how one call site inside a
`for_each` produces three distinct instances.

- `as` must expand to a valid identifier (`_IDENT_RE`, `validate.py:256`), so qualified names are
  legal expression `NAME` tokens.
- **Duplicate `as` post-expansion is a load error.** Instance names are the identity of the
  emitted streams and bindings; two instances sharing one would silently merge two tubes' data.
- `as` is optional for a group with no locals, where it has nothing to qualify.

Rejected alternatives: deriving the name from the call-site path yields opaque column names that
churn whenever blocks are reordered — bad for a chart being watched live; an export-name template
per local (`export: "c_series_{tube}"`) preserves today's exact names but reintroduces the name
concatenation this increment exists to remove.

Output column names therefore change: `c_series_1` becomes `tube_1_c_series`. Accepted — the
naming is now generated from a declaration instead of assembled by hand.

## 7. Schema break and migration

Settled fork: **hard break**, `SCHEMA_VERSION = 2`. There is no document-migration machinery in
the repo today — both loaders are strict equality rejects (`serialize.py:377-380`,
`convert.ts:72-73`) with zero version-conditional behaviour anywhere, so this increment builds the
first one. The only `MIGRATIONS` that exists (`db.py:10-73`) is SQLite table DDL, unrelated.

What can and cannot be migrated automatically, stated honestly:

- **Roles into the workflow: mechanical.** Studio documents already hold role names in `device:`
  and role types in the envelope, so the v1→v2 lift is a move plus a `schema_version` bump.
- **Typed group params: not migratable.** The types are precisely the information v1 never
  recorded. A v1 document using `groups` with `params`, or `for_each`, **fails to load** with a
  message naming the group or block that needs hand-typing.
- **Stale localStorage drafts are the sharp edge.** `draftStorage.ts:75-78` casts persisted JSON
  to `DocContent` after a shallow shape check, so a v1 draft would be silently accepted as v2
  content. A version guard that discards non-v2 drafts ships in the same change; without it W16's
  draft persistence quietly resurrects unloadable documents.

## 8. Blast radius

- **Engine tests:** ~42 of 77 files touch `device`/`groups`/`params`. Most churn is mechanical and
  concentrates in two shared helpers — `tests/experiment_run_helpers.py:20` and
  `tests/experiment_validate_helpers.py:11`. About 52 tests across
  `test_experiment_expand*.py`, `test_experiment_foreach_*.py`, and
  `test_experiment_validate_groups.py` need genuine semantic rewrites.
- **Webapp:** backend `test_roles.py` (11 tests) is rewritten or largely deleted with
  `substitute`/`placeholder_ids`. Frontend `paths.test.ts`, `convert.test.ts`, `docStore.test.ts`
  carry the bulk.
- **JSON documents:** ~4,400 lines across 14 files. Two of the largest fixtures are **generated**
  — `webapp/fixtures/gen_torture.py:266`, `gen_run.py:91` — so regenerate rather than hand-edit.
  The `docs/*/after/probe.json` UI-audit artifacts are disposable historical evidence, not
  migrated.
- **Docs:** there is **no schema reference document** in the repo; the schema is described only
  inside dated design specs. This increment adds `docs/workflow-schema.md` as the first
  maintained reference, and updates `docs/experiment-engine-limitations.md:437-471`, which
  documents the untyped `params`/`args` as shipped.

## 9. Decomposition — one spec, two PRs

Settled fork. Main is knowingly broken between them: Studio cannot load v2 documents until PR 2
lands. The alternative (one PR) was rejected as an unreviewably large diff.

### 9.1 PR 1 — engine

Kind system and declaration parsing; group locals with init hoisting; typed `for_each` with the
scalar shorthand removed; roles in `Workflow` with parse-ordering fix; `registry.device_type`
deleted and `lookup` re-signatured; `Occupancy`/`RunContext` role resolution; mapping injectivity;
`SCHEMA_VERSION = 2` with the v1 load-failure message; `expand.py` rewritten around typed
substitution; `validate.py` reference-kind checks; `examples/morbidostat.json` and
`morbidostat-demo-speed.json` migrated; `docs/workflow-schema.md` written.

### 9.2 PR 2 — Studio

Typed param and local editors (name + kind + `device_type`) replacing the newline-split textarea
(`Inspector.tsx:89-119`); `group_ref` form gains `as` and one **typed** editor per param — role
dropdown filtered by `device_type`, stream picker, typed value field — reusing the machinery
already present at `Inspector.tsx:379-409` and `StreamIntoPicker.tsx`; `for_each` editor with the
typed `in` grid; `roles` moved from the doc envelope into `workflow`, updating the `docStore`
dirty-check (`:139-150`) and undo `partialize` (`:414-424`) **together** — the file's own comment
at `:133-138` documents that a field round-tripping but missing from `snapshotOf` reads clean and
is silently dropped on navigate-away; `draftStorage` version guard; `roles.py` reduced to
`role_diagnostics`; fixtures regenerated.

Note `builder/files.test.ts:36-42` asserts the exported envelope key order
`doc_version, name, description, roles, workflow`. Moving `roles` breaks it by design — that test
is the intended tripwire, not collateral damage.

## 10. Testing

- **Kind checking:** one negative test per kind per position — wrong JSON type for a value kind;
  unknown role, wrong `device_type`, undeclared stream, malformed binding for reference kinds.
- **Concatenation rule:** `"od_{od}"` for a reference kind is a load error; `"tube {tube}: x"` for
  a value kind is not.
- **Typed substitution:** `{"position": "{tube}"}` with `tube: int` produces the JSON integer `1`.
- **Locals:** qualified emission; `init` hoisting order; constant-only `init` rejection; duplicate
  `as` rejection; the escaping-local case — a top-level expression reading
  `tube_1_contaminated`.
- **Injectivity:** two roles on one device is a run-start error; the same workflow with distinct
  devices runs.
- **Affinity equivalence:** a workflow whose two parallel lanes touch two roles is diagnosed
  identically whether analysed by role name or by mapped device id — the property §5.4 relies on.
- **Name rules:** param/local collision rejected; `args` missing or extra a param rejected
  per-param; a group param shadowing an enclosing `for_each` var is now diagnosed rather than
  silently shadowing (`expand.py:216-217`).
- **Migration:** a v1 document with `groups` fails to load with a message naming the group; a v1
  localStorage draft is discarded rather than loaded.
- **Behaviour preservation:** `tests/test_examples_morbidostat.py`'s 120-cycle IC50 assertion must
  hold unchanged across the migration — same leaf count, same drug-arm terms, same freshness
  guards. This is the increment's main regression oracle.
- **Preprod:** the migrated `morbidostat-demo-speed.json` on `windows_arm64_test_client`, proving
  typed roles resolve to real densitometers and valves, group-locals namespace per tube, and
  per-tube accumulators stay independent (the property Increment 7's purpose-built `step(tube)`
  run established, re-proved under the new naming).
