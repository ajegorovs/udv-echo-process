"""Focused tests for the WP0 sweep-inventory command (plan ``WP0``).

Written RED first: ``analysis.sweep_inventory``, its CLI verb and the two
reviewer-visible artefacts (``manifest.csv``, ``qc-summary.json``) did not
exist, so this module failed at import. The tests pin:

- the manifest's row/column contract, one row per committed ``.BDD``;
- the QC summary's own assertions (counts, decodes, NaNs, timestamps, invariant
  words, analysis commit);
- byte-for-byte reproducibility, and the committed report artefacts against a
  fresh regeneration with the recorded commit.

Float columns are pinned by value here on purpose: the manifest is evidence, so
its serialization is part of the contract. Paths are pinned to the dataset
root, never to this checkout, so a regeneration elsewhere is byte-identical.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

from udv_echo_process.analysis.sweep_inventory import (
    COLUMNS,
    DATASET_ROOT,
    EXPECTED_AXIS_COUNTS,
    EXPECTED_FILES,
    EXPECTED_INVARIANT_WORDS,
    MANIFEST_NAME,
    QC_NAME,
    build_sweep_inventory,
    discover_sweep_files,
    write_sweep_inventory,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "mixer-sensitivity-analysis"
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout

REQUIRED_COLUMNS = (
    "relative_path",
    "axis",
    "requested_label",
    "source_sha256",
    "quantity",
    "unit",
    "profiles",
    "gates",
    "duration_s",
    "median_dt_s",
    "depth_min_mm",
    "depth_max_mm",
    "velocity_min_mm_s",
    "velocity_max_mm_s",
    "emit_freq_khz",
    "prf_period_us",
    "prf_hz",
    "burst_length",
    "emissions_per_profile",
    "emit_power",
    "sensitivity",
    "resolution_mm",
    "sampling_volume_index",
    "sound_speed_ms",
    "doppler_angle_deg",
    "velo_max_ms",
    "tgc_mode",
    "tgc_start_db",
    "tgc_end_db",
    "skipped_profiles",
    "op_word_14",
    "op_word_27",
    "op_word_84",
    "zero_fraction",
    "nan_count",
    "timestamps_monotone",
    "decode_error",
)

#: ``res/1-8.BDD`` (the base state), exactly as the dataset README decodes it.
RES_1_8 = {
    "source_sha256": "92ef87e3df57b443d37d62ed6cb84a99a5a4173c3b3c646e1a4d6c50b0fb67de",
    "profiles": "517",
    "gates": "50",
    "duration_s": "11.5529",
    "median_dt_s": "0.0224",
    "depth_min_mm": "10.1626666667",
    "depth_max_mm": "100.812666667",
    "velocity_min_mm_s": "-74.6603920131",
    "velocity_max_mm_s": "184.24258029",
    "prf_period_us": "600",
    "resolution_mm": "1.85",
    "velo_max_ms": "154.137583511",
    "tgc_start_db": "19.9215686275",
    "emissions_per_profile": "20",
    "sampling_volume_index": "4",
    "skipped_profiles": "0",
    "op_word_14": "20",
    "op_word_27": "4",
    "op_word_84": "0",
    "nan_count": "0",
    "timestamps_monotone": "true",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_discovery_finds_the_40_committed_bdd_files() -> None:
    files = discover_sweep_files(ROOT / DATASET_ROOT)
    assert len(files) == EXPECTED_FILES == 40
    assert all(path.suffix == ".BDD" for path in files)
    counted: dict[str, int] = {}
    for path in files:
        axis = path.parent.name
        counted[axis] = counted.get(axis, 0) + 1
    assert counted == EXPECTED_AXIS_COUNTS
    assert counted == {"res": 13, "burst_len": 12, "tgc": 8, "prf": 5, "em_pow": 2}


def test_build_inventory_reports_the_manifest_row_contract() -> None:
    inventory = build_sweep_inventory(ROOT / DATASET_ROOT, analysis_commit=COMMIT)
    assert list(COLUMNS) == list(REQUIRED_COLUMNS)
    assert len(inventory.rows) == EXPECTED_FILES
    assert all(tuple(row) == REQUIRED_COLUMNS for row in inventory.rows)
    # Deterministic order: axis, then the requested label, both lexicographic.
    ordering = [(row["axis"], row["requested_label"]) for row in inventory.rows]
    assert ordering == sorted(ordering)
    assert ordering[0] == ("burst_len", "12")

    row = next(r for r in inventory.rows if r["relative_path"] == "res/1-8.BDD")
    for column, expected in RES_1_8.items():
        assert row[column] == expected, column
    assert (row["axis"], row["requested_label"]) == ("res", "1-8")
    assert (row["quantity"], row["unit"]) == ("axial_velocity", "mm/s")
    assert (row["emit_power"], row["sensitivity"]) == ("medium", "medium")
    assert (row["burst_length"], row["tgc_mode"]) == ("10", "uniform")
    assert row["decode_error"] == ""


def test_build_inventory_qc_asserts_the_dataset_invariants() -> None:
    inventory = build_sweep_inventory(ROOT / DATASET_ROOT, analysis_commit=COMMIT)
    assert inventory.analysis_commit == COMMIT
    assert inventory.files == EXPECTED_FILES == 40
    assert inventory.expected_files == EXPECTED_FILES
    assert inventory.axis_counts == EXPECTED_AXIS_COUNTS
    assert inventory.axis_counts == {
        "burst_len": 12,
        "em_pow": 2,
        "prf": 5,
        "res": 13,
        "tgc": 8,
    }
    assert inventory.expected_axis_counts == EXPECTED_AXIS_COUNTS
    assert inventory.decode_failures == 0
    assert inventory.decode_failure_files == ()
    assert inventory.nan_cells == 0
    assert inventory.non_monotone_files == ()
    assert inventory.invariant_words == EXPECTED_INVARIANT_WORDS
    assert inventory.invariant_words == {"14": 20, "27": 4, "84": 0}
    assert inventory.expected_invariant_words == EXPECTED_INVARIANT_WORDS
    assert inventory.checks == {
        "file_count": True,
        "axis_counts": True,
        "decode_failures": True,
        "nan_cells": True,
        "timestamps_monotone": True,
        "invariant_words": True,
        "analysis_commit": True,
    }
    assert inventory.ok is True


def test_write_inventory_outputs_are_byte_for_byte_reproducible(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(ROOT)
    first = write_sweep_inventory(DATASET_ROOT, tmp_path / "a", analysis_commit=COMMIT)
    second = write_sweep_inventory(DATASET_ROOT, tmp_path / "b", analysis_commit=COMMIT)
    assert first.ok is True and second.ok is True
    manifest_a = (tmp_path / "a" / MANIFEST_NAME).read_bytes()
    manifest_b = (tmp_path / "b" / MANIFEST_NAME).read_bytes()
    qc_a = (tmp_path / "a" / QC_NAME).read_bytes()
    qc_b = (tmp_path / "b" / QC_NAME).read_bytes()
    assert manifest_a == manifest_b
    assert qc_a == qc_b
    # Text artefacts: LF only, one trailing newline, no CR, no absolute path.
    for blob in (manifest_a, qc_a):
        assert b"\r" not in blob
        assert blob.endswith(b"\n")
        assert str(ROOT).encode() not in blob


def test_written_manifest_and_qc_documents_agree(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(ROOT)
    write_sweep_inventory(DATASET_ROOT, tmp_path, analysis_commit=COMMIT)
    document = json.loads((tmp_path / QC_NAME).read_text(encoding="utf-8"))
    rows = _rows(tmp_path / MANIFEST_NAME)
    assert document["ok"] is True
    assert document["analysis_commit"] == COMMIT
    assert document["dataset_root"] == DATASET_ROOT.as_posix()
    assert document["files"] == document["expected_files"] == 40
    assert document["manifest_rows"] == len(rows) == 40
    assert document["axis_counts"] == EXPECTED_AXIS_COUNTS
    assert document["decode_failures"] == 0
    assert document["nan_cells"] == 0
    assert document["invariant_words"] == EXPECTED_INVARIANT_WORDS
    assert set(document["checks"].values()) == {True}
    # The recorded manifest hash is the manifest actually written.
    digest = hashlib.sha256((tmp_path / MANIFEST_NAME).read_bytes()).hexdigest()
    assert document["manifest_sha256"] == f"sha256:{digest}"


def test_cli_verb_writes_both_artefacts_and_exits_zero(tmp_path, capsys) -> None:
    from udv_echo_process.cli import sweep_inventory_main

    with pytest.raises(SystemExit) as excinfo:
        sweep_inventory_main(
            [
                "--dataset-root",
                str(ROOT / DATASET_ROOT),
                "--report-dir",
                str(tmp_path),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert excinfo.value.code == 0
    assert (tmp_path / MANIFEST_NAME).is_file()
    assert (tmp_path / QC_NAME).is_file()
    out = capsys.readouterr().out
    assert "40" in out and MANIFEST_NAME in out and QC_NAME in out


def test_cli_exits_nonzero_when_a_gate_check_fails(tmp_path, capsys) -> None:
    """The gate must be able to fail: an incomplete dataset exits 1, honestly."""
    from udv_echo_process.cli import sweep_inventory_main

    axis_dir = tmp_path / "dataset" / "prf"
    axis_dir.mkdir(parents=True)
    (axis_dir / "600.BDD").write_bytes(
        (ROOT / DATASET_ROOT / "prf" / "600.BDD").read_bytes()
    )
    with pytest.raises(SystemExit) as excinfo:
        sweep_inventory_main(
            [
                "--dataset-root",
                str(tmp_path / "dataset"),
                "--report-dir",
                str(tmp_path / "reports"),
                "--analysis-commit",
                COMMIT,
            ]
        )
    assert excinfo.value.code == 1
    errors = capsys.readouterr().err
    assert "check failed: file_count" in errors
    assert "check failed: axis_counts" in errors
    document = json.loads(
        (tmp_path / "reports" / QC_NAME).read_text(encoding="utf-8")
    )
    assert document["ok"] is False
    assert document["files"] == 1
    assert document["decode_failures"] == 0
    assert len(_rows(tmp_path / "reports" / MANIFEST_NAME)) == 1


def test_committed_report_artefacts_match_a_regeneration(tmp_path, monkeypatch) -> None:
    """The reviewer-visible artefacts are exactly what the command produces."""
    monkeypatch.chdir(ROOT)
    committed_qc = REPORT_DIR / QC_NAME
    assert committed_qc.is_file(), "WP0 must commit qc-summary.json"
    assert (REPORT_DIR / MANIFEST_NAME).is_file(), "WP0 must commit manifest.csv"
    recorded = json.loads(committed_qc.read_text(encoding="utf-8"))["analysis_commit"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", recorded or ""), recorded

    write_sweep_inventory(DATASET_ROOT, tmp_path, analysis_commit=recorded)
    # The writer always emits LF; a checkout can present the committed copy with
    # the platform's line endings (``core.autocrlf``), so compare normalized
    # text — everything else, byte for byte.
    def normalized(path: Path) -> bytes:
        return path.read_bytes().replace(b"\r\n", b"\n")

    assert normalized(tmp_path / MANIFEST_NAME) == normalized(
        REPORT_DIR / MANIFEST_NAME
    )
    assert normalized(tmp_path / QC_NAME) == normalized(committed_qc)


def test_report_readme_states_the_regeneration_command() -> None:
    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    assert ".venv/Scripts/python.exe -m udv_echo_process.cli sweep-inventory" in readme
    assert MANIFEST_NAME in readme and QC_NAME in readme


def test_report_readme_states_how_to_reproduce_the_committed_commit() -> None:
    """F3: the bare command records HEAD; the committed artefact must pass its own commit."""
    readme = (REPORT_DIR / "README.md").read_text(encoding="utf-8")
    assert "--analysis-commit" in readme
    assert "current HEAD" in readme
    assert "generator" in readme


# ── malformed and empty inputs: the gate reports, the command never aborts ──


def _truncated_fixture(directory: Path, name: str) -> Path:
    """Write ``<name>`` as a deliberately truncated copy of ``prf/600.BDD``.

    1000 bytes is long enough to be identified as a file and short enough that
    the operation-table read raises ``struct.error`` — an ordinary decoder
    exception that is neither ``OSError`` nor ``ValueError``.
    """
    source = (ROOT / DATASET_ROOT / "prf" / "600.BDD").read_bytes()[:1000]
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)
    return path


def _inventory_argv(tmp_path: Path) -> list[str]:
    return [
        "--dataset-root",
        str(tmp_path / "dataset"),
        "--report-dir",
        str(tmp_path / "reports"),
        "--analysis-commit",
        COMMIT,
    ]


def _multi_stream_fixture(directory: Path, name: str) -> Path:
    """Write ``<name>`` as a copy of a committed four-channel recording.

    It decodes without raising, but no single profile block belongs to it, so
    ``read_manifest_row`` reports it as a decode failure with no timestamps —
    the second, exception-free kind of decode-error row.
    """
    source = (ROOT / "data" / "4-sensor-velocity" / "200RPM.BDD").read_bytes()
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(source)
    return path


def test_truncated_bdd_becomes_one_decode_error_row_and_a_failed_gate(tmp_path) -> None:
    """F1: a file that breaks a decoder is a row failure, never an abort."""
    dataset = tmp_path / "dataset"
    _truncated_fixture(dataset, "res/0-6.BDD")
    inventory = write_sweep_inventory(
        dataset, tmp_path / "reports", analysis_commit=COMMIT
    )
    assert inventory.files == 1
    assert inventory.manifest_rows == 1
    assert len(inventory.rows) == 1
    row = inventory.rows[0]
    assert row["relative_path"] == "res/0-6.BDD"
    assert (row["axis"], row["requested_label"]) == ("res", "0-6")
    assert re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]), row["source_sha256"]
    assert row["decode_error"].startswith("error: "), row["decode_error"]
    assert row["timestamps_monotone"] == ""
    assert inventory.decode_failures == 1
    assert inventory.decode_failure_files == ("res/0-6.BDD",)
    # F2 for the same row: no timestamps, so no non-monotone claim either.
    assert inventory.non_monotone_files == ()
    assert inventory.checks["decode_failures"] is False
    assert inventory.checks["timestamps_monotone"] is True
    assert inventory.ok is False
    document = json.loads(
        (tmp_path / "reports" / QC_NAME).read_text(encoding="utf-8")
    )
    assert document["decode_failures"] == 1
    assert document["decode_failure_files"] == ["res/0-6.BDD"]
    assert document["non_monotone_files"] == []
    assert document["ok"] is False
    assert len(_rows(tmp_path / "reports" / MANIFEST_NAME)) == 1


def test_decode_error_rows_are_not_listed_as_non_monotone(tmp_path) -> None:
    """F2: a row with no timestamps carries no timestamp evidence.

    Uses the exception-free decode failure (a multi-channel recording) so the
    classification is observable without F1's abort in the way.
    """
    dataset = tmp_path / "dataset"
    (dataset / "prf").mkdir(parents=True)
    (dataset / "prf" / "600.BDD").write_bytes(
        (ROOT / DATASET_ROOT / "prf" / "600.BDD").read_bytes()
    )
    _multi_stream_fixture(dataset, "res/1-8.BDD")
    inventory = build_sweep_inventory(dataset, analysis_commit=COMMIT)
    row = next(r for r in inventory.rows if r["relative_path"] == "res/1-8.BDD")
    assert row["decode_error"].startswith("expected exactly one channel stream")
    assert row["timestamps_monotone"] == ""
    assert inventory.decode_failure_files == ("res/1-8.BDD",)
    assert inventory.non_monotone_files == ()
    assert inventory.checks["timestamps_monotone"] is True
    assert inventory.checks["decode_failures"] is False


def test_empty_dataset_writes_a_header_only_manifest_and_a_failed_gate(tmp_path) -> None:
    """F4: an empty discovery is a gate failure the QC reports, not an exception."""
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    assert discover_sweep_files(dataset) == ()
    inventory = write_sweep_inventory(
        dataset, tmp_path / "reports", analysis_commit=COMMIT
    )
    assert inventory.files == 0
    assert inventory.manifest_rows == 0
    assert inventory.rows == ()
    assert inventory.decode_failures == 0
    assert inventory.checks["file_count"] is False
    assert inventory.ok is False
    manifest = (tmp_path / "reports" / MANIFEST_NAME).read_text(encoding="utf-8")
    assert manifest == ",".join(COLUMNS) + "\n"
    document = json.loads(
        (tmp_path / "reports" / QC_NAME).read_text(encoding="utf-8")
    )
    assert document["files"] == 0
    assert document["ok"] is False
    assert document["checks"]["file_count"] is False
    assert document["manifest_sha256"] == (
        f"sha256:{hashlib.sha256(manifest.encode('utf-8')).hexdigest()}"
    )


def test_cli_exits_one_without_a_traceback_on_a_truncated_bdd(tmp_path, capsys) -> None:
    from udv_echo_process.cli import sweep_inventory_main

    _truncated_fixture(tmp_path / "dataset", "res/0-6.BDD")
    with pytest.raises(SystemExit) as excinfo:
        sweep_inventory_main(_inventory_argv(tmp_path))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "check failed: decode_failures" in captured.err
    assert "Traceback" not in captured.err
    assert len(_rows(tmp_path / "reports" / MANIFEST_NAME)) == 1


def test_cli_exits_one_without_a_traceback_on_an_empty_dataset(tmp_path, capsys) -> None:
    from udv_echo_process.cli import sweep_inventory_main

    (tmp_path / "dataset").mkdir()
    with pytest.raises(SystemExit) as excinfo:
        sweep_inventory_main(_inventory_argv(tmp_path))
    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "check failed: file_count" in captured.err
    assert "Traceback" not in captured.err
    assert (tmp_path / "reports" / QC_NAME).is_file()
