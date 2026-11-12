"""Distribution checks: PATH-aware doctor, setup hint, and ``-m cyrrus``.

These tests are deliberately OS-agnostic: the Windows and Linux branches of
the PATH guidance are exercised by monkeypatching ``shutil.which`` and
``sysconfig.get_path`` instead of relying on the host OS.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import cyrrus
from cyrrus.setup import run_setup
from cyrrus.tools import doctor
from cyrrus.ui.caps import COLOR_NONE, Caps
from cyrrus.ui.widgets import UI


def _config(tmp_path):
    return {
        "schema_version": 1,
        "provider": {},
        "memory": {"db_path": str(tmp_path / "cyrrus.db")},
        "context": {"slides_path": str(tmp_path / "slides.json")},
        "gateway": {},
        "ui": {},
    }


def _check(result):
    return next(check for check in result["checks"] if check["name"] == "command_on_path")


def _patch_doctor_dependencies(monkeypatch):
    monkeypatch.setattr("cyrrus.tools.detect_services", lambda timeout=1.0: {})


def test_command_on_path_ok_when_which_finds_it(tmp_path, monkeypatch):
    _patch_doctor_dependencies(monkeypatch)
    found = r"C:\Users\me\AppData\Roaming\Python\Python313\Scripts\cyrrus.exe"
    monkeypatch.setattr("cyrrus.tools.shutil.which", lambda name: found)

    check = _check(doctor(_config(tmp_path)))

    assert check["status"] == "ok"
    assert found in check["message"]


def test_command_on_path_windows_user_install_shows_powershell_fix(tmp_path, monkeypatch):
    _patch_doctor_dependencies(monkeypatch)
    scripts = r"C:\Users\me\AppData\Roaming\Python\Python313\Scripts"
    schemes = []

    def fake_get_path(name, scheme=None):
        schemes.append((name, scheme))
        if name == "scripts" and scheme == "nt_user":
            return scripts
        return None

    monkeypatch.setattr("cyrrus.tools.shutil.which", lambda name: None)
    monkeypatch.setattr("cyrrus.tools.sys.platform", "win32")
    monkeypatch.setattr("cyrrus.tools.sysconfig.get_path", fake_get_path)
    before = os.environ.get("PATH")

    check = _check(doctor(_config(tmp_path)))
    message = check["message"]

    assert check["status"] == "warning"
    assert ("scripts", "nt_user") in schemes
    assert scripts in message
    assert "python -m cyrrus" in message
    assert "[Environment]::SetEnvironmentVariable" in message
    assert "'User'" in message
    assert "uv tool install" in message
    assert "pipx install" in message
    assert "setx" not in message.lower()
    assert os.environ.get("PATH") == before  # the check must not modify anything


def test_command_on_path_linux_user_install_shows_export_fix(tmp_path, monkeypatch):
    _patch_doctor_dependencies(monkeypatch)
    scripts = "/home/me/.local/bin"
    schemes = []

    def fake_get_path(name, scheme=None):
        schemes.append((name, scheme))
        if name == "scripts" and scheme == "posix_user":
            return scripts
        return None

    monkeypatch.setattr("cyrrus.tools.shutil.which", lambda name: None)
    monkeypatch.setattr("cyrrus.tools.sys.platform", "linux")
    monkeypatch.setattr("cyrrus.tools.sysconfig.get_path", fake_get_path)

    check = _check(doctor(_config(tmp_path)))
    message = check["message"]

    assert check["status"] == "warning"
    assert ("scripts", "posix_user") in schemes
    assert scripts in message
    assert "python -m cyrrus" in message
    assert "export PATH=" in message
    assert "[Environment]::SetEnvironmentVariable" not in message
    assert "uv tool install" in message


def test_doctor_does_not_modify_path_environment(tmp_path, monkeypatch):
    _patch_doctor_dependencies(monkeypatch)
    monkeypatch.setattr("cyrrus.tools.shutil.which", lambda name: None)
    monkeypatch.setattr("cyrrus.tools.sysconfig.get_path", lambda name, scheme=None: "/tmp/scripts")
    before = dict(os.environ)
    doctor(_config(tmp_path))
    assert dict(os.environ) == before


def _patch_setup_network(monkeypatch):
    monkeypatch.setattr("cyrrus.setup.detect_services", lambda timeout=1.0: {"ollama": True})
    monkeypatch.setattr(
        "cyrrus.setup.list_models",
        lambda service_id, base_url=None, timeout=5.0: {
            "success": True,
            "models": ["qwen2.5-coder:0.5b"],
            "error": None,
        },
    )
    monkeypatch.setattr(
        "cyrrus.setup.check_connection",
        lambda config, timeout=10.0: {
            "success": True,
            "reachable": True,
            "completion_ok": True,
            "error": None,
            "service": "ollama",
            "model": "qwen2.5-coder:0.5b",
        },
    )
    monkeypatch.setattr("cyrrus.setup._detect_hybrid_available", lambda: False)


def test_setup_final_screen_points_to_doctor_when_missing(tmp_path, monkeypatch, capsys):
    _patch_setup_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cyrrus.tools.shutil.which", lambda name: None)

    run_setup(
        UI(caps=Caps(is_tty=False, color_depth=COLOR_NONE, unicode=False, width=80, height=24,
                     ci=False, reduced_motion=False, ansi=False, term_dumb=False)),
        non_interactive=True,
        plain=True,
        force=True,
        overrides={
            "goal": "library",
            "service": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:0.5b",
            "starter_slide": "none",
            "scope": "project",
            "yes": True,
            "skip_test": True,
        },
    )

    out = capsys.readouterr().out
    assert "cyrrus doctor" in out
    assert "not on PATH" in out


def test_setup_final_screen_silent_when_command_on_path(tmp_path, monkeypatch, capsys):
    _patch_setup_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("cyrrus.tools.shutil.which", lambda name: "/usr/local/bin/cyrrus")

    run_setup(
        UI(caps=Caps(is_tty=False, color_depth=COLOR_NONE, unicode=False, width=80, height=24,
                     ci=False, reduced_motion=False, ansi=False, term_dumb=False)),
        non_interactive=True,
        plain=True,
        force=True,
        overrides={
            "goal": "library",
            "service": "ollama",
            "base_url": "http://localhost:11434",
            "model": "qwen2.5-coder:0.5b",
            "starter_slide": "none",
            "scope": "project",
            "yes": True,
            "skip_test": True,
        },
    )

    out = capsys.readouterr().out
    assert "cyrrus doctor" not in out


def test_python_m_cyrrus_runs_from_installed_package(tmp_path):
    package_file = Path(cyrrus.__file__).resolve()
    assert (package_file.parent / "__main__.py").is_file()
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "cyrrus", "--version"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "cyrrus" in result.stdout.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="py launcher is Windows-only")
def test_py_m_cyrrus_runs(tmp_path):
    if shutil.which("py") is None:
        pytest.skip("py launcher not installed")
    listing = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=60)
    wanted = "%d.%d" % sys.version_info[:2]
    selector = None
    for line in listing.stdout.splitlines():
        tag = line.strip().split()[0] if line.strip() else ""
        if tag.startswith("-V:") and wanted in tag:
            selector = tag
            break
    if selector is None:
        pytest.skip("py launcher has no %s runtime registered" % wanted)
    env = dict(os.environ)
    # Make the repository importable for the interpreter the launcher starts;
    # the wheel-installed form is verified manually in the item report.
    env["PYTHONPATH"] = str(Path(cyrrus.__file__).resolve().parents[1])
    result = subprocess.run(
        ["py", selector, "-m", "cyrrus", "--version"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "cyrrus" in result.stdout.lower()
