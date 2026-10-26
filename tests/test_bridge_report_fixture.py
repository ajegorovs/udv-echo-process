"""The saved dispatch report, as it was actually recorded — shape, and refusal when altered.

``tests/data/bridge_dispatch_s3_run_20261022_06.json`` is a faithful, path-normalised projection of one
real application-backed record cycle (capture ``s3-run-20261022-06``, 2026-10-22): the store verdict,
the artifact digest and byte count, the configuration verdict and the identity verdict, copied
verbatim from the report that cycle wrote.  What was dropped and rewritten is declared in the
companion ``.provenance.json`` beside it, and the captured report itself is **not** committed — it
carries machine and vendor bindings (an absolute store path, window and process handles, routine
addresses, the instrument image's digest).

The stored artifact is not committed either: ``outputs/live`` is ignored, so nothing here opens the
``.BDD``.  This suite therefore proves **saved-report schema compatibility only** — that
:func:`evidence_from_report` reads a real cycle's own words as typed evidence.  It says nothing about a
:class:`BridgeDispatch` adapter turning a :class:`BridgeRequest` into such a report, nor about the live
route that would produce one.

The refusals themselves are already pinned on a synthetic report in ``test_bridge_actuator.py``; the
perturbations at the bottom of this file exist for a different reason — to show the fixture passes
because it is a real report and not because the parser is forgiving.  Every mutation there is labelled
**SYNTHETIC**: a mutated copy of a real capture is not a recording of anything, so it is never
presented as raw evidence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from udv_echo_process.acquire.bridge import BridgeUnavailable, evidence_from_report

DATA = Path(__file__).parent / "data"
FIXTURE = DATA / "bridge_dispatch_s3_run_20261022_06.json"
PROVENANCE = DATA / "bridge_dispatch_s3_run_20261022_06.provenance.json"

#: A digest as the parser accepts it: 64 hex digits and nothing else.
SHA256 = re.compile(r"[0-9a-f]{64}")

#: The artifact this capture stored, as the cycle reported it.
CAPTURE = "s3-run-20261022-06"
ARTIFACT_NAME = "bridged-20261022-06.BDD"
ARTIFACT_SHA256 = "722e3ea2aad75eb3ac6638a86069c8c5589845df8be052a7ad34b4388a7a9504"
ARTIFACT_BYTES = 49793

#: The captured report itself, which is not committed — the provenance file must keep naming it.
ORIGINAL_REPORT_SHA256 = (
    "1e26659fde2ae37046bc992cd75e65825e01545c172f39b1ada30dc7f01edd4e"
)
ORIGINAL_REPORT_BYTES = 20930


def capture() -> dict[str, Any]:
    """The committed projection, read fresh so a test cannot mutate another test's copy."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def perturbed(edit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """A **SYNTHETIC** mutation of the real capture — not a capture of any refusal."""
    report = capture()
    edit(report)
    return report


def provenance() -> dict[str, Any]:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


def refusal(report: Mapping[str, Any]) -> str:
    with pytest.raises(BridgeUnavailable) as caught:
        evidence_from_report(report)
    return caught.value.reason


class TestTheRecordedCaptureIsEvidence:
    def test_it_parses_to_typed_evidence(self):
        evidence = evidence_from_report(capture())

        assert evidence.stored is True
        assert evidence.config_matches is True
        assert evidence.identity_unchanged is True
        assert evidence.reason is None

    def test_the_verdicts_are_booleans_and_not_truthy_strings(self):
        """``"true"`` would parse under ``bool()`` and mean nothing; the capture states real booleans."""
        report = capture()

        assert isinstance(report["stored"]["stored"], bool)
        assert isinstance(report["decoded"]["config_matches"], bool)
        assert isinstance(report["identity_unchanged"], bool)

    def test_the_artifact_is_named_and_sized_as_the_cycle_stored_it(self):
        report = capture()
        stored = report["stored"]

        assert stored["stored_path"] == f"outputs/live/store/{ARTIFACT_NAME}"
        assert stored["stored_bytes"] == ARTIFACT_BYTES
        assert stored["stored_sha256"] == ARTIFACT_SHA256

    def test_the_digest_is_a_bare_sha256_and_the_path_is_the_artifact(self):
        evidence = evidence_from_report(capture())

        assert evidence.stored_sha256 is not None
        assert SHA256.fullmatch(evidence.stored_sha256)
        assert evidence.stored_path is not None
        assert evidence.stored_path.name == ARTIFACT_NAME
        assert evidence.stored_path.suffix == ".BDD"

    def test_the_evidence_keeps_the_report_it_was_read_from(self):
        report = capture()

        assert evidence_from_report(report).raw is report


