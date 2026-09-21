"""Tests for the supported live commands: the read-only surface, the preflight, the CLI.

The driver-level cases run against the same fake the driver's own tests use
(:class:`FakeUdopWindow` through :class:`FakeDriver`), because the point of the seam is that a
*faked* actuator satisfies it — that is what makes these commands testable off the instrument at
all. The command-level cases go one step further and replace the actuator, because what the CLI
owes a caller is its argument handling and its exit codes, not the cycle it delegates to.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_acquire_driver import STORE_THREE, FakeUdopWindow, fake_driver

from udv_echo_process.acquire import driver, live
from udv_echo_process.acquire.actuator import (
    PreflightReport,
    ScreenFingerprint,
)
from udv_echo_process.cli import acquire_main

#: The stored point the repository already carries, with a known channel block.
FIXTURE = Path("data/dop3010-velocity/sim-label-2.BDD")


class _SpyActuator:
    """Records what a command asked of the driver, and answers what a test scripts."""

    def __init__(self, *, store: tuple[bool, Path | str] = (True, Path("x.BDD"))) -> None:
        self.store = store
        self.calls: list[tuple] = []

    def screen_fingerprint(self) -> ScreenFingerprint:
        self.calls.append(("screen_fingerprint",))
        return _fingerprint()

    def ensure_channel(self) -> int:
        """The routing step: ``channel`` verifies the measurement channel through it."""
        self.calls.append(("ensure_channel",))
        return 1

    def try_record_and_store(
        self,
        name: str,
        duration_s: float,
        directory: Path,
        *,
        expected_mode: object = None,
    ) -> tuple[bool, Path | str]:
        stated = getattr(expected_mode, "value", expected_mode)
        self.calls.append(("try_record_and_store", name, duration_s, str(directory), stated))
        return self.store

    def preflight(self, duration_s: float, *, expect_directory: Path | None = None):
        self.calls.append(("preflight", duration_s, expect_directory))
        return _preflight()


def _fingerprint() -> ScreenFingerprint:
    return ScreenFingerprint(
        class_name="TMain_Scr",
        hwnd=1,
        rect=(-8, -8, 1928, 1058),
        maximized=True,
        screen=(1920, 1080),
        panels=4,
        visible_controls=43,
        strip={"button_count": 3, "has_slider": False, "slider_max": None},
        overlay=None,
        layout_note=None,
        cursor=(1268, 676),
        is_foreground=True,
    )


def _preflight() -> PreflightReport:
    return PreflightReport(
        started_from="ready",
        view_after_record="recording",
        held_s=2.0,
        view_after_stop="store",
        view_after_cancel="ready",
        channel=1,
        store_dialog_size="584x330",
        store_dialog_children=7,
    )


def _spy(monkeypatch: pytest.MonkeyPatch, **kwargs) -> _SpyActuator:
    spy = _SpyActuator(**kwargs)
    monkeypatch.setattr(live, "live_actuator", lambda *a, **k: spy)
    return spy


# ------------------------------------------------------------------ the read-only surface


def test_a_fingerprint_reads_the_screen_without_pressing_anything() -> None:
    """It is safe on an instrument someone else is using: nothing is pressed, nothing written."""
    actuator, app = _driver()

    fingerprint = actuator.screen_fingerprint()

    assert fingerprint.class_name == "TMain_Scr"
    assert fingerprint.strip == actuator.strip_state()
    assert fingerprint.screen[0] > 0 and fingerprint.screen[1] > 0
    # Self-consistent with the primitives the driver already has, rather than with this
    # install's numbers: 43 controls in 4 panels here is a *fact about this machine*
    # (docs/dop3000/live-bringup.md §4), not part of the contract.
    roles = actuator._resolve()
    assert fingerprint.visible_controls == len(roles["raw"])
    assert fingerprint.panels == len(roles["panels"])
    assert fingerprint.overlay is None
    assert [event for event in app.events if event[0] == "press"] == []  # nothing was pressed


def test_a_fingerprint_carries_the_layout_note_when_the_screen_is_not_the_measurement_one() -> (
    None
):
    """The field a bring-up reads first: is this a screen a run may start on, and if not why.

    The fake's own overlay is pre-created and hidden, and its visibility model is what the
    overlay detector reads — so the overlay *field* is exercised on the instrument (the live
    preflight reads a real Store dialog through the same detector) rather than here.
    """
    actuator, _ = _driver()

    fingerprint = actuator.screen_fingerprint()

    # A fingerprint may not report a screen the guard would refuse to start on, and vice versa:
    # it carries the guard's own verdict rather than a second opinion about it. The *unclean*
    # screen — a modal left up, an assisted-mode channel — is read on the instrument, where the
    # note names what is wrong (docs/dop3000/live-bringup.md stage 1).
    assert fingerprint.layout_note == actuator.layout_note()


def test_a_fingerprint_survives_a_cursor_this_session_cannot_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent's own shell runs in a service session, where ``GetCursorPos`` fails (1459)."""
    actuator, _ = _driver()

    def refuse() -> tuple[int, int]:
        raise OSError(1459, "This operation requires an interactive window station")

    monkeypatch.setattr(actuator, "_cursor_position", refuse)

    fingerprint = actuator.screen_fingerprint()

    assert fingerprint.cursor is None
    assert fingerprint.visible_controls > 0  # ...and everything else was still read


