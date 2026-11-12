"""Contract checks for the non-developer installer scripts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install.sh"
PS1 = ROOT / "scripts" / "install.ps1"


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
