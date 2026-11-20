"""Hidden --dump-frame hook: deterministic frames without pyte."""
from __future__ import annotations

import sys

import pytest

from cyrrus.cli import build_parser, main


def test_dump_frame_prints_a_size_exact_screen(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["ui", "--dump-frame", "gallery", "--size", "100x30"])
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    rows = out.splitlines()
    assert len(rows) == 30
    assert all(len(row) == 100 for row in rows), [len(row) for row in rows]
    assert "SESSIONS" in rows[2]
    assert "work" in out


def test_dump_frame_rejects_unknown_screen(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["ui", "--dump-frame", "nope", "--size", "80x24"])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "nope" in combined


def test_dump_flags_are_hidden_from_help():
    help_text = build_parser().format_help()
    assert "--dump-frame" not in help_text
