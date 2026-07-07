"""Expression sublanguage: typed AST and tokenizer. See design §6 and §15."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lab_devices.experiment.durations import DURATION_PATTERN
from lab_devices.experiment.errors import ExpressionError

STAT_FNS = frozenset({"last", "mean", "min", "max", "count"})


@dataclass(frozen=True)
class Const:
    value: int | float | bool


@dataclass(frozen=True)
class BindingRef:
    name: str


@dataclass(frozen=True)
class AllWindow:
    pass


@dataclass(frozen=True)
class SampleWindow:
    n: int


@dataclass(frozen=True)
class DurationWindow:
    seconds: float


Window = AllWindow | SampleWindow | DurationWindow


@dataclass(frozen=True)
class StatCall:
    fn: str  # one of STAT_FNS
    stream: str
    window: Window


@dataclass(frozen=True)
class UnaryOp:
    op: str  # "-" | "not"
    operand: Expr


@dataclass(frozen=True)
class BinaryOp:
    op: str  # "+" "-" "*" "/" "<" "<=" ">" ">=" "==" "!=" "and" "or"
    left: Expr
    right: Expr


Expr = Const | BindingRef | StatCall | UnaryOp | BinaryOp


@dataclass(frozen=True)
class Token:
    kind: str  # "NUMBER" | "DURATION" | "NAME" | "OP" | "END"
    text: str
    pos: int


_TOKEN_RE = re.compile(
    rf"\s+|(?P<DURATION>{DURATION_PATTERN})"
    r"|(?P<NUMBER>\d+(?:\.\d+)?)"
    r"|(?P<NAME>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<OP><=|>=|==|!=|[-+*/(),<>=])"
)


def tokenize(text: str) -> list[Token]:
    """Lex an expression string; raises ExpressionError on an unexpected character."""
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise ExpressionError(f"unexpected character {text[pos]!r} at position {pos}")
        if match.lastgroup is not None:  # None == whitespace
            tokens.append(Token(match.lastgroup, match.group(), pos))
        pos = match.end()
    tokens.append(Token("END", "", len(text)))
    return tokens
