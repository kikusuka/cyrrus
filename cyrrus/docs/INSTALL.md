# Install Cyrrus

Cyrrus is pure Python and has no required third-party dependencies. Pick one
of three routes:

* the one-line installer (uses `uv`, no Python knowledge needed),
* a standalone binary (no Python at all),
* pip (servers, Raspberry Pi, Termux, or an existing Python environment).

After installing, open a **new** terminal and run `cyrrus setup`.

## 1. One-line installer (Windows, macOS, Linux)

The installer uses `uv` to put console tools in their own environment and keeps
them off the system Python. No admin rights are required.

### Windows (PowerShell)

**`-File` form (tested):**

```powershell
powershell -ExecutionPolicy ByPass -File .\install.ps1 -Version 0.3.0b6
```

**`irm | iex` form (tested):**

```powershell
$env:CYRRUS_VERSION = "0.3.0b6"
irm https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1 | iex
```

*The `irm | iex` form cannot pass script parameters, so set the version in the
environment first.  The script was tested both ways from a fresh `cmd` shell with a
reduced PATH (simulating a minimal environment).  PowerShell 7 (`pwsh`) is also
supported.*

**NOT RUN** as written: the branch is not pushed, so the raw GitHub URL does not
exist yet.  The same script was run locally with:

```powershell
powershell -ExecutionPolicy ByPass -File C:\path\to\cyrrus\scripts\install.ps1 -Version 0.3.0b6
```

### macOS and Linux

```sh
sh install.sh 0.3.0b6
```

**NOT RUN** as written: the branch is not pushed, so the raw GitHub URL does not
exist yet.  The same script was run end to end inside Docker (`python:3.13-slim`)
with:

```sh
sh /src/install.sh 0.3.0b6
```

The installer prints:

```text
Cyrrus is installed.
Open a NEW terminal and run: cyrrus setup
Uninstall later with: uv tool uninstall cyrrus
```

### Termux and 32-bit Raspberry Pi OS

**uv does not support Termux.**  Use `pip` instead:

```sh
pkg install python
pip install --pre cyrrus
```

**32-bit Raspberry Pi OS** has no standalone binary.  Use `pip`:

```sh
python3 -m pip install --pre cyrrus
```

### Docker (hosting)

```sh
docker run --rm -v cyrrus-data:/data ghcr.io/kikusuka/cyrrus:0.3.0b6 cyrrus serve
```

*Do NOT expose the gateway network unless you configure `api_key_env` in the
config file.  The gateway binds to `127.0.0.1` by default; setting
`api_key_env` in the config file allows non-loopback binding and requires a
Bearer token on incoming requests.  The constant-time compare never logs the
token.  To enable, add `api_key_env: CYRRUS_AUTH_TOKEN` to your config and set
that environment variable.*

## 2. Standalone binary (no Python)

Releases are uploaded per platform and architecture.  Download an explicit
versioned URL — **never** `releases/latest` because "latest" ignores
pre-releases and every cyrrus release is a pre-release (they 404).

### Asset naming

`cyrrus-<version>-<os>-<arch>.<ext>` where:

* `os` in `{windows, macos, linux}`
* `arch` in `{x64, arm64}`
* `ext` in `{zip, tar.gz}` (Windows zip / onedir; Linux/macOS tarball)
* `<version>` taken from the release tag (e.g. `0.3.0b6`)

### Windows

| Archive | Extractor | Notes |
|---|---|---|
| `cyrrus-0.3.0b6-windows-x64.zip` | Extract the whole folder, run `cyrrus\cyrrus.exe` | Recommended; cold-start median 0.79 s (onefile 2.60 s). |
| `cyrrus-0.3.0b6-windows-arm64.zip` | Same as above | ARM64 build. |

**SHA-256 verification (Windows PowerShell):**

```powershell
# Download both the archive and its filename-only checksum file:
Invoke-WebRequest -Uri "https://github.com/kikusuka/cyrrus/releases/download/v0.3.0b6/SHA256SUMS" -OutFile SHA256SUMS
Invoke-WebRequest -Uri "https://github.com/kikusuka/cyrrus/releases/download/v0.3.0b6/cyrrus-0.3.0b6-windows-x64.zip" -OutFile cyrrus-0.3.0b6-windows-x64.zip

# Verify: the SUMS file contains lines "<hash>  <filename>" (no directory prefix).
Get-FileHash -Algorithm SHA256 .\cyrrus-0.3.0b6-windows-x64.zip
# Compare the hash against the line whose second field is "cyrrus-0.3.0b6-windows-x64.zip"
# SmartScreen: downloaded files do NOT carry the Windows SmartScreen "Mark of the Web"
# when served over HTTPS from GitHub; the archive is safe to unblock if prompted.
```

**NOT RUN** against a GitHub release (none published yet).  Built and tested
locally from an empty folder.

### macOS

| Archive | Extractor | Notes |
|---|---|---|
| `cyrrus-0.3.0b6-macos-arm64.tar.gz` | `tar -xzf` then `./cyrrus --version` | ARM64 (Apple Silicon). |
| `cyrrus-0.3.0b6-macos-x64.tar.gz` | `tar -xzf` then `./cyrrus --version` | Intel (x86_64). |

