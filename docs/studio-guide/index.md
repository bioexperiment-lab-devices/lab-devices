# Experiment Studio — user guide

Experiment Studio is where you **design an experiment as a workflow** and then **run it**
on your lab's devices. You build the experiment by dragging blocks onto a canvas — no
coding, no scripts. This guide teaches you how, starting from nothing.

It is written for **lab staff**: biologists and technicians who run the bench, not
programmers. Every term is explained the first time it appears, in lab language.

## Who this guide is for

- You want to automate an experiment — dosing, reading optical density, holding a
  temperature, repeating a cycle — without writing code.
- You have Experiment Studio open in a web browser.
- You may or may not have a lab connected yet. The first quickstart needs no devices at all.

## Reading order

Work through these in order the first time. After that, keep the **block reference** and
the **cookbook** open as you build.

1. **[Overview](01-overview.md)** — what Studio is, the tabs, and how the Builder is laid out.
2. **[Quickstart](02-quickstart/index.md)** — two hands-on walkthroughs:
   - [A. Your first run, no lab needed](02-quickstart/a-no-lab.md) — learn the flow with zero hardware.
   - [B. One pump and one densitometer](02-quickstart/b-pump-densitometer.md) — a real little experiment.
3. **[Concepts](03-concepts/index.md)** — the four ideas every workflow is built from:
   [roles](03-concepts/roles.md), [streams](03-concepts/streams.md),
   [bindings & constants](03-concepts/bindings-and-constants.md), and
   [expressions](03-concepts/expressions.md).
4. **[Block reference](04-blocks/index.md)** — every block you can place, and what its
   settings mean.
5. **[Cookbook](05-cookbook/index.md)** — eight ready-to-build recipes, from simple to advanced.

## How to use this guide

- **New to Studio?** Do [Quickstart A](02-quickstart/a-no-lab.md) first — it takes a few
  minutes and shows you the whole loop: build → save → run → look at the results.
- **Building a real experiment?** Skim [Concepts](03-concepts/index.md), then keep the
  [block reference](04-blocks/index.md) open in a second tab while you work.
- **Want a head start?** Find the closest [cookbook recipe](05-cookbook/index.md) and
  rebuild it by hand — Studio is visual, so you recreate a recipe rather than copy-paste it.

> **Note:** This first edition focuses on **creating** workflows. Running and analyzing are
> covered only as far as the quickstarts need them; a full guide to the Run and Records
> tabs comes later.
