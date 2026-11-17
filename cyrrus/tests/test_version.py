"""Release version must be one consistent, stable string.

Added for the 0.3.0 stable release: a pre-release suffix (``b6``) in any of
the three shipped locations is a release blocker.
"""

import re
from pathlib import Path

import cyrrus

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "0.3.0"


def _pyproject_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version = "([^"]+)"$', text)
    assert match, "pyproject.toml has no project version"
    return match.group(1)


def test_version_is_stable_and_matches_every_shipped_location():
    version = _pyproject_version()
    assert version == EXPECTED, "pyproject.toml version is %r" % version
    assert cyrrus.__version__ == EXPECTED, "__init__.py version is %r" % cyrrus.__version__
    cli_text = (ROOT / "cyrrus" / "cli.py").read_text(encoding="utf-8")
    assert 'version="cyrrus %s"' % EXPECTED in cli_text, "cli.py --version string is stale"
