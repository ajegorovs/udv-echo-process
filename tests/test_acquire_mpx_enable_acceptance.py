"""Offline: the acceptance probe's **baseline claim**, derived from presses, never pre-written.

The live run ``enabled-clipped-acceptance-01`` refused at its preflight (the measured Channels
hover read ``ABSENT`` after 7 reads, zero presses) and its report still carried the static
"the multiplexer is enabled and idle … baseline 'off' restore" clause, which reads as if the probe
had enabled the multiplexer. Nothing had been pressed. These tests pin the derived rule: zero
presses state ``UNKNOWN`` and owe nothing, a possibly-started gesture without a proven mode states
a *pending conditional* obligation, and only this run's own fresh ``VISUAL_ENABLED`` capture makes
the concrete ``off`` restore owed.

The historical report on disk is evidence and is never rewritten by this module or by the probe.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

PROBE = REPO / "tools" / "live" / "probes" / "mpx_enable_close_acceptance.py"


def _probe():
    spec = importlib.util.spec_from_file_location("mpx_enable_close_acceptance", PROBE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["mpx_enable_close_acceptance"] = module
    spec.loader.exec_module(module)
    return module


def test_zero_presses_state_unknown_and_owe_nothing() -> None:
    probe = _probe()
    state, owed, note = probe.restoration_view("not_attempted", "UNKNOWN")

    assert state == "UNKNOWN"
    assert owed == []
    assert "zero settings presses" in note
    assert "enabled and idle" not in note
    assert "restore is the parent's separate step" not in note


def test_a_possibly_started_gesture_without_a_proven_mode_is_pending_conditional() -> (
    None
):
    probe = _probe()
    state, owed, note = probe.restoration_view("may_have_been_attempted", "UNKNOWN")

    assert state == "PENDING_CONDITIONAL"
    assert len(owed) == 1
    assert "UNKNOWN" in owed[0]
    assert "UNKNOWN" in note
    assert not any("enabled and idle" in clause for clause in owed)


def test_only_a_proven_enabled_mode_owes_the_concrete_restore() -> None:
    probe = _probe()
    state, owed, note = probe.restoration_view(
        "may_have_been_attempted", "VISUAL_ENABLED"
    )

    assert state == "OWED"
    assert list(owed) == list(probe.RESTORATION_OWED)
    assert any("baseline 'off' restore" in clause for clause in owed)
    assert "VISUAL_ENABLED" in note


def test_a_zero_press_refusal_report_never_claims_the_multiplexer_is_enabled(
    capsys, tmp_path
) -> None:
    """The measured failure, offline: a refused preflight writes a zero-obligation report."""
    probe = _probe()
    relative = Path("relative-root-that-is-refused")

    code = probe.main(["--root", str(relative)])
    printed = json.loads(capsys.readouterr().out)

    assert code == 3
    assert printed["phase"] == "refused"
    assert printed["press"] == "not_attempted"
    assert printed["restoration_state"] == "UNKNOWN"
    assert printed["restoration_owed"] == []
    assert "enabled and idle" not in json.dumps(printed)
    assert "zero settings presses" in printed["restoration_note"]
    assert not (relative / "report.json").exists()  # a refusal creates nothing


def test_the_durable_pre_gesture_report_states_unknown_and_nothing_owed(
    tmp_path,
) -> None:
    probe = _probe()
    report = tmp_path / "report.json"
    payload = {
        "phase": "pending",
        "press": "not_attempted",
        "mode_after": "UNKNOWN",
    }
    probe._sync_restoration(payload)
    probe._write(report, payload)
    written = json.loads(report.read_text(encoding="utf-8"))

    assert written["restoration_state"] == "UNKNOWN"
    assert written["restoration_owed"] == []


def test_a_refusal_after_the_enable_child_keeps_the_mode_and_owes_the_restore(
    tmp_path,
) -> None:
    probe = _probe()
    report = tmp_path / "report.json"
    payload = {
        "phase": "pending",
        "press": "may_have_been_attempted",
        "mode_after": "VISUAL_ENABLED",
    }

    probe._finish(
        report,
        payload,
        "refused",
        refused="identity drift",
        press="may_have_been_attempted",
    )
    written = json.loads(report.read_text(encoding="utf-8"))

    assert written["mode_after"] == "VISUAL_ENABLED"  # not rewritten as UNKNOWN
    assert written["restoration_state"] == "OWED"
    assert any(
        "baseline 'off' restore" in clause for clause in written["restoration_owed"]
    )


def test_the_report_records_the_starting_pointer_and_the_park() -> None:
    probe = _probe()
    opened = SimpleNamespace(
        outcome=SimpleNamespace(value="unknown"),
        reads=7,
        initial_cursor=(561, 40),
        pre_move={"from": [561, 40], "to": [600, 61], "moves": 1},
        clause="the hover produced 'absent'",
    )

    facts = probe._open_facts(opened)

    assert facts["initial_cursor"] == [561, 40]  # the fact the live run did not log
    assert facts["pre_move"]["moves"] == 1
    assert facts["reads"] == 7
    assert probe._open_facts(None) is None


def test_the_probe_writes_no_restoration_before_it_states_a_press() -> None:
    probe = _probe()
    source = PROBE.read_text(encoding="utf-8")

    # The constant may only enter a report through the derived view.
    assert source.count("list(RESTORATION_OWED)") == 1
    assert probe.RESTORATION_OWED
