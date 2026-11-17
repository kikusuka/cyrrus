# Install Cyrrus

Cyrrus is pure Python and has no required third-party dependencies. Pick one
route:

* the one-line installer (uses `uv`, no Python knowledge needed),
* a standalone binary (no Python at all),
* the Docker image (hosting the gateway),
* pip (servers, Raspberry Pi, Termux, or an existing Python environment).

This page documents the stable **0.3.0** release. After installing, open a
**new** terminal and run `cyrrus setup`.

## 1. One-line installer (Windows, macOS, Linux)

The installer uses `uv` to put console tools in their own environment and keeps
them off the system Python. No admin rights are required. A stable release
installs with no special flags.

### Windows (PowerShell)

**`irm | iex` form:**

```powershell
irm https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1 | iex
```

**`-File` form:**

```powershell
powershell -ExecutionPolicy ByPass -File .\install.ps1
```

Pin an exact version (the `irm | iex` form cannot pass parameters, so set the
environment variable instead):

```powershell
powershell -ExecutionPolicy ByPass -File .\install.ps1 -Version 0.3.0

$env:CYRRUS_VERSION = "0.3.0"
irm https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1 | iex
```

Pre-releases are opt-in. Set `$env:CYRRUS_PRERELEASE = "1"` before running the
script (or use `-Version` with the exact pre-release number).

### macOS and Linux

```sh
curl -fsSL https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh | sh
```

`wget` works too:

```sh
wget -qO- https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh | sh
```

Pin an exact version by passing it to `sh -s --`:

```sh
curl -fsSL https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh | sh -s -- 0.3.0
```

Pre-releases are opt-in with `CYRRUS_PRERELEASE=1`, for example
`curl ... | CYRRUS_PRERELEASE=1 sh -s -- 0.3.0b6`.

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
python -m pip install cyrrus
python -m cyrrus --version
```

**32-bit Raspberry Pi OS** has no standalone binary (uv and the released
binaries are 64-bit only). Use `pip`:

```sh
python3 -m pip install cyrrus
python3 -m cyrrus --version
```

### Test status (installers)

`install.sh` was run end to end in `python:3.11-slim` and in
`debian:bookworm-slim` with **no system Python** (uv downloaded CPython). In
both cases it installed `cyrrus==0.3.0b6` with the pre-release opt-in, and the
installed command printed `cyrrus 0.3.0b6`.

`install.ps1` was run both as `-File` and as a local `Get-Content | iex` form
from a fresh `cmd` shell with PATH reduced to `C:\Windows\System32;C:\Windows`.
Both exited 0 and the installed command printed `cyrrus 0.3.0b6`.

**NOT RUN:** the new raw.githubusercontent.com URLs above (the changes were not
pushed when these tests ran), and a no-flag install of the stable **0.3.0**
release (it was not on PyPI yet). With uv 0.12.8 a no-flag install resolved
`0.2.0`; with uv 0.13.9 it resolved `0.3.0b6`. If a no-flag install picks an
older version, pin `0.3.0` explicitly.

## 2. Standalone binary (no Python)

Stable downloads use names that never change, so
`/releases/latest/download/<name>` keeps working across versions:

| Platform | Stable URL |
|---|---|
| Windows x64 | `https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-windows-x64.zip` |
| Windows ARM64 | `https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-windows-arm64.zip` |
| macOS Apple Silicon | `https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-macos-arm64.tar.gz` |
| macOS Intel | `https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-macos-x64.tar.gz` |
| Linux x64 | `https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-linux-x64.tar.gz` |
| Linux ARM64 | `https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-linux-arm64.tar.gz` |

Pin an exact version by replacing `latest/download/<name>` with
`download/v0.3.0/cyrrus-0.3.0-<os>-<arch>.<ext>`, for example:

```text
https://github.com/kikusuka/cyrrus/releases/download/v0.3.0/cyrrus-0.3.0-windows-x64.zip
https://github.com/kikusuka/cyrrus/releases/download/v0.3.0/cyrrus-0.3.0-linux-x64.tar.gz
https://github.com/kikusuka/cyrrus/releases/download/v0.3.0/SHA256SUMS
```

Every release also ships `SHA256SUMS`. It lists **both** the versioned files and
the stable aliases (12 lines), and both names hash identically. Verify before
running:

```sh
# Linux / macOS
curl -fLsS "https://github.com/kikusuka/cyrrus/releases/latest/download/SHA256SUMS" -o SHA256SUMS
curl -fLsS "https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-linux-x64.tar.gz" -o cyrrus-linux-x64.tar.gz
sha256sum -c SHA256SUMS --ignore-missing
```

```powershell
# Windows PowerShell
Invoke-WebRequest -Uri "https://github.com/kikusuka/cyrrus/releases/latest/download/SHA256SUMS" -OutFile SHA256SUMS
Invoke-WebRequest -Uri "https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-windows-x64.zip" -OutFile cyrrus-windows-x64.zip
Get-FileHash -Algorithm SHA256 .\cyrrus-windows-x64.zip
# Compare with the line whose filename is cyrrus-windows-x64.zip
```

### Windows

Extract the **whole folder** and run `cyrrus\cyrrus.exe`. The zip is a onedir
build; keep the DLLs and the `_internal` folder next to the exe. Cold start was
measured at 0.79 s median for the onedir build.

The executable is not code-signed. SmartScreen can warn about an unknown
publisher; verify the SHA-256 first, then choose **More info → Run anyway** if
you trust the release.

### macOS

```sh
tar -xzf cyrrus-macos-arm64.tar.gz
chmod +x cyrrus
xattr -d com.apple.quarantine cyrrus 2>/dev/null || true
./cyrrus --version
```

Gatekeeper can block an unsigned downloaded binary. Either right-click the
binary and choose **Open**, or remove the quarantine attribute as above after
checking the checksum. **NOT RUN** on macOS hardware.

### Linux

```sh
tar -xzf cyrrus-linux-x64.tar.gz
chmod +x cyrrus
./cyrrus --version
```

The Linux tarball is built in `manylinux_2_28` (glibc 2.28 floor). **NOT RUN**
on a live Linux host; the binary and its smoke test ran in containers.

### Test status (binaries)

The release workflow gained a "Create stable alias names" step and a checksum
step. Both shell blocks were executed against fake 9.9.9 assets: six aliases were
created, `SHA256SUMS` contained 12 lines (six versioned + six aliases), and
`sha256sum -c SHA256SUMS` passed. All 14 `run:` scripts in `binaries.yml` and
`docker.yml` pass `bash -n`.

**NOT RUN:** downloading from the live `/releases/latest/download/...` URLs.
The 0.3.0 release was not uploaded, so those URLs did not exist at test time.

## 3. Docker (hosting the gateway)

```sh
docker pull ghcr.io/kikusuka/cyrrus:0.3.0
```

**NOT RUN:** the 0.3.0 image was not published. The package may start private;
after the first publish, set the `ghcr.io/kikusuka/cyrrus` package visibility to
public once so anonymous pulls work.

Build from the repository root (the Dockerfile installs the pinned PyPI
release):

```sh
docker build --platform linux/amd64 --build-arg CYRRUS_VERSION=0.3.0 -t cyrrus:0.3.0 .
docker run --rm cyrrus:0.3.0 cyrrus --version
```

**NOT RUN:** this build needs `cyrrus==0.3.0` on PyPI, which did not exist at
test time.

`docs/docker.config.example.json` is the starting point for a public run. It
sets `gateway.host` to `0.0.0.0`, sets `gateway.api_key_env` to
`CYRRUS_GATEWAY_TOKEN` (the **incoming** token), and sets
`provider.api_key_env` to `OPENAI_API_KEY` (the **outgoing** provider key).
Edit the provider section for your model service.

```sh
cp docs/docker.config.example.json ./cyrrus.config.json
# Edit cyrrus.config.json: provider.base_url, provider.model and the key names.

