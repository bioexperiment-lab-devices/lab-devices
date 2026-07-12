"""Runtime settings resolved from environment variables. See webapp design §5."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    static_dir: Path | None = None
    data_dir: Path = Path("/data")

    @classmethod
    def from_env(cls) -> Settings:
        raw = os.environ.get("STUDIO_STATIC_DIR")
        static = Path(raw) if raw else None
        if static is not None and not static.is_dir():
            static = None
        return cls(
            static_dir=static,
            data_dir=Path(os.environ.get("STUDIO_DATA_DIR") or "/data"),
        )
