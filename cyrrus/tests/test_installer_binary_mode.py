"""End-to-end binary-mode checks against a fake local GitHub release.

The scripts normally download from
``https://github.com/kikusuka/cyrrus/releases/download/v<version>``.  These
tests set ``CYRRUS_RELEASE_BASE_URL`` to a local HTTP server so no network or
real release is involved.
"""

import functools
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install.sh"
PS1 = ROOT / "scripts" / "install.ps1"
VERSION = "9.9.9"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_sums(release, asset, digest=None):
    digest = digest or _sha256(release / asset)
    (release / "SHA256SUMS").write_text(
        "%s  %s\n" % (digest, asset), encoding="utf-8"
    )


def _make_windows_zip(release):
    asset = "cyrrus-%s-windows-x64.zip" % VERSION
    with zipfile.ZipFile(release / asset, "w") as archive:
        archive.writestr("cyrrus.exe", b"fake windows binary\n")
        archive.writestr("_internal/data.txt", b"fake data\n")
    _write_sums(release, asset)
    return asset


def _make_linux_tar(release):
    asset = "cyrrus-%s-linux-x64.tar.gz" % VERSION
    with tarfile.open(release / asset, "w:gz") as archive:
        info = tarfile.TarInfo("cyrrus")
        payload = b"#!/bin/sh\necho fake\n"
        info.size = len(payload)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(payload))
        data = b"fake data\n"
        info = tarfile.TarInfo("_internal/data.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    _write_sums(release, asset)
    return asset


def _serve(directory):
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    handler.log_message = lambda *args, **kwargs: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def _release_env(tmp_path, base_url):
    env = dict(os.environ)
    env["CYRRUS_RELEASE_BASE_URL"] = base_url
    env["LOCALAPPDATA"] = str(tmp_path / "localappdata")
    env["HOME"] = str(tmp_path / "home")
    env["USERPROFILE"] = str(tmp_path / "home")
    return env


def _powershell():
    return shutil.which("powershell")


@pytest.mark.skipif(_powershell() is None, reason="Windows PowerShell not available")
def test_powershell_binary_mode_installs_a_verified_archive(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    _make_windows_zip(release)
    server, base_url = _serve(release)
    try:
        env = _release_env(tmp_path, base_url)
        result = subprocess.run(
            [
                _powershell(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PS1),
                "-Binary",
                "-Version",
                VERSION,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    target = tmp_path / "localappdata" / "Programs" / "cyrrus"
    assert (target / "cyrrus.exe").read_bytes() == b"fake windows binary\n"
    assert (target / "_internal" / "data.txt").is_file()
    assert "PATH" in output


@pytest.mark.skipif(_powershell() is None, reason="Windows PowerShell not available")
def test_powershell_binary_mode_rejects_a_bad_checksum(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    asset = _make_windows_zip(release)
    _write_sums(release, asset, digest="0" * 64)
    server, base_url = _serve(release)
    try:
        env = _release_env(tmp_path, base_url)
        result = subprocess.run(
            [
                _powershell(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PS1),
                "-Binary",
                "-Version",
                VERSION,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "checksum" in output.lower()
    target = tmp_path / "localappdata" / "Programs" / "cyrrus"
    assert not (target / "cyrrus.exe").exists()


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")
def test_shell_binary_mode_installs_a_verified_archive(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    _make_linux_tar(release)
    server, base_url = _serve(release)
    try:
        env = _release_env(tmp_path, base_url)
        result = subprocess.run(
            ["sh", str(SH), "--binary", "--version", VERSION],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    target = tmp_path / "home" / ".local" / "bin" / "cyrrus" / "cyrrus"
    assert target.is_file()
    assert os.access(str(target), os.X_OK)
    assert "PATH" in output


@pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh not available")
def test_shell_binary_mode_rejects_a_bad_checksum(tmp_path):
    release = tmp_path / "release"
    release.mkdir()
    asset = _make_linux_tar(release)
    _write_sums(release, asset, digest="0" * 64)
    server, base_url = _serve(release)
    try:
        env = _release_env(tmp_path, base_url)
        result = subprocess.run(
            ["sh", str(SH), "--binary", "--version", VERSION],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )
    finally:
        server.shutdown()
        server.server_close()
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "checksum" in output.lower()
    target = tmp_path / "home" / ".local" / "bin" / "cyrrus" / "cyrrus"
    assert not target.exists()
