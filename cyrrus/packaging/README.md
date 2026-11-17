# Standalone binaries

Build a standalone `cyrrus` executable for people who do not want Python.
PyInstaller supports two layouts from the same spec and entry point.

## Windows: the onedir zip is the default

Windows releases ship `cyrrus-Windows-X64.zip`. Extract the whole archive and
run `cyrrus\cyrrus.exe`; keep the `cyrrus` folder together because the
executable needs its `_internal` directory.

```powershell
Expand-Archive .\cyrrus-Windows-X64.zip -DestinationPath .
.\cyrrus\cyrrus.exe --version
```

Build it locally from the project root:

```powershell
python -m pip install . pyinstaller
$env:CYRRUS_ONEDIR = "1"
python -m PyInstaller packaging/cyrrus.spec --noconfirm
Compress-Archive -Path dist\cyrrus -DestinationPath cyrrus-Windows-X64.zip
```

The folder is written to `dist\cyrrus\` (`dist/cyrrus/` on POSIX).

## One-file executable (optional Windows asset, default elsewhere)

The one-file build is a single `cyrrus.exe` (or `cyrrus`). It is convenient to
copy around, but every cold start extracts the bundled runtime to a temporary
directory first.

```powershell
python -m pip install . pyinstaller
python -m PyInstaller packaging/cyrrus.spec --noconfirm
```

The executable is written to `dist\cyrrus.exe` (`dist/cyrrus` on POSIX).
Windows releases keep it as an optional second asset,
`cyrrus-Windows-X64.exe`. Linux and macOS releases use this layout.

## Measured tradeoff (this Windows machine, 5 cold starts each)

| Layout | Cold start (median) | On-disk size | Distribution |
| --- | --- | --- | --- |
| onedir | 0.79 s (range 0.79-0.83 s) | 23.0 MiB folder (9.8 MiB zip) | zip; extract the folder |
| one-file | 2.60 s (range 2.43-2.72 s) | 9.9 MiB | one executable; unpacks every launch |

`packaging/smoke_test.py` runs `--version`, `doctor`, and a real start/stop of
`cyrrus serve` against a local fake upstream. CI smoke-tests both Windows
layouts (the zip is extracted first) plus the one-file build on macOS/Linux.

## Known limitation: entry-point plugins

Frozen binaries do **not** discover `cyrrus.plugins` entry points from
third-party packages. PyInstaller bundles the modules it can see at build
time, and plugin distributions installed later next to the executable are not
visible to `importlib.metadata`. The built-in `bm25`, `token_knapsack` and
`sqlite` defaults work normally. If you need a third-party retriever, packer or
backend, install cyrrus with `uv tool install` or `pip` instead of using the
standalone binary.
