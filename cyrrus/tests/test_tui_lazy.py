"""The UI extra must stay optional.

Core imports and the existing CLI must never import textual or rich.  When the
extra is missing, ``cyrrus ui`` must fail with one clear install message.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

BLOCKER = r"""
import sys

class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("textual", "rich"):
            raise ImportError("blocked optional dependency: " + name)
        return None

sys.meta_path.insert(0, _Block())
"""


def run_python(code, cwd):
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-c", BLOCKER + code],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )


def test_import_cyrrus_does_not_import_textual_or_rich(tmp_path):
    result = run_python(
        "import cyrrus\n"
        "assert 'textual' not in sys.modules, 'textual imported by cyrrus'\n"
        "assert 'rich' not in sys.modules, 'rich imported by cyrrus'\n"
        "print('clean')\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_doctor_works_and_stays_lazy_without_textual(tmp_path):
    result = run_python(
        "from cyrrus.cli import main\n"
        "main(['doctor', '--json'])\n"
        "assert 'textual' not in sys.modules, 'textual imported by doctor'\n"
        "assert 'rich' not in sys.modules, 'rich imported by doctor'\n",
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert '"overall_status"' in result.stdout


def test_ui_without_extra_prints_install_command_and_exits_1(tmp_path):
    result = run_python(
        "from cyrrus.cli import main\n"
        "try:\n"
        "    main(['ui'])\n"
        "except SystemExit as exc:\n"
        "    raise SystemExit(exc.code)\n",
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 1, combined
    assert 'pip install "cyrrus[ui]"' in combined, combined
