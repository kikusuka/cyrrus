"""Run every test in its own empty temporary working directory so any
default relative files (slides_memory.db, test_slides_memory.db, etc.)
are created in a throwaway folder instead of the project folder."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_working_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
