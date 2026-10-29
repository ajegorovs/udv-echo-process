"""Re-derive the actual BDD; check, but do not remeasure, derived live observations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.acquire import RUN_ARM_BIT, StripState
from udv_echo_process.io.dop.bdd import read

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/dop3000/evidence/finite-operator-sitting-20261028.json"


@pytest.fixture(scope="module")
def evidence() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bundle(evidence):
    return read(ROOT / evidence["artifact"]["path"])


def test_second_actual_file_and_recording_identities(evidence, bundle) -> None:
    artifact = evidence["artifact"]
    path = ROOT / artifact["path"]
    raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert raw_hash == artifact["file_sha256"]
    assert path.stat().st_size == artifact["bytes"] == 32616
    assert bundle.recording.recording_id == artifact["recording_id"]
    assert bundle.recording.recording_id != "sha256:" + raw_hash


def test_complete_requested_channel_quantity_geometry_and_config(
    evidence, bundle
) -> None:
    request = evidence["request"]
    streams = bundle.recording.streams
    assert len(streams) == 2
    assert sorted(s.acquisition.channel.device_channel for s in streams) == [1, 2]
    assert bundle.recording.acquisition_mode.value == "sequential"
    for stream in streams:
        assert stream.descriptor.quantity.value == request["quantity"]
        assert stream.descriptor.unit == "mm/s"
        assert stream.data.values.shape == (5, 80)
        assert stream.config.source_freq_khz == request["frequency_khz"]
        assert stream.config.pulse_repetition_freq_hz == pytest.approx(
            1_000_000 / request["prf_us"]
        )
        assert stream.config.emissions_per_profile == request["emissions_per_profile"]
        assert stream.data.support.valid.all()


def test_stream_facts_and_signal_limits_are_rederived(evidence, bundle) -> None:
    declared = {s["channel"]: s for s in evidence["artifact"]["streams"]}
    for stream in bundle.recording.streams:
        facts = declared[stream.acquisition.channel.device_channel]
        np.testing.assert_allclose(stream.data.time_s, facts["time_s"])
        np.testing.assert_allclose(stream.data.gate_depths_mm, facts["gate_depths_mm"])
        assert stream.config.model_dump(mode="json") == facts["config"]
        assert int(np.count_nonzero(stream.data.values)) == facts["nonzero_cells"]
    assert declared[2]["nonzero_cells"] == 0
    assert evidence["acceptance"]["flow_signal_validity"] is False


def test_owner_retained_settings_are_not_historical_restoration(evidence) -> None:
    decisions = evidence["owner_decisions"]
    assert decisions["channel10"]["assisted_observed_by_operator"] is False
    assert decisions["channel10"]["tgc_mode"] == "auto"
    assert decisions["channel10"]["gain_db_retained"] == 60
    assert decisions["channel4"]["assisted_retained"] is True
    assert decisions["historical_values_restored"] is False
    assert decisions["assisted_tgc_transition_traced"] is False


def test_cleanup_requires_real_receipt_and_own_exit_not_closed_flag(evidence) -> None:
    cleanup = evidence["cleanup"]
    receipt = cleanup["detach_receipt"]
    assert receipt["calls"] == 1
    assert receipt["hooks_removed"] is True
    assert receipt["hooks_detached"] == receipt["hook_count"] > 0
    assert receipt["cleanup_ok"] is True
    assert receipt["cleanup_errors"] == []
    assert receipt["restoration_owed"] is False
    assert cleanup["helper"] == {"exited": True, "code": 0, "killed": False}
    assert cleanup["cli_cleanup_error"] is None
    assert cleanup["host_close_problem"] is None
    assert cleanup["reasons"] == []
    assert cleanup["steps"] == [
        "detach_requested",
        "detach_acknowledged",
        "helper_exited",
        "evidence_clean",
    ]
    assert cleanup["host_descriptor_refusal_lease"]["native_calls"] == 0


def test_derived_restoration_and_recovery_limits_remain_explicit(evidence) -> None:
    restoration = evidence["restoration"]
    assert all(restoration["checks"].values())
    assert restoration["before_words"] == restoration["final_words"]
    words = restoration["final_words"]
    assert not words["Mpx_Mode"] & RUN_ARM_BIT
    assert words["Current_Channel"] == 1
    assert words["Mpx_Nb_Sequences"] == 10
    assert words["pending"] == 0
    assert StripState.model_validate(restoration["final_strip"]).view.value == "ready"
    assert restoration["raw_byte_equality_required"] is False
    assert evidence["execution"]["native_run_calls"] == 1
    assert evidence["execution"]["explicit_record_calls"] == 0
    assert evidence["execution"]["explicit_stop_calls"] == 0
    assert evidence["execution"]["recovery_required"] is True
    assert evidence["acceptance"]["one_command_workflow"] is False
