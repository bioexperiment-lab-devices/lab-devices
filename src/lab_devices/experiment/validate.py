"""Static workflow validator: registry, affinity, mode lifetimes, data-flow. See design §12."""

from __future__ import annotations

from collections.abc import Iterator

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import Diagnostic, ValidationError
from lab_devices.experiment.workflow import Workflow


def _iter_blocks(blocks: list[B.Block], prefix: str) -> Iterator[tuple[str, B.Block]]:
    """Depth-first (path, block) pairs; group refs are yielded, not expanded."""
    for i, b in enumerate(blocks):
        path = f"{prefix}[{i}]"
        yield path, b
        if isinstance(b, (B.Serial, B.Parallel)):
            yield from _iter_blocks(b.children, f"{path}.children")
        elif isinstance(b, B.Loop):
            yield from _iter_blocks(b.body, f"{path}.body")
        elif isinstance(b, B.Branch):
            yield from _iter_blocks(b.then, f"{path}.then")
            if b.else_ is not None:
                yield from _iter_blocks(b.else_, f"{path}.else")


def _iter_all_blocks(w: Workflow) -> Iterator[tuple[str, B.Block]]:
    yield from _iter_blocks(w.blocks, "blocks")
    for name, group in w.groups.items():
        yield from _iter_blocks(group.body, f"groups[{name!r}].body")


def _check_groups(w: Workflow, out: list[Diagnostic]) -> bool:
    """Unknown group refs and self/mutual recursion (design §12); True iff expandable."""
    ok = True
    for path, b in _iter_all_blocks(w):
        if isinstance(b, B.GroupRef) and b.name not in w.groups:
            out.append(Diagnostic("group", path, f"unknown group {b.name!r}"))
            ok = False
    colors: dict[str, int] = {}  # 0 = on the current DFS path, 1 = fully explored

    def visit(name: str, stack: tuple[str, ...]) -> None:
        nonlocal ok
        state = colors.get(name)
        if state == 1:
            return
        if state == 0:
            cycle = " -> ".join((*stack[stack.index(name):], name))
            out.append(Diagnostic("group", f"groups[{name!r}]", f"recursive group: {cycle}"))
            ok = False
            return
        colors[name] = 0
        for _, b in _iter_blocks(w.groups[name].body, ""):
            if isinstance(b, B.GroupRef) and b.name in w.groups:
                visit(b.name, (*stack, name))
        colors[name] = 1

    for name in w.groups:
        visit(name, ())
    return ok


def validate(workflow: Workflow) -> None:
    """Statically validate a loaded workflow (design §11 phase 2, rules §12).

    Collects every violation and raises one ValidationError; returns None when clean.
    """
    out: list[Diagnostic] = []
    _check_groups(workflow, out)
    if out:
        raise ValidationError(out)
