r"""Ensure no invalid escape sequences lurk in package source.

Compiles every .py file in the cyrrus package with SyntaxWarning promoted to an
error, so invalid escape sequences (for example r"\c" in a docstring) can never
be reintroduced without failing the test suite.
"""

from __future__ import annotations

import pathlib
import warnings

import pytest

PACKAGE_DIR = pathlib.Path(__file__).resolve().parent.parent / "cyrrus"


def _package_py_files() -> list[pathlib.Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


@pytest.mark.parametrize(
    "path",
    _package_py_files(),
    ids=lambda p: str(p.relative_to(PACKAGE_DIR)),
)
def test_no_invalid_escape_sequences(path: pathlib.Path) -> None:
    source = path.read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        compile(source, str(path), "exec")
