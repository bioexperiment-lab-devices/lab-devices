"""Expression sublanguage: typed AST, tokenizer, parser. See design §6 and §15."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from lab_devices.experiment.durations import DURATION_PATTERN, parse_duration
from lab_devices.experiment.errors import ExpressionError

STAT_FNS = frozenset({"last", "mean", "min", "max", "count"})
_MAX_NESTING = 64


@dataclass(frozen=True)
class Const:
    value: int | float | bool | str  # str is a single-quoted string literal (design §6)


@dataclass(frozen=True)
class DurationConst:
    """A duration literal used as a value (`5min`), carrying its seconds. Typed `number<s>`
    (design 2026-07-21 §6). Distinct from `Const` so the inferencer can stamp the seconds
    unit — a bare `Const(300.0)` is unitless, a `DurationConst(300.0)` is `number<s>`."""

    seconds: float


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


Expr = Const | DurationConst | BindingRef | StatCall | UnaryOp | BinaryOp


@dataclass(frozen=True)
class Token:
    kind: str  # "NUMBER" | "DURATION" | "NAME" | "OP" | "END"
    text: str
    pos: int


_TOKEN_RE = re.compile(
    rf"\s+|(?P<DURATION>{DURATION_PATTERN})"
    r"|(?P<NUMBER>\d+(?:\.\d+)?)"
    r"|(?P<STRING>'[^']*')"  # single-quoted string literal, e.g. 'chemostat' (design §6)
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


_KEYWORDS = frozenset({"and", "or", "not", "true", "false"})
_COMPARE_OPS = frozenset({"<", "<=", ">", ">=", "==", "!="})


class _Parser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._tokens = tokenize(text)
        self._pos = 0
        self._depth = 0

    def parse(self) -> Expr:
        expr = self._or_expr()
        tok = self._peek()
        if tok.kind != "END":
            raise self._fail(tok, "unexpected trailing input")
        return expr

    def _peek(self) -> Token:
        return self._tokens[self._pos]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _fail(self, tok: Token, msg: str) -> ExpressionError:
        where = f"at position {tok.pos}" if tok.kind != "END" else "at end of input"
        shown = f" (got {tok.text!r})" if tok.text else ""
        return ExpressionError(f"{msg}{shown} {where} in {self._text!r}")

    def _match_op(self, *ops: str) -> Token | None:
        tok = self._peek()
        if tok.kind == "OP" and tok.text in ops:
            return self._advance()
        return None

    def _expect_op(self, op: str) -> None:
        if self._match_op(op) is None:
            raise self._fail(self._peek(), f"expected {op!r}")

    def _match_name(self, name: str) -> bool:
        tok = self._peek()
        if tok.kind == "NAME" and tok.text == name:
            self._advance()
            return True
        return False

    def _bump_depth(self, tok: Token) -> None:
        """Guard the recursive productions (parens, unary '-', 'not') against
        pathologically nested input; a plain recursion-depth counter is used instead
        of catching RecursionError, since which frame raises it is unreliable."""
        self._depth += 1
        if self._depth > _MAX_NESTING:
            raise self._fail(tok, f"expression too deeply nested (max {_MAX_NESTING})")

    def _or_expr(self) -> Expr:
        expr = self._and_expr()
        while self._match_name("or"):
            expr = BinaryOp("or", expr, self._and_expr())
        return expr

    def _and_expr(self) -> Expr:
        expr = self._not_expr()
        while self._match_name("and"):
            expr = BinaryOp("and", expr, self._not_expr())
        return expr

    def _not_expr(self) -> Expr:
        tok = self._peek()
        if self._match_name("not"):
            self._bump_depth(tok)
            try:
                return UnaryOp("not", self._not_expr())
            finally:
                self._depth -= 1
        return self._comparison()

    def _comparison(self) -> Expr:
        expr = self._additive()
        op_tok = self._match_op(*_COMPARE_OPS)
        if op_tok is None:
            return expr
        right = self._additive()
        trailing = self._peek()
        if trailing.kind == "OP" and trailing.text in _COMPARE_OPS:
            raise self._fail(trailing, "comparisons cannot be chained")
        return BinaryOp(op_tok.text, expr, right)

    def _additive(self) -> Expr:
        expr = self._multiplicative()
        while (tok := self._match_op("+", "-")) is not None:
            expr = BinaryOp(tok.text, expr, self._multiplicative())
        return expr

    def _multiplicative(self) -> Expr:
        expr = self._unary()
        while (tok := self._match_op("*", "/")) is not None:
            expr = BinaryOp(tok.text, expr, self._unary())
        return expr

    def _unary(self) -> Expr:
        tok = self._peek()
        if self._match_op("-") is not None:
            self._bump_depth(tok)
            try:
                return UnaryOp("-", self._unary())
            finally:
                self._depth -= 1
        return self._atom()

    def _atom(self) -> Expr:
        tok = self._advance()
        if tok.kind == "NUMBER":
            if "." not in tok.text:
                return Const(int(tok.text))
            value = float(tok.text)
            if not math.isfinite(value):
                raise self._fail(tok, "numeric literal is not finite")
            return Const(value)
        if tok.kind == "DURATION":
            return DurationConst(parse_duration(tok.text))  # a value typed number<s> (§6)
        if tok.kind == "STRING":
            return Const(tok.text[1:-1])  # strip the surrounding single quotes
        if tok.kind == "NAME":
            if tok.text == "true":
                return Const(True)
            if tok.text == "false":
                return Const(False)
            if tok.text in _KEYWORDS:
                raise self._fail(tok, f"unexpected keyword {tok.text!r}")
            nxt = self._peek()
            if nxt.kind == "OP" and nxt.text == "(":
                return self._stat_call(tok)
            return BindingRef(tok.text)
        if tok.kind == "OP" and tok.text == "(":
            self._bump_depth(tok)
            try:
                expr = self._or_expr()
            finally:
                self._depth -= 1
            self._expect_op(")")
            return expr
        raise self._fail(tok, "expected a literal, name, stat call, or '('")

    def _stat_call(self, fn_tok: Token) -> Expr:
        if fn_tok.text not in STAT_FNS:
            raise self._fail(
                fn_tok,
                f"unknown function {fn_tok.text!r}; expected one of {', '.join(sorted(STAT_FNS))}",
            )
        self._expect_op("(")
        stream_tok = self._advance()
        if stream_tok.kind != "NAME" or stream_tok.text in _KEYWORDS:
            raise self._fail(stream_tok, "expected a stream name")
        window: Window = AllWindow()
        if self._match_op(",") is not None:
            window = self._window()
        self._expect_op(")")
        return StatCall(fn=fn_tok.text, stream=stream_tok.text, window=window)

    def _window(self) -> Window:
        key = self._advance()
        if key.kind != "NAME" or key.text != "last":
            raise self._fail(key, "window must be last=<N> or last=<duration>")
        self._expect_op("=")
        val = self._advance()
        if val.kind == "NUMBER":
            if "." in val.text:
                raise self._fail(val, "window sample count must be an integer")
            n = int(val.text)
            if n <= 0:
                raise self._fail(val, "window sample count must be positive")
            return SampleWindow(n)
        if val.kind == "DURATION":
            return DurationWindow(parse_duration(val.text))
        raise self._fail(val, "window must be last=<N> or last=<duration>")


def parse_expression(text: str) -> Expr:
    """Parse an infix expression string into a typed AST; raises ExpressionError."""
    if not text.strip():
        raise ExpressionError("empty expression")
    return _Parser(text).parse()
