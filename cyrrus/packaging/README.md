# Standalone binaries

Build a one-file `cyrrus` executable for people who do not want Python:

```sh
python -m pip install . pyinstaller
python -m PyInstaller packaging/cyrrus.spec --noconfirm
```

The executable is written to `dist/cyrrus` (`dist\cyrrus.exe` on Windows).
`packaging/smoke_test.py` runs `--version`, `doctor`, and a real start/stop of
`cyrrus serve` against a local fake upstream.

## Known limitation: entry-point plugins

Frozen binaries do **not** discover `cyrrus.plugins` entry points from
third-party packages. PyInstaller bundles the modules it can see at build
time, and plugin distributions installed later next to the executable are not
visible to `importlib.metadata`. The built-in `bm25`, `token_knapsack` and
`sqlite` defaults work normally. If you need a third-party retriever, packer or
backend, install cyrrus with `uv tool install` or `pip` instead of using the
standalone binary.
