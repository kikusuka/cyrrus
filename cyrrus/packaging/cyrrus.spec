# -*- mode: python ; coding: utf-8 -*-
"""Build a ``cyrrus`` executable with PyInstaller.

Run from the project root:

    python -m PyInstaller packaging/cyrrus.spec --noconfirm

The default is one-file mode: ``dist/cyrrus`` (``dist\\cyrrus.exe`` on Windows).
Non-developers get one file to download, check and run.  Set
``CYRRUS_ONEDIR=1`` to build the same entry point as an onedir folder instead:
``dist/cyrrus/cyrrus`` (``cyrrus.exe`` on Windows).  The folder starts much
faster because it does not extract the bundled runtime to a temporary
directory on every launch, but it has to be shipped (and extracted) as a
folder/zip rather than copied as a single file.

All ``cyrrus`` submodules are collected explicitly so the UI and the optional
gateway pieces are not missed by static analysis.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent

hiddenimports = collect_submodules("cyrrus")
datas = collect_data_files("cyrrus")
onedir = os.environ.get("CYRRUS_ONEDIR") == "1"

a = Analysis(
    [str(ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

common = dict(
    name="cyrrus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if onedir:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **common
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="cyrrus",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        **common
    )
