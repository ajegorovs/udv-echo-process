"""Portable checks of the real packaged recording and qualified foreground evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from udv_echo_process.io.dop.bdd import read

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/dop3000/evidence/finite-packaged-covered-20261029.json"


def test_packaged_recording_original_bytes_and_decoded_streams():
    evidence = json.loads(EVIDENCE.read_text())
    path = ROOT / evidence["artifact"]["path"]
    raw = path.read_bytes()
    assert len(raw) == evidence["artifact"]["bytes"] == 32616
    assert hashlib.sha256(raw).hexdigest() == evidence["artifact"]["sha256"]
    bundle = read(path)
    observed = {
        (s.acquisition.channel.device_channel, s.descriptor.quantity.value): (
            s.data.values.shape,
            s.config.source_freq_khz,
        )
        for s in bundle.recording.streams
    }
    assert observed == {
        (1, "axial_velocity"): ((5, 80), 4000),
        (2, "axial_velocity"): ((5, 80), 4000),
    }


def test_packaged_receipts_and_independent_final_are_explicit():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["cli_exit"] == 0
    assert evidence["outcome"] == "stored_and_restored"
    assert evidence["restoration_owed"] is False
    assert evidence["command_receipts"] == {
        "invocations": 1,
        "pending_after_run": 5,
        "record_dispatches": 0,
        "stop_dispatches": 0,
    }
    assert evidence["configure_phases"] == 3
    assert evidence["restore_phases"] == 7
    assert evidence["store_invocations"] == 1
    final = evidence["independent_final"]
    assert final["ready"] and final["multiplexing_disabled"]
    assert (final["pending"], final["current_channel"], final["repeat_count"]) == (
        0,
        1,
        10,
    )
    assert final["same_identity"] and final["native_words_equal"]
    assert final["ten_parameter_images_equal"] and final["ten_tgc_tables_equal"]
    for field in ("parameter_image_sha256", "tgc_sha256"):
        assert set(final[field]) == {str(c) for c in range(1, 11)}
        assert all(len(bytes.fromhex(value)) == 32 for value in final[field].values())


def test_raw_phase_and_store_cleanup_acceptance_is_not_empty():
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["independent_adjudication"] == "accepted-offline-from-raw-captures"
    phases = evidence["native_phases"]
    assert len(phases) == 11
    assert sum(p["native_calls"] for p in phases) == 19
    assert all(
        p["native_calls"] == p["native_returns"]
        and p["native_calls"] > 0
        and p["hooks_removed"] is True
        and p["attachment_exit"] == 0
        and len(bytes.fromhex(p["executed_script_sha256"])) == 32
        for p in phases
    )
    assert [p["phase"] for p in phases if not p["legacy_aggregate_ok"]] == [
        "02-finite-run",
        "04-restore-4-route",
    ]
    assert next(p for p in phases if p["phase"] == "02-finite-run")["native_calls"] == 1
    cleanup = evidence["cleanup"]
    assert cleanup["sessions_opened"] == 1 and cleanup["closed"]
    assert cleanup["hook_count"] == cleanup["hooks_detached"] == 2
    assert cleanup["helper_exits"] == cleanup["attach_exits"] == [0]
    assert cleanup["helper_killed"] is False
    assert cleanup["cleanup_errors"] == cleanup["close_problems"] == []
    assert cleanup["elapsed_ms"] < cleanup["exit_timeout_ms"]


def test_console_exceptions_are_not_hidden_as_continuous_explorer_foreground():
    foreground = json.loads(EVIDENCE.read_text())["foreground"]
    assert foreground["classes"] == {"CabinetWClass": 2384, "ConsoleWindowClass": 3}
    assert sum(foreground["classes"].values()) == foreground["samples"] == 2387
    assert foreground["initial_explorer_maximized"]
    assert foreground["same_foreground_every_sample"] is False
    assert foreground["udop_foreground_observed"] is False
    assert foreground["monitor_joined"]
    assert "unsampled" in foreground["limitation"]
