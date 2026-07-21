# Workflow schema reference

**Schema version: 2.** This is the maintained reference for the workflow JSON the experiment
engine loads. Design specs under `docs/superpowers/specs/` are frozen records of *decisions*;
this document describes the format *as it is now*. When the two disagree, this one is wrong and
should be fixed — every ` ```json ` block below is loaded through `workflow_from_dict` and
`expand_dict` by `tests/test_docs_workflow_schema.py`, so a stale example fails the suite.

Editing convention: ` ```json ` fences are complete workflow documents and are executed by that
test; ` ```jsonc ` fences are fragments and must still be self-contained JSON objects; anything
else is prose.

## 1. Document shape

A workflow is a single JSON object. Only `schema_version` and `blocks` are required.

```json
{
  "schema_version": 2,
  "metadata": {
    "name": "Minimal",
    "author": "lab-devices",
    "description": "The smallest document the loader accepts."
  },
  "persistence": {"default": "in_memory", "format": "jsonl"},
  "defaults": {"retry": {"attempts": 3, "backoff": "2s"}},
  "roles": {"od_meter_1": {"type": "densitometer"}},
  "streams": {"od_1": {"units": "AU"}},
  "blocks": [
    {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}}
  ]
}
```

| key | required | meaning |
|---|---|---|
| `schema_version` | yes | must be `2`; see §7 |
| `metadata` | no | `name`, `author`, `description` — free text |
| `persistence` | no | `default`: `"in_memory"` \| `"disk"`; `format`: `"jsonl"` \| `"csv"` |
| `defaults` | no | `retry` only — a blanket `on_error` would make a missed injection silently survivable |
| `roles` | no | named instrument slots (§5) |
| `streams` | no | declared sample series; a block may only write a declared stream |
| `groups` | no | reusable, parametrized block bodies (§3) |
| `blocks` | yes | the ordered tree the run executes |

`workflow_to_dict` emits these keys in exactly the order above (omitting any optional section
that has no content), so a load/save round-trip of a hand-written document that follows this
order and omits empty optional sections is a no-op diff. The example above round-trips exactly
for this reason: it has no `groups`, so it does not write `"groups": {}`.

## 2. Block grammar

A block is a JSON object with **exactly one** type key plus optional block-level keys. The type
keys are:

| type key | body | what it does |
|---|---|---|
| `command` | `device`, `verb`, `params` | one device verb, no result recorded |
| `measure` | `device`, `verb`, `into` | one device verb whose reading appends to a stream |
| `compute` | `into`, `value` | evaluates an expression into a binding |
| `record` | `into`, `value` | appends a computed value to a declared stream |
| `operator_input` | `name`, `type`, `prompt`, `min`, `max`, `choices` | asks the operator; binds the answer |
| `wait` | `duration` | sleeps |
| `serial` | `children` | runs children in order |
| `parallel` | `children` | runs children concurrently, one lane each |
| `loop` | `body`, `count` \| `until`+`check`, `pace` | repeats `body`; `pace` is a floor, not a deadline |
| `branch` | `if`, `then`, `else` | conditional |
| `abort` | `if`, `message` | stops the whole run (`AbortSignalError`, status `"aborted"`) |
| `alarm` | `if`, `message` | flags and continues (`RunReport.alarms`) |
| `for_each` | `vars`, `in`, `body` | splicing macro over a typed table (§4) |
| `group_ref` | `name`, `as`, `args` | inlines a group body as one `serial` (§3) |

`loop` requires **exactly one** of `count` (an integer) or `until` (a boolean expression,
re-checked each iteration per `check: "before"` or `"after"`, default `"after"`).

Block-level keys, legal on any block alongside its type key:
`label`, `gap_after`, `start_offset`, `retry`, `on_error`. Two exceptions:

- `retry` is only semantically valid on `command`/`measure` — parseable on any block, but
  flagged by `validate()` everywhere else.
- `for_each` may not carry `retry`, `on_error`, `gap_after`, or `start_offset` at all — put
  them on the body blocks instead. Unlike the `retry` case above, this one is enforced by
  `expand_dict` itself as a hard load error, not just a `validate()` diagnostic, because those
  four keys would otherwise apply once to the macro instead of per iteration to what it splices.

```json
{
  "schema_version": 2,
  "roles": {"drug_pump": {"type": "pump"}, "od_meter_1": {"type": "densitometer"}},
  "streams": {"od_1": {"units": "AU"}},
  "blocks": [
    {
      "serial": {
        "children": [
          {"operator_input": {"name": "dose_ml", "type": "float", "prompt": "Dose (ml)?",
                              "min": 0.1, "max": 5.0}},
          {"compute": {"into": "total_ml", "value": "0"}, "label": "seed the accumulator"},
          {
            "loop": {
              "body": [
                {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"},
                 "on_error": "continue",
                 "label": "a dropped read costs one sample, not the run"},
                {
                  "branch": {
                    "if": "count(od_1, last=90s) > 0 and last(od_1) > 0.15",
                    "then": [
                      {"command": {"device": "drug_pump", "verb": "dispense",
                                   "params": {"volume_ml": "dose_ml", "speed_ml_min": 6.0,
                                              "direction": "forward"}}},
                      {"compute": {"into": "total_ml", "value": "total_ml + dose_ml"}}
                    ]
                  }
                },
                {"alarm": {"if": "total_ml > 20", "message": "dose budget exceeded"}}
              ],
              "count": 10,
              "pace": "60s"
            }
          }
        ]
      },
      "label": "a small controller"
    }
  ]
}
```

`retry` on a block (or `defaults.retry` for the document) is only ever applied to a verb the
registry marks retry-safe: `dispense` takes a *relative* volume, so a retried dispense would
double-dose, and no default will retry it.

## 3. Groups: typed params and locals

### 3.1 The kind system

One kind set is used identically by group params, group locals, and `for_each` vars.

| kind | the argument is | checked before expansion |
|---|---|---|
| `int`, `number`, `bool`, `string` | a literal value | the JSON type matches the kind |
| `role` | a declared role name | the role exists and `roles[r].type == device_type` |
| `stream` | a declared stream name | the stream exists in `streams` |
| `binding` | a binding name | identifier shape; must not collide with a stream |

`int`/`number`/`bool`/`string` are **value kinds**; `role`/`stream`/`binding` are **reference
kinds**. `device_type` is required on `role` and forbidden on every other kind, and must name a
device type the verb registry knows (`pump`, `valve`, `densitometer`).

`binding` is deliberately the weakest reference: bindings have no declaration section — they are
created implicitly by their writer (`compute.into`, `operator_input.name`) — so a `binding`
argument can be checked for shape and for stream-disjointness, not for existence. Existence
stays the job of the path-sensitive analysis, which reports *"may be read before it is
written"*. Group locals are how you get a **declared** binding.

### 3.2 `params`

`params` is an **ordered list of objects** — the order is the authoring order, and it is the
order Studio renders.

```jsonc
{
  "params": [
    {"name": "tube",  "kind": "int"},
    {"name": "od",    "kind": "stream"},
    {"name": "meter", "kind": "role", "device_type": "densitometer"}
  ]
}
```

`group_ref.args` must supply **exactly** the declared names — no missing, no extra — and each
argument is checked against its declared kind before anything is substituted.

### 3.3 `locals`

A group declares the streams and bindings it **owns**. Without this, typing gets verbose fast:
the morbidostat's `service` group touches eight stream/binding names in total. One (`od`) is
already a `stream` param; without `locals`, the other seven — `c`, `contaminated`, `alarmed`,
`r`, `od_high`, `c_series`, `r_series` — would each need to become an explicit reference param,
threaded through every call site.

```jsonc
{
  "locals": {
    "c":            {"kind": "binding", "init": "0"},
    "contaminated": {"kind": "binding", "init": "false"},
    "r":            {"kind": "binding"},
    "c_series":     {"kind": "stream", "units": "x_MIC"},
    "r_series":     {"kind": "stream", "units": "per_hour", "persistence": "disk"}
  }
}
```

- Only `stream` and `binding` are legal in `locals`. A local *value* would just be a constant,
  which `compute` already expresses.
- A `stream` local may carry `units` and `persistence`; the expander copies them into the
  emitted declaration.
- A `binding` local may carry `init`, an expression evaluated once. The expander hoists one
  `compute` per initialized local to the **front of `blocks`**, in deterministic expansion
  order.
- **`init` must be a constant expression**: literals and operators over them. No `stat` calls,
  no stream references, no binding references. A hoisted initializer runs before every other
  block in the document, so any data dependency it could express is guaranteed unwritten at that
  point; restricting `init` makes the hoist total and order-insensitive.
- Param names and local names share one namespace and may not collide. Both must match the
  identifier shape and must not be reserved names (`and`, `or`, `not`, `true`, `false`).

**Locals are namespaced, not private.** They expand to ordinary top-level streams and bindings
under a qualified name, and any expression anywhere in the document may read that name. This is
required, not merely tolerated: `examples/morbidostat.json` aborts the whole run on
`tube_1_contaminated and tube_2_contaminated and tube_3_contaminated`, reading three per-tube
latches from outside the group that owns them. The point of locals is to stop the *author* doing
name surgery, not to hide the resulting names from the rest of the document.

### 3.4 Holes: everything is `{name}`

Inside a group body, params and locals are referenced as `{name}` in **every** position,
including inside expression strings. There is no bare-name-in-expressions special case.
Uniformity is what makes the post-expansion residual-hole scan a complete check: any name that
is neither substituted nor a real identifier is caught by construction.

```jsonc
{
  "compute": {
    "into": "{od_high}",
    "value": "count({od}, last=11min) > 0 and mean({od}, last=11min) > 2.0"
  }
}
```

Concatenation splits by kind:

- **Reference kinds** may not be concatenated with adjacent identifier text. In a name field
  (`device`, `into`, an `args` value) the hole must be the entire string: `"{od}"` is legal,
  `"od_{od}"` and `"{od}_raw"` are load errors. In an expression the hole must be a complete
  `NAME` token: `"count({od}, last=5)"` is legal, `"count(od_{od})"` is not. This is the rule
  that guarantees a reference resolves to a name that provably exists in a declaration.
- **Value kinds** interpolate anywhere: `"position": "{tube}"` and
  `"label": "tube {tube}: service"` are both fine.

A **whole-string hole of a value kind substitutes as a typed JSON value**, not a string. With
`tube: int = 1`, `{"position": "{tube}"}` yields `{"position": 1}` — the JSON integer. Embedded
holes stringify, because the result is by definition a larger string.

### 3.5 `group_ref` and `as`

```jsonc
{
  "group_ref": {
    "name": "service",
    "as": "tube_{tube}",
    "args": {"tube": "{tube}", "od": "{od}"}
  }
}
```

`as` is the instance name. Locals qualify as `{as}_{local}` — `tube_1_c`, `tube_1_c_series`.

- `as` is **required** when the group declares locals, optional otherwise.
- `as` is an ordinary string field, so value-kind holes interpolate into it. That is how one
  call site inside a `for_each` produces three distinct instances.
- `as` must expand to a valid identifier, so qualified names are legal expression tokens.
- A duplicate `as` after expansion is a load error: instance names are the identity of the
  emitted streams and bindings, and two instances sharing one would silently merge two tubes'
  data.

Here is the whole mechanism in one loadable document — a group with both param kinds and both
local kinds, called twice:

```json
{
  "schema_version": 2,
  "roles": {
    "od_meter_1": {"type": "densitometer"},
    "od_meter_2": {"type": "densitometer"},
    "drug_pump": {"type": "pump"},
    "drug_valve": {"type": "valve"}
  },
  "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}},
  "groups": {
    "service": {
      "params": [
        {"name": "tube", "kind": "int"},
        {"name": "od", "kind": "stream"}
      ],
      "locals": {
        "c": {"kind": "binding", "init": "0"},
        "c_series": {"kind": "stream", "units": "x_MIC"}
      },
      "body": [
        {"command": {"device": "drug_valve", "verb": "set_position",
                     "params": {"position": "{tube}", "rotation": "direct"}},
         "label": "drug line -> tube {tube}"},
        {"command": {"device": "drug_pump", "verb": "dispense",
                     "params": {"volume_ml": "1.0", "speed_ml_min": 6.0,
                                "direction": "forward"}}},
        {"compute": {"into": "{c}", "value": "{c} * 12/13 + 10 * 1/13"},
         "label": "tube {tube}: concentration recursion"},
        {"record": {"into": "{c_series}", "value": "{c}"}},
        {"alarm": {"if": "count({od}, last=90s) > 0 and mean({od}, last=90s) > 2.0",
                   "message": "tube {tube}: OD stuck high"}}
      ]
    }
  },
  "blocks": [
    {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}},
    {"measure": {"device": "od_meter_2", "verb": "measure", "into": "od_2"}},
    {"group_ref": {"name": "service", "as": "tube_1",
                   "args": {"tube": 1, "od": "od_1"}}},
    {"group_ref": {"name": "service", "as": "tube_2",
                   "args": {"tube": 2, "od": "od_2"}}},
    {"abort": {"if": "tube_1_c > 9.9 and tube_2_c > 9.9",
               "message": "both tubes maxed out"}}
  ]
}
```

After expansion this document begins with two hoisted `compute` blocks — `tube_1_c = 0` and
`tube_2_c = 0` — and declares two extra streams, `tube_1_c_series` and `tube_2_c_series`, both
with `units: "x_MIC"`. `position` in each `set_position` command becomes the JSON integer `1` or
`2`, not the string `"1"`/`"2"` (§3.4's typed-substitution rule). The final `abort` reads two
group locals from top level, which is the escaping-local case §3.3 permits on purpose.

## 4. `for_each`: a typed table

`for_each` vars take the same declarations as group params, and `in` is a table of typed rows.
It is a **splicing** macro: it copies `body` once per row and splices the copies into the
*enclosing* block list, so `len(in) x len(body)` siblings appear where the `for_each` was. As
the sole child of a `parallel` that means N concurrent lanes; inside a `serial`, N steps.

```jsonc
{
  "for_each": {
    "vars": [
      {"name": "tube",  "kind": "int"},
      {"name": "meter", "kind": "role", "device_type": "densitometer"},
      {"name": "od",    "kind": "stream"}
    ],
    "in": [
      {"tube": 1, "meter": "od_meter_1", "od": "od_1"},
      {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
      {"tube": 3, "meter": "od_meter_3", "od": "od_3"}
    ],
    "body": [
      {"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}
    ]
  }
}
```

Every row must supply **exactly** the declared var names — a missing or extra key is a load
error. The `role<densitometer>` column is the point of the shape: `od_meter_{tube}` was string
surgery whose result was merely *hoped* to be a role name; a typed column is checked against the
role declarations before a single copy is made.

> **The scalar shorthand is removed.** `{"for_each": {"var": "tube", "in": [1, 2, 3], "body": …}}`
> no longer loads. It cannot carry a kind, and keeping it would leave the untyped path alive
> next to the typed one.

Substitution is order-independent: a hole not in the running substitution's own environment
passes through untouched rather than erroring, which is what lets a parametrized group body
contain a nested `for_each`, and vice versa. The residual-hole scan after all expansion is the
backstop. A group param that shadows an enclosing `for_each` var is now diagnosed rather than
silently shadowing.

```json
{
  "schema_version": 2,
  "roles": {
    "od_meter_1": {"type": "densitometer"},
    "od_meter_2": {"type": "densitometer"},
    "od_meter_3": {"type": "densitometer"}
  },
  "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}, "od_3": {"units": "AU"}},
  "blocks": [
    {
      "parallel": {
        "children": [
          {
            "for_each": {
              "vars": [
                {"name": "tube", "kind": "int"},
                {"name": "meter", "kind": "role", "device_type": "densitometer"},
                {"name": "od", "kind": "stream"}
              ],
              "in": [
                {"tube": 1, "meter": "od_meter_1", "od": "od_1"},
                {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
                {"tube": 3, "meter": "od_meter_3", "od": "od_3"}
              ],
              "body": [
                {"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"},
                 "label": "tube {tube} OD",
                 "on_error": "continue"}
              ]
            }
          }
        ]
      },
      "label": "read all three tubes at once"
    }
  ]
}
```

## 5. Roles

A role is a named instrument slot. **`device` fields hold role names, end to end** — through
load, validation, expansion, and execution.

```json
{
  "schema_version": 2,
  "roles": {
    "od_meter_1": {"type": "densitometer"},
    "medium_pump": {"type": "pump", "device": "pump_2"}
  },
  "streams": {"od_1": {"units": "AU"}},
  "blocks": [
    {"command": {"device": "medium_pump", "verb": "dispense",
                 "params": {"volume_ml": 1.0, "speed_ml_min": 6.0, "direction": "forward"}}},
    {"measure": {"device": "od_meter_1", "verb": "measure", "into": "od_1"}}
  ]
}
```

- `type` must be a device type the verb registry knows. It is what every *type* decision reads:
  which verbs exist, which are retry-safe, which open a mode, which the finalizer sweeps.
- `device` is optional and binds the role directly. Supply it for a fixed rig so a standalone
  user of the published `bioexperiment-lab-devices` package need not pass a mapping; leave it
  out when a UI supplies the mapping per run (`RunOptions.role_mapping`, which overrides a
  role's own `device` when both are present).
- Every role must be bound at run start, by `device` or by the mapping, or the run fails to
  start.
- **The mapping must be injective.** Two roles resolving to one device id is an error, not a
  warning. A role denotes a distinct physical instrument, and the static affinity and
  mode-lifetime analyses intersect footprints by name: injectivity is what makes analysis over
  role names provably equivalent to analysis over device ids. Without it, two aliased roles pass
  every static check and then collide mid-run on one `(device, channel)` slot — an
  `InvariantViolationError` that is neither retried nor tolerated.

Exactly one place resolves a role to a physical id: `RunContext.device(role)`, at the wire
boundary. Locks, occupancy slots, and every event payload key on the **role name**, which is
what the author wrote and what a diagnostic should say. The role→device mapping is recorded once
on `RunReport.role_devices`.

```jsonc
{
  "role_devices": {
    "od_meter_1": "densitometer_1",
    "medium_pump": "pump_2"
  }
}
```

## 6. Expressions, briefly

Expression strings appear in `branch.if`, `abort.if`, `alarm.if`, `compute.value`,
`record.value`, and in any device param slot. They evaluate numbers and booleans over bindings
and over stream statistics: `last(s)`, `count(s)`, `mean(s)`, each optionally windowed by
`last=N` (the last N **samples**) or `last=<duration>` (a **time** window, e.g. `last=11min`).
The full stat function set (`last`, `mean`, `min`, `max`, `count`) and its known gaps (no scalar
math functions such as `ln`/`abs`) are catalogued in limitation #2 of
[`experiment-engine-limitations.md`](experiment-engine-limitations.md).

The two windows are not interchangeable, and the difference is load-bearing. A sample window
over an append-only stream always returns N values, reaching back across cycle boundaries if it
must. A duration window can be **empty**, which is why a guard like `count(s, last=11min) > 0`
proves a sample landed *recently* where `count(s) > 0` only proves one landed *ever* — the
latter latches true forever and can leave a controller running open-loop on a dead sensor. There
is no clock primitive and no way to derive a window from an enclosing loop's `pace`, so this
coupling is manual and unchecked; see limitation #8 in
[`experiment-engine-limitations.md`](experiment-engine-limitations.md).

## 7. Schema version 2 — what broke, and what to do

`schema_version` must be `2`. A version-1 document is rejected at load with:

```text
unsupported schema_version 1; expected 2. Workflows using groups or for_each cannot be
migrated automatically: their param types were never recorded in v1
(design 2026-07-20 §7)
```

This is a deliberate hard break rather than a migration shim, and the message says why: the
types are precisely the information v1 never wrote down.

### 7.1 What v1 looked like

```jsonc
{
  "schema_version": 1,
  "groups": {"service": {"params": ["tube"], "body": []}},
  "blocks": [
    {"for_each": {"var": "tube", "in": [1, 2, 3],
                  "body": [{"group_ref": {"name": "service",
                                          "args": {"tube": "{tube}"}}}]}}
  ]
}
```

`params: ["tube"]` was a bare textual macro. In `examples/morbidostat.json` that single `tube`
hole was simultaneously a stream-name suffix (`od_{tube}`), a binding-name suffix (`c_{tube}`),
an `int` verb param (`position: "{tube}"`), and a device-role suffix (`od_meter_{tube}`) — four
distinct things behind one untyped hole, and nothing checkable until after expansion.

### 7.2 Migrating by hand

1. **`schema_version`: 1 → 2.**
2. **Move `roles` into the workflow.** If your document came from Experiment Studio, its
   envelope held `roles` next to `workflow`; move that object inside `workflow`, between
   `defaults` and `streams`. This step is purely mechanical.
3. **Type every group param.** `"params": ["tube"]` becomes a list of objects. Decide, per hole,
   which of the four things it was. A hole used as `position: "{tube}"` is `int`; a hole used as
   `od_{tube}` was a stream reference and should become a `stream` param (or a local, per step
   4); a hole used as `od_meter_{tube}` becomes a `role` param with a `device_type`.
4. **Turn name surgery into locals.** Any binding or stream the group *creates* — `c_{tube}`,
   `contaminated_{tube}`, `c_series_{tube}` — becomes a local, and its hand-written top-level
   `streams` declaration is deleted. Any stream the group only *reads* stays a top-level
   declaration and becomes a `stream` param.
5. **Fold accumulator seeds into `init`.** A `for_each` of `compute` blocks placed before the
   main loop purely to seed accumulators is deleted; put the constant in `locals.<name>.init`
   and let the expander hoist it. If the seed was not a constant, it was reading data that had
   not been written yet — fix that first.
6. **Add `as` to every `group_ref`** that calls a group with locals, and expect names to change:
   `c_series_1` becomes `tube_1_c_series`. Update anything downstream that reads those columns.
7. **Rewrite `for_each` to `vars` + row objects.** The scalar `"var"`/`"in": [1, 2, 3]`
   shorthand is gone.
8. **Make every reference a whole hole**, including inside expressions: `c_{tube}` → `{c}`,
   `mean(od_{tube}, last=5)` → `mean({od}, last=5)`.

Applying all eight steps to the v1 snippet above — typing `tube` as `int`, adding a
`role<densitometer>` var for the meter, and a `stream` var for the reading — produces a document
that loads and expands under schema 2:

```json
{
  "schema_version": 2,
  "roles": {
    "od_meter_1": {"type": "densitometer"},
    "od_meter_2": {"type": "densitometer"},
    "od_meter_3": {"type": "densitometer"}
  },
  "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}, "od_3": {"units": "AU"}},
  "groups": {
    "service": {
      "params": [
        {"name": "tube",  "kind": "int"},
        {"name": "meter", "kind": "role", "device_type": "densitometer"},
        {"name": "od",    "kind": "stream"}
      ],
      "body": [
        {"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"},
         "label": "tube {tube} OD"}
      ]
    }
  },
  "blocks": [
    {
      "for_each": {
        "vars": [
          {"name": "tube",  "kind": "int"},
          {"name": "meter", "kind": "role", "device_type": "densitometer"},
          {"name": "od",    "kind": "stream"}
        ],
        "in": [
          {"tube": 1, "meter": "od_meter_1", "od": "od_1"},
          {"tube": 2, "meter": "od_meter_2", "od": "od_2"},
          {"tube": 3, "meter": "od_meter_3", "od": "od_3"}
        ],
        "body": [
          {"group_ref": {"name": "service",
                         "args": {"tube": "{tube}", "meter": "{meter}", "od": "{od}"}}}
        ]
      }
    }
  ]
}
```

`examples/morbidostat.json` is the worked example of all eight steps on the real, larger
document — one `service` group with locals rather than the empty-bodied stand-in above.

### 7.3 Stale drafts

Experiment Studio persists an in-progress document to `localStorage`. A draft saved under v1 is
discarded on load rather than restored, because a shallow shape check cannot tell a v1 body from
a v2 one and would otherwise silently resurrect a document that no longer loads.