docker run --rm --name cyrrus \
  -p 127.0.0.1:8787:8787 \
  -v cyrrus-data:/data \
  -v "$PWD/cyrrus.config.json:/data/cyrrus.config.json:ro" \
  -e CYRRUS_GATEWAY_TOKEN=replace-with-a-long-random-token \
  -e OPENAI_API_KEY=replace-with-the-provider-key \
  cyrrus:0.3.0
```

**Gateway auth warning.** `gateway.api_key_env` only checks that the incoming
bearer token is an exact match. It does **not** enforce a minimum length, and
the gateway itself listens over plain HTTP. Use a long random token, for
example:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep the `-p 127.0.0.1:8787:8787` form. Publishing `-p 8787:8787` exposes the
plain-HTTP gateway on every host interface. For real hosting, terminate TLS in a
reverse proxy (Caddy, nginx, Traefik) and let the proxy reach the container.
Binding to a non-loopback host without `gateway.api_key_env` is refused:

```text
ValueError: Non-loopback gateway binding requires gateway.api_key_env
```

That refusal was reproduced with the built 0.3.0 wheel.

The gateway keeps its SQLite database in `/data/memory.sqlite` with this example
config, so it survives container replacement in the `cyrrus-data` volume. Stop
it with a drain-aware timeout; the image uses `STOPSIGNAL SIGINT`:

```sh
docker stop --timeout 40 cyrrus
```

## 4. pip (servers, Raspberry Pi, Termux)

```sh
# Servers / existing Python environment:
python -m pip install cyrrus
python -m cyrrus --version
python -m cyrrus doctor

# Raspberry Pi (64-bit, arm64 wheel):
python3 -m pip install cyrrus
python3 -m cyrrus --version

# Termux: uv does not support Termux. Use pip.
pkg install python
python -m pip install cyrrus
```

No `--pre` flag is needed for a stable release. `python -m cyrrus` works even
when the scripts directory is not on PATH, which is the reliable form on Windows
user installs, Raspberry Pi and Termux:

```sh
python -m cyrrus setup
python -m cyrrus serve
```

### Test status (pip)

The built `cyrrus-0.3.0-py3-none-any.whl` was installed with `--no-index` into
fresh Python 3.9 and 3.13 virtual environments on Windows and into
`python:3.11-slim`. Each install printed `cyrrus 0.3.0`; `ask()` stored facts and
retrieved them on the next turn; a database created by published `0.3.0b6` was
read successfully by 0.3.0 on both Python versions.

**NOT RUN:** `pip install cyrrus` for 0.3.0 from PyPI (not uploaded), the
interactive `setup` wizard, Termux, Raspberry Pi hardware, and `cyrrus serve` as
a module (the same server was started through the console script and the
gateway API).

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

On Windows the `py` launcher also works (avoiding any unrelated global Python):

```powershell
py -3.13 -m cyrrus --version
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
uv tool install cyrrus
uv tool update-shell
```

Add `--prerelease allow` (or set `CYRRUS_PRERELEASE=1` with the installers) only
when installing a pre-release. `pipx install cyrrus` is also an option, but
**NOT RUN**: pipx was deliberately absent from the test environment.
