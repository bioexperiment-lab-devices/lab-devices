# Groups & group calls

A **group** is a reusable subroutine — a piece of workflow you build once and **call** in
several places. If you find yourself building the same "service one vial" steps three times,
a group lets you build them once and call them three times, each time pointed at a different
vial.

Groups are the advanced payoff. You can build entire experiments without them, but they keep
big workflows tidy and consistent. Neither [quickstart](../02-quickstart/index.md) uses them.

---

## The group (definition)

**What it does** — defines a named routine with its own body, its own **inputs**, and
optionally its own **private** streams and bindings.

**When to use it** — repeated logic that differs only by which device or stream it acts on
(service vial 1, vial 2, vial 3).

![](../images/block-group-scope.png)
> *Screenshot: the canvas scope switcher set to a group ("Editing: service ▾") with the
> hatched group background, and the group's Params/Locals in the Inspector.*

**How to edit one** — use the canvas **scope switcher** at the top ("Editing: Main
workflow ▾") and choose **+ New group**, or the pencil on a group in the Groups panel. The
canvas switches to that group's body (shown on a hatched background). Switch back to **Main
workflow** when done.

**Settings (a group's Inspector)**

- **Params** — the group's **inputs**, each typed: a [role](../03-concepts/roles.md), a
  [stream](../03-concepts/streams.md), a [binding](../03-concepts/bindings-and-constants.md),
  or a plain int / number / bool / string. Inside the body you refer to a param by name; the
  caller supplies the actual value.
- **Locals** — the group's **private** values that don't leak outside: a private
  `binding` (with an optional starting value) or a private `stream` (with optional units).

---

## The group call (`group_ref`)

**What it does** — runs a group at this point in the workflow, supplying its inputs.

**When to use it** — anywhere you want the group's steps to happen.

![](../images/block-group-call.png)
> *Screenshot: a group-call block selected; Inspector shows the Group picker, the "As"
> prefix field, and one Arg field per group param.*

**How to add one** — drag the group's chip from the **Groups panel** onto the canvas.

**Settings**

- **Group** — which group to call.
- **As (call-site prefix)** — a short prefix that names this call's private streams/bindings
  (e.g. `tube_1`). **Required** when the group has **Locals**, so each call's private data
  stays separate.
- **Args** — one value per group param, in the param's type: pick a role for a role param, a
  stream for a stream param, type a number for a number param, and so on.

<details><summary>Details &amp; gotchas — calling a group per vial</summary>

The real power is combining a group with **[For each](flow.md)**. Give a For each a
variable — say `tube` — and in the group call, switch an Arg to a **`{hole}`** (the small
**ƒ** toggle) and enter `{tube}`. Now each For each row calls the same group pointed at a
different vial, valve, or stream. That's how one `service(tube)` group services every vial in
the experiment. See [cookbook recipe 7](../05-cookbook/07-service-group.md).

Note: threading a For each variable into a **role/stream/binding** arg via a `{hole}` is the
supported path; plain value params (int/number/bool/string) take literals or expressions.
</details>

---

**Related:** [For each](flow.md) · [Roles](../03-concepts/roles.md) · [Cookbook: service group](../05-cookbook/07-service-group.md)
