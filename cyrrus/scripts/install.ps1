# Cyrrus installer for Windows.
#
# Usage (normal PowerShell, no admin):
#   powershell -ExecutionPolicy ByPass -File .\install.ps1
#   powershell -ExecutionPolicy ByPass -File .\install.ps1 -Version 0.3.0
#   powershell -ExecutionPolicy ByPass -File .\install.ps1 -Binary -Version 0.3.0
#
# A stable release needs no extra flags.  To install a pre-release that is not
# selected by default, opt in explicitly (the irm form has no parameters):
#   $env:CYRRUS_PRERELEASE = "1"
#
# The same script works with `irm <url> | iex`.  That form cannot pass script
# parameters, so set the version and binary mode in the environment first:
#   $env:CYRRUS_VERSION = "0.3.0"
#   $env:CYRRUS_BINARY = "1"          # optional
#   irm https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1 | iex
#
# uv is used for the default install because it puts console tools in their
# own environment and keeps them off the system Python.  `-Binary` skips
# Python and downloads the standalone release archive instead.  No admin
# rights are required for either mode.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Fail([string]$Message) {
    throw [System.InvalidOperationException]::new($Message)
}

function Get-CyrrusArch {
    try {
        $arch = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    } catch {
        $arch = $env:PROCESSOR_ARCHITECTURE
    }
    switch ($arch.ToLowerInvariant()) {
        "x64" { return "x64" }
        "amd64" { return "x64" }
        "arm64" { return "arm64" }
        default {
            Fail "Unsupported Windows architecture '$arch'. Install with pip instead: py -m pip install cyrrus"
        }
    }
}

