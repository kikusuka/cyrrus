# -*- mode: python ; coding: utf-8 -*-
"""Build a single-file ``cyrrus`` executable with PyInstaller.

Run from the project root:

    python -m PyInstaller packaging/cyrrus.spec --noconfirm

The result is ``dist/cyrrus`` (``dist\\cyrrus.exe`` on Windows).  One-file
mode is used on purpose: non-developers get one file to download, check and
run.  All ``cyrrus`` submodules are collected explicitly so the UI and the
optional gateway pieces are not missed by static analysis.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent

hiddenimports = collect_submodules("cyrrus")
datas = collect_data_files("cyrrus")

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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
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
