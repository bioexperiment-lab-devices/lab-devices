"""Shared duration-literal parser for stat windows and interval fields. See design §6, §9."""

from __future__ import annotations

import re

_UNIT_SECONDS = {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0}
# Longest first so "min" is not half-matched as "m"; \b stops e.g. "5s2"/"5min_x".
_UNITS_ALT = "|".join(sorted(_UNIT_SECONDS, key=len, reverse=True))

# Anchorless, group-free fragment for embedding in the expression tokenizer.
DURATION_PATTERN = rf"\d+(?:\.\d+)?(?:{_UNITS_ALT})\b"

_DURATION_RE = re.compile(rf"(?P<number>\d+(?:\.\d+)?)(?P<unit>{_UNITS_ALT})")


def parse_duration(text: str) -> float:
    """Parse "30s" / "5min" / "250ms" / "1.5h" into seconds.

    Raises ValueError on anything else; callers wrap it into their own taxonomy.
    """
    match = _DURATION_RE.fullmatch(text.strip())
    if match is None:
        raise ValueError(
            f"invalid duration {text!r}: expected <number><unit> with unit ms|s|min|h"
        )
    return float(match.group("number")) * _UNIT_SECONDS[match.group("unit")]
