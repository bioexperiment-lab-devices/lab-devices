# Cookbook

Eight ready-to-build recipes, ordered from simplest to most advanced. Studio is a **visual**
builder, so you can't copy-paste a recipe — instead you **rebuild it by hand** from the
steps. That's good practice: after a couple you'll be composing your own.

Each recipe has the same shape:

- **Goal** — what it does.
- **Blocks used** — the parts list.
- **Build it** — numbered steps you can follow on the canvas.
- **Finished canvas** — a screenshot of the result.
- **Why it's built this way** — the reasoning, so you can adapt it.

## The recipes

| # | Recipe | Exercises |
|---|--------|-----------|
| 1 | [Add dye, then read OD](01-add-dye-read-od.md) | Command + Measure, in sequence |
| 2 | [Hold a temperature and log it](02-hold-temperature-log.md) | Loop + Measure + Record |
| 3 | [Timed repeated dosing](03-timed-dosing.md) | Loop count + Pace |
| 4 | [Dilute only when OD is too high](04-dilute-when-high.md) | Branch + a guard expression |
| 5 | [Ask the operator for a dose](05-operator-dose.md) | Operator input → a device param |
| 6 | [Run three vials in parallel](06-parallel-vials.md) | Parallel lanes |
| 7 | [A reusable `service` group](07-service-group.md) | Groups + For each |
| 8 | [Stop safely on contamination](08-safety-guard.md) | Alarm + Abort, latching |

Recipes 1–6 use only what the [quickstarts](../02-quickstart/index.md) and
[concepts](../03-concepts/index.md) cover. Recipes 7–8 add
[groups](../04-blocks/groups.md) and [safety](../04-blocks/safety.md).

New to Studio? Do the [quickstarts](../02-quickstart/index.md) first, then start at recipe 1.
