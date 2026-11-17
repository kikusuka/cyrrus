# Install Cyrrus

> **DRAFT.** This file is not linked from the README yet. Commands marked
> **NOT RUN** could not be executed while drafting; everything else was run in
> a fresh uv venv, Docker, or on the Windows test machine.

Cyrrus is pure Python and has no required third-party dependencies. Pick one
of three routes:

* the one-line installer (uses `uv`, no Python knowledge needed),
* a standalone binary (no Python at all),
* pip (servers, Raspberry Pi, Termux, or an existing Python environment).

After installing, open a **new** terminal and run `cyrrus setup`.

## 1. One-line installer (Windows, macOS, Linux)

The installer installs `uv` with its official installer when needed, then runs
`uv tool install --prerelease allow cyrrus` and `uv tool update-shell`. It does
not need sudo or administrator rights and does not edit PATH itself.

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.ps1 | iex"
```

**NOT RUN** as written: the branch is not pushed, so the raw URL does not exist
yet. The same script was run locally with:

```powershell
powershell -ExecutionPolicy ByPass -File C:\path\to\cyrrus\scripts\install.ps1
```

### macOS and Linux

```sh
curl -LsSf https://raw.githubusercontent.com/kikusuka/cyrrus/main/cyrrus/scripts/install.sh | sh
```

**NOT RUN** as written for the same reason. The same script was run end to end
inside Docker (`python:3.11-slim`) with:

```sh
sh scripts/install.sh
```

The installer prints:

```text
Open a NEW terminal and run: cyrrus setup
```

`cyrrus setup` is the interactive wizard. It was **NOT RUN** interactively
here; its non-interactive form was run against the standalone binary (section
2). The installer itself also prints the uninstall command.

## 2. Standalone binary (no Python)

Windows releases ship two layouts:

* `cyrrus-Windows-X64.zip` — recommended. Extract the whole folder and run
  `cyrrus\cyrrus.exe`; cold start took 0.79-0.83 s (median 0.79 s) on this
  machine because the runtime is not unpacked on every launch.
* `cyrrus-Windows-X64.exe` — optional single file. It needs no extraction, but
  each cold start unpacks the bundled runtime first and took 2.43-2.72 s
  (median 2.60 s) here. Use it only when one file is a hard requirement.

macOS and Linux releases use the one-file layout:

* `cyrrus-Linux-X64`
* `cyrrus-macOS-X64` or `cyrrus-macOS-ARM64`

Example download (Windows PowerShell):

```powershell
Invoke-WebRequest -Uri "https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-Windows-X64.zip" -OutFile "cyrrus-Windows-X64.zip"
Expand-Archive .\cyrrus-Windows-X64.zip -DestinationPath .
```

The optional single-file asset is downloaded the same way:

```powershell
Invoke-WebRequest -Uri "https://github.com/kikusuka/cyrrus/releases/latest/download/cyrrus-Windows-X64.exe" -OutFile "cyrrus-Windows-X64.exe"
```

**NOT RUN** as written: no GitHub release with binaries exists yet. Both
layouts were built locally instead and tested from an empty folder.

### Check the SHA-256 before running it

Every release asset has a matching `.sha256` file.

Windows:

```powershell
Get-FileHash .\cyrrus-Windows-X64.zip -Algorithm SHA256
Get-Content .\cyrrus-Windows-X64.zip.sha256
Get-FileHash .\cyrrus-Windows-X64.exe -Algorithm SHA256
Get-Content .\cyrrus-Windows-X64.exe.sha256
```

Both `Get-FileHash` commands were run against the locally built zip and exe and
matched their generated `.sha256` values. `Get-Content` was not run for a
release checksum file (no release exists yet). The hashes are build-specific;
compare against the file shipped with the same build, do not copy a value from
this draft.

Linux:

```sh
sha256sum cyrrus-Linux-X64
cat cyrrus-Linux-X64.sha256
```

The `sha256sum` form was run on the Windows builds (Git Bash) and matched.
`cat` of a release checksum file was **NOT RUN**.

macOS:

```sh
shasum -a 256 cyrrus-macOS-ARM64
cat cyrrus-macOS-ARM64.sha256
```

**NOT RUN**: no macOS machine or binary was available.

### Run it

```powershell
.\cyrrus\cyrrus.exe --version
.\cyrrus\cyrrus.exe doctor
```

Both commands were run from an empty folder with
`PATH=C:\Windows\System32;C:\Windows` (no Python on PATH):

```text
cyrrus 0.3.0b6
```

`doctor` printed its checks and exited normally. To use the optional
single-file build instead, run `.\cyrrus-Windows-X64.exe --version`. On
Linux/macOS run `./cyrrus --version`; that form was **NOT RUN** because only
the Windows binaries were built locally.

**Limitation:** a frozen binary does not discover third-party
`cyrrus.plugins` entry points. Use pip or the uv installer if you need a
third-party retriever, packer or backend. The built-in defaults work normally.

## 3. pip (servers, Raspberry Pi, Termux)

Use `--pre` until a stable release newer than 0.2.0 exists: plain
`pip install cyrrus` gets the old 0.2.0 because pip skips pre-releases.

```sh
python -m pip install --pre cyrrus
python -m cyrrus --version
python -m cyrrus doctor
```

All three commands were run in a fresh `python:3.11-slim` Docker container
against PyPI: it installed `cyrrus 0.3.0b6`, and `python -m cyrrus --version`
printed `cyrrus 0.3.0b6`.

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

## 4. Uninstalling

uv install:

```sh
uv tool uninstall cyrrus
```

Run on Windows and verified: `Uninstalled 1 executable: cyrrus`.

pip install:

```sh
python -m pip uninstall -y cyrrus
```

Run inside the Docker container and verified:
`Successfully uninstalled cyrrus-0.3.0b6`.

Standalone binary: delete the downloaded zip and the extracted `cyrrus` folder
(or the single-file exe) and its `.sha256` file. No system files were written,
so there is nothing else to remove. **NOT RUN** as a command (the local test
binaries were kept for the report).

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

`python -m cyrrus` was run and verified. On Windows the `py` launcher also
works:

```powershell
py -m cyrrus --version
```

**NOT RUN literally** on this machine: `py` defaults to Python 3.14, which is
excluded for this task. It was run through the launcher's selector instead:
`py -V:Astral/CPython3.13.15 -m cyrrus --version`.

`cyrrus doctor` prints the exact scripts directory and a safe PowerShell
append. **The PATH-changing block was NOT RUN**, because the check must not
modify anything:

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