class TestTheProvenanceDeclaresWhatTheFixtureIs:
    def test_the_declared_required_keys_are_the_fixture_keys(self):
        declared = provenance()

        assert declared["fixture"]["kept_keys"] == sorted(capture())

    def test_every_omitted_key_is_really_absent(self):
        declared = provenance()

        report = capture()
        assert declared["fixture"]["omitted_top_level_keys"]
        for key in declared["fixture"]["omitted_top_level_keys"]:
            assert key not in report, key

    def test_the_original_report_identity_is_recorded_as_a_digest(self):
        declared = provenance()

        assert declared["capture"]["capture_id"] == CAPTURE
        original = declared["capture"]["report"]
        assert SHA256.fullmatch(original["sha256"])
        assert original["sha256"] == ORIGINAL_REPORT_SHA256
        assert original["bytes"] == ORIGINAL_REPORT_BYTES

    def test_nothing_here_carries_a_machine_or_vendor_binding(self):
        """The tracked text must stay publishable: no drive path, no home path, no routine address."""
        fixture_text = FIXTURE.read_text(encoding="utf-8")
        provenance_text = PROVENANCE.read_text(encoding="utf-8")
        text = fixture_text + provenance_text

        assert not re.search(r"[A-Za-z]:[\\/]", text)
        assert not re.search(r"\\\\[A-Za-z0-9._-]+\\", text)
        assert not re.search(r"0x[0-9a-fA-F]{2,}", text)
        for machine in ("/home/", "/Users/", "C:\\", "AppData", "LOCALAPPDATA"):
            assert machine not in text, machine

    def test_the_provenance_states_the_limit_of_this_evidence(self):
        limit = provenance()["limitation"].lower()

        assert "schema" in limit
        assert "not" in limit
        assert "request" in limit


class TestAPerturbedCaptureIsRefused:
    """SYNTHETIC mutations of the real fixture — each is a refusal the parser must name."""

    def test_a_synthetic_capture_without_a_digest_is_incomplete(self):
        report = perturbed(lambda report: report["stored"].pop("stored_sha256"))

        assert refusal(report) == "bridge_evidence_incomplete:stored_sha256"

    def test_a_synthetic_capture_with_a_malformed_digest_is_invalid(self):
        def shorten(report: dict[str, Any]) -> None:
            report["stored"]["stored_sha256"] = ARTIFACT_SHA256[:-1]

        assert refusal(perturbed(shorten)) == "bridge_evidence_invalid:stored_sha256"

    def test_a_synthetic_capture_with_a_stored_flag_as_text_is_invalid(self):
        def as_text(report: dict[str, Any]) -> None:
            report["stored"]["stored"] = "true"

        assert refusal(perturbed(as_text)) == "bridge_evidence_invalid:stored"

    def test_a_synthetic_capture_without_the_identity_verdict_is_incomplete(self):
        report = perturbed(lambda report: report.pop("identity_unchanged"))

        assert refusal(report) == "bridge_evidence_incomplete:identity_unchanged"

    def test_a_synthetic_capture_claiming_no_store_reads_as_no_store(self):
        """The real capture with its verdict flipped: lenient by design, and still not a store."""

        def not_stored(report: dict[str, Any]) -> None:
            report["stored"]["stored"] = False

        evidence = evidence_from_report(perturbed(not_stored))

        assert evidence.stored is False
        assert evidence.reason is None
