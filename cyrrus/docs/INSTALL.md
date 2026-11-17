# Install Cyrrus

Cyrrus is pure Python and has no required third-party dependencies. Pick one
of these routes:

* the one-line installer (uses `uv`, no Python knowledge needed),
* a standalone binary (no Python at all),
* the Docker image (hosting the gateway),
* pip (servers, Raspberry Pi, Termux, or an existing Python environment).

After installing, open a **new** terminal and run `cyrrus setup`.

`0.3.0b6` is used below as a **placeholder example version**. Replace it with
the version you are installing. Standalone binaries and the `ghcr.io` image
exist only from the first release published after the distribution workflows
land; earlier releases have no such assets.

## 1. One-line installer (Windows, macOS, Linux)

The installer uses `uv` to put console tools in their own environment and keeps
them off the system Python. No admin rights are required.

### Windows (PowerShell)

**`irm | iex` form (tested):**

```powershell
$env:CYRRUS_VERSION = "0.3.0b6"
irm https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1 | iex
```

**`-File` form (tested):**

```powershell
powershell -ExecutionPolicy ByPass -File .\install.ps1 -Version 0.3.0b6
```

*The `irm | iex` form cannot pass script parameters, so set the version in the
environment first. The script was tested both ways from a fresh `cmd` shell
with a reduced PATH (simulating a minimal environment). PowerShell 7 (`pwsh`)
is also supported.*

**NOT RUN** as written: the branch is not pushed, so the raw GitHub URL does
not exist yet. The same script was run locally with:

```powershell
powershell -ExecutionPolicy ByPass -File C:\path\to\cyrrus\scripts\install.ps1 -Version 0.3.0b6
```

### macOS and Linux

```sh
curl -fsSL https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh | sh -s -- 0.3.0b6
```

`wget` works too:

```sh
wget -qO- https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh | sh -s -- 0.3.0b6
```

**NOT RUN** as written: the branch is not pushed, so the raw GitHub URL does
not exist yet. The same script was run end to end inside Docker
(`python:3.13-slim`) with:

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

**uv does not support Termux.** Use `pip` instead:

```sh
pkg install python
pip install --pre cyrrus
```

**32-bit Raspberry Pi OS** has no standalone binary. Use `pip`:

```sh
python3 -m pip install --pre cyrrus
```

## 2. Standalone binary (no Python)

Releases are uploaded per platform and architecture. Download an explicit
versioned URL -- **never** the `latest` release alias, because "latest" ignores
pre-releases and every Cyrrus release is currently a pre-release (those URLs
404).

### Asset naming

`cyrrus-<version>-<os>-<arch>.<ext>` where:

* `os` in `{windows, macos, linux}`
* `arch` in `{x64, arm64}`
* `ext` in `{zip, tar.gz}` (Windows zip / onedir; Linux/macOS tarball)
* `<version>` taken from the release tag (for example `0.3.0b6`)

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

**NOT RUN** against a GitHub release (no binary release published yet). Built
and tested locally from an empty folder.

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

The tarball is built inside an old-glibc container (`manylinux_2_28` / Debian
11) so the binary runs on older distributions (Raspberry Pi OS Bullseye, many
hosting images). The glibc floor is documented in the workflow.

**NOT RUN** on a live Linux host (tests performed inside containers).

## 3. Docker (hosting the gateway)

The image is built from the pinned PyPI release and runs as uid 1000. The
following commands were run locally on **linux/amd64**; the GitHub workflow is
also configured to build linux/arm64, but **arm64 was not run locally**.

Build (the `CYRRUS_VERSION` build argument is required):

```sh
docker build --platform linux/amd64 --build-arg CYRRUS_VERSION=0.3.0b6 -t cyrrus:0.3.0b6 .
```

Check the image and the non-root user:

```sh
docker run --rm cyrrus:0.3.0b6 cyrrus --version
docker run --rm cyrrus:0.3.0b6 id
```

`docs/docker.config.example.json` is the starting point for a public run. It
sets `gateway.host` to `0.0.0.0`, sets `gateway.api_key_env` to
`CYRRUS_GATEWAY_TOKEN` (the **incoming** token), and sets
`provider.api_key_env` to `OPENAI_API_KEY` (the **outgoing** provider key).
Edit the provider section for your model service.

