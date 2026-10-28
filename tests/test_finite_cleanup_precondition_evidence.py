"""Check the derived refusal summary, not the unpublished live memory observations."""

from __future__ import annotations

import json
from pathlib import Path

from udv_echo_process.acquire import RUN_ARM_BIT, StripState

EVIDENCE = (
    Path(__file__).resolve().parents[1]
    / "docs/dop3000/evidence/finite-cleanup-precondition-20261028.json"
)


def test_ready_refusal_is_not_reported_as_live_cleanup_acceptance() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["outcome"] == "refused-before-instrumentation"
    assert evidence["producer_exit"] == 3
    assert evidence["instrumentation_started"] is False
    assert evidence["cleanup_acceptance"] == "not-exercised"
    assert evidence["native_call_receipt"] is None
    assert evidence["device_commands_requested"] == []
    assert evidence["host_operations_dispatched"] == []
    assert evidence["raw_captures_published"] is False


def test_summary_keeps_disabled_state_and_complete_preservation_links() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert all(evidence["checks"].values())
    assert evidence["before"]["words"] == evidence["after"]["words"]
    assert not evidence["after"]["words"]["Mpx_Mode"] & RUN_ARM_BIT
    assert evidence["after"]["words"]["pending"] == 0
    assert StripState.model_validate(evidence["after"]["strip"]).view.value == "ready"
    for key in ("all_ten_parameter_images", "all_ten_tgc"):
        records = evidence[key]
        assert set(records) == {str(channel) for channel in range(1, 11)}
        assert all(
            row["before_sha256"] == row["after_sha256"] for row in records.values()
        )


def test_real_readonly_admission_is_not_native_workflow_acceptance() -> None:
    path = EVIDENCE.with_name("finite-readonly-admission-20261028.json")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["outcome"] == "read-only-admitted"
    assert evidence["native_workflow_accepted"] is False
    assert evidence["instrumentation_started"] is False
    assert evidence["mutation_attempted"] is False
    assert evidence["device_commands_requested"] == []
    assert evidence["template"]["attached_sha256"] is None
    assert evidence["resolved_setup_restore_count"] == len(
        evidence["admission"]["resolved_operations"]
    )
    assert all(evidence["checks"].values())


def test_readonly_summary_preserves_all_channel_and_tgc_links() -> None:
    path = EVIDENCE.with_name("finite-readonly-admission-20261028.json")
    evidence = json.loads(path.read_text(encoding="utf-8"))
    assert evidence["before_words"] == evidence["after_words"]
    assert not evidence["after_words"]["Mpx_Mode"] & RUN_ARM_BIT
    assert evidence["after_words"]["pending"] == 0
    for key in ("all_ten_parameter_images", "all_ten_tgc"):
        assert set(evidence[key]) == {str(channel) for channel in range(1, 11)}
        assert all(
            row["before_sha256"] == row["after_sha256"]
            for row in evidence[key].values()
        )