function Install-CyrrusBinary([string]$Version) {
    # curl-downloaded files do not get the macOS quarantine flag; on Windows
    # the same download avoids the browser's SmartScreen "Mark of the Web".
    # GitHub serves over HTTPS and the archive is verified below.
    if (-not $Version) {
        Fail "binary mode needs an explicit version (-Version X or `$env:CYRRUS_VERSION)."
    }
    if ($Version.StartsWith("v")) { $Version = $Version.Substring(1) }

    $arch = Get-CyrrusArch
    $asset = "cyrrus-$Version-windows-$arch.zip"
    if ($env:CYRRUS_RELEASE_BASE_URL) {
        # Test hook: point the installer at a local fake release.
        $base = $env:CYRRUS_RELEASE_BASE_URL.TrimEnd("/")
    } else {
        $base = "https://github.com/kikusuka/cyrrus/releases/download/v$Version"
    }

    $tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("cyrrus-install-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tmp | Out-Null
    try {
        $sums = Join-Path $tmp "SHA256SUMS"
        $archive = Join-Path $tmp $asset
        Write-Host "Downloading $base/$asset ..."
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS" -OutFile $sums
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset" -OutFile $archive
        } catch {
            Fail "download failed: $($_.Exception.Message). Check that version v$Version has a Windows $arch build."
        }

        $expected = $null
        foreach ($line in Get-Content -Path $sums) {
            $parts = $line.Trim() -split "\s+", 2
            if ($parts.Count -eq 2 -and $parts[1] -eq $asset) {
                $expected = $parts[0].ToLowerInvariant()
            }
        }
        if (-not $expected) {
            Fail "SHA256SUMS does not list $asset."
        }
        $actual = (Get-FileHash -Algorithm SHA256 -Path $archive).Hash.ToLowerInvariant()
        if ($actual -ne $expected) {
            Fail "checksum mismatch for $asset. Expected $expected but got $actual. Do not run this file."
        }
        Write-Host "SHA-256 verified: $actual"

        $dest = Join-Path $env:LOCALAPPDATA "Programs\cyrrus"
        if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Expand-Archive -Path $archive -DestinationPath $dest -Force
        $exe = Join-Path $dest "cyrrus.exe"
        if (-not (Test-Path $exe)) {
            Fail "the archive did not contain cyrrus.exe."
        }

        Write-Host ""
        Write-Host "Cyrrus is installed at $exe" -ForegroundColor Green
        Write-Host ""
        Write-Host "Add this folder to your PATH:" -ForegroundColor Green
        Write-Host "  $dest"
        Write-Host "Then open a NEW terminal and run: cyrrus --version"
        Write-Host ""
        Write-Host "Uninstall later by deleting: $dest"
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}

function Install-CyrrusWithUv([string]$Version) {
    # Official uv standalone installer:
    # https://docs.astral.sh/uv/getting-started/installation/#standalone-installer
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "uv not found. Installing uv with the official installer..."
        # Run the current PowerShell executable instead of assuming the
        # Windows PowerShell 5.1 path: PowerShell 7 keeps pwsh.exe there.
        $currentExe = (Get-Process -Id $PID).Path
        & $currentExe -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        if ($LASTEXITCODE -ne 0) {
            Fail "uv installation failed. See the output above."
        }
        # uv's installer puts binaries in %USERPROFILE%\.local\bin but only
        # updates future shells. Use it for the rest of this script.
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    }

    $uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $uv) {
        $uv = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    }
    if (-not (Test-Path $uv)) {
        Fail "uv is still not available. Open a new terminal and re-run this script."
    }

    $installArgs = @("tool", "install")
    if ($env:CYRRUS_PRERELEASE -eq "1") {
        # Stable releases install by default; pre-releases are opt-in.
        $installArgs += @("--prerelease", "allow")
    }
    if ($Version) {
        if ($Version.StartsWith("v")) { $Version = $Version.Substring(1) }
        Write-Host "Installing cyrrus $Version with uv..."
        $installArgs += "cyrrus==$Version"
    } else {
        Write-Host "Installing cyrrus with uv..."
        $installArgs += "cyrrus"
    }
    & $uv @installArgs
    if ($LASTEXITCODE -ne 0) {
        Fail "uv tool install failed. Check your network connection and the version number."
    }

    # Add uv's tool directory to the user PATH so future shells find cyrrus.
    & $uv tool update-shell
    if ($LASTEXITCODE -ne 0) {
        Fail "uv tool update-shell failed."
    }

    Write-Host ""
    Write-Host "Cyrrus is installed." -ForegroundColor Green
    Write-Host ""
    Write-Host "Open a NEW terminal and run: cyrrus setup" -ForegroundColor Green
    Write-Host ""
    Write-Host "Uninstall later with: uv tool uninstall cyrrus"
}

function Invoke-CyrrusInstall([string]$Version, [bool]$Binary) {
    if (-not $Version) { $Version = $env:CYRRUS_VERSION }
    if ($Version) { $Version = $Version.Trim() }
    if ($env:CYRRUS_BINARY -eq "1") { $Binary = $true }

    if ($Binary) {
        Install-CyrrusBinary $Version
        return
    }
    if ($Version.StartsWith("v")) { $Version = $Version.Substring(1) }
    Install-CyrrusWithUv $Version
}

# `irm <url> | iex` does not allow a top-level param() block or a
# CmdletBinding attribute, so parse the two supported -File arguments by hand.
$versionArg = ""
$binaryArg = $false
for ($i = 0; $i -lt $args.Count; $i++) {
    $arg = [string]$args[$i]
    if ($arg -match "^-{0,2}[Vv]ersion(?:=(.*))?$") {
        if ($Matches[1] -ne $null -and $Matches[1] -ne "") {
            $versionArg = $Matches[1]
        } elseif ($i + 1 -lt $args.Count) {
            $i++
            $versionArg = [string]$args[$i]
        } else {
            Fail "-Version needs a value."
        }
    } elseif ($arg -match "^-{0,2}[Bb]inary$") {
        $binaryArg = $true
    } else {
        Fail "unknown argument '$arg'. Use -Version X and/or -Binary."
    }
}

try {
    Invoke-CyrrusInstall -Version $versionArg -Binary $binaryArg
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($PSCommandPath) { exit 1 }
    throw
}
