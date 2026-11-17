# Cyrrus installer for Windows.
#
# Usage (normal PowerShell, no admin):
#   powershell -ExecutionPolicy ByPass -File .\install.ps1
#   powershell -ExecutionPolicy ByPass -File .\install.ps1 -Version 0.3.0b6
#
# uv is used because it installs console tools into their own environment and
# keeps them off the system Python. No admin rights are required.

[CmdletBinding()]
param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

# Official uv standalone installer:
# https://docs.astral.sh/uv/getting-started/installation/#standalone-installer
# (Windows: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex")
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Installing uv with the official installer..."
    # $PSHOME is used so this also works in a shell with a reduced PATH.
    & "$PSHOME\powershell.exe" -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if ($LASTEXITCODE -ne 0) {
        Fail "uv installation failed. See the output above."
    }
    # uv's installer puts binaries in %USERPROFILE%\.local\bin but only updates
    # future shells. Use it for the rest of this script without changing
    # anything permanently.
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is still not available. Open a new terminal and re-run this script."
}

if ($Version) {
    Write-Host "Installing cyrrus $Version with uv..."
    & uv tool install --prerelease allow "cyrrus==$Version"
} else {
    Write-Host "Installing cyrrus with uv..."
    # TODO: remove --prerelease once a stable release exists on PyPI.
    & uv tool install --prerelease allow cyrrus
}
if ($LASTEXITCODE -ne 0) {
    Fail "uv tool install failed. Check your network connection and the version number."
}

# Add uv's tool directory to the user PATH so future shells find cyrrus.
& uv tool update-shell
if ($LASTEXITCODE -ne 0) {
    Fail "uv tool update-shell failed."
}

Write-Host ""
Write-Host "Cyrrus is installed." -ForegroundColor Green
Write-Host ""
Write-Host "Open a NEW terminal and run: cyrrus setup" -ForegroundColor Green
Write-Host ""
Write-Host "Uninstall later with: uv tool uninstall cyrrus"
