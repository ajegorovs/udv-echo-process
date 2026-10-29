"""Offline checks of the read-only live build verification summary."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/dop3000/evidence/finite-live-build-readonly-20261028.json"


def test_live_build_summary_is_not_native_or_workflow_acceptance() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["outcome"] == "all-builders-built-from-live-fields"
    assert evidence["native_calls"] == 0
    assert evidence["instrumentation_attached"] is False
    assert evidence["mutation_attempted"] is False
    assert evidence["device_commands_requested"] == []
    assert evidence["raw_captures_published"] is False
    assert any(
        "no native operation was dispatched" in line for line in evidence["limits"]
    )


def test_every_consumed_builder_resolved_and_state_stayed_disabled() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    operations = evidence["built_operations"]
    assert set(operations) == {
        "participants",
        "count",
        "flag",
        "route",
        "refresh",
    }
    assert all(row["built"] is True for row in operations.values())
    assert operations["count"]["op"] == "set-repeat-count"
    assert operations["flag"]["op"] == "set-flag"
    assert evidence["run_contract"]["name"] == "Btn_Mpx_Run"
    assert all(evidence["checks"].values())
    assert evidence["before_words"] == evidence["after_words"]
    assert evidence["after_words"]["pending"] == 0
    assert not evidence["after_words"]["Mpx_Mode"] & 1 << 1


def test_measured_control_and_model_agreement_is_recorded() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    agreement = evidence["control_agreement"]
    assert agreement["button_int_cache"] == agreement["model_count"] == 10
    assert evidence["generated_source_text_sha256"].startswith("e638429adc")
