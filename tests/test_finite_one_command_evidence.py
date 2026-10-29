"""Rederive BDD facts; check (not remeasure) retained one-command live observations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.acquire import RUN_ARM_BIT, StripState
from udv_echo_process.io.dop.bdd import read

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/dop3000/evidence/finite-one-command-20261029.json"


@pytest.fixture(scope="module")
def evidence() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bundle(evidence):
    return read(ROOT / evidence["artifact"]["path"])


def test_actual_file_and_model_identities(evidence, bundle) -> None:
    artifact = evidence["artifact"]
    path = ROOT / artifact["path"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == artifact["file_sha256"]
    assert digest == "73e462f145ea6d4561b387da947347a6c62a61bc9a02f954401e27f7e20ed5aa"
    assert path.stat().st_size == artifact["bytes"] == 32616
    assert bundle.recording.recording_id == artifact["recording_id"]
    assert bundle.recording.recording_id != "sha256:" + digest


def test_requested_geometry_configuration_and_signal_facts(evidence, bundle) -> None:
    request = evidence["request"]
    facts = {s["channel"]: s for s in evidence["artifact"]["streams"]}
    assert set(facts) == set(request["channels"]) == {1, 2}
    assert len(bundle.recording.streams) == 2
    assert bundle.recording.acquisition_mode.value == "sequential"
    for stream in bundle.recording.streams:
        observed = facts[stream.acquisition.channel.device_channel]
        assert stream.data.values.shape == tuple(observed["shape"]) == (5, 80)
        assert (
            stream.descriptor.quantity.value == request["quantity"] == "axial_velocity"
        )
        assert stream.descriptor.unit == observed["unit"] == "mm/s"
        assert stream.config.source_freq_khz == request["frequency_khz"] == 4000
        assert stream.config.pulse_repetition_freq_hz == pytest.approx(
            1_000_000 / request["prf_us"]
        )
        assert stream.config.emissions_per_profile == request["emissions_per_profile"]
        assert stream.config.model_dump(mode="json") == observed["config"]
        np.testing.assert_allclose(stream.data.time_s, observed["time_s"])
        np.testing.assert_allclose(
            stream.data.gate_depths_mm, observed["gate_depths_mm"]
        )
        assert int(np.count_nonzero(stream.data.values)) == observed["nonzero_cells"]
        assert stream.data.support.valid.all() and observed["all_observed"]
    assert facts[1]["nonzero_cells"] == 33
    assert facts[2]["nonzero_cells"] == 0


def test_derived_same_command_execution_and_all_native_phases(evidence) -> None:
    execution = evidence["execution"]
    assert execution["outcome"] == "stored_and_restored"
    assert execution["command_exit"] == 0
    assert execution["native_run_calls"] == 1
    assert execution["explicit_record_calls"] == execution["explicit_stop_calls"] == 0
    assert execution["store_invocations"] == execution["store_native_calls"] == 1
    assert execution["recovery_required"] is False
    assert execution["operator_recovery_requested"] is False
    assert len(execution["configure"]) == 3
    assert len(execution["restore"]) == 7
    expected = {
        "01-configure-1-participants": 1,
        "01-configure-2-count": 2,
        "01-configure-3-flag": 2,
        "02-finite-run": 1,
        "04-restore-1-count": 2,
        "04-restore-2-flag": 2,
        "04-restore-3-participants": 1,
        "04-restore-4-route": 2,
        "04-restore-5-refresh": 2,
        "04-restore-6-refresh": 2,
        "04-restore-7-refresh": 2,
    }
    phases = execution["native_phases"]
    assert len(phases) == len(expected)
    assert {p["phase"]: p["native_calls"] for p in phases} == expected
    for phase in phases:
        assert phase["native_returns"] == phase["native_calls"]
        assert phase["attachment_exit"] == 0
        assert phase["detached"] is True
    # Preserve the original carrier's reporting limits rather than rewriting them to green.
    assert {p["phase"] for p in phases if not p["legacy_aggregate_ok"]} == {
        "02-finite-run",
        "04-restore-4-route",
    }


def test_derived_cleanup_is_receipted_not_merely_closed(evidence) -> None:
    cleanup = evidence["cleanup"]
    assert cleanup["sessions_opened"] == 1
    assert cleanup["steps"] == [
        "detach_requested",
        "detach_acknowledged",
        "helper_exited",
        "evidence_clean",
    ]
    receipt = cleanup["detach_receipt"]
    assert receipt["calls"] == 1
    assert receipt["hooks_removed"] is True
    assert receipt["hooks_detached"] == receipt["hook_count"] == 2
    assert receipt["cleanup_ok"] is True
    assert receipt["cleanup_errors"] == []
    assert receipt["restoration_owed"] is False
    assert cleanup["helper"] == {"exited": True, "code": 0, "killed": False}
    assert cleanup["cli_cleanup_error"] is None
    assert cleanup["host_close_problem"] is None
    assert cleanup["reasons"] == []


def test_derived_independent_final_state_and_restoration(evidence) -> None:
    restoration = evidence["restoration"]
    checks = restoration["checks"]
    assert set(checks) == {
        "controls_restored",
        "multiplexing_disabled",
        "participants_restored",
        "trigger_unchanged",
        "same_identity",
        "ready_pending_zero_no_error",
        "all_ten_tgc_unchanged",
        "only_cached_words_differ",
    }
    assert all(checks.values())
    assert restoration["all_ten_parameter_images_equal_to_fresh_trial_baseline"] is True
    assert restoration["all_ten_tgc_equal"] is True
    assert restoration["before_words"] == restoration["final_words"]
    words = restoration["final_words"]
    assert not words["Mpx_Mode"] & RUN_ARM_BIT
    assert (words["Current_Channel"], words["Mpx_Nb_Sequences"], words["pending"]) == (
        1,
        10,
        0,
    )
    assert StripState.model_validate(restoration["final_strip"]).view.value == "ready"
    assert restoration["final_error"] is restoration["final_overlay"] is None
    assert restoration["changed_cached_words"] == {}
    assert restoration["same_identity"] is True
    assert restoration["raw_byte_equality_required"] is False


def test_acceptance_does_not_extend_to_unmeasured_boundaries(evidence) -> None:
    acceptance = evidence["acceptance"]
    assert acceptance["one_command_execution_demonstrated"] is True
    assert (
        acceptance["independent_adjudication"] == "accepted-offline-from-raw-captures"
    )
    for field in (
        "flow_signal_validity",
        "occluded_window_trial_this_sitting",
        "software_abort_demonstrated",
        "public_cli_promoted",
    ):
        assert acceptance[field] is False
    assert evidence["authorization"]["physical_fallback_confirmed"] is True
    assert "private retained captures" in evidence["limits"]
