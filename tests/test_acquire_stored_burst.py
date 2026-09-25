"""B6 — the strict stored burst oracle (word 8) and the stored bandwidth index (word 27).

The committed B4/B5 recordings are the only oracle this repository has for what the
application *stores*, so the strict-burst rule is pinned on them rather than on a
synthetic buffer:

- **word 8 is the strict burst oracle.** Each of the twelve B5 recordings verifies against
  its own committed request, and against a request whose burst is another value of the
  same pass it comes back ``ok=False`` naming word 8 — with the module's own defaults, so
  the rule belongs to the check rather than to a caller's switch;
- **word 27 is the stored receiver-bandwidth-definition index and nothing else.** It reads
  ``1`` in all sixteen B4/B5 recordings while word 8 reads ``4 / 10 / 18`` and the dialog's
  effective Sampling volume was read back as ``1.776 / 1.850 / 3.330`` mm (the READMEs
  beside them), the decoder publishes the same integer with ``sampling_volume_mm`` unset,
  and no verdict moves when the index changes. The four B4 files are the sharpest form of
  that: one index, three different effective millimetres, so no inverse index -> mm
  relation can be consistent with them.

What this module cannot check, and does not claim: the dialog's effective millimetres are
a live statement of the application (carried by the boundary's burst transitions,
``JobManifest.burst_transitions``), and no reviewed index -> mm relation exists — B6
forbids deriving one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from udv_echo_process.acquire.config import ParameterSet
from udv_echo_process.acquire.verify import read_words, verify_stored_point
from udv_echo_process.io.dop.bdd import read

REPO_ROOT = Path(__file__).resolve().parents[1]
B4 = REPO_ROOT / "data" / "burst-commissioning-b4"
B5 = REPO_ROOT / "data" / "burst-commissioning-b5"

#: Another burst of the same pass, for the swapped-request case (all three values occur).
OTHER_BURST = {4: 10, 10: 18, 18: 4}

#: The dialog's own effective Sampling volume per B4 recording, in mm, exactly as the
#: committed B4 README records it (the paired CLI logs are that number's authority). It is
#: here to be *contrasted* with the stored index, never derived from it.
B4_EFFECTIVE_MM = {
    "b4_burst_4.BDD": "1.776",
    "b4_burst_10_a.BDD": "1.850",
    "b4_burst_10_b.BDD": "1.850",
    "b4_burst_18.BDD": "3.330",
}


def evidence_required() -> None:
    """Skip when the committed commissioning evidence is not in this checkout."""
    if not (B4 / "manifest.json").is_file() or not (B5 / "manifest.json").is_file():
        pytest.skip(
            "the committed B4/B5 commissioning evidence is not in this checkout"
        )


def b4_rows() -> list[tuple[Path, int, int]]:
    """``(file, stored word 8, stored word 27)`` as the committed B4 manifest states them."""
    manifest = json.loads((B4 / "manifest.json").read_text(encoding="utf-8"))
    return [
        (B4 / row["file"], int(row["op_word_8"]), int(row["op_word_27"]))
        for row in manifest["rows"]
    ]


def b5_points() -> list[dict[str, object]]:
    """Every committed B5 point: its file, its requested parameters and its stored words."""
    manifest = json.loads((B5 / "manifest.json").read_text(encoding="utf-8"))
    return [
        {**point, "job": job["job"]}
        for job in manifest["jobs"]
        for point in job["points"]
    ]


def test_the_committed_evidence_is_the_pass_it_claims_to_be() -> None:
    """Four B4 recordings and twelve B5 points — the pass the B6 claim is made on."""
    evidence_required()
    assert len(b4_rows()) == 4
    assert len(b5_points()) == 12


def test_the_stored_bandwidth_index_is_fixed_while_the_stored_burst_moves() -> None:
    """One index, three bursts: word 27 does not follow the burst (plan §B4/§B6).

    This is the independent qualification B6 asks for, and it is made from the committed
    files alone: the burst sweep moved the stored burst across ``4 / 10 / 18`` while every
    file kept the same receiver-bandwidth definition. It says nothing about *which* other
    bandwidth a different selection would store — no committed evidence moves that field.
    """
    evidence_required()
    recorded = [
        (read_words(path).burst_length, read_words(path).bandwidth_definition_index)
        for path, _word8, _word27 in b4_rows()
    ] + [
        (
            read_words(B5 / str(point["file"])).burst_length,
            read_words(B5 / str(point["file"])).bandwidth_definition_index,
        )
        for point in b5_points()
    ]

    assert {burst for burst, _index in recorded} == {4, 10, 18}
    assert {index for _burst, index in recorded} == {1}
    assert len(recorded) == 16


def test_the_index_is_not_a_function_of_the_dialog_effective_millimetres() -> None:
    """Four files the dialog read at three different millimetres, all storing index ``1``.

    The withdrawn criterion was ``word 27 == the index the displayed mm implies``. These
    bytes refute it: the effective thickness moved by 1.55 mm across the four while the
    stored index did not move at all, so no inverse relation to the dialog's millimetres
    can be consistent with the committed evidence.
    """
    evidence_required()
    rows = b4_rows()

    assert {index for _path, _word8, index in rows} == {1}
    assert {B4_EFFECTIVE_MM[path.name] for path, _word8, _index in rows} == {
        "1.776",
        "1.850",
        "3.330",
    }


def test_every_committed_recording_stores_the_words_its_manifest_names() -> None:
    """The two independent reads agree with the committed manifest, file by file."""
    evidence_required()
    for path, word8, word27 in b4_rows():
        words = read_words(path)
        assert (words.burst_length, words.bandwidth_definition_index) == (word8, word27)
    for point in b5_points():
        path = B5 / str(point["file"])
        words = read_words(path)
        assert (words.burst_length, words.bandwidth_definition_index) == (
            point["op_word_8"],
            point["op_word_27"],
        )


def test_the_word_reader_and_the_decoder_agree_about_word_27() -> None:
    """Two independent reads of the stored index, and no millimetre published anywhere."""
    evidence_required()
    for path, _word8, word27 in b4_rows():
        config = read(path).recording.streams[0].config
        assert read_words(path).bandwidth_definition_index == word27
        assert config.sampling_volume_index == word27
        assert config.sampling_volume_mm is None
    for point in b5_points():
        path = B5 / str(point["file"])
        config = read(path).recording.streams[0].config
        assert (
            read_words(path).bandwidth_definition_index == config.sampling_volume_index
        )
        assert config.sampling_volume_mm is None


def test_every_committed_b5_request_verifies_its_own_recording() -> None:
    """The 12 B5 recordings are their own points' data, at their committed requests."""
    evidence_required()
    for point in b5_points():
        requested = dict(point["requested"])  # type: ignore[arg-type]
        result = verify_stored_point(
            B5 / str(point["file"]),
            ParameterSet(**requested),
            check_covariates=True,
        )
        assert result.ok, (point["job"], point["label"], result.mismatches)
        assert "burst_length" in result.enforced_covariates
        assert result.facts.bandwidth_definition_index == point["op_word_27"]


def test_a_swapped_burst_invalidates_each_committed_recording() -> None:
    """The strict rule on real files, at the module's **defaults**.

    Word 8 is compared whether or not a caller asked for the covariates (plan §B6), so each
    of the twelve recordings read against another burst of its own pass is not a point:
    ``ok`` false, one mismatch, and the mismatch names word 8 and both sides.
    """
    evidence_required()
    for point in b5_points():
        stored = int(point["op_word_8"])  # type: ignore[arg-type]
        swapped = dict(point["requested"])  # type: ignore[arg-type]
        swapped["burst_length"] = OTHER_BURST[stored]

        result = verify_stored_point(B5 / str(point["file"]), ParameterSet(**swapped))

        assert result.ok is False, (point["job"], point["label"])
        assert result.mismatches == (
            f"burst_length: requested {OTHER_BURST[stored]}, found {stored} in word 8",
        )
        assert result.enforced_covariates == ("burst_length",)
