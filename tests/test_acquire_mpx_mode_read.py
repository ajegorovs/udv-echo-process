"""Read-boundary tests: the ``mpx-mode-read`` command and the capture field it feeds.

Two boundaries are held here rather than in the pixel tests:

1. the **CLI** reads a *retained* capture directory and nothing else — no window binding, no
   grab, no gesture — and reports the derived mode as a visual attribution;
2. ``channels-read --capture-dir`` grows one **additive** field, ``visual_mode_mark``, which is
   absent unless the capture is ``ok``, still, and cropped to the measured settings popup.

The capture path's own ``status`` semantics are untouched: a clipped entry capture is *not*
declared ``ok`` by this change, and the mode reader refuses to widen any of the five numeric
settings checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from udv_echo_process.acquire import channels_capture, mode_marks

DATA = Path(__file__).parent / "data" / "mpx-mode"


def _run(capsys, argv: list[str]) -> tuple[int, str, str]:
    from udv_echo_process.cli import acquire_main

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(argv)
    captured = capsys.readouterr()
    return int(exit_info.value.code or 0), captured.out, captured.err


def test_cli_reads_the_settings_shape_from_a_retained_capture(capsys):
    code, out, _err = _run(
        capsys,
        ["mpx-mode-read", "--json", "--capture-dir", str(DATA / "disabled-rolling-on")],
    )
    assert code == 0
    report = json.loads(out)
    assert report["surface"] == "SETTINGS_FULL"
    assert report["label"] == "ENABLE_MULTIPLEXER"
    assert report["mode"] == "VISUAL_DISABLED"
    assert report["rolling"] == "ON_PROVEN"
    assert report["native_fact"] is False
    assert report["action_authority"] is False
    assert report["frames_agreed"] is True
    # The read says which boundary produced it: a retained directory is history, not a moment.
    assert report["acquisition_context"] == "retained"
    assert report["freshness"] == "not_established"
    assert report["integrity"] == "decoded-pair-only"
    assert report["enable_precondition"] is False
    # The record carries no path: a portable report must not name the capture machine.
    assert "disabled-rolling-on" not in out


def test_cli_reads_the_clipped_entry_with_no_rolling_state(capsys):
    code, out, _err = _run(
        capsys,
        [
            "mpx-mode-read",
            "--json",
            "--capture-dir",
            str(DATA / "entry-clipped-enabled"),
        ],
    )
    assert code == 0
    report = json.loads(out)
    assert report["surface"] == "MULTIPLEXER_ON_ENTRY"
    assert report["label"] == "DESABLE_MULTIPLEXER"
    assert report["mode"] == "VISUAL_ENABLED"
    assert report["rolling"] == "ABSENT"
    assert report["mark"] == "ABSENT"


def test_cli_refuses_to_capture_on_its_own(capsys):
    code, out, err = _run(capsys, ["mpx-mode-read", "--json"])
    assert code == 2
    assert out.strip() == ""
    assert "--capture-dir" in err


def test_cli_exits_two_when_the_two_frames_are_not_one_state(tmp_path, capsys):
    for name in mode_marks.PAIR_FILES:
        (tmp_path / name).write_bytes(
            (DATA / "disabled-rolling-on" / name).read_bytes()
            if name.endswith("1.png")
            else (DATA / "entry-clipped-enabled" / name).read_bytes()
        )
    code, out, err = _run(
        capsys, ["mpx-mode-read", "--json", "--capture-dir", str(tmp_path)]
    )
    assert code == 2
    assert json.loads(out)["mode"] == "UNKNOWN"
    assert "differ" in err


def test_cli_without_json_prints_the_record_fields(capsys):
    code, out, _err = _run(
        capsys, ["mpx-mode-read", "--capture-dir", str(DATA / "disabled-rolling-off")]
    )
    assert code == 0
    assert "mode" in out and "VISUAL_DISABLED" in out
    assert "OFF_PROVEN" in out


def test_capture_evidence_has_no_mode_read_by_default():
    evidence = channels_capture.CaptureEvidence(
        guards=channels_capture.GuardComparison(
            before=channels_capture.WindowGuard(label="b")
        ),
        numeric=channels_capture.NumericBracketing(),
    )
    assert evidence.visual_mode_mark is None
    assert evidence.status == "UNKNOWN"


def test_only_the_measured_settings_rect_qualifies_for_a_mode_read():
    assert mode_marks.is_settings_rect((0, 0, *mode_marks.SETTINGS_SIZE))
    assert not mode_marks.is_settings_rect((10, 10, 10 + 158, 10 + 43))
    assert not mode_marks.is_settings_rect(None)


def test_a_capture_of_another_shape_carries_its_own_mode_read_not_the_settings_one():
    """The clipped shape is read only through the retained-evidence boundary."""
    record = mode_marks.attribute_capture(DATA / "entry-clipped-enabled")
    assert record.surface == "MULTIPLEXER_ON_ENTRY"
    # No numeric settings bracketing exists on this record, and none is claimed.
    assert "numeric" not in record.model_dump()


def test_channels_read_puts_the_mode_read_beside_the_caption_without_touching_it(
    tmp_path, monkeypatch
):
    """The field is additive: same still pair, same guards, and the caption is untouched."""
    import test_acquire_channels_capture as harness

    from udv_echo_process.acquire import channels_read

    monkeypatch.setattr(
        channels_read, "Win32Actuator", lambda **kwargs: harness.CaptureActuator()
    )
    monkeypatch.setattr(channels_read, "_grab_screen", harness.backend())
    monkeypatch.setattr(channels_read, "_window_state", harness.states())
    monkeypatch.setattr(
        channels_read, "visible_main_windows", lambda *args: (harness.WINDOW,)
    )
    report = channels_read.read_channels(capture_dir=tmp_path)
    assert report.capture is not None
    assert report.capture.status == "ok"
    # The fake backend writes ``b"fake-png"``: the read is attempted from the same pair and
    # refuses the synthetic pixels by name rather than guessing a mode from them.
    attribution = report.capture.visual_mode_mark
    assert attribution is not None
    assert attribution.mode == "UNKNOWN"
    assert attribution.unknown_reasons
    assert attribution.native_fact is False and attribution.action_authority is False
    # The live path says so: these grabs bracket this read on the one bound window, and that
    # is the only reason the record may ever call its freshness live.
    assert attribution.acquisition_context == "live-bracketed"
    assert attribution.integrity == "not_established"  # the synthetic frame was refused
    assert attribution.enable_precondition is False
    # The caption field and its own attribution are exactly what they were.
    assert report.capture.caption == "UNKNOWN"
    assert report.capture.recognition == "NOT_PERFORMED"
