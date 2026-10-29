"""Offline production-coordinator tests; only the machine backend is a labelled double."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire.finite_workflow import (
    FiniteChannel,
    FiniteInvocation,
    run_finite,
)

ROOT = Path(__file__).resolve().parents[1]
BDD = ROOT / "data/automation-acceptance/finite-multiplex-20261029/mux-finite-01.BDD"


def invocation(tmp_path, **updates):
    values = {
        "name": "finite-test",
        "store_directory": tmp_path,
        "expect_mode": "instrument",
        "channels": [
            {
                "channel": c,
                "frequency_khz": 4000,
                "profiles": 5,
                "gates": 80,
                "prf_us": 600,
                "emissions": 50,
            }
            for c in (1, 2)
        ],
    }
    values.update(updates)
    return FiniteInvocation(**values)


class Backend:
    """No target access: copies one genuine BDD when Store is requested."""

    def __init__(self, request, fail=None):
        self.request, self.fail = request, fail
        self.calls = []

    def prepare(self):
        self.calls.append("prepare")
        return {"process_mode": "instrument"}

    def configure(self):
        self.calls.append("configure")
        return []

    def enable(self):
        from udv_echo_process.acquire.finite import FiniteRunReceipt, FiniteRunRequest

        self.calls.append("enable")
        if self.fail == "enable":
            raise RuntimeError("unknown native outcome")
        request = FiniteRunRequest(
            channels=(1, 2),
            sequences=1,
            trigger_word=4,
            mode_before=65585,
            run_token="fixture",
        )
        receipt = FiniteRunReceipt(
            run_token="fixture",
            identity="fixture",
            invocations=1,
            pending_after_run=5,
            record_dispatches=0,
            stop_dispatches=0,
        )
        return request, receipt, {}

    def observe(self, request, receipt):
        self.calls.append("observe")
        return {
            "outcome": "operator_fallback_required"
            if self.fail == "timeout"
            else "completed"
        }

    def store(self):
        self.calls.append("store")
        path = self.request.store_directory / (self.request.name + ".BDD")
        shutil.copyfile(BDD, path)
        return {"ok": True, "path": str(path)}

    def close(self):
        self.calls.append("close")
        return {
            "ok": self.fail != "close",
            "sessions_opened": 1,
            "sessions": [
                {
                    "closed": True,
                    "close_problem": None,
                    "receipt_ok": True,
                    "helper_exit": 0,
                    "attach_exit": 0,
                }
            ],
        }

    def restore(self):
        self.calls.append("restore")
        return []

    def verify(self):
        self.calls.append("verify")
        keys = (
            "controls_restored",
            "multiplexing_disabled",
            "participants_restored",
            "trigger_unchanged",
            "same_identity",
            "ready_pending_zero_no_error",
            "all_ten_tgc_unchanged",
            "only_cached_words_differ",
        )
        return {"checks": {k: True for k in keys if self.fail != "empty_verification"}}

    def residual(self):
        self.calls.append("residual")
        return {"read": "fixture", "restoration_owed": True}

    def source_evidence(self):
        return {"fixture": True}


def test_real_coordinator_stores_and_decodes_before_restore(tmp_path):
    request = invocation(tmp_path)
    backend = Backend(request)
    report = run_finite(request, backend)
    assert report["ok"] and report["outcome"] == "stored_and_restored"
    assert backend.calls == [
        "prepare",
        "configure",
        "enable",
        "observe",
        "store",
        "close",
        "restore",
        "verify",
        "close",
    ]
    assert report["artifact"]["streams"] == 2
    assert not report["restoration_owed"]


@pytest.mark.parametrize(
    "failure", ["enable", "timeout", "close", "empty_verification"]
)
def test_failure_is_terminal_and_retains_residual_debt(tmp_path, failure):
    request = invocation(tmp_path)
    backend = Backend(request, failure)
    report = run_finite(request, backend)
    assert report["ok"] is False
    assert report["restoration_owed"] is True
    assert "residual" in report
    assert backend.calls.count("enable") == 1
    if failure in {"enable", "timeout"}:
        assert "store" not in backend.calls
    if failure != "empty_verification":
        assert "restore" not in backend.calls


def test_mixed_frequency_is_not_a_universal_rejection():
    specs = [
        FiniteChannel(
            channel=1,
            frequency_khz=4000,
            profiles=5,
            gates=80,
            prf_us=600,
            emissions=50,
        ),
        FiniteChannel(
            channel=2,
            frequency_khz=10000,
            profiles=5,
            gates=80,
            prf_us=600,
            emissions=50,
        ),
    ]
    request = FiniteInvocation(
        name="mixed",
        store_directory=Path("."),
        expect_mode="instrument",
        channels=specs,
    )
    assert [s.frequency_khz for s in request.channels] == [4000, 10000]


@pytest.mark.parametrize("bad", [True, 0, -1, "1"])
def test_channel_identifiers_are_not_coerced(bad):
    with pytest.raises(ValidationError):
        FiniteChannel(
            channel=bad,
            frequency_khz=4000,
            profiles=5,
            gates=80,
            prf_us=600,
            emissions=50,
        )


def test_collision_refuses_before_backend_prepare(tmp_path):
    request = invocation(tmp_path)
    (tmp_path / "finite-test.BDD").write_bytes(b"existing")
    backend = Backend(request)
    report = run_finite(request, backend)
    assert report["ok"] is False
    assert "prepare" not in backend.calls
    assert (tmp_path / "finite-test.BDD").read_bytes() == b"existing"


def test_promoted_workflow_has_canonical_public_exports():
    import udv_echo_process as package
    from udv_echo_process import acquire
    from udv_echo_process.acquire import finite_workflow

    for name in ("FiniteBackend", "FiniteChannel", "FiniteInvocation", "run_finite"):
        assert name in package.__all__ and name in acquire.__all__
        assert getattr(package, name) is getattr(finite_workflow, name)
        assert getattr(acquire, name) is getattr(finite_workflow, name)


def test_wrong_frequency_in_actual_bdd_refuses_before_restore(tmp_path):
    request = invocation(tmp_path)
    values = request.model_dump()
    values["channels"][1]["frequency_khz"] = 10000
    request = FiniteInvocation.model_validate(values)
    backend = Backend(request)
    report = run_finite(request, backend)
    assert not report["ok"]
    assert "configuration_mismatch" in report["reason"]
    assert "restore" not in backend.calls
    assert report["restoration_owed"]
    assert (tmp_path / "finite-test.BDD").is_file()


def test_process_mode_mismatch_refuses_before_configuration(tmp_path):
    request = invocation(tmp_path, expect_mode="simulation")
    backend = Backend(request)
    report = run_finite(request, backend)
    assert not report["ok"]
    assert "configure" not in backend.calls
    assert report["restoration_owed"] is False


def test_failed_close_and_residual_reads_do_not_escape_or_restore(tmp_path):
    request = invocation(tmp_path)
    backend = Backend(request)

    def broken():
        raise OSError("fixture boundary failure")

    backend.close = broken
    backend.residual = broken
    report = run_finite(request, backend)
    assert not report["ok"] and report["restoration_owed"]
    assert "restore" not in backend.calls
    assert report["residual"]["read"] == "failed"
    assert report["closeout"]["ok"] is False


@pytest.mark.parametrize(
    "key,value",
    [
        ("poll_s", float("nan")),
        ("observe_timeout_s", float("inf")),
        ("attachment_window_s", True),
        ("poll_s", 0),
    ],
)
def test_invalid_deadlines_cannot_reach_the_backend(tmp_path, key, value):
    with pytest.raises(ValidationError):
        invocation(tmp_path, **{key: value})


def test_invalid_run_command_receipt_stops_before_observe_or_store(tmp_path):
    from udv_echo_process.acquire.finite import FiniteRunReceipt

    request = invocation(tmp_path)
    backend = Backend(request)
    original = backend.enable

    def enable():
        declared, receipt, evidence = original()
        receipt = FiniteRunReceipt(**{**receipt.model_dump(), "pending_after_run": 0})
        return declared, receipt, evidence

    backend.enable = enable
    report = run_finite(request, backend)
    assert not report["ok"]
    assert "observe" not in backend.calls and "store" not in backend.calls
    assert report["restoration_owed"]


def test_colliding_invocation_closes_supplied_backend_and_retains_source(tmp_path):
    request = invocation(tmp_path)
    (tmp_path / "finite-test.BDD").write_bytes(b"existing")
    backend = Backend(request)
    report = run_finite(request, backend)
    assert not report["ok"]
    assert backend.calls == ["close"]
    assert "closeout" in report and report["source"] == {"fixture": True}
    assert report["restoration_owed"] is False


def test_unrelated_directory_prefix_does_not_refuse_recording(tmp_path):
    (tmp_path / "finite-test-notes").mkdir()
    request = invocation(tmp_path)
    backend = Backend(request)
    report = run_finite(request, backend)
    assert report["ok"]


def test_store_digest_claim_must_match_decoded_bytes(tmp_path):
    request = invocation(tmp_path)
    backend = Backend(request)
    original = backend.store

    def store():
        return {**original(), "sha256": "0" * 64}

    backend.store = store
    report = run_finite(request, backend)
    assert not report["ok"]
    assert "restore" not in backend.calls
    assert "digest" in report["reason"]


def test_file_changed_after_decode_is_not_credited_to_decoded_geometry(
    tmp_path, monkeypatch
):
    from udv_echo_process.acquire import finite_workflow

    request = invocation(tmp_path)
    backend = Backend(request)
    original = finite_workflow.read

    def read_then_change(path):
        bundle = original(path)
        path.write_bytes(path.read_bytes() + b"changed-after-decode")
        return bundle

    monkeypatch.setattr(finite_workflow, "read", read_then_change)
    report = run_finite(request, backend)
    assert not report["ok"]
    assert "restore" not in backend.calls
    assert "digest" in report["reason"]
