"""Contract checks for the standalone binary packaging and release workflow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
SPEC = ROOT / "packaging" / "cyrrus.spec"
ENTRY = ROOT / "packaging" / "entrypoint.py"
SMOKE = ROOT / "packaging" / "smoke_test.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "binaries.yml"


def test_packaging_files_exist():
    assert SPEC.is_file(), "packaging/cyrrus.spec is missing"
    assert ENTRY.is_file(), "packaging/entrypoint.py is missing"
    assert SMOKE.is_file(), "packaging/smoke_test.py is missing"
    assert WORKFLOW.is_file(), ".github/workflows/binaries.yml is missing"


def test_workflow_is_in_repo_root_for_github():
    workflow = REPO_ROOT / ".github" / "workflows" / "binaries.yml"
    assert workflow.is_file(), (
        "GitHub only runs workflows from the repository-root .github/workflows; "
        "binaries.yml must live there, not under cyrrus/."
    )
    assert not (ROOT / ".github" / "workflows" / "binaries.yml").exists()
    text = workflow.read_text(encoding="utf-8")
    assert "working-directory: cyrrus" in text
    assert "cyrrus/release-assets" in text


def test_spec_collects_all_cyrrus_submodules():
    text = SPEC.read_text(encoding="utf-8")
    assert 'collect_submodules("cyrrus")' in text
    assert "cyrrus/ui" in text or "collect_data_files" in text
    assert "EXE(" in text
    assert "a.binaries" in text and "a.datas" in text
    assert "console=True" in text


def test_entrypoint_uses_console_main():
    text = ENTRY.read_text(encoding="utf-8")
    assert "from cyrrus.cli import main" in text
    assert "main()" in text


def test_workflow_triggers_matrix_and_release_upload():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "release:" in text
    assert "published" in text
    assert "workflow_dispatch:" in text
    for runner in ("windows-latest", "macos-latest", "ubuntu-latest"):
        assert runner in text
    assert "3.13" in text
    assert "smoke_test.py" in text
    assert "hashlib.sha256" in text
    assert "gh release upload" in text
    assert "actions/upload-artifact" in text
    assert "actions/checkout" in text
    assert "setup-python" in text
