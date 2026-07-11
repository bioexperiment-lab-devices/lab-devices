"""Runtime settings resolved from environment variables. See webapp design §5."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    static_dir: Path | None = None

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("STUDIO_STATIC_DIR")
        if not raw:
            return cls(static_dir=None)
        static = Path(raw)
        return cls(static_dir=static if static.is_dir() else None)
