# UI audit harness

A reusable probe + capture pair for auditing the Builder's layout. This exists because the
audit's original scripts lived in a scratchpad and were lost; the UI gets audited by hand
repeatedly, and re-deriving the harness each time makes that manual work unrepeatable.

These are **not** part of `npm test`. vitest runs in a node environment (pure functions
only — no jsdom, no component rendering), and this harness drives a real browser via
Playwright. Keep them separate.

## `probe.mjs` — the rules

`probeRules()` is a single pure function with no imports, because it is serialised and run
inside the page by `page.evaluate()`. It returns `Violation[]`, where
`Violation = {rule, selector, detail}`.

| Rule | Catches |
|---|---|
| `clipped-overflow` | Content wider than its box under a **non-scrolling** overflow — text the user cannot reach by any means. |
| `truncate-without-title` | An ellipsised label with no `title`, so the hidden text is unreadable even on hover. |
| `tiny-target` | A `<button>` rendering below the 24px hit-area floor. |
| `sibling-height-mismatch` | Sibling controls in a non-`stretch` flex row whose heights disagree by more than 1px. |

### Two exclusions carry the rule set

`clipped-overflow` skips two categories, and **both are load-bearing** — each was found by
running the probe against the real app, not by argument:

1. **Deliberate single-line ellipsis** (`white-space: nowrap` + `text-overflow: ellipsis`).
   Tailwind's `truncate` compiles to exactly that plus `overflow: hidden`, so every actively
   ellipsizing element satisfies the naive condition *by construction*. Whether that text is
   still reachable is `truncate-without-title`'s job, not this rule's.
2. **Native text controls** (`<input>` of a text-like type, `<textarea>`). Chromium reports
   `overflow-x: clip` for these, but they scroll their own value — measured on the
   Inspector's Label field holding a 138-char morbidostat label, setting `scrollLeft` moved
   it 0 → 325. `<select>` is deliberately *not* excluded: a too-long option really is
   unreachable.

Without either guard the rule can never return empty, goes permanently red, and gets
ignored — which is strictly worse than not having the rule at all.

## `probe-selftest.mjs` — why the probe is trustworthy

    npm run probe:selftest

**A probe reporting zero violations is indistinguishable from a working app.** Silence only
means something once the probe is known to break its silence. `probe-selftest.html` plants
exactly one violation per rule plus traps that must *not* fire (scrollable overflow;
truncation with a `title`; matching control heights; a long-valued text input). The runner
fails if any planted violation is missed **or** if any rule fires more than once, so a guard
that over-suppresses fails just as loudly as one that under-fires.

When changing a rule, mutate a planted case, watch that rule go red, then revert. A rule
that has never gone red proves nothing.

## `capture.mjs` — screenshots + probe run

**Prerequisite: the app must already be running. This script does not start it.** Either:

- the dev server — `npm run dev`, which proxies `/api` to the backend on `:8000`
  (see `webapp/README.md` for backend setup); pass no `--url` (defaults to `:5173`), or
- a single origin serving the built SPA — `npm run build`, then run the backend with
  `STUDIO_STATIC_DIR=../frontend/dist`, and pass `--url` for that port.

<!-- -->

    node tools/capture.mjs --out ../../.tmp/capture
    node tools/capture.mjs --out /tmp/shots --url http://127.0.0.1:8001

It drives five states — the morbidostat example loaded, a branch selected, the Inspector on
an operator-input block, the expression popover open, the torture fixture, plus a
deliberately over-long group name — at 1024×720, 1440×900 and 1920×1080, writing one PNG per
state/viewport and a single `probe.json`.

`probe.json` also records `metrics` per state (viewport width, document scroll width,
whether the page overflows the viewport). Those are **not** rules — they are the numbers the
canvas-width work is judged on.

Docs are loaded by importing the fixture JSON through the Toolbar's file input, so the run
does not depend on whatever happens to be saved in the backend already. Note that every
`branch` in `morbidostat.json` lives inside `groups.service`, which the main tree cannot
reach — the branch states switch scope first.
