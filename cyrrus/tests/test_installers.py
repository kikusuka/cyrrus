"""Contract checks for the non-developer installer scripts."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install.sh"
PS1 = ROOT / "scripts" / "install.ps1"
DOCS = ROOT / "docs" / "INSTALL.md"


def test_installer_scripts_exist():
    assert SH.is_file(), "scripts/install.sh is missing"
    assert PS1.is_file(), "scripts/install.ps1 is missing"


def test_shell_installer_contract():
    text = SH.read_text(encoding="utf-8")
    assert "https://astral.sh/uv/install.sh" in text
    assert 'if [ "${CYRRUS_PRERELEASE:-}" = "1" ]' in text
    assert 'uv tool install --prerelease allow "$@"' in text
    assert "uv tool update-shell" in text
    assert "cyrrus setup" in text
    assert "uv tool uninstall cyrrus" in text
    assert "TODO" not in text
    assert "sudo" not in text
    assert "setx" not in text.lower()


def test_install_guide_uses_real_repo_paths():
    text = DOCS.read_text(encoding="utf-8")
    assert (
        "raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1"
        in text
    )
    assert (
        "raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh"
        in text
    )

    # Release assets are versioned per platform and architecture.  "latest"
    # ignores pre-releases, and every Cyrrus release is currently a
    # pre-release, so a latest URL would 404.
    assert "releases/latest" not in text
    assert "cyrrus-Windows-X64" not in text
    assert "cyrrus-<version>-<os>-<arch>.<ext>" in text
    assert "releases/download/v0.3.0b6/SHA256SUMS" in text
    assert (
        "releases/download/v0.3.0b6/cyrrus-0.3.0b6-windows-x64.zip" in text
    )
    assert (
        "releases/download/v0.3.0b6/cyrrus-0.3.0b6-macos-arm64.tar.gz" in text
    )
    assert (
        "releases/download/v0.3.0b6/cyrrus-0.3.0b6-linux-x64.tar.gz" in text
    )
    for asset in (
        "cyrrus-0.3.0b6-windows-x64.zip",
        "cyrrus-0.3.0b6-windows-arm64.zip",
        "cyrrus-0.3.0b6-macos-arm64.tar.gz",
        "cyrrus-0.3.0b6-macos-x64.tar.gz",
        "cyrrus-0.3.0b6-linux-x64.tar.gz",
        "cyrrus-0.3.0b6-linux-arm64.tar.gz",
    ):
        assert asset in text


def test_powershell_installer_contract():
    text = PS1.read_text(encoding="utf-8")
    assert "https://astral.sh/uv/install.ps1" in text
    assert "$env:CYRRUS_PRERELEASE" in text
    assert '"--prerelease", "allow"' in text
    assert "uv tool update-shell" in text
    assert "cyrrus setup" in text
    assert "uv tool uninstall cyrrus" in text
    assert "TODO" not in text
    assert "setx" not in text.lower()
    assert "RunAs" not in text


def test_powershell_installer_is_iex_safe():
    """`irm <url> | iex` rejects a script-level param block or attributes."""
    text = PS1.read_text(encoding="utf-8")
    assert "[CmdletBinding()]" not in text
    assert not re.search(r"(?m)^\s*param\s*\(", text)
    assert "$env:CYRRUS_VERSION" in text
    # Never assume Windows PowerShell 5.1 lives at $PSHOME: PowerShell 7 has
    # pwsh.exe there instead.
    assert "$PSHOME\\powershell.exe" not in text
    assert "Get-Process -Id $PID" in text


def test_powershell_installer_parses_without_a_top_level_param_block():
    powershell = shutil.which("powershell")
    if powershell is None:
        return
    command = (
        "$tokens=$null;$errors=$null;"
        "$ast=[System.Management.Automation.Language.Parser]::ParseFile("
        "'%s',[ref]$tokens,[ref]$errors);"
        "if ($errors.Count) { $errors | ForEach-Object { $_.Message }; exit 1 };"
        "if ($ast.ParamBlock) { Write-Output 'HAS_PARAM_BLOCK'; exit 2 };"
        "Write-Output 'PARSE_OK'" % PS1
    )
    result = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PARSE_OK" in result.stdout


def test_shell_installer_no_longer_claims_termux_support():
    text = SH.read_text(encoding="utf-8")
    assert "Termux" not in text.splitlines()[1]
    assert "TERMUX_VERSION" in text or "com.termux" in text
    assert "pip install cyrrus" in text
    assert "uv does not support Termux" in text


def test_shell_installer_rejects_unsupported_platforms_with_pip_guidance():
    text = SH.read_text(encoding="utf-8")
    assert "uname -s" in text
    assert "uname -m" in text
    assert "pip install cyrrus" in text
    assert "32-bit" in text or "armv7" in text


def test_installers_offer_explicit_version_binary_mode():
    sh = SH.read_text(encoding="utf-8")
    assert "--binary" in sh
    assert "--version" in sh
    assert "SHA256SUMS" in sh
    assert "releases/download" in sh
    assert "releases/latest" not in sh
    assert "chmod +x" in sh

    ps = PS1.read_text(encoding="utf-8")
    assert "Binary" in ps
    assert "SHA256SUMS" in ps
    assert "releases/download" in ps
    assert "releases/latest" not in ps
    assert "Get-FileHash" in ps
    assert "Expand-Archive" in ps


def test_binary_mode_requires_an_explicit_version():
    sh = SH.read_text(encoding="utf-8")
    assert "binary mode needs an explicit version" in sh
    ps = PS1.read_text(encoding="utf-8")
    assert "binary mode needs an explicit version" in ps


def test_release_assets_are_versioned_per_platform_and_arch():
    sh = SH.read_text(encoding="utf-8")
    assert "cyrrus-${VERSION}-" in sh or "cyrrus-$VERSION-" in sh
    ps = PS1.read_text(encoding="utf-8")
    assert "cyrrus-$Version-" in ps or "cyrrus-${Version}-" in ps


def _fake_uv_cmd(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "uv-args.txt"
    (bin_dir / "uv.cmd").write_text(
        '@echo off\r\necho %*>>"%UV_LOG%"\r\nexit /b 0\r\n',
        encoding="ascii",
    )
    return bin_dir, log


def _run_powershell_installer(tmp_path, extra_env=None):
    powershell = shutil.which("powershell")
    if powershell is None:
        pytest.skip("Windows PowerShell not available")
    bin_dir, log = _fake_uv_cmd(tmp_path)
    env = dict(os.environ)
    env["PATH"] = str(bin_dir)
    env["UV_LOG"] = str(log)
    env["LOCALAPPDATA"] = str(tmp_path / "localappdata")
    env["USERPROFILE"] = str(tmp_path / "home")
    env["HOME"] = str(tmp_path / "home")
    env.pop("CYRRUS_PRERELEASE", None)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PS1),
            "-Version",
            "9.9.9",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return log.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell not available")
def test_powershell_installer_has_no_prerelease_flag_by_default(tmp_path):
    log = _run_powershell_installer(tmp_path)
    install = [line for line in log.splitlines() if line.startswith("tool install")]
    assert install, log
    assert "--prerelease" not in install[0], install[0]


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows PowerShell not available")
def test_powershell_installer_prerelease_opt_in_restores_the_flag(tmp_path):
    log = _run_powershell_installer(tmp_path, {"CYRRUS_PRERELEASE": "1"})
    install = [line for line in log.splitlines() if line.startswith("tool install")]
    assert install, log
    assert "--prerelease allow" in install[0], install[0]
