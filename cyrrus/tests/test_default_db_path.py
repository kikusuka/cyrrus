import os
import sys

import pytest

from cyrrus.memory import MemoryVault
from cyrrus.sqlite_backend import SQLiteBackend, default_db_path


def test_default_db_path_env_override(tmp_path, monkeypatch):
    custom = str(tmp_path / "override" / "memory.db")
    monkeypatch.setenv("CYRRUS_DB_PATH", custom)
    assert default_db_path() == custom


@pytest.mark.skipif(sys.platform != "win32", reason="Windows uses LOCALAPPDATA")
def test_default_db_path_creates_user_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("CYRRUS_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    path = default_db_path()

    assert path == os.path.join(str(tmp_path), "cyrrus", "memory.db")
    assert os.path.isdir(os.path.join(str(tmp_path), "cyrrus"))


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses LOCALAPPDATA")
def test_default_db_path_uses_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CYRRUS_DB_PATH", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    path = default_db_path()

    assert path == os.path.join(str(tmp_path), "cyrrus", "memory.db")
    assert os.path.isdir(os.path.join(str(tmp_path), "cyrrus"))


def test_explicit_path_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("CYRRUS_DB_PATH", str(tmp_path / "env.db"))

    explicit = str(tmp_path / "explicit.db")
    backend = SQLiteBackend(db_path=explicit)
    assert backend.db_path == explicit

    memory = MemoryVault(db_path=":memory:")
    assert memory._backend.db_path == ":memory:"

    relative = "relative_memory.db"
    memory2 = MemoryVault(db_path=relative)
    assert memory2._backend.db_path == relative


def test_default_uses_env_path(tmp_path, monkeypatch):
    monkeypatch.delenv("CYRRUS_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("CYRRUS_DB_PATH", str(tmp_path / "env.db"))

    memory = MemoryVault()
    assert memory._backend.db_path == str(tmp_path / "env.db")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows uses LOCALAPPDATA")
def test_default_logs_resolved_path(caplog, tmp_path, monkeypatch):
    monkeypatch.delenv("CYRRUS_DB_PATH", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    with caplog.at_level("INFO", logger="cyrrus.sqlite_backend"):
        MemoryVault()

    resolved = os.path.abspath(os.path.join(str(tmp_path), "cyrrus", "memory.db"))
    assert any(
        rec.levelname == "INFO" and resolved in rec.getMessage()
        for rec in caplog.records
    ), caplog.records
