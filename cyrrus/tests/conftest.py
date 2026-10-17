import os

import pytest


@pytest.fixture(autouse=True)
def _cyrrus_default_db_tmp_path(tmp_path, monkeypatch):
    """Redirect the default memory database to a fresh file under tmp_path
    for every test, so no test writes into the real per-user data folder."""
    db_file = tmp_path / "cyrrus_test_memory.db"
    monkeypatch.setenv("CYRRUS_DB_PATH", str(db_file))
    yield
    monkeypatch.delenv("CYRRUS_DB_PATH", raising=False)
