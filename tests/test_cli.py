"""CLI tests for ``udv-inspect``: content dispatch and honest failure paths.

PLAN Phase 1 step 10: extend the existing ``udv-inspect`` rather than adding a
new CLI, dispatching by *content* — ``ASCUDOPV`` text through
:func:`parser.extract`, recognized ``BINUDOPV`` bytes through :func:`io.load`,
and a clear non-zero failure for anything else (an image masquerading as a
recording, unknown bytes). No adapter unifies the two result types.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.cli import DEFAULT_TARGET, inspect_main

DATA = Path("data")
ECHO_ADD = DATA / "echo" / "200.ADD"
ECHO_BDD = DATA / "echo" / "200.BDD"
VEL_BDD = DATA / "4-sensor-velocity" / "200RPM.BDD"
MISNAMED_BDD = DATA / "echo-4-sensors-2x2" / "20260723_143754.jpg"
IMAGE = DATA / "echo-4-sensors-2x2" / "300RPM.png"


def test_inspect_add_dispatches_to_extract(capsys):
    inspect_main([str(ECHO_ADD)])
    out = capsys.readouterr().out
    assert "Header: ASCUDOPV4.03.4" in out
    assert "Recording type:  single-sensor" in out
    assert "Channel 4  (echo):" in out


def test_inspect_bdd_dispatches_to_load(capsys):
    inspect_main([str(ECHO_BDD)])
    out = capsys.readouterr().out
    assert "Format: BDD (binary, DOP 3010)" in out
    assert "Acquisition mode: unknown" in out
    assert "Channel 4  (echo_amplitude, module):" in out
    assert "PRF:              8000 Hz" in out


def test_inspect_multichannel_bdd(capsys):
    inspect_main([str(VEL_BDD)])
    out = capsys.readouterr().out
    assert "Acquisition mode: sequential" in out
    for channel in (6, 7, 8, 9):
        assert f"Channel {channel}  (axial_velocity, mm/s):" in out


def test_inspect_misnamed_valid_bdd(capsys):
    """A genuine BDD with a .jpg extension still inspects as a recording."""
    inspect_main([str(MISNAMED_BDD)])
    out = capsys.readouterr().out
    assert "Format: BDD (binary, DOP 3010)" in out
    assert "Channel 6  (echo_amplitude, module):" in out


def test_inspect_image_masquerading_fails(capsys):
    with pytest.raises(SystemExit) as excinfo:
        inspect_main([str(IMAGE)])
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "udv-inspect:" in captured.err


def test_inspect_unknown_bytes_fails(tmp_path, capsys):
    bad = tmp_path / "recording.ADD"
    bad.write_bytes(b"not a udv file at all\n")
    with pytest.raises(SystemExit) as excinfo:
        inspect_main([str(bad)])
    assert excinfo.value.code == 1
    assert "udv-inspect:" in capsys.readouterr().err


def test_inspect_png_named_as_bdd_fails(tmp_path, capsys):
    """The extension is irrelevant: content decides (a PNG named .BDD)."""
    fake = tmp_path / "300RPM.BDD"
    fake.write_bytes(b"\x89PNG\r\n\x1a\n" + IMAGE.read_bytes()[8:])
    with pytest.raises(SystemExit):
        inspect_main([str(fake)])
    assert "udv-inspect:" in capsys.readouterr().err


def test_inspect_default_target(capsys):
    inspect_main([])
    out = capsys.readouterr().out
    assert Path(DEFAULT_TARGET).name in out
    assert "ASCUDOPV" in out


def test_inspect_mixed_reports_good_and_fails_bad(tmp_path, capsys):
    bad = tmp_path / "nope.bin"
    bad.write_bytes(b"\x00\x01\x02\x03")
    with pytest.raises(SystemExit):
        inspect_main([str(ECHO_ADD), str(bad)])
    captured = capsys.readouterr()
    assert "Header: ASCUDOPV4.03.4" in captured.out
    assert "udv-inspect:" in captured.err
