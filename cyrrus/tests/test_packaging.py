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


def test_spec_supports_onedir_mode():
    text = SPEC.read_text(encoding="utf-8")
    assert "CYRRUS_ONEDIR" in text
    assert "COLLECT(" in text
    assert "exclude_binaries=True" in text


def test_entrypoint_uses_console_main():
    text = ENTRY.read_text(encoding="utf-8")
    assert "from cyrrus.cli import main" in text
    assert "main()" in text


def test_workflow_triggers_matrix_and_release_upload():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "release:" in text
    assert "published" in text
    assert "workflow_dispatch:" in text
    assert "3.13" in text
    assert "smoke_test.py" in text
    assert "gh release upload" in text
    assert "actions/upload-artifact" in text
    assert "actions/checkout" in text
    assert "setup-python" in text


def test_workflow_matrix_covers_all_six_confirmed_targets():
    text = WORKFLOW.read_text(encoding="utf-8")
    # Labels checked 2026-11-15 against
    # https://docs.github.com/en/actions/reference/runners/github-hosted-runners
    for runner in (
        "windows-2025",
        "windows-11-arm",
        "macos-15",
        "macos-15-intel",
        "ubuntu-24.04",
        "ubuntu-24.04-arm",
    ):
        assert runner in text, "runner label missing: %s" % runner
    for os_name in ("windows", "macos", "linux"):
        assert os_name in text
    for arch in ("x64", "arm64"):
        assert arch in text
    assert "docs.github.com/en/actions/reference/runners/github-hosted-runners" in text


def test_workflow_builds_linux_against_an_old_glibc_floor():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "manylinux_2_28" in text
    assert "manylinux_2_28_x86_64" in text
    assert "manylinux_2_28_aarch64" in text
    assert "debian:10" in text or "debian:11" in text
    assert "ldd --version" in text
    # The manylinux interpreter has no shared libpython; uv supplies one.
    assert "uv python install 3.13" in text
    assert "shared library" in text.lower()


def test_workflow_ships_windows_onedir_zip_and_tarballs_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CYRRUS_ONEDIR=1" in text
    assert "shutil.make_archive" in text
    assert "tar -czf" in text
    assert ".zip" in text
    assert ".tar.gz" in text
    # The one-file Windows exe is no longer a release asset.
    assert "cyrrus-Windows-%s.exe" not in text
    assert "cyrrus-Windows-X64.exe" not in text


def test_workflow_names_assets_with_version_os_and_arch():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.release.tag_name" in text
    assert "cyrrus-${VERSION}-" in text
    assert "windows" in text and "macos" in text and "linux" in text
    assert "x64" in text and "arm64" in text


def test_workflow_writes_one_filename_only_sha256sums_file():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "SHA256SUMS" in text
    assert "sha256sum -c SHA256SUMS" in text
    snippet = text.split("- name: Write per-asset SHA-256 line", 1)[1]
    snippet = snippet.split("- name:", 1)[0]
    # A directory prefix in the checksum line makes sha256sum -c fail.
    assert '"  " + path.name' in snippet
    assert "path.as_posix" not in snippet
    # Windows text mode would write CRLF and break sha256sum -c on Linux.
    assert 'part.write_bytes(line.encode("utf-8"))' in snippet
    assert "part.write_text" not in snippet
    assert 'cat checksum-*.txt | sort -k2 > SHA256SUMS' in text
    assert "rm checksum-*.txt" in text


def test_workflow_pr_builds_without_uploads_and_release_job_owns_write():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "paths:" in text
    for path in ("cyrrus/packaging/**", "cyrrus/scripts/**", ".github/workflows/binaries.yml"):
        assert path in text, "PR path filter missing: %s" % path
    assert "\n  build-desktop:" in text
    assert "\n  build-linux:" in text
    assert "\n  upload:" in text
    # Only the dedicated upload job gets write; the workflow and both build
    # jobs default to read.
    assert text.count("\n      contents: write\n") == 1
    build, upload = text.split("\n  upload:\n", 1)
    assert "\n      contents: write\n" not in build
    assert "\n      contents: write\n" in upload
    assert "actions/download-artifact@v4" in upload
    assert "gh release upload" in upload
    # Both staging steps and the upload job are release-only.
    assert text.count("if: github.event_name == 'release'") == 3
    assert build.count("actions/upload-artifact@v4") == 2
    assert build.count("- name: Stage workflow artifact") == 2
    assert build.count("if: github.event_name == 'release'") == 2