# --------------------------------------------------------------------------- the preflight


def test_a_preflight_runs_a_cycle_and_stores_nothing() -> None:
    """The operator's sequence with the dangerous step removed: the dialog's LEFT button."""
    actuator, app = _driver()

    report = actuator.preflight(0.05)

    assert report.view_after_record == "recording"
    assert report.view_after_stop == "store"
    assert report.held_s == 0.05
    assert report.store_dialog_children is not None
    assert report.store_dialog_size == "560x300"
    assert report.store_name is not None  # the dialog was read, not guessed at
    assert report.view_after_cancel  # the view after the cancel is reported, whatever it is
    # Nothing was committed. Asserted on the event the store path itself raises, because the
    # fake leaves its dialog model open across the cancel — its limitation, not the driver's.
    assert [event for event in app.events if event[0] == "stored"] == []


def test_a_preflight_clears_a_leftover_store_view_first() -> None:
    """A stopped recording leaves the store view up, and a point may not start from it."""
    actuator, app = _driver()
    app.strip = STORE_THREE  # a stopped recording left the store view up

    report = actuator.preflight(0.05)

    assert report.started_from == "store"
    assert any("leftover store view" in note for note in report.notes)
    assert report.view_after_stop == "store"


def test_a_preflight_reports_a_directory_that_is_not_what_was_expected(tmp_path: Path) -> None:
    """It compares the dialog's directory and never writes it — that is the cycle's job."""
    actuator, app = _driver()
    app.directory = "C:\\some\\where"  # what the dialog would show

    matched = actuator.preflight(0.05, expect_directory=Path("C:/some/where"))
    missed = actuator.preflight(0.05, expect_directory=tmp_path / "somewhere-else")

    assert matched.store_working_directory == "C:\\some\\where"
    assert matched.working_directory_matches is True  # same directory, different spelling
    assert missed.working_directory_matches is False


# ------------------------------------------------------------------------------- the CLI


def test_status_prints_a_report_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _spy(monkeypatch)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["status"])

    assert exit_info.value.code == 0
    assert "TMain_Scr" in capsys.readouterr().out


def test_status_json_is_the_only_thing_on_stdout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A machine reads the report; notes go to stderr so they cannot corrupt it."""
    _spy(monkeypatch)

    with pytest.raises(SystemExit):
        acquire_main(["status", "--json"])

    captured = capsys.readouterr()
    assert json.loads(captured.out)["class_name"] == "TMain_Scr"


def test_a_point_passes_its_name_duration_and_directory_to_the_cycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spy = _spy(monkeypatch)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "point",
                "bringup-01",
                "--seconds",
                "3",
                "--store-dir",
                str(tmp_path),
                "--channel",
                "2",
                "--expect-mode",
                "instrument",
            ]
        )

    assert exit_info.value.code == 0
    # The declared process reaches the cycle too: the record path is handed the expectation on
    # every call (plan §24.4), and a CLI that took the flag and dropped it would pass this only
    # if the assertion did not carry it.
    assert spy.calls == [
        ("try_record_and_store", "bringup-01", 3.0, str(tmp_path), "instrument")
    ]


def test_a_refused_point_exits_one(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _spy(monkeypatch, store=(False, "the working directory is not the one asked for"))

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "point",
                "x",
                "--seconds",
                "3",
                "--store-dir",
                str(tmp_path),
                "--expect-mode",
                "simulation",
            ]
        )

    assert exit_info.value.code == 1


def test_a_sweep_needs_its_ladder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The rungs are the axis: a sweep without them is a usage error, not a default."""
    _spy(monkeypatch)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "sweep",
                "--seconds",
                "3",
                "--store-dir",
                str(tmp_path),
                "--expect-mode",
                "simulation",
            ]
        )

    assert exit_info.value.code == 2