```sh
cp docs/docker.config.example.json ./cyrrus.config.json
# Edit cyrrus.config.json: provider.base_url, provider.model and the key names.
```

Run with a fresh named volume, a host-loopback port binding, and both keys
passed as environment variables:

```sh
docker run --rm --name cyrrus \
  -p 127.0.0.1:8787:8787 \
  -v cyrrus-data:/data \
  -v "$PWD/cyrrus.config.json:/data/cyrrus.config.json:ro" \
  -e CYRRUS_GATEWAY_TOKEN=replace-with-a-long-random-token \
  -e OPENAI_API_KEY=replace-with-the-provider-key \
  cyrrus:0.3.0b6
```

Keep the `-p 127.0.0.1:8787:8787` form. Publishing `-p 8787:8787` exposes the
plain-HTTP gateway on every host interface. For real hosting, terminate TLS in
a reverse proxy (Caddy, nginx, Traefik) and let the proxy reach the container.

The gateway keeps its SQLite database in `/data/memory.sqlite` with this
example config, so it survives container replacement in the `cyrrus-data`
volume. The tested image wrote the database as uid 1000 in a fresh named
volume.

Check health and authentication from the host:

```sh
curl -H "Authorization: Bearer $CYRRUS_GATEWAY_TOKEN" http://127.0.0.1:8787/health
curl -H "Authorization: Bearer $CYRRUS_GATEWAY_TOKEN" http://127.0.0.1:8787/cyrrus/status
curl http://127.0.0.1:8787/cyrrus/status   # 401 without the token
```

Stop it with a drain-aware timeout. The image uses `STOPSIGNAL SIGINT` so the
gateway drains pending turns:

```sh
docker stop --timeout 40 cyrrus
```

Starting the same config with `gateway.host` set to `0.0.0.0` and no
`gateway.api_key_env` exits with:

```text
ValueError: Non-loopback gateway binding requires gateway.api_key_env
```

A new `ghcr.io/kikusuka/cyrrus` package starts **private**. After the first
release publishes it, open the package settings on GitHub once and change the
visibility to public so anonymous `docker pull` works.

## 4. pip (servers, Raspberry Pi, Termux)

```sh
# Servers / existing Python environment:
python -m pip install --pre cyrrus
python -m cyrrus --version
python -m cyrrus doctor

# Raspberry Pi (64-bit, arm64 wheel):
python3 -m pip install --pre cyrrus
python3 -m cyrrus --version

# Termux: uv does not support Termux. Use pip.
pkg install python
pip install --pre cyrrus
```

All three were run in a fresh `python:3.11-slim` Docker container against PyPI:
it installed `cyrrus 0.3.0b6`, and `python -m cyrrus --version` printed
`cyrrus 0.3.0b6`.

`python -m cyrrus` works even when the scripts directory is not on PATH. This
is the reliable form on Windows user installs, Raspberry Pi and Termux:

```sh
python -m cyrrus setup
python -m cyrrus serve
```

The interactive `setup` command was **NOT RUN** interactively here (scripted
tests and the binary's non-interactive wizard were used). `python -m cyrrus
serve` was **NOT RUN** as a module; the same gateway was started and stopped
with the standalone binary in the smoke test.

Raspberry Pi and Termux were **NOT RUN**: no ARM device or Termux environment
was available. The package is pure Python, so the wheel should not need a
compiler.

## 5. Uninstalling

* uv: `uv tool uninstall cyrrus`
* pip: `python -m pip uninstall -y cyrrus`
* Docker: `docker rm -f cyrrus`, then `docker volume rm cyrrus-data` if you
  also want to delete the database.
* Standalone binary: delete the downloaded archive and the extracted folder
  (or the single-file exe). No system files were written, so there is nothing
  else to remove.

*Verified*: `uv tool uninstall cyrrus` on Windows uninstalled 1 executable.
*Verified*: `python -m pip uninstall -y cyrrus` inside Docker succeeded.

## 6. Troubleshooting: "command not found" / "not recognized"

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

Do not use `setx`: it truncates long PATH values. Open a new terminal after
changing PATH.

The recommended alternative avoids PATH editing entirely:

```sh
uv tool install --prerelease allow cyrrus
uv tool update-shell
```

Both commands were run by the installer tests. `pipx install --pre cyrrus` is
also an option, but **NOT RUN**: pipx was deliberately absent from the test
environment.
