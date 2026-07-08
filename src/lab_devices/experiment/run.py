"""Public run facade for the executor. See design 4-exec §3, §13."""

from __future__ import annotations

from lab_devices.experiment import blocks as B
from lab_devices.experiment.workflow import Workflow


def assign_block_ids(workflow: Workflow) -> None:
    """Engine-assigned structural ids matching validator diagnostic paths (4-exec §13)."""

    def walk(blocks: list[B.Block], prefix: str) -> None:
        for i, block in enumerate(blocks):
            path = f"{prefix}[{i}]"
            block.id = path
            if isinstance(block, (B.Serial, B.Parallel)):
                walk(block.children, f"{path}.children")
            elif isinstance(block, B.Loop):
                walk(block.body, f"{path}.body")
            elif isinstance(block, B.Branch):
                walk(block.then, f"{path}.then")
                if block.else_ is not None:
                    walk(block.else_, f"{path}.else")

    walk(workflow.blocks, "blocks")
    for name, group in workflow.groups.items():
        walk(group.body, f"groups[{name!r}].body")