def test_the_store_directory_must_be_named_somewhere(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never a default: the cycle writes the dialog's directory when it differs."""
    _spy(monkeypatch)
    monkeypatch.delenv("UDV_STORE_DIR", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["point", "x", "--seconds", "3", "--expect-mode", "simulation"])

    assert exit_info.value.code == 2
    assert "UDV_STORE_DIR" in capsys.readouterr().err


def test_decode_reads_a_stored_file(capsys: pytest.CaptureFixture[str]) -> None:
    """The certificate path works off the instrument: the file is the authority."""
    pytest.importorskip("numpy")
    assert FIXTURE.is_file(), f"the repository fixture moved: {FIXTURE}"

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["decode", str(FIXTURE), "--channel", "1"])

    assert exit_info.value.code == 0
    assert "depth_mm" in capsys.readouterr().out


#: A driver refusal in the driver's own words: the foreground precondition, measured live
#: 2026-09-17. It is the refusal the first live `acquire compile` hit on a non-foreground
#: application (plan §16.2); these verbs drive the same driver and reach it before anything is
#: printed, so they answer it the way the campaign verbs do (``test_acquire_campaign``).
REFUSAL = (
    "the 'TMain_Scr' window is not the foreground window, so its menubar cannot be hovered"
)


def _refuse(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    """Make the actuator's own ``method`` refuse, the way the driver refuses."""
    spy = _SpyActuator()

    def refuse(*args: object, **kwargs: object) -> object:
        raise driver.AcquisitionError(REFUSAL)

    monkeypatch.setattr(spy, method, refuse)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: spy)


@pytest.mark.parametrize(
    ("argv", "method"),
    [
        (["status"], "screen_fingerprint"),
        (["channel", "1"], "ensure_channel"),
        (["preflight", "--seconds", "1"], "preflight"),
    ],
)
def test_a_driver_refusal_is_one_line_and_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    method: str,
) -> None:
    """A refused step is a refusal, not a crash: one ``udv-acquire:`` line, exit 2, no traceback.

    These three verbs have no handler of their own, so a driver refusal used to leave
    ``acquire_main`` as an exception — a traceback and exit 1, which says "crash" about a run
    that never started. The answer has to be the one the campaign verbs give (§16.2): the
    driver's own words on one line, and exit 2, because every other refusal on this surface
    returns 2 and this is one.
    """
    _refuse(monkeypatch, method)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(argv)

    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"udv-acquire: {REFUSAL}\n"  # one line: no traceback, no re-wrap


# --------------------------------------------------------------------------- module dispatch


def test_the_module_dispatcher_names_every_command() -> None:
    """`python -m udv_echo_process.cli <command>` is the form the live dispatcher uses."""
    from udv_echo_process import cli

    # WP0, WP1 and WP2 add the read-only analysis verbs beside the four live ones,
    # and the sparse pass adds its ingest and its two measurement slices beside them.
    assert set(cli._COMMANDS) == {
        "acquire",
        "burst-ladder",
        "gain-power-screen",
        "inspect",
        "prf-ladder",
        "reference-repeat",
        "resolution-ladder",
        "run-all",
        "sparse-anchor-floor",
        "sparse-decision",
        "sparse-emissions-ladder",
        "sparse-inventory",
        "sparse-pitch-burst",
        "sparse-reference-floor",
        "sweep-inventory",
        "viz",
    }


def test_the_module_dispatcher_refuses_an_unknown_command() -> None:
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, "-m", "udv_echo_process.cli", "not-a-command"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert done.returncode == 2
    assert "usage: python -m udv_echo_process.cli" in done.stderr


def _driver() -> tuple[object, FakeUdopWindow]:
    """A driver over the fake window the driver's own tests use, in its clean state."""
    app = FakeUdopWindow(channel=1)
    return fake_driver(app, channel=1), app