**SHA-256 verification (macOS/Linux):**

```sh
# Download both the archive and its filename-only checksum file:
curl -fLsS "https://github.com/kikusuka/cyrrus/releases/download/v0.3.0b6/SHA256SUMS" -o SHA256SUMS
curl -fLsS "https://github.com/kikusuka/cyrrus/releases/download/v0.3.0b6/cyrrus-0.3.0b6-macos-arm64.tar.gz" -o cyrrus-0.3.0b6-macos-arm64.tar.gz

# Verify: filename-only lines accepted by `sha256sum -c`:
sha256sum -c SHA256SUMS
# shasum -a 256 is also acceptable on macOS.

# Gatekeeper: macOS marks browser-downloaded binaries with a quarantine flag.
# Files served over HTTPS from GitHub do NOT carry the quarantine flag.
# If macOS warns that the file is from an unidentified developer, right-click
# (or Ctrl-click) and select "Open" once, then confirm.  After that the
# executable bit is preserved and `cyrrus` runs normally.
```

**NOT RUN** on macOS hardware.

### Linux

| Archive | Extractor | Notes |
|---|---|---|
| `cyrrus-0.3.0b6-linux-x64.tar.gz` | `tar -xzf` then `./cyrrus --version` | x86_64. |
| `cyrrus-0.3.0b6-linux-arm64.tar.gz` | `tar -xzf` then `./cyrrus --version` | ARM64. |

**SHA-256 verification (Linux):**

```sh
curl -fLsS "https://github.com/kikusuka/cyrrus/releases/download/v0.3.0b6/SHA256SUMS" -o SHA256SUMS
curl -fLsS "https://github.com/kikusuka/cyrrus/releases/download/v0.3.0b6/cyrrus-0.3.0b6-linux-x64.tar.gz" -o cyrrus-0.3.0b6-linux-x64.tar.gz
sha256sum -c SHA256SUMS
```

The tarball is built inside an old-glibc container (`manylinux_2_28` / Debian 11)
so the binary runs on older distributions (Raspberry Pi OS Bullseye, many
hosting images).  The glibc floor is documented in the workflow.

**NOT RUN** on a live Linux host (tests performed inside containers).

## 3. pip (servers, Raspberry Pi, Termux)

```sh
# Servers / existing Python environment:
python -m pip install --pre cyrrus
python -m cyrrus --version
python -m cyrrus doctor

# Raspberry Pi (64-bit, arm64 wheel):
python3 -m pip install --pre cyrrus
python3 -m cyrrus --version

# Termux: uv does not support Termux.  Use pip.
pkg install python
pip install --pre cyrrus
```

All three were run in a fresh `python:3.11-slim` Docker container against PyPI:
it installed `cyrrus 0.3.0b6`, and `python -m cyrrus --version` printed
`cyrrus 0.3.0b6`.

`python -m cyrrus` works even when the scripts directory is not on PATH.  This
is the reliable form on Windows user installs, Raspberry Pi and Termux:

```sh
python -m cyrrus setup
python -m cyrrus serve
```

The interactive `setup` command was **NOT RUN** interactively here (scripted
tests and the binary's non-interactive wizard were used).  `python -m cyrrus
serve` was **NOT RUN** as a module; the same gateway was started and stopped
with the standalone binary in the smoke test.

Raspberry Pi and Termux were **NOT RUN**: no ARM device or Termux environment
was available.  The package is pure Python, so the wheel should not need a
compiler.

## 4. Uninstalling

* uv: `uv tool uninstall cyrrus`
* pip: `python -m pip uninstall -y cyrrus`
* Standalone binary: delete the downloaded archive and the extracted folder
  (or the single-file exe).  No system files were written, so there is nothing
  else to remove.

*Verified*: `uv tool uninstall cyrrus` on Windows uninstalled 1 executable.
*Verified*: `python -m pip uninstall -y cyrrus` inside Docker succeeded.

## 5. Troubleshooting: "command not found" / "not recognized"

Run the doctor first:

```powershell
cyrrus doctor
```

If `cyrrus` itself is not recognized, use the form that always works:

```powershell
python -m cyrrus doctor
python -m cyrrus --version
```

On Windows the `py` launcher also works (avoiding the global Python 3.14):

```powershell
py -V:Astral/CPython3.13.15 -m cyrrus --version
```

`cyrrus doctor` prints the exact scripts directory and a safe PowerShell append.
**The PATH-changing block was NOT RUN**, because the check must not modify
anything:

```powershell
$dir = 'C:\Users\YOU\AppData\Roaming\Python\Python313\Scripts'
$old = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($old) { $new = $old.TrimEnd(';') + ';' + $dir } else { $new = $dir }
[Environment]::SetEnvironmentVariable('Path', $new, 'User')
```

Do not use `setx`: it truncates long PATH values.  Open a new terminal after
changing PATH.

The recommended alternative avoids PATH editing entirely:

```sh
uv tool install --prerelease allow cyrrus
uv tool update-shell
```

Both commands were run by the installer tests.  `pipx install --pre cyrrus` is
also an option, but **NOT RUN**: pipx was deliberately absent from the test
environment.