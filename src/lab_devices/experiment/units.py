"""Opaque symbolic units for the DSL type system (design 2026-07-21 §5).

A `Unit` is a canonical, hashable mapping from opaque symbol to integer exponent, stored as a
tuple of `(symbol, exponent)` pairs sorted by symbol with no zero exponents; the empty tuple is
unitless. The algebra is *opaque*: it has no ontology, so `per_hour` and `x_MIC` are single
symbols and the checker never knows that `per_hour` equals `1/s`. Units combine under ×/÷ and
are compared for equality; that is the whole vocabulary.
"""

from __future__ import annotations

import re

from lab_devices.experiment.errors import UnitError

Unit = tuple[tuple[str, int], ...]
UNITLESS: Unit = ()

_SYMBOL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(?:\^(-?\d+))?$")
_UNITLESS_TEXTS = frozenset({"", "unitless", "1"})


def _canon(exponents: dict[str, int]) -> Unit:
    return tuple(sorted((s, e) for s, e in exponents.items() if e != 0))


def parse_unit(text: str | None) -> Unit:
    """Parse a unit annotation. `None`/``''``/``'unitless'``/``'1'`` are unitless. A `/`
    starts the denominator (`a/b/c` == `a/(b·c)`); `*` multiplies within a group; a term may
    carry an integer exponent (`m^2`). Raises `UnitError` on anything else."""
    if text is None:
        return UNITLESS
    stripped = text.strip()
    if stripped in _UNITLESS_TEXTS:
        return UNITLESS
    exponents: dict[str, int] = {}
    for group_index, group in enumerate(stripped.split("/")):
        sign = 1 if group_index == 0 else -1
        for term in group.split("*"):
            term = term.strip()
            if term == "1":
                continue  # a bare 1 is a unitless factor, e.g. the numerator of "1/s"
            match = _SYMBOL.fullmatch(term)
            if match is None:
                raise UnitError(f"invalid unit {text!r}: bad term {term!r}")
            symbol, exp_text = match.group(1), match.group(2)
            exp = int(exp_text) if exp_text is not None else 1
            exponents[symbol] = exponents.get(symbol, 0) + sign * exp
    return _canon(exponents)


def unit_mul(a: Unit, b: Unit) -> Unit:
    exponents = dict(a)
    for symbol, exp in b:
        exponents[symbol] = exponents.get(symbol, 0) + exp
    return _canon(exponents)


def unit_div(a: Unit, b: Unit) -> Unit:
    exponents = dict(a)
    for symbol, exp in b:
        exponents[symbol] = exponents.get(symbol, 0) - exp
    return _canon(exponents)


def unit_str(u: Unit) -> str:
    """Render a unit the way an author would write it: `AU/s`, `1/s`, `unitless`."""
    if not u:
        return "unitless"
    numer = [(s, e) for s, e in u if e > 0]
    denom = [(s, -e) for s, e in u if e < 0]

    def render(terms: list[tuple[str, int]]) -> str:
        return "*".join(s if e == 1 else f"{s}^{e}" for s, e in terms)

    head = render(numer) if numer else "1"
    return head if not denom else f"{head}/{render(denom)}"
