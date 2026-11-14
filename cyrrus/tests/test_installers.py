"""Contract checks for the non-developer installer scripts."""

import re
import shutil
import subprocess
from pathlib import Path

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
    assert "uv tool install --prerelease allow" in text
    assert "uv tool update-shell" in text
    assert "cyrrus setup" in text
    assert "uv tool uninstall cyrrus" in text
    assert "TODO" in text  # remove --prerelease once a stable release exists
    assert "sudo" not in text
    assert "setx" not in text.lower()


def test_install_guide_uses_real_repo_paths():
    text = DOCS.read_text(encoding="utf-8")
    assert "kikuska/cyrrus" not in text
    assert (
        "raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1"
        in text
    )
    assert (
        "raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh"
        in text
    )
    assert (
        "github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-Windows-X64.zip"
        in text
    )
    assert (
        "github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-Windows-X64.exe"
        in text
    )


def test_powershell_installer_contract():
    text = PS1.read_text(encoding="utf-8")
    assert "https://astral.sh/uv/install.ps1" in text
    assert "uv tool install --prerelease allow" in text
    assert "uv tool update-shell" in text
    assert "cyrrus setup" in text
    assert "uv tool uninstall cyrrus" in text
    assert "TODO" in text
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
