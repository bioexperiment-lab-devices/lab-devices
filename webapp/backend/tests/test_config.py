"""Settings.from_env coverage (W2 carry-forward)."""

from pathlib import Path

import pytest

from experiment_studio.config import Settings


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIO_STATIC_DIR", raising=False)
    monkeypatch.delenv("STUDIO_DATA_DIR", raising=False)
    settings = Settings.from_env()
    assert settings.static_dir is None
    assert settings.data_dir == Path("/data")


def test_from_env_reads_vars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    monkeypatch.setenv("STUDIO_STATIC_DIR", str(static))
    monkeypatch.setenv("STUDIO_DATA_DIR", str(tmp_path / "data"))
    settings = Settings.from_env()
    assert settings.static_dir == static
    assert settings.data_dir == tmp_path / "data"


def test_from_env_nulls_missing_static_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("STUDIO_STATIC_DIR", str(tmp_path / "absent"))
    assert Settings.from_env().static_dir is None
