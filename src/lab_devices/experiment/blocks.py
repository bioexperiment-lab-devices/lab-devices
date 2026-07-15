"""Typed AST for experiment workflows. See design §5."""

from __future__ import annotations

from dataclasses import dataclass, field

# A scalar slot: a literal, or an infix-expression string (parsed in Increment 2).
ValueExpr = str | int | float | bool

ON_ERROR_VALUES = ("fail", "continue")


@dataclass(frozen=True)
class Retry:
    """Retry policy for one action block (design 2026-07-14 §2.1)."""

    attempts: int  # TOTAL tries, not retries-after-the-first
    backoff: str = "1s"
    allow_repeat: bool = False  # explicit opt-in to retry a non-idempotent verb (§4)


@dataclass(kw_only=True)
class BlockBase:
    id: str | None = None  # engine-assigned at load; never serialized (design §5, 4-exec §13)
    label: str | None = None
    gap_after: str | None = None  # serial: end-of-this -> start-of-next
    start_offset: str | None = None  # parallel: container-start -> this-start
    retry: Retry | None = None  # command/measure only (2026-07-14 §2.1)
    on_error: str = "fail"  # one of ON_ERROR_VALUES (2026-07-14 §2.2)


@dataclass(kw_only=True)
class Command(BlockBase):
    device: str
    verb: str
    params: dict[str, ValueExpr] = field(default_factory=dict)


@dataclass(kw_only=True)
class Measure(BlockBase):
    device: str
    verb: str
    into: str
    params: dict[str, ValueExpr] = field(default_factory=dict)


@dataclass(kw_only=True)
class OperatorInput(BlockBase):
    name: str
    type: str
    prompt: str | None = None
    min: float | None = None
    max: float | None = None
    choices: list[str] | None = None


@dataclass(kw_only=True)
class Wait(BlockBase):
    duration: str


@dataclass(kw_only=True)
class Serial(BlockBase):
    children: list[Block] = field(default_factory=list)


@dataclass(kw_only=True)
class Parallel(BlockBase):
    children: list[Block] = field(default_factory=list)


@dataclass(kw_only=True)
class Loop(BlockBase):
    body: list[Block] = field(default_factory=list)
    count: int | None = None
    pace: str | None = None
    until: str | None = None
    check: str = "after"


@dataclass(kw_only=True)
class Branch(BlockBase):
    if_: str
    then: list[Block] = field(default_factory=list)
    else_: list[Block] | None = None


@dataclass(kw_only=True)
class GroupRef(BlockBase):
    name: str
    args: dict[str, ValueExpr] = field(default_factory=dict)


@dataclass(kw_only=True)
class Compute(BlockBase):
    into: str
    value: ValueExpr  # scalar bound into RunState.bindings (number or boolean)


@dataclass(kw_only=True)
class Record(BlockBase):
    into: str
    value: ValueExpr  # numeric sample appended to a declared stream


@dataclass(kw_only=True)
class ForEach(BlockBase):
    body: list[Block] = field(default_factory=list)
    var: str | None = None
    items: list[ValueExpr | dict[str, ValueExpr]] = field(default_factory=list)


Block = (
    Command
    | Measure
    | OperatorInput
    | Wait
    | Serial
    | Parallel
    | Loop
    | Branch
    | GroupRef
    | Compute
    | Record
    | ForEach
)
