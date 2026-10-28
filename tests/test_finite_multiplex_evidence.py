"""Offline re-derivation of the finite-MPX artifact, not live-state remeasurement."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.acquire.actuator import StripState
from udv_echo_process.acquire.finite import (
    FiniteAction,
    FiniteObservation,
    FiniteRunReceipt,
    FiniteRunRequest,
    classify_finite_run,
)
from udv_echo_process.io.dop.bdd import read

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/dop3000/evidence/finite-multiplex-live-20261028.json"


@pytest.fixture(scope="module")
def evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bundle(evidence):
    return read(ROOT / evidence["artifact"]["path"])


def test_raw_file_identity_is_not_the_model_recording_identity(evidence, bundle):
    artifact = evidence["artifact"]
    path = ROOT / artifact["path"]
    raw_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert raw_digest == artifact["file_sha256"]
    assert path.stat().st_size == artifact["bytes"]
    assert bundle.recording.recording_id == artifact["recording_id"]
    assert "sha256:" + raw_digest != bundle.recording.recording_id
    assert artifact["acquisition_mode"] == "sequential"
    assert bundle.recording.acquisition_mode.value == artifact["acquisition_mode"]


def test_every_stored_stream_satisfies_the_finite_channel_count_request(
    evidence, bundle
):
    request = evidence["request"]
    streams = bundle.recording.streams
    assert sorted(s.acquisition.channel.device_channel for s in streams) == sorted(
        request["channels"]
    )
    actual = {
        (s.acquisition.channel.device_channel, s.descriptor.quantity.value): s
        for s in streams
    }
    declared = {
        (s["channel"], s["quantity"]): s for s in evidence["artifact"]["streams"]
    }
    assert len(streams) == len(actual) == len(declared) == 2
    assert actual.keys() == declared.keys()
    for key, stream in actual.items():
        assert stream.data.values.shape == (
            request["profiles_per_channel"],
            request["gates_per_channel"],
        )
        assert stream.descriptor.unit == declared[key]["unit"]
        assert declared[key]["profiles"] == request["profiles_per_channel"]
        assert declared[key]["gates"] == request["gates_per_channel"]


def test_native_request_matches_all_decoded_channel_configurations(evidence, bundle):
    request = evidence["request"]
    for stream in bundle.recording.streams:
        config = stream.config
        channel = str(stream.acquisition.channel.device_channel)
        assert config.source_freq_khz == request["source_frequency_khz"]
        assert config.pulse_repetition_freq_hz == pytest.approx(
            1_000_000 / request["prf_us"]
        )
        assert config.emissions_per_profile == request["emissions_per_profile"]
        assert config.burst_length == request["burst_length"]
        assert config.sound_speed_ms == request["sound_speed_ms"]
        assert config.doppler_angle_deg == request["doppler_angle_deg"]
        assert config.emit_power == request["power"]
        assert config.sensitivity == request["sensitivity_by_channel"][channel]
        assert config.n_gates == request["gates_per_channel"]
        declared = next(
            item
            for item in evidence["artifact"]["streams"]
            if item["channel"] == int(channel)
        )
        assert config.model_dump(mode="json") == declared["config"]


def test_time_geometry_and_support_are_rederived_from_the_file(evidence, bundle):
    for stream in bundle.recording.streams:
        declared = next(
            item
            for item in evidence["artifact"]["streams"]
            if item["channel"] == stream.acquisition.channel.device_channel
        )
        times = stream.data.time_s
        gates = stream.data.gate_depths_mm
        dt_ms = np.diff(times) * 1000
        assert np.all(dt_ms > 0)
        assert times[0] == pytest.approx(declared["time"]["first_s"])
        assert times[-1] == pytest.approx(declared["time"]["last_s"])
        assert times[-1] - times[0] == pytest.approx(declared["time"]["span_s"])
        assert np.median(dt_ms) == pytest.approx(declared["time"]["median_dt_ms"])
        assert gates[0] == pytest.approx(declared["gate_depths_mm"]["first"])
        assert gates[-1] == pytest.approx(declared["gate_depths_mm"]["last"])
        assert np.median(np.diff(gates)) == pytest.approx(
            declared["gate_depths_mm"]["median_step_mm"]
        )
        assert stream.data.support.valid.all()
        assert int(stream.data.support.valid.sum()) == declared["observed_cells"]
        assert stream.data.support.valid.size == declared["cells"]
    first, second = sorted(
        bundle.recording.streams, key=lambda s: s.acquisition.channel.device_channel
    )
    assert first.data.time_s[-1] < second.data.time_s[0]


def test_classifier_accepts_the_published_completed_state(evidence):
    """Replay derived scalar facts, not a native call or a proof of live freshness."""
    live = evidence["live_derived"]["enable"]
    configured = evidence["request"]
    completed = live["completed_state"]
    # Synthetic correlation labels exercise the helper's caller-supplied trust boundary.
    token = "fixture:finite-trial-20261028"
    identity = "fixture:same-instance"
    request = FiniteRunRequest(
        channels=tuple(configured["channels"]),
        sequences=configured["sequences"],
        trigger_word=configured["trigger_word_preserved"],
        mode_before=live["mode_before"],
        run_token=token,
    )
    receipt = FiniteRunReceipt(
        run_token=token,
        identity=identity,
        invocations=live["native_returns"],
        pending_after_run=live["pending_returned"],
        record_dispatches=live["record_commands_dispatched"],
        stop_dispatches=live["stop_commands_dispatched"],
    )
    observed = FiniteObservation(
        strip=StripState(**live["completed_strip"]),
        identity=identity,
        error=completed["application_error"] or "",
        mode_after=completed["mode"],
        pending=completed["pending"],
        sequences=completed["sequences"],
        participants=tuple(
            channel for channel in range(1, 11) if completed["mode"] & (8 << channel)
        ),
        current_channel=completed["current_channel"],
        assisted_mode=bool(completed["assisted_mode"]),
        trigger_word=completed["trigger_word"],
        held_block_token=token,
    )
    decision = classify_finite_run(request, receipt, observed)
    assert decision.action is FiniteAction.STORE_COMPLETED
    assert decision.store_token == token
    assert completed["sequences"] == 1  # global count, not arbitrary image word 53


def test_owner_selected_settings_restoration_policy(evidence):
    """The policy decision accepts settings, not fabricated byte identity or cleanup."""
    acceptance = evidence["acceptance"]
    policy = acceptance["restoration_policy"]
    assert acceptance["settings_restoration_accepted"] is True
    assert policy["kind"] == "settings-and-tgc-with-enumerated-runtime-differences"
    assert policy["owner_decision_date"] == "2026-10-28"
    assert policy["raw_byte_identity_required"] is False
    assert policy["allowed_cached_word_indices"] == [52, 53, 83]
    assert policy["allowed_native_mode_difference_bits"] == [21]
    restoration = evidence["live_derived"]["restoration"]
    assert set(restoration["checks"]) == {
        "control_configuration_restored",
        "multiplexing_disabled",
        "all_ten_non_bookkeeping_words_unchanged",
        "all_ten_tgc_tables_unchanged",
        "same_identity",
        "ready_no_error_pending_zero",
        "trigger_unchanged",
    }
    assert all(restoration["checks"].values())
    assert restoration["multiplex_enabled"] is False
    assert restoration["pending"] == 0
    assert restoration["pre_existing_channel4_and_gain10_debt_unchanged"] is True
    assert acceptance["strict_full_image_restoration_accepted"] is False
    assert acceptance["graceful_store_helper_shutdown_accepted"] is False


def test_derived_live_claims_retain_their_limits(evidence):
    """Check declared evidence consistency; this does not remeasure a live application."""
    live = evidence["live_derived"]
    restoration = live["restoration"]
    assert live["enable"]["record_commands_dispatched"] == 0
    assert live["enable"]["stop_commands_dispatched"] == 0
    assert live["enable"]["raw_actor_ok"] is False
    assert live["store"]["stored"] is True
    assert live["store"]["invocations"] == 1
    assert live["store"]["host_sessions_closed"] is True
    assert live["store"]["helper_exit"] == 1
    assert restoration["mode_after"] & 2 == 0
    assert restoration["mode_after"] ^ restoration["mode_before"] == 1 << 21
    assert restoration["raw_byte_identity_restored"] is False
    assert all(
        set(indices) <= {52, 53, 83}
        for indices in restoration["remaining_cache_word_differences"].values()
    )
    acceptance = evidence["acceptance"]
    assert acceptance["finite_artifact_demonstrated"] is True
    assert acceptance["one_command_workflow_accepted"] is False
    assert acceptance["graceful_store_helper_shutdown_accepted"] is False
    assert acceptance["strict_full_image_restoration_accepted"] is False
    assert acceptance["scientific_signal_validity_established"] is False
