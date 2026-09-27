"""SA2.4 S3: an independent verifier for the *published bytes* of the scalar report.

This file exists to answer one question the S2 writer's own tests cannot: **is the published
artefact what the committed recordings and the estimator's own density say it is?** It shares no
arithmetic with S1 or S2. Every number it checks is recomputed here, from the two things the
report claims to rest on:

* the **decoded committed passes** - :func:`decode_pass` and the view cutters of
  ``_sparse_view``, the same recordings the sweep selected, decoded afresh;
* the **estimator's own density** - :func:`periodogram_of_view` per native gate, whose raw
  ``frequency_hz``, ``psd`` and ``delta_f_hz`` this file reduces with its **own handwritten
  cell boundaries** (:func:`_band_power_and_total`), never with S1's
  ``low_frequency_power_fraction`` and never with the writer's ``_checks``.

The rows it holds the report to:

* **the source row set** - the published cells are exactly the committed reproducibility
  sweep's ``recording x view`` pairs, the campaign absent, one row per ``cell x supported gate``;
* **per-gate native support identities** - each published ``gate_index`` is a native column of
  the decoded view, the sequence is ``supported_columns`` in native order, and the depth is the
  view's own coordinate of that column;
* **the numbers** - every published ``band_power``, ``total_power``, ``band_fraction`` and band
  state against the handwritten-boundary oracle over all 5720 gate rows, plus the axis scalars
  against the estimate's own characterization;
* **the digests** - ``table_sha256`` recomputed by hand over the CSV's canonical LF bytes, the
  per-pass plan fingerprints recomputed from the raw plan JSON, and the aggregate fingerprint
  recomputed as the SHA-256 of the canonical JSON of that map;
* **E128 by label** - the rotor refusal read by ``target_label``, with the Nyquist and cell
  arithmetic redone from the decoded axis;
* **symmetry** - the two views of every recording, the shared native-gate set across them, and
  the descriptive within-sitting repeat spread recomputed from the same fractions;
* **refusal status** - the published band state equals the estimator's own verdict, a refusal
  carries no number, and the reserved refusal vocabulary is shown to be a real estimator answer.

The report is written once, into a scratch directory **outside the repository** (pytest's own
temp tree): no committed report exists yet, and this file never touches ``reports/``. Nothing
here quotes an exploratory datum, a floor or an expectation - the checks are all identities.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import sparse_signal_report as writer
from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis._sparse_view import (
    SparseView,
    full_record_view,
    primary_view,
    view_provenance,
)
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES
from udv_echo_process.analysis.sparse_periodogram import (
    SpectralVerdict,
    periodogram_of_view,
)

# --------------------------------------------------------------------------------------
# the contract's fixed names and numbers, restated here rather than imported
# --------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

#: The revision recorded in the scratch run. The report is built once, so its provenance is fixed.
REVISION = "s3-verifier"

#: §1's row set: 52 recordings x 2 views, one row per ``cell x supported gate``.
EXPECTED_CELLS = 104
EXPECTED_GATE_ROWS = 5720

#: The two reproducibility sittings, and the campaign the default scope deliberately excludes.
SITTINGS = ("sparse-mixer-live-1", "sparse-mixer-live-2")
CAMPAIGN = "stage2-e20-e64"

#: §2's declared band edge; the design's two probe targets, by label.
LOW_HZ = 1.0
RECURRENCE_LABEL = "recurrence-1hz"
ROTOR_LABEL = "rotor-8.333hz"
RECURRENCE_HZ = 1.0
ROTOR_HZ = 25.0 / 3.0

#: §5's published precisions: ``band_fraction`` at 6 decimals, other floats at 12 significant
#: digits. The comparisons happen at those precisions.
FRACTION_ABS = 1e-6
POWER_REL = 1e-9

#: The three band states, as the enum's own ``.value`` strings.
STATE_DEFINED = "defined"
STATE_ZERO = "defined-zero-power"
STATE_REFUSED = "refused-axis"

#: The CSV's frozen schema, in order, spelled out independently of the writer's constant: a
#: published table is a contract, and a schema change must fail here rather than pass silently.
SURFACE_COLUMNS: tuple[str, ...] = (
    "pass",
    "job",
    "point_label",
    "order",
    "relative_path",
    "source_sha256",
    "view",
    "gate_index",
    "depth_mm",
    "quantity",
    "unit",
    "psd_unit",
    "detrending",
    "low_band_hz",
    "taper_name",
    "profiles",
    "span_s",
    "dt_eff_s",
    "effective_sample_rate_hz",
    "nyquist_hz",
    "delta_f_hz",
    "duration_resolution_scale_hz",
    "max_relative_timing_error",
    "max_timing_error_s",
    "max_relative_interval_deviation",
    "largest_gap_ratio",
    "spectral_uniformity_tol",
    "admitted",
    "enbw_bins",
    "enbw_hz",
    "verdict",
    "band_state",
    "band_fraction",
    "band_power",
    "total_power",
    "parseval_relative_error",
)


def _require_writer() -> object:
    """The published interface S3 verifies: the entry point and the three artefact names."""
    for name in ("CSV_NAME", "DOC_NAME", "README_NAME", "write_sparse_signal_report"):
        assert hasattr(writer, name), f"the writer is missing the frozen name {name!r}"
    return writer


CSV_NAME = str(_require_writer().CSV_NAME)
DOC_NAME = str(_require_writer().DOC_NAME)
README_NAME = str(_require_writer().README_NAME)


# --------------------------------------------------------------------------------------
# the handwritten oracle: bins, cell boundaries and the band reduction - all local
# --------------------------------------------------------------------------------------


def _edges(profiles: int, rate: float, nyquist: float) -> tuple[np.ndarray, np.ndarray]:
    """Every bin's cell ``(low, high)``, written out from the rule - never called.

    A deliberate second implementation of the repository's one cell rule, sharing no helper with
    S1 or S2: edges are the midpoints to the neighbouring bins, the DC cell opens at ``0.0``, and
    the highest represented cell closes at ``min(nyquist, (k + 0.5) * delta_f)``.
    """
    delta = rate / profiles
    bins = profiles // 2 + 1
    index = np.arange(bins, dtype=float)
    low = np.where(index == 0.0, 0.0, (index - 0.5) * delta)
    high = (index + 0.5) * delta
    high = np.where(index == bins - 1, np.minimum(nyquist, high), high)
    return low, high


def _cell_edges(
    index: int, *, profiles: int, rate: float, nyquist: float
) -> tuple[float, float]:
    """One bin's cell ``(low_hz, high_hz)`` as scalars, for a target-row comparison."""
    delta = rate / profiles
    bins = profiles // 2 + 1
    low = 0.0 if index == 0 else (index - 0.5) * delta
    high = (index + 0.5) * delta
    if index == bins - 1:
        high = min(nyquist, high)
    return low, high


def _weight(low: float, high: float, *, low_hz: float) -> float:
    """The overlap *fraction of one cell* with the closed band ``[0, low_hz]``, piecewise.

    Written as a cut of the cell against the band rather than as a min/max expression, so the
    arithmetic is a visibly different route to the same weight.
    """
    if low >= low_hz:
        return 0.0
    if high <= low_hz:
        return 1.0
    return (low_hz - low) / (high - low)


def _band_power_and_total(estimate, *, low_hz: float = LOW_HZ) -> tuple[float, float]:
    """``(B, T)`` of §2 from the estimate's own axis, density and spacing.

    ``B`` weights each bin by the fraction of its own cell inside the closed band; ``T`` is the
    one-sided integral ``sum(psd) * delta_f`` recomputed here as an independent *check* of the
    read denominator, never as the value the report quotes.
    """
    profiles = int(estimate.profiles)
    rate = float(estimate.effective_sample_rate_hz)
    nyquist = float(estimate.nyquist_hz)
    psd = np.asarray(estimate.psd, dtype=float)
    delta = float(estimate.delta_f_hz)
    bins = profiles // 2 + 1
    assert psd.size == bins, (profiles, psd.size)
    assert delta == pytest.approx(rate / profiles, rel=1e-12)
    low, high = _edges(profiles, rate, nyquist)
    weight = np.where(
        low >= low_hz,
        0.0,
        np.where(
            high <= low_hz,
            1.0,
            (low_hz - low) / np.maximum(high - low, np.finfo(float).tiny),
        ),
    )
    band = float(np.sum(weight * psd * delta))
    total = float(np.sum(psd) * delta)
    return band, total


def _state_of(verdict: SpectralVerdict, total: float | None) -> str:
    """The band state of one estimate, from its own verdict and measured total - locally.

    The three states are defined here from first principles: an axis the estimator refused was
    not measured; a defined spectrum whose window-normalized mean-square power is zero is a
    measured zero whose ratio is 0/0; every other defined spectrum carries a fraction.
    """
    if verdict is SpectralVerdict.REFUSED_AXIS:
        return STATE_REFUSED
    assert verdict is SpectralVerdict.DEFINED, verdict
    return STATE_ZERO if total == 0.0 else STATE_DEFINED


# --------------------------------------------------------------------------------------
# fixtures: one report, one decode, one recomputation - each built once
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def published(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The scratch report, written once into pytest's temp tree (never under ``reports/``)."""
    scratch = tmp_path_factory.mktemp("sa2-4-s3-verifier")
    _require_writer().write_sparse_signal_report(scratch, analysis_commit=REVISION)
    assert scratch.is_dir()
    return scratch


@pytest.fixture(scope="module")
def sweep() -> dict[tuple[str, str, str], object]:
    """The committed reproducibility sweep, decoded afresh: ``(pass, relative_path, view)``.

    The key carries the recording's own relative path, so a job's several recordings do not
    collapse onto one cell, and the two views are separate cells.
    """
    views: dict[tuple[str, str, str], object] = {}
    for ref in COMMITTED_PASSES:
        if not ref.is_reproducibility_sitting:
            continue
        decoding = decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
        for point in decoding.points:
            for view in (
                primary_view(
                    point, window_s=decoding.window_s, support_mm=decoding.support_mm
                ),
                full_record_view(point, support_mm=decoding.support_mm),
            ):
                label = SparseView(view.view).value
                views[(ref.name, view.relative_path, label)] = view
    return views


@pytest.fixture(scope="module")
def published_rows(published: Path) -> tuple[list[str], list[dict[str, str]]]:
    """The published table's header and rows, parsed as CSV (quoting honoured)."""
    text = (published / CSV_NAME).read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    assert rows, "the published CSV carries no data row"
    return list(rows[0].keys()), rows


@pytest.fixture(scope="module")
def document(published: Path) -> dict:
    """The published JSON document."""
    return json.loads((published / DOC_NAME).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recomputed(sweep) -> dict:
    """Every published gate row, recomputed from the decoded view and its own density.

    One entry per ``(pass, relative_path, view, gate_index)``, holding the estimator's verdict and
    the handwritten-oracle ``(B, T, fraction)`` and state; plus, per cell, the axis scalars read
    off the first supported gate's estimate. This is the independent statement of what the report
    should publish.
    """
    cells: dict[tuple[str, str, str], dict] = {}
    gates: dict[tuple[str, str, str, int], dict] = {}
    for key, view in sweep.items():
        depths = np.asarray(view.depths_mm, dtype=float)
        columns = [int(c) for c in np.asarray(view.supported_columns)]
        first = None
        for index in columns:
            estimate = periodogram_of_view(view, depth_mm=float(depths[index]))
            if first is None:
                first = estimate
            if estimate.verdict is SpectralVerdict.DEFINED:
                band, total = _band_power_and_total(estimate)
                fraction = band / total if total > 0.0 else None
            else:
                band, total, fraction = None, None, None
            gates[(*key, index)] = {
                "verdict": estimate.verdict.value,
                "state": _state_of(estimate.verdict, None if total is None else total),
                "band_power": band,
                "total_power": total,
                "fraction": fraction,
                "depth_mm": float(depths[index]),
                "parseval_relative_error": estimate.parseval_relative_error,
                "enbw_bins": estimate.enbw_bins,
                "enbw_hz": estimate.enbw_hz,
                "integrated_psd_power": estimate.integrated_psd_power,
            }
        assert first is not None, key
        characterization = first.characterization
        cells[key] = {
            "profiles": int(first.profiles),
            "span_s": first.span_s,
            "dt_eff_s": first.dt_eff_s,
            "effective_sample_rate_hz": first.effective_sample_rate_hz,
            "nyquist_hz": first.nyquist_hz,
            "delta_f_hz": first.delta_f_hz,
            "duration_resolution_scale_hz": characterization.duration_resolution_scale_hz,
            "max_relative_timing_error": characterization.max_relative_timing_error,
            "max_timing_error_s": characterization.max_timing_error_s,
            "max_relative_interval_deviation": (
                characterization.max_relative_interval_deviation
            ),
            "largest_gap_ratio": characterization.largest_gap_ratio,
            "spectral_uniformity_tol": float(first.admission.spectral_uniformity_tol),
            "admitted": bool(first.admission.admitted),
            "supported_gates": len(columns),
            "columns": columns,
        }
    return {"gates": gates, "cells": cells}


# --------------------------------------------------------------------------------------
# small typed readers over the published row text
# --------------------------------------------------------------------------------------


def _num(row: dict[str, str], name: str) -> float | None:
    value = row[name]
    return None if value == "" else float(value)


def _cell_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (row["pass"], row["relative_path"], row["view"])


def _rows_by_cell(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], list[dict]]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault(_cell_key(row), []).append(row)
    return grouped


def _json_cells(document: dict) -> dict[tuple[str, str, str], dict]:
    return {
        (entry["pass"], entry["relative_path"], entry["view"]): entry
        for entry in document["cells"]
    }


def _target(entry: dict, label: str) -> dict:
    for row in entry["targets"]:
        if row["target_label"] == label:
            return row
    raise AssertionError(f"{label!r} is not among {entry['targets']}")


def _supported_per_view(sweep) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for (pass_name, _relative, label), view in sweep.items():
        counts[label] += len(np.asarray(view.supported_columns))
    return counts


# --------------------------------------------------------------------------------------
# 1. the source row set and the per-gate native support identities
# --------------------------------------------------------------------------------------


def test_the_published_cells_are_exactly_the_decoded_committed_sweep(
    published_rows, sweep
) -> None:
    """The row set is the committed sweep's ``recording x view`` pairs - and nothing else."""
    header, rows = published_rows
    assert tuple(header) == SURFACE_COLUMNS, header
    published_cells = {_cell_key(row) for row in rows}
    assert published_cells == set(sweep), (
        "the published cells are exactly the committed sweep's recording x view pairs"
    )
    assert len(published_cells) == EXPECTED_CELLS == 104
    passes = {key[0] for key in published_cells}
    assert passes == set(SITTINGS), passes
    assert CAMPAIGN not in passes, "the Stage-2 campaign is not a default SA2.4 scope"
    assert {key[2] for key in published_cells} == {"primary-comparison", "full-record"}


def test_every_gate_row_is_a_native_supported_column_of_its_decoded_view(
    published_rows, sweep
) -> None:
    """Each published gate is the view's own native column, in native order, with its own depth."""
    _header, rows = published_rows
    grouped = _rows_by_cell(rows)
    assert set(grouped) == set(sweep)
    for key, cell_rows in grouped.items():
        view = sweep[key]
        depths = np.asarray(view.depths_mm, dtype=float)
        expected = [int(column) for column in np.asarray(view.supported_columns)]
        published = [int(row["gate_index"]) for row in cell_rows]
        assert published == expected, (
            f"{key}: the rows are supported_columns in native depth order"
        )
        assert published == sorted(published) and len(set(published)) == len(published)
        mask = np.asarray(view.support_mask)
        for row in cell_rows:
            index = int(row["gate_index"])
            assert bool(mask[index]), (key, index)
            assert float(row["depth_mm"]) == pytest.approx(float(depths[index])), (
                key,
                index,
            )


def test_the_row_count_is_one_per_supported_gate_and_the_document_agrees(
    published_rows, document, sweep
) -> None:
    """The CSV is the sole per-gate record: one row per supported gate, and no JSON copy of it.

    The document's per-cell rows carry the gate *count* (``supported_gates``) but not the gate
    rows: the 5720 ``cell x supported gate`` rows are serialized once, in the table, so a reader
    joins a gate's numbers to its cell by the table's own keys.
    """
    _header, rows = published_rows
    assert len(rows) == EXPECTED_GATE_ROWS == 5720
    pairs = [(_cell_key(row), int(row["gate_index"])) for row in rows]
    assert len(set(pairs)) == len(pairs) == EXPECTED_GATE_ROWS
    expected = sum(
        int(view_provenance(view).supported_gates) for view in sweep.values()
    )
    assert len(rows) == expected
    js = _json_cells(document)
    assert set(js) == set(sweep)
    for key, entry in js.items():
        provenance = view_provenance(sweep[key])
        assert entry["supported_gates"] == provenance.supported_gates
        assert entry["native_gates"] == provenance.native_gates
        assert entry["profiles"] == provenance.profiles
        assert "gates" not in entry, (
            f"{key}: the document duplicates the table's per-gate rows under a 'gates' array"
        )
    # and the table's own rows are that view's supported columns, one per gate, in native order.
    for key, cell_rows in _rows_by_cell(rows).items():
        assert [int(row["gate_index"]) for row in cell_rows] == [
            int(column) for column in np.asarray(sweep[key].supported_columns)
        ], key
        assert len(cell_rows) == int(view_provenance(sweep[key]).supported_gates), key


def test_the_published_provenance_is_the_decoded_recording_s(
    published_rows, sweep
) -> None:
    """Identity, source digest and window travel from the decoded view, not a rebuilt summary."""
    _header, rows = published_rows
    for key, cell_rows in _rows_by_cell(rows).items():
        provenance = view_provenance(sweep[key])
        row = cell_rows[0]
        assert row["job"] == provenance.job
        assert row["point_label"] == provenance.point_label
        assert int(row["order"]) == int(provenance.order)
        assert row["source_sha256"] == provenance.source_sha256
        assert row["view"] == provenance.view.value
        assert int(row["profiles"]) == provenance.profiles
        assert row["relative_path"].endswith(".BDD")
        assert len(row["source_sha256"]) == 64
        int(row["source_sha256"], 16)  # a real hex digest, not a placeholder


# --------------------------------------------------------------------------------------
# 2. the numbers: the handwritten-boundary oracle over every gate row
# --------------------------------------------------------------------------------------


def test_every_published_fraction_is_the_handwritten_boundary_reduction(
    published_rows, recomputed
) -> None:
    """All 5720 rows: ``B``, ``T``, ``Phi`` and the state against a self-contained oracle."""
    _header, rows = published_rows
    oracle = recomputed["gates"]
    assert len(rows) == len(oracle) == EXPECTED_GATE_ROWS
    for row in rows:
        key = (*_cell_key(row), int(row["gate_index"]))
        expected = oracle[key]
        assert row["verdict"] == expected["verdict"], key
        assert row["band_state"] == expected["state"], key
        assert float(row["depth_mm"]) == pytest.approx(expected["depth_mm"])
        if expected["state"] == STATE_REFUSED:
            assert row["band_fraction"] == "" and row["band_power"] == "", key
            assert row["total_power"] == "", key
            continue
        if expected["state"] == STATE_ZERO:
            assert row["band_fraction"] == "", key
            assert float(row["band_power"]) == 0.0
            assert float(row["total_power"]) == 0.0
            continue
        published_fraction = _num(row, "band_fraction")
        published_band = _num(row, "band_power")
        published_total = _num(row, "total_power")
        assert published_fraction is not None and published_band is not None
        assert published_total is not None and published_total > 0.0
        assert published_fraction == pytest.approx(
            expected["fraction"], abs=FRACTION_ABS
        ), key
        assert published_band == pytest.approx(expected["band_power"], rel=POWER_REL), (
            key
        )
        assert published_total == pytest.approx(
            expected["total_power"], rel=POWER_REL
        ), key
        # the published denominator is the estimate's own integrated power, not a re-summed one
        assert published_total == pytest.approx(
            expected["integrated_psd_power"], rel=POWER_REL
        ), key
        # the fraction printed beside the two powers is their ratio, at its own precision
        assert math.isclose(
            published_fraction, published_band / published_total, abs_tol=FRACTION_ABS
        ), key


def test_the_handwritten_cells_tile_the_band_and_the_endpoints_hold(recomputed) -> None:
    """§2's boundary arithmetic, on the decoded axes: the cells tile ``[0, f_N]`` exactly.

    The whole-band integral of the weight function is one, the DC cell opens at ``0.0`` and the
    top cell closes at ``min(nyquist, (k + 0.5) * delta_f)``, for both grid parities - checked on
    every distinct axis the sweep holds.
    """
    axes = {
        (cell["profiles"], cell["nyquist_hz"]) for cell in recomputed["cells"].values()
    }
    assert axes, "no axis was recomputed"
    for profiles, nyquist in axes:
        delta = nyquist * 2.0 / profiles
        rate = delta * profiles
        bins = profiles // 2 + 1
        low0, high0 = _cell_edges(0, profiles=profiles, rate=rate, nyquist=nyquist)
        assert low0 == 0.0
        assert high0 == pytest.approx(0.5 * delta)
        _low_last, high_last = _cell_edges(
            bins - 1, profiles=profiles, rate=rate, nyquist=nyquist
        )
        assert high_last == pytest.approx(min(nyquist, (bins - 0.5) * delta))
        lows, highs = _edges(profiles, rate, nyquist)
        assert np.allclose(lows[1:], highs[:-1]), (
            "the cells must tile without a gap or overlap"
        )
        # the whole band [0, nyquist] is exactly covered: the weighted cell lengths sum to it
        covered = sum(
            _weight(lows[k], highs[k], low_hz=nyquist) * (highs[k] - lows[k])
            for k in range(bins)
        )
        assert covered == pytest.approx(nyquist, rel=1e-9), (profiles, nyquist)


def test_the_published_axis_is_the_estimate_s_own_characterization(
    published_rows, recomputed
) -> None:
    """§3's axis scalars, all 104 cells, against the decoded estimate's own characterization."""
    _header, rows = published_rows
    cells = recomputed["cells"]
    grouped = _rows_by_cell(rows)
    assert set(grouped) == set(cells)
    for key, published_cell in grouped.items():
        row = published_cell[0]
        expected = cells[key]
        assert int(row["profiles"]) == expected["profiles"], key
        assert float(row["low_band_hz"]) == LOW_HZ, key
        for column in (
            "span_s",
            "dt_eff_s",
            "effective_sample_rate_hz",
            "nyquist_hz",
            "delta_f_hz",
            "duration_resolution_scale_hz",
            "max_relative_timing_error",
            "max_timing_error_s",
            "spectral_uniformity_tol",
        ):
            assert _num(row, column) == pytest.approx(expected[column]), (key, column)
        assert (row["admitted"] == "true") is expected["admitted"], key
        assert row["detrending"] == "mean", key
        assert row["quantity"] == "axial_velocity" and row["unit"] == "mm/s", key
        assert row["psd_unit"] == "(mm/s)^2/Hz", key


def test_the_gate_enbw_and_qa_fields_are_the_estimates_own(
    published_rows, recomputed
) -> None:
    """The QA column and the equivalent-noise bandwidth are read, not recomputed differently."""
    _header, rows = published_rows
    oracle = recomputed["gates"]
    for row in rows:
        key = (*_cell_key(row), int(row["gate_index"]))
        expected = oracle[key]
        for column in ("enbw_bins", "enbw_hz", "parseval_relative_error"):
            published = _num(row, column)
            value = expected[column]
            if value is None:
                assert published is None, (key, column)
            else:
                assert published == pytest.approx(float(value), rel=1e-9), (key, column)


# --------------------------------------------------------------------------------------
# 3. the digests: recomputed by hand, from bytes and files
# --------------------------------------------------------------------------------------


def _canonical_lf(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_the_table_digest_is_the_hand_computed_canonical_lf_sha256(
    published, document
) -> None:
    """``table_sha256`` is the SHA-256 of the CSV's canonical LF bytes, computed here by hand."""
    csv_path = published / CSV_NAME
    digest = "sha256:" + hashlib.sha256(_canonical_lf(csv_path)).hexdigest()
    assert document["table_sha256"] == digest, document["table_sha256"]
    assert document["table"] == CSV_NAME
    assert document["analysis_commit"] == REVISION
    # the digest is over the canonical form: a CRLF-materialised copy hashes identically
    crlf = csv_path.with_name("crlf-check.tmp")
    crlf.write_bytes(csv_path.read_bytes().replace(b"\n", b"\r\n"))
    try:
        other = "sha256:" + hashlib.sha256(_canonical_lf(crlf)).hexdigest()
    finally:
        crlf.unlink()
    assert other == digest


def _without_none(node):
    """The plan model's own ``exclude_none`` identity: drop every null field, recursively."""
    if isinstance(node, dict):
        return {
            key: _without_none(value)
            for key, value in node.items()
            if value is not None
        }
    if isinstance(node, list):
        return [_without_none(value) for value in node]
    return node


def test_the_plan_fingerprints_are_recomputed_from_the_plan_files(
    published, document
) -> None:
    """Each per-pass fingerprint is the plan file's canonical-JSON SHA-256, and the aggregate is
    the SHA-256 over the canonical JSON of that map."""
    fingerprints = document["plan_fingerprints"]
    assert set(fingerprints) == set(SITTINGS), fingerprints
    for ref in COMMITTED_PASSES:
        if not ref.is_reproducibility_sitting:
            continue
        payload = json.loads(Path(ref.plan_path).read_text(encoding="utf-8"))
        canonical = json.dumps(
            _without_none(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert fingerprints[ref.name] == expected, ref.name
    aggregate = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                dict(fingerprints),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    )
    assert document["plan_fingerprint"] == aggregate, document["plan_fingerprint"]
    assert CAMPAIGN not in fingerprints


def test_the_published_files_are_the_three_scalar_artefacts(
    published, document
) -> None:
    """§5's file set is closed: the table, the document and the README, nothing else."""
    produced = sorted(
        path.relative_to(published).as_posix()
        for path in published.rglob("*")
        if path.is_file()
    )
    assert produced == sorted((CSV_NAME, DOC_NAME, README_NAME)), produced
    assert document["artefact"].endswith("sa2-4-spectral-characterization")


# --------------------------------------------------------------------------------------
# 4. E128 by label, against the decoded axis
# --------------------------------------------------------------------------------------


def test_e128_refuses_the_rotor_band_by_label_from_the_decoded_axis(
    document, published_rows, recomputed
) -> None:
    """E128's rotor is refused for the Nyquist reason, read by label and redone from the axis."""
    js = _json_cells(document)
    e128 = {key: entry for key, entry in js.items() if entry["job"] == "emissions-128"}
    assert len(e128) == 16, "eight E128 recordings on two views"
    oracle = recomputed["gates"]
    _header, table_rows = published_rows
    by_cell = _rows_by_cell(table_rows)
    for key, entry in e128.items():
        rotor = _target(entry, ROTOR_LABEL)
        assert rotor["target_hz"] == pytest.approx(ROTOR_HZ)
        assert rotor["band_supported"] is False
        assert rotor["analysis_supported"] is True, (
            "the estimator is admitted; only the 8.333 Hz band is impossible"
        )
        assert rotor["supported"] is False
        assert "Nyquist" in rotor["reason"], rotor["reason"]
        nyquist = recomputed["cells"][key]["nyquist_hz"]
        assert nyquist is not None and nyquist < ROTOR_HZ, key
        recurrence = _target(entry, RECURRENCE_LABEL)
        assert recurrence["band_supported"] is True
        assert recurrence["analysis_supported"] is True
        assert recurrence["supported"] is True
        # and the E128 gate rows are measurements, not refusals - read from the table, which is
        # the sole per-gate record (the document no longer carries a 'gates' array)
        cell_rows = by_cell[key]
        assert cell_rows, key
        for row in cell_rows:
            index = int(row["gate_index"])
            assert oracle[(*key, index)]["state"] == STATE_DEFINED, key
            assert row["band_state"] == STATE_DEFINED
            assert row["verdict"] == SpectralVerdict.DEFINED.value
            assert 0.0 <= float(row["band_fraction"]) <= 1.0 + 1e-9


def test_every_target_row_is_the_direct_axis_answer_by_label(
    document, recomputed
) -> None:
    """Both probe rows per cell, in the design's order, with the Nyquist and cell arithmetic redone.

    ``band_supported`` is the strict-below-Nyquist answer, recomputed from the decoded axis;
    ``analysis_supported`` is the admission's own ``admitted``; the nearest bin's cell edges are
    this file's own.
    """
    js = _json_cells(document)
    assert len(js) == EXPECTED_CELLS
    for key, entry in js.items():
        cell = recomputed["cells"][key]
        labels = [row["target_label"] for row in entry["targets"]]
        assert labels == [RECURRENCE_LABEL, ROTOR_LABEL], labels
        frequencies = [row["target_hz"] for row in entry["targets"]]
        assert frequencies == pytest.approx([RECURRENCE_HZ, ROTOR_HZ])
        nyquist = cell["nyquist_hz"]
        delta = cell["delta_f_hz"]
        bins = cell["profiles"] // 2 + 1
        for row in entry["targets"]:
            target = row["target_hz"]
            expected_band = bool(target < nyquist)
            assert row["band_supported"] is expected_band, (key, row["target_label"])
            assert row["analysis_supported"] is cell["admitted"], key
            assert row["supported"] is (expected_band and cell["admitted"]), key
            assert row["nyquist_hz"] == pytest.approx(nyquist), key
            index = int(row["prospective_bin"])
            assert 0 <= index < bins, key
            assert row["prospective_bin_hz"] == pytest.approx(index * delta, rel=1e-9)
            assert row["bin_offset_hz"] == pytest.approx(
                target - index * delta, rel=1e-9
            )
            low, high = _cell_edges(
                index,
                profiles=cell["profiles"],
                rate=cell["effective_sample_rate_hz"],
                nyquist=nyquist,
            )
            assert row["cell_low_hz"] == pytest.approx(low, rel=1e-9), (key, index)
            assert row["cell_high_hz"] == pytest.approx(high, rel=1e-9), (key, index)


# --------------------------------------------------------------------------------------
# 5. symmetry: the two views, the shared gate set and the published repeat spread
# --------------------------------------------------------------------------------------


def test_the_two_views_are_published_symmetrically_for_every_recording(
    published_rows, sweep
) -> None:
    """Each recording appears once per view, over the same native gate set, on one admitted axis.

    The support is the *pass's* restriction, not the view's, so the two views of a recording hold
    the same supported columns and depths; only the time window differs. That is the symmetry the
    row set must show: no view silently carries a different gate set.
    """
    _header, rows = published_rows
    grouped = _rows_by_cell(rows)
    by_recording: dict[tuple[str, str], dict[str, list[dict]]] = defaultdict(dict)
    for (pass_name, relative_path, view_label), cell_rows in grouped.items():
        by_recording[(pass_name, relative_path)][view_label] = cell_rows
    assert len(by_recording) == 52, "52 recordings, one pair of view cells each"
    for recording, by_view in by_recording.items():
        assert set(by_view) == {"primary-comparison", "full-record"}, recording
        primary = by_view["primary-comparison"]
        full = by_view["full-record"]
        assert [r["gate_index"] for r in primary] == [r["gate_index"] for r in full], (
            recording
        )
        assert [r["depth_mm"] for r in primary] == [r["depth_mm"] for r in full], (
            recording
        )
        assert int(primary[0]["profiles"]) <= int(full[0]["profiles"]), recording
        assert primary[0]["admitted"] == full[0]["admitted"], recording
        for view_label, cell_rows in by_view.items():
            view = sweep[(recording[0], recording[1], view_label)]
            assert int(cell_rows[0]["profiles"]) == int(view.values.shape[0]), recording
    per_view: dict[str, int] = defaultdict(int)
    for row in rows:
        per_view[row["view"]] += 1
    expected = _supported_per_view(sweep)
    assert per_view == expected, (dict(per_view), expected)
    assert per_view["primary-comparison"] == per_view["full-record"]


def test_the_primary_window_is_the_passes_own_declared_cut(document, sweep) -> None:
    """The primary view's declared window is the pass's shared one; the full record declares none."""
    js = _json_cells(document)
    for key, entry in js.items():
        provenance = view_provenance(sweep[key])
        assert entry["window_s"] == pytest.approx(provenance.window_s), key
        assert entry["declared_window_s"] == provenance.declared_window_s, key
        assert entry["view_rule"] == provenance.view_rule, key
        if entry["view"] == "full-record":
            assert entry["declared_window_s"] is None, key
        else:
            assert entry["window_s"] <= entry["declared_window_s"] + 1e-9, key


def test_the_repeat_spread_groups_by_condition_rather_than_by_job_or_label(
    document, sweep
) -> None:
    """F1: the published groups are one *whole condition* each, never a job- or label-keyed average.

    One job's cells span several point labels (the ``ctrl-*`` anchors beside the ``cc``/``e``
    contrasts) **and** one label recurs under different conditions, so any grouping by ``job`` or by
    ``point_label`` would average distinct conditions and read as a repeat where none was measured.
    The verifier reads the decoded conditions afresh and requires every published group to be
    exactly a decoded same-condition set. The committed set is asserted to really mix, so the row
    cannot pass by finding nothing to check.
    """
    labels: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for key, view in sweep.items():
        provenance = view_provenance(view)
        labels[(key[0], provenance.job, key[2])].add(provenance.point_label)
    mixed = sorted(key for key, values in labels.items() if len(values) > 1)
    assert mixed, (
        "this row is only non-vacuous because a job's cells span several conditions; the decoded "
        "sweep shows no mixing, so a job-keyed group could not be ruled out"
    )

    repeats, _singletons = _true_repeat_recordings(sweep)
    decoded_keys = {
        (pass_name, condition[0], condition[1:4], condition[4], condition[5])
        for (pass_name, condition, _depths) in repeats
    }
    groups = document[VERIFIER_REPEAT_GROUPS_KEY]
    published_keys = {_verifier_group_key(group) for group in groups}
    assert published_keys == decoded_keys, published_keys ^ decoded_keys

    # the point label really is not the key: one label, several distinct conditions.
    label_conditions: dict[str, set[tuple]] = defaultdict(set)
    for group in groups:
        for member in group["members"]:
            label_conditions[str(member["point_label"])].add(
                (
                    group["condition"]["burst_length"],
                    group["condition"]["emissions_per_profile"],
                    group["condition"]["prf_us"],
                    group["resolution_mm"],
                )
            )
    assert any(len(values) > 1 for values in label_conditions.values()), (
        "no published point label recurs under distinct conditions, so the label-keyed pooling "
        "argument is vacuous"
    )


# --------------------------------------------------------------------------------------
# 5b. the §4 repeat spread, grounded in the decoded condition rather than in a label
#
# The published identity is not a condition: ``ctrl-begin`` recurs under burst-4 and burst-18, and
# one job holds several conditions (its ``cc``/``e`` contrasts). The plan's condition - the job's
# condition triple and kind, plus the window the point requested (resolution and gate count) - comes
# from the decoded binding, and two cells repeat one condition only when their primary depth vectors
# match too. That grouping is the only one that repeats a condition rather than contrasting several.
# --------------------------------------------------------------------------------------


def _decoded_conditions() -> dict[tuple[str, str], tuple]:
    """Each committed recording's true condition, keyed by ``(pass, relative_path)``."""
    conditions: dict[tuple[str, str], tuple] = {}
    for ref in COMMITTED_PASSES:
        if not ref.is_reproducibility_sitting:
            continue
        decoding = decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
        for point in decoding.points:
            job = point.binding.job
            parameters = point.binding.point.parameters
            conditions[(ref.name, str(point.binding.relative_path))] = (
                str(job.kind),
                int(job.burst_length),
                int(job.emissions_per_profile),
                float(job.prf_us),
                round(float(parameters.resolution_mm), 9),
                int(parameters.gates),
            )
    return conditions


def _primary_depths(view) -> tuple[float, ...]:
    depths = np.asarray(view.depths_mm, dtype=float)
    return tuple(
        round(float(depths[int(column)]), 9)
        for column in np.asarray(view.supported_columns)
    )


def _true_repeat_recordings(
    sweep,
) -> tuple[dict[tuple, set[str]], list[tuple[str, str]]]:
    """The committed recordings grouped by true condition + primary depth vector.

    Returns ``(repeats, singletons)``: ``repeats`` maps
    ``(pass, condition, primary_depths)`` to the set of member relative paths, and ``singletons``
    lists the ``(pass, relative_path)`` pairs whose condition-and-depths occur once.
    """
    conditions = _decoded_conditions()
    grouped: dict[tuple, set[str]] = defaultdict(set)
    for key, view in sweep.items():
        pass_name, _relative, _label = key
        relative = str(view_provenance(view).relative_path)
        primary = sweep[(pass_name, relative, "primary-comparison")]
        grouped[
            (pass_name, conditions[(pass_name, relative)], _primary_depths(primary))
        ].add(relative)
    repeats = {key: paths for key, paths in grouped.items() if len(paths) > 1}
    singletons = sorted(
        (key[0], relative)
        for key, paths in grouped.items()
        if len(paths) == 1
        for relative in paths
    )
    return repeats, singletons


def test_the_decoded_sweep_grounds_twelve_repeat_groups_and_sixteen_singleton_cells(
    sweep,
) -> None:
    """§4 grounding: 12 true same-condition groups (6 per sitting), 44 recordings, 16 singletons.

    Counted from the decoded bindings and the sweep's own views: 6 groups per sitting, 22 recordings
    per sitting (44), each on both views (88 cells), and 8 singleton recordings (16 cells) - the
    ``cc`` contrast points, each at its own resolution, which are no repeat at all.
    """
    repeats, singletons = _true_repeat_recordings(sweep)
    assert len(repeats) == 12, sorted(key[:2] for key in repeats)
    for pass_name in SITTINGS:
        assert sum(1 for key in repeats if key[0] == pass_name) == 6, pass_name

    grouped_recordings = sum(len(paths) for paths in repeats.values())
    assert grouped_recordings == 44, grouped_recordings
    assert grouped_recordings * 2 == 88
    assert len(singletons) == 8, singletons
    assert len(singletons) * 2 == 16
    assert {key[0] for key in repeats} == set(SITTINGS)

    # the grouped and singleton recordings partition the committed sweep, so no cell is both a
    # repeat and a singleton, and none is quietly dropped.
    grouped_recordings_set = {
        (key[0], relative) for key, paths in repeats.items() for relative in paths
    }
    singleton_set = set(singletons)
    assert not (grouped_recordings_set & singleton_set)
    assert len(grouped_recordings_set | singleton_set) == 2 * 26


def test_the_published_repeat_spread_is_true_repeats_of_the_decoded_condition(
    document, sweep, recomputed
) -> None:
    """§4: the published spread is over true same-condition groups, with recomputed arithmetic.

    Each published group must be a true same-condition repeat of the decoded sweep (condition
    triple, kind, resolution and gates equal, primary depth vectors identical) and its members must
    be exactly that group's recordings. Each row must exclude the 16 singleton cells, cover one
    ``(group, view, gate)`` each, and carry min/max/range recomputed here from **this verifier's own
    handwritten-oracle fractions** at that view and gate - never a number quoted from anywhere. The
    §4 summary's counts are pinned against the decoded sweep, so the singletons are shown excluded
    rather than dropped.
    """
    repeats, singletons = _true_repeat_recordings(sweep)
    singleton_cells = {(pass_name, relative) for pass_name, relative in singletons}
    path_to_identity = {
        (key[0], str(view_provenance(view).relative_path)): (
            str(view_provenance(view).job),
            str(view_provenance(view).point_label),
        )
        for key, view in sweep.items()
    }
    identity_to_path = {
        (pass_name, *identity): relative
        for (pass_name, relative), identity in path_to_identity.items()
    }
    decoded_by_key = {
        (pass_name, condition[0], condition[1:4], condition[4], condition[5]): members
        for (pass_name, condition, _depths), members in repeats.items()
    }

    groups = document[VERIFIER_REPEAT_GROUPS_KEY]
    assert {_verifier_group_key(group) for group in groups} == set(decoded_by_key)
    for group in groups:
        key = _verifier_group_key(group)
        members = decoded_by_key[key]
        assert group["n_recordings"] == len(members), key
        assert group["n_cells"] == len(members) * 2, key

    rows = document[VERIFIER_REPEAT_SPREAD_KEY]
    covered: list[tuple] = []
    for row in rows:
        key = _verifier_group_key(row)
        assert key in decoded_by_key, (key, sorted(row))
        members = decoded_by_key[key]
        assert not ({(key[0], relative) for relative in members} & singleton_cells), key
        published = [
            (str(member["job"]), str(member["point_label"]))
            for member in row["members"]
        ]
        assert set(published) == {
            path_to_identity[(key[0], relative)] for relative in members
        }, (key, published)

        values = [member["band_fraction"] for member in row["members"]]
        defined = [float(value) for value in values if value is not None]
        assert row["n"] == len(defined), (key, row["gate_index"])
        if not defined:
            assert row["min"] is None and row["max"] is None and row["range"] is None
        else:
            assert row["min"] == min(defined) and row["max"] == max(defined)
            assert row["range"] == max(defined) - min(defined)

        # the same spread, recomputed from this verifier's own oracle fractions at this view/gate.
        from_oracle = [
            recomputed["gates"][
                (
                    key[0],
                    identity_to_path[(key[0], *identity)],
                    row["view"],
                    int(row["gate_index"]),
                )
            ]["fraction"]
            for identity in published
            if (
                key[0],
                identity_to_path[(key[0], *identity)],
                row["view"],
                int(row["gate_index"]),
            )
            in recomputed["gates"]
        ]
        defined_oracle = [value for value in from_oracle if value is not None]
        assert defined_oracle == pytest.approx(defined, abs=FRACTION_ABS), (
            key,
            row["view"],
            row["gate_index"],
        )
        covered.append((key, row["view"], int(row["gate_index"])))

    assert len(covered) == len(set(covered)), "a (group, view, gate) is published twice"
    assert {key for key, _view, _gate in covered} == set(decoded_by_key)

    summary = document[VERIFIER_REPEAT_SPREAD_SUMMARY_KEY]
    assert summary["groups"] == len(repeats) == 12
    assert (
        summary["recordings"]
        == sum(len(members) for members in decoded_by_key.values())
        == 44
    )
    assert summary["cells"] == summary["recordings"] * 2 == 88
    assert summary["singleton_recordings"] == len(singletons) == 8
    assert summary["singleton_cells"] == len(singletons) * 2 == 16
    assert summary["spread_rows"] == len(rows)


def _verifier_group_key(source: dict) -> tuple:
    """A published group's or row's whole condition, in the decoded grouping key's shape."""
    triple = source["condition"]
    return (
        source["pass"],
        source["kind"],
        (
            int(triple["burst_length"]),
            int(triple["emissions_per_profile"]),
            float(triple["prf_us"]),
        ),
        float(source["resolution_mm"]),
        int(source["window_gates"]),
    )


#: The planned native gate count of the window the committed repeats were acquired on, and the
#: supported gate rows a cell of such a group publishes. The two differ on the committed set (50
#: planned, 49 supported), so ``window_gates`` is the window's own dimension and not a row count
#: under a new name (F1/F8).
PLANNED_WINDOW_GATES = 50
SUPPORTED_GATES_PER_REPEAT_CELL = 49


def test_the_repeat_window_gate_count_is_the_planned_dimension_not_the_supported_rows(
    document, sweep, published_rows
) -> None:
    """F1/F8: §4 publishes ``window_gates`` - the plan's own planned count - distinct from the rows.

    Recomputed from the decoded bindings rather than trusted as a constant: every committed repeat
    plans 50 native gates on its 1.85 mm window while each of its cells publishes 49 supported gate
    rows, so the window's own dimension (50) and the row count (49) are different numbers. Both §4
    shapes must carry the renamed field and no ambiguous ``gates``; the planned count is read from
    the decoded plan's ``parameters.gates``, so the field cannot be a clone of the row count.
    """
    conditions = _decoded_conditions()
    groups = document[VERIFIER_REPEAT_GROUPS_KEY]
    rows = document[VERIFIER_REPEAT_SPREAD_KEY]
    assert groups and rows
    assert PLANNED_WINDOW_GATES != SUPPORTED_GATES_PER_REPEAT_CELL, (
        "this row is only non-vacuous because the planned count and the supported row count "
        "differ on the committed set"
    )

    # the rename: neither §4 shape publishes the ambiguous name, both publish the window dimension.
    for source in (*groups, *rows):
        assert "gates" not in source, (
            "§4 publishes the window dimension under the ambiguous name 'gates': "
            + repr(sorted(source))
        )
        assert "window_gates" in source, sorted(source)

    # the published window count is the decoded plan's own planned gate count, member for member.
    identity_to_path: dict[tuple[str, str, str], str] = {}
    for (pass_name, _relative, _label), view in sweep.items():
        provenance = view_provenance(view)
        identity_to_path[
            (pass_name, str(provenance.job), str(provenance.point_label))
        ] = str(provenance.relative_path)
    for group in groups:
        planned = {
            conditions[
                (
                    group["pass"],
                    identity_to_path[
                        (group["pass"], str(m["job"]), str(m["point_label"]))
                    ],
                )
            ][5]
            for m in group["members"]
        }
        assert planned == {int(group["window_gates"])} == {PLANNED_WINDOW_GATES}, (
            group["pass"],
            planned,
        )
    for row in rows:
        planned = {
            conditions[
                (
                    row["pass"],
                    identity_to_path[
                        (row["pass"], str(m["job"]), str(m["point_label"]))
                    ],
                )
            ][5]
            for m in row["members"]
        }
        assert planned == {int(row["window_gates"])} == {PLANNED_WINDOW_GATES}, (
            row["pass"],
            row["gate_index"],
        )

    # the distinctness: 50 planned gates, 49 published rows per cell of a group.
    _header, published = published_rows
    grouped = _rows_by_cell(published)
    js = _json_cells(document)
    planned_cells = [
        key
        for key, entry in js.items()
        if int(entry["window_gates"]) == PLANNED_WINDOW_GATES
    ]
    assert len(planned_cells) == 88, len(
        planned_cells
    )  # 44 repeat recordings x 2 views
    for key in planned_cells:
        entry = js[key]
        assert entry["supported_gates"] == SUPPORTED_GATES_PER_REPEAT_CELL, key
        # the row count is read from the table - the sole per-gate record; the document's cell
        # carries the gate count and no per-gate array.
        assert "gates" not in entry, key
        assert len(grouped[key]) == SUPPORTED_GATES_PER_REPEAT_CELL, key
        assert entry["window_gates"] != entry["supported_gates"], key

    # and the §4 row set covers one row per *supported* gate - 49 - never the 50 planned.
    per_group_view: dict[tuple[tuple, str], int] = defaultdict(int)
    for row in rows:
        per_group_view[(_verifier_group_key(row), row["view"])] += 1
    assert set(per_group_view.values()) == {SUPPORTED_GATES_PER_REPEAT_CELL}


# --------------------------------------------------------------------------------------
# 6. refusal status: the state is the estimator's, and no number is invented
# --------------------------------------------------------------------------------------


def test_the_published_band_state_is_the_estimator_s_own_verdict(
    published_rows, document, recomputed
) -> None:
    """Every published state equals the decoded estimator's verdict mapping, row for row."""
    _header, rows = published_rows
    oracle = recomputed["gates"]
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        key = (*_cell_key(row), int(row["gate_index"]))
        state = oracle[key]["state"]
        assert row["band_state"] == state, key
        counts[state] += 1
    summary = document["summary"]
    assert summary["defined_gates"] == counts[STATE_DEFINED]
    assert summary["defined_zero_power_gates"] == counts[STATE_ZERO]
    assert summary["refused_axis_gates"] == counts[STATE_REFUSED]
    assert summary["gate_rows"] == len(rows)
    assert summary["cells"] == EXPECTED_CELLS
    assert summary["admitted_cells"] + summary["refused_cells"] == summary["cells"]
    assert document["ok"] is True
    assert document["failed_checks"] == []
    assert all(document["checks"].values()), document["checks"]


def test_no_committed_gate_is_refused_and_the_refusal_vocabulary_is_a_real_answer(
    published_rows, recomputed
) -> None:
    """The committed set is admitted throughout, and ``refused-axis`` is the estimator's own word.

    No committed cell is refused, so this shows the reserved state is not decorative but the
    answer the estimator gives a non-uniform axis, by asking it directly.
    """
    _header, rows = published_rows
    states = {row["band_state"] for row in rows}
    assert states == {STATE_DEFINED}, states
    assert all(info["state"] == STATE_DEFINED for info in recomputed["gates"].values())
    assert all(row["band_fraction"] != "" for row in rows)

    from udv_echo_process.analysis._sparse_view import SparseView, WindowView, view_rule

    stamps = np.arange(256, dtype=float) * 0.02
    stamps[10] = stamps[11]
    matrix = np.cos(2.0 * np.pi * 3.0 * stamps).reshape(-1, 1)
    view = WindowView(
        view=SparseView.PRIMARY,
        view_rule=view_rule(SparseView.PRIMARY),
        relative_path="synthetic.BDD",
        source_sha256="0" * 64,
        job="synthetic",
        point_label="synthetic",
        order=1,
        values=matrix,
        time_s=stamps,
        depths_mm=np.array([10.0]),
        support_mask=np.ones(1, dtype=bool),
        native_gates=1,
        native_depth_extent_mm=(8.0, 12.0),
        pass_support_mm=(8.0, 12.0),
        start_index=0,
        stop_index=int(stamps.size),
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
    )
    estimate = periodogram_of_view(view, depth_mm=10.0)
    assert estimate.verdict is SpectralVerdict.REFUSED_AXIS
    assert estimate.admission.admitted is False
    assert estimate.psd.size == 0 and estimate.frequency_hz.size == 0
    assert _state_of(estimate.verdict, None) == STATE_REFUSED


# --------------------------------------------------------------------------------------
# 7. the closed schema and strict JSON: the contract's field set, restated independently
# --------------------------------------------------------------------------------------
#
# The verifier restates the published schema rather than importing the writer's constant: a
# schema change is a contract change, and a pin that read the writer's own tuple could drift
# with it. The sets below are the whole field set - a *new* field is a failure here, not a value.

VERIFIER_DOCUMENT_KEYS: frozenset[str] = frozenset(
    {
        "analysis_commit",
        "artefact",
        "cells",
        "checks",
        "constants",
        "failed_checks",
        "json_precision_rule",
        "ok",
        "plan_fingerprint",
        "plan_fingerprint_rule",
        "plan_fingerprints",
        "repeat_condition_key",
        "repeat_groups",
        "repeat_spread",
        "repeat_spread_rule",
        "repeat_spread_summary",
        "study",
        "summary",
        "table",
        "table_sha256",
    }
)

#: Plan §4's own published names, restated independently: the row set, the groups it was taken
#: over, the key it was grouped by, its rule and its counts. A §4 field appearing under any other
#: name is a schema change this verifier must fail on.
VERIFIER_REPEAT_SPREAD_KEY = "repeat_spread"
VERIFIER_REPEAT_GROUPS_KEY = "repeat_groups"
VERIFIER_REPEAT_SPREAD_SUMMARY_KEY = "repeat_spread_summary"

VERIFIER_CONSTANT_KEYS: frozenset[str] = frozenset(
    {
        "detrending",
        "fraction_decimals",
        "gate_rule",
        "low_band_hz",
        "low_band_rule",
        "number_significant_digits",
        "probe_targets",
        "psd_unit",
        "quantity",
        "unit",
        "views",
    }
)

VERIFIER_CHECK_KEYS: frozenset[str] = frozenset(
    {
        "one_hundred_and_four_cells",
        "both_reproducibility_sittings_are_present",
        "both_views_are_present",
        "every_cell_publishes_one_table_row_per_supported_gate",
        "the_table_schema_is_the_closed_one",
        "one_axis_per_cell",
        "the_band_edge_is_the_prespecified_one",
        "detrending_is_mean_on_both_views",
        "published_fractions_lie_in_the_unit_interval",
        "a_published_band_power_is_a_part_of_its_total",
        "a_published_fraction_is_the_ratio_of_its_published_powers",
        "a_refused_axis_publishes_no_numeric_fraction",
        "a_defined_zero_power_publishes_two_zeros_and_no_fraction",
        "a_repeat_group_is_one_whole_condition",
        "the_repeat_groups_are_the_conditions_the_sweep_repeats",
        "the_repeat_spread_covers_each_group_view_and_gate_once",
        "the_repeat_spread_is_its_members_own_descriptive_arithmetic",
        "plan_fingerprints_are_per_pass_and_the_aggregate_is_their_hash",
        "the_destination_is_the_designated_root_or_outside_the_repository",
    }
)

VERIFIER_CELL_KEYS: frozenset[str] = frozenset(
    {
        "axis",
        "condition",
        "declared_window_s",
        "detrending",
        "estimator_name",
        "job",
        "kind",
        "low_band_hz",
        "native_depth_extent_mm",
        "native_gates",
        "normalization_rule",
        "one_sided_rule",
        "order",
        "participating_depth_extent_mm",
        "pass",
        "pass_support_mm",
        "plan_fingerprint",
        "point_label",
        "profiles",
        "psd_unit",
        "quantity",
        "relative_path",
        "resolution_mm",
        "source_sha256",
        "supported_gates",
        "taper_convention",
        "taper_name",
        "targets",
        "unit",
        "view",
        "view_rule",
        "window_gates",
        "window_s",
    }
)

VERIFIER_AXIS_KEYS: frozenset[str] = frozenset(
    {
        "admission_reason",
        "admitted",
        "delta_f_hz",
        "dt_eff_s",
        "duration_resolution_scale_hz",
        "effective_sample_rate_hz",
        "estimator",
        "largest_gap_ratio",
        "max_relative_interval_deviation",
        "max_relative_timing_error",
        "max_timing_error_s",
        "min_samples",
        "nyquist_hz",
        "profiles",
        "span_s",
        "spectral_uniformity_tol",
    }
)

VERIFIER_TARGET_KEYS: frozenset[str] = frozenset(
    {
        "actual_span_s",
        "analysis_reason",
        "analysis_supported",
        "band_reason",
        "band_supported",
        "bin_offset_bins",
        "bin_offset_hz",
        "cell_high_hz",
        "cell_low_hz",
        "cycles_in_view",
        "duration_resolution_scale_hz",
        "frequency_resolution_hz",
        "nyquist_hz",
        "nyquist_represented",
        "prospective_bin",
        "prospective_bin_hz",
        "reason",
        "resolution_bins_to_target",
        "supported",
        "target_hz",
        "target_label",
    }
)

VERIFIER_SUMMARY_KEYS: frozenset[str] = frozenset(
    {
        "admitted_cells",
        "cells",
        "cells_by_pass",
        "cells_by_view",
        "defined_gates",
        "defined_zero_power_gates",
        "gate_rows",
        "refused_axis_gates",
        "refused_cells",
        "target_band_supported_by_label",
        "target_supported_by_label",
    }
)


def test_the_published_schema_is_closed_and_uniform(published_rows, document) -> None:
    """F8: every published field set is exactly the contract's, pinned rather than bounded.

    ``tuple(header) == SURFACE_COLUMNS`` is the CSV half; this row adds the JSON half - the
    top-level keys, the constants, the summary and the checks - and requires each shape's key set
    to be identical across every row, so a field added to one cell and not another fails too.
    """
    _header, _rows = published_rows
    assert set(document) == VERIFIER_DOCUMENT_KEYS, sorted(document)
    assert set(document["constants"]) == VERIFIER_CONSTANT_KEYS
    assert set(document["summary"]) == VERIFIER_SUMMARY_KEYS
    assert set(document["checks"]) == VERIFIER_CHECK_KEYS

    cells = document["cells"]
    assert len(cells) == EXPECTED_CELLS
    assert {frozenset(cell) for cell in cells} == {VERIFIER_CELL_KEYS}
    assert all("gates" not in cell for cell in cells), (
        "the document duplicates the CSV's per-gate rows under a 'gates' array; the per-gate "
        "rows are the table's alone"
    )
    for cell in cells:
        assert set(cell["axis"]) == VERIFIER_AXIS_KEYS
        assert [row["target_label"] for row in cell["targets"]], cell["relative_path"]
        assert {frozenset(row) for row in cell["targets"]} == {VERIFIER_TARGET_KEYS}


def _document_floats(node) -> list[float]:
    """Every float in the document, read as a value rather than a token in the text."""
    if isinstance(node, bool):
        return []
    if isinstance(node, (int, float)):
        return [float(node)]
    if isinstance(node, dict):
        return [value for item in node.values() for value in _document_floats(item)]
    if isinstance(node, list):
        return [value for item in node for value in _document_floats(item)]
    return []


def test_the_published_document_is_strict_json_without_non_finite_numbers(
    published, document
) -> None:
    """F5: the document is strict JSON - ``NaN``/``Infinity`` are refused, not serialized.

    The prose legitimately contains the word "NaN" (the precision rule says it is refused), so
    the guard is a token/value check plus a strict re-parse, not a raw substring scan.
    """
    text = (published / DOC_NAME).read_text(encoding="utf-8")

    def reject(constant: str):
        raise AssertionError(
            f"the document carries the non-finite constant {constant!r}"
        )

    parsed = json.loads(text, parse_constant=reject)
    assert isinstance(parsed, dict)
    assert not re.search(r":\s*-?(?:NaN|Infinity)\b", text), (
        "the document carries a non-finite value token"
    )
    json.dumps(parsed, allow_nan=False)  # raises if a published value is non-finite
    assert all(math.isfinite(value) for value in _document_floats(document))


def test_the_summary_partitions_every_published_row_and_the_gate_holds(
    published_rows, document
) -> None:
    """F9 (published side): the population each state check runs over is visible and exhaustive.

    The document's counts partition the published gate rows by band state, so a check over
    ``refused-axis`` or ``defined-zero-power`` is demonstrably over the rows the summary counts -
    an empty population shows as ``0`` rather than hiding behind a vacuously true ``all(...)``.
    """
    _header, rows = published_rows
    summary = document["summary"]
    states: dict[str, int] = defaultdict(int)
    for row in rows:
        states[row["band_state"]] += 1
    assert summary["gate_rows"] == len(rows) == EXPECTED_GATE_ROWS
    assert summary["defined_gates"] == states[STATE_DEFINED]
    assert summary["defined_zero_power_gates"] == states[STATE_ZERO]
    assert summary["refused_axis_gates"] == states[STATE_REFUSED]
    assert (
        summary["defined_gates"]
        + summary["defined_zero_power_gates"]
        + summary["refused_axis_gates"]
        == summary["gate_rows"]
    ), "every published gate row is counted under exactly one band state"
    checks = document["checks"]
    assert isinstance(checks, dict) and checks
    assert all(checks.values()), {
        name: held for name, held in checks.items() if not held
    }
    assert document["failed_checks"] == []


# --------------------------------------------------------------------------------------
# 8. S3: the committed artefact, its regeneration and the frozen trees
# --------------------------------------------------------------------------------------
#
# §8.11 asks of the committed bytes two things nothing above can ask of a scratch tree: the
# report *as committed* must regenerate byte for byte at the revision it records, and every
# pre-existing file under `reports/` must hash as it did before the report. The first is
# checked by writing the report a second time - into pytest's own temp tree, outside the
# repository - at the revision the committed document names, so the comparison is against the
# committed bytes themselves and not against a tree generated beside them. The second is a
# git-blob check: the frozen trees' blobs at the frozen base revision must be the blobs on
# disk and at HEAD now, which is §9's stop condition (f) - a frozen-tree byte change - stated
# as a test rather than as a promise.
#
# Nothing here requires the report to be *git-tracked*: it is read from disk, and the frozen
# check compares revisions and disk, never `git ls-files` of the report's own paths. A parent
# commit that stages it changes none of these expectations.

#: The plan's designated publish root (§5), restated here rather than read from the writer.
COMMITTED_REPORT_DIR = ROOT / "reports" / "sparse-signal"

#: The three artefacts, in publication order.
COMMITTED_ARTEFACTS: tuple[str, ...] = (CSV_NAME, DOC_NAME, README_NAME)

#: The frozen base the report was built on top of: every pre-existing file under `reports/`
#: must hash as it did at this revision (§8.11, §9(f)).
BASE_REVISION = "ca7b043"

#: The plan's own frozen report trees, restated independently of the writer's tuple: one per
#: committed pass's `report_dir`, plus the tree the plan names as frozen with no pass of its
#: own. The designated publish root is deliberately *not* one of them.
FROZEN_REPORT_DIRS: tuple[str, ...] = (
    "reports/mixer-sensitivity-analysis",
    "reports/sparse-mixer-live-1",
    "reports/sparse-mixer-live-2",
    "reports/stage2-e20-e64",
)

#: The trees whose bytes the published report is a function of: the source that computes it,
#: the plan files whose fingerprints it binds, and the two committed sittings it decodes. A
#: byte change in any of them is the drift the regeneration would silently absorb.
SOURCE_TREE = "src/udv_echo_process"
INPUT_TREES: tuple[str, ...] = (
    "examples/",
    "data/sparse-mixer-live-1",
    "data/sparse-mixer-live-2",
)

#: The `python -m udv_echo_process.cli` subcommand the README's reproduction command names.
REPORT_SUBCOMMAND = "sparse-signal-report"


def _run_git(*arguments: str) -> str:
    """One git query in this checkout, or a hard failure - never a skip."""
    try:
        result = subprocess.run(
            ("git", "-C", str(ROOT), *arguments),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except (
        OSError
    ) as error:  # a checkout without git cannot answer a provenance question
        raise AssertionError(
            f"git is required for the frozen-tree check and is not runnable: {error}"
        ) from error
    assert result.returncode == 0, (
        f"git {' '.join(arguments)} failed ({result.returncode}): {result.stderr.strip()}"
    )
    return result.stdout


def _git_holds(*arguments: str) -> bool:
    """Whether a git query succeeds, for the questions whose honest answer may be no."""
    result = subprocess.run(
        ("git", "-C", str(ROOT), *arguments),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return result.returncode == 0


def _git_blob_sha(data: bytes) -> str:
    """Git's own blob identity of a byte string: ``sha1("blob <n>\\0" + data)``."""
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def _git_tree(revision: str, path: str) -> dict[str, str]:
    """Every tracked blob under ``path`` at ``revision``: repository-relative path -> blob sha."""
    entries: dict[str, str] = {}
    for line in _run_git(
        "ls-tree", "-r", "--full-tree", revision, "--", path
    ).splitlines():
        meta, _tab, name = line.partition("\t")
        entries[name] = meta.split()[2]
    return entries


def _disk_is_blob(path: Path, blob: str) -> bool:
    """Whether ``path``'s bytes are the blob, raw or in the repository's canonical LF form.

    A blob is stored in canonical LF, and a Windows checkout whose ``core.autocrlf`` is true
    may have materialised a file with CRLF. That is the same file by the repository's own
    rule - the rule that makes a materialised CRLF copy hash identically (§3) - so both forms
    are accepted, and no other difference is.
    """
    data = path.read_bytes()
    return (
        _git_blob_sha(data) == blob
        or _git_blob_sha(data.replace(b"\r\n", b"\n")) == blob
    )


def _disk_drift(base: Path, expected: dict[str, str]) -> list[str]:
    """The ``expected`` paths absent from ``base`` or holding bytes other than their blob.

    The pure disk predicate, split from the git query so it can be exercised on a synthetic tree:
    only the ``expected`` keys are ever inspected, so a file ``base`` carries and ``expected`` does
    not is outside the closure and is allowed - the same one-directional rule as the source guard.
    """
    return sorted(
        relative
        for relative, blob in expected.items()
        if not (base / relative).is_file() or not _disk_is_blob(base / relative, blob)
    )


def _assert_disk_matches(tree: str, revision: str, *, subject: str) -> None:
    """Every tracked file under ``tree`` at ``revision`` must be on disk with that blob."""
    expected = _git_tree(revision, tree)
    assert expected, f"{revision} tracks nothing under {tree!r}"
    drifted = _disk_drift(ROOT, expected)
    assert not drifted, (
        f"{subject} has drifted from {revision}: {drifted[:8]} "
        f"({len(drifted)} of {len(expected)} files)"
    )


def _committed_document(report: Path) -> dict:
    """The committed (or freshly written) report's JSON document."""
    return json.loads((report / DOC_NAME).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def committed_report() -> Path:
    """The committed report directory: absent bytes are a failure here, never a skip."""
    assert COMMITTED_REPORT_DIR.is_dir(), (
        f"SA2.4 must commit its three artefacts under {COMMITTED_REPORT_DIR.as_posix()} "
        "(plan §5); the report directory does not exist"
    )
    for name in COMMITTED_ARTEFACTS:
        path = COMMITTED_REPORT_DIR / name
        assert path.is_file(), f"SA2.4 must commit {name} ({path.as_posix()})"
    return COMMITTED_REPORT_DIR


@pytest.fixture(scope="module")
def recorded_revision(committed_report: Path) -> str:
    """The revision the committed report records - read from the published bytes, not a guess."""
    recorded = str(_committed_document(committed_report).get("analysis_commit") or "")
    assert re.fullmatch(r"[0-9a-f]{7,40}", recorded), recorded
    return recorded


@pytest.fixture(scope="module")
def regeneration(
    committed_report: Path,
    recorded_revision: str,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """The report written a second time, outside the repository, at the recorded revision."""
    scratch = tmp_path_factory.mktemp("sa2-4-s3-regeneration")
    _require_writer().write_sparse_signal_report(
        scratch, analysis_commit=recorded_revision
    )
    assert scratch.is_dir()
    return scratch


def test_the_committed_report_is_the_three_artefacts_under_the_designated_root(
    committed_report: Path,
) -> None:
    """§5: the committed directory holds the table, the document and the README - nothing else."""
    assert (
        Path(writer.REPORT_DIR).as_posix()
        == COMMITTED_REPORT_DIR.relative_to(ROOT).as_posix()
    )
    produced = sorted(
        path.relative_to(committed_report).as_posix()
        for path in committed_report.rglob("*")
        if path.is_file()
    )
    assert produced == sorted(COMMITTED_ARTEFACTS), produced


def test_the_committed_report_regenerates_byte_for_byte_at_the_recorded_revision(
    committed_report: Path, recorded_revision: str, regeneration: Path
) -> None:
    """§8.11: the committed bytes are exactly what the writer produces at the revision they name.

    All three artefacts, in the artefact's canonical LF form - the form the digest rule and the
    README's one-trailing-newline rule fix. A CRLF-materialised checkout is the same bytes by
    that rule and no other filesystem difference is accepted.
    """
    assert recorded_revision == _committed_document(committed_report)["analysis_commit"]
    for name in COMMITTED_ARTEFACTS:
        committed_bytes = (committed_report / name).read_bytes()
        regenerated_bytes = (regeneration / name).read_bytes()
        assert regenerated_bytes in (
            committed_bytes,
            committed_bytes.replace(b"\r\n", b"\n"),
        ), (
            f"{name}: the committed bytes are not the bytes the writer produces at "
            f"{recorded_revision} ({len(committed_bytes)} committed against "
            f"{len(regenerated_bytes)} regenerated)"
        )


def test_the_regeneration_is_bound_to_the_recorded_revision(
    committed_report: Path, recorded_revision: str, regeneration: Path
) -> None:
    """The second run is the same report, not merely identical files: commit and digest agree."""
    fresh = _committed_document(regeneration)
    published = _committed_document(committed_report)
    assert fresh["analysis_commit"] == published["analysis_commit"] == recorded_revision
    assert fresh["table_sha256"] == published["table_sha256"]
    readme = (regeneration / README_NAME).read_text(encoding="utf-8")
    assert f"- analysis revision: `{recorded_revision}`" in readme


def test_the_committed_document_binds_the_committed_table_bytes(
    committed_report: Path,
) -> None:
    """§9: the published digest is the SHA-256 of the committed table's canonical LF bytes."""
    published = _committed_document(committed_report)
    digest = (
        "sha256:"
        + hashlib.sha256(_canonical_lf(committed_report / CSV_NAME)).hexdigest()
    )
    assert published["table"] == CSV_NAME
    assert published["table_sha256"] == digest, published["table_sha256"]
    readme = (committed_report / README_NAME).read_text(encoding="utf-8")
    assert f"`{CSV_NAME}` sha256: `{digest}`" in readme


def test_the_frozen_report_directories_are_the_plan_s_and_exclude_the_publish_root() -> (
    None
):
    """§5/§9(f): the frozen set is the committed passes' trees plus the pass-less one."""
    from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES

    passes = {
        Path(ref.report_dir).as_posix()
        for ref in COMMITTED_PASSES
        if ref.report_dir is not None
    }
    assert set(FROZEN_REPORT_DIRS) == passes | {"reports/mixer-sensitivity-analysis"}, (
        sorted(passes)
    )
    assert COMMITTED_REPORT_DIR.relative_to(ROOT).as_posix() not in FROZEN_REPORT_DIRS


def test_the_frozen_base_is_an_ancestor_of_the_recorded_revision(
    recorded_revision: str,
) -> None:
    """The base the frozen bytes are compared against is a real, reachable revision."""
    assert _git_holds("cat-file", "-e", f"{BASE_REVISION}^{{commit}}"), BASE_REVISION
    assert _git_holds("cat-file", "-e", f"{recorded_revision}^{{commit}}"), (
        recorded_revision
    )
    assert _git_holds(
        "merge-base", "--is-ancestor", BASE_REVISION, recorded_revision
    ), f"{BASE_REVISION} is not an ancestor of {recorded_revision}"


def test_every_pre_existing_file_under_reports_hashes_as_before_the_frozen_base() -> (
    None
):
    """§8.11/§9(f): the report commit moved no committed report byte and added none outside it."""
    frozen = _git_tree(BASE_REVISION, "reports/")
    current = _git_tree("HEAD", "reports/")
    assert frozen, f"{BASE_REVISION} tracks nothing under reports/"
    missing = sorted(set(frozen) - set(current))
    assert not missing, f"pre-existing files under reports/ are gone: {missing}"
    changed = sorted(path for path in frozen if current[path] != frozen[path])
    assert not changed, f"pre-existing files under reports/ changed: {changed}"
    added = sorted(set(current) - set(frozen))
    outside = [
        path
        for path in added
        if not path.startswith(COMMITTED_REPORT_DIR.relative_to(ROOT).as_posix() + "/")
    ]
    assert not outside, (
        f"new files appeared outside the designated publish root: {outside}"
    )


def test_the_frozen_report_trees_on_disk_hash_as_before_the_frozen_base() -> None:
    """The working tree beside the published report holds the frozen bytes, not a regenerated set."""
    for tree in FROZEN_REPORT_DIRS:
        _assert_disk_matches(tree, BASE_REVISION, subject=f"the frozen tree {tree!r}")


def test_the_committed_inputs_the_report_decodes_are_frozen() -> None:
    """The plan files whose fingerprints the report binds and the sittings it decodes are frozen."""
    for tree in INPUT_TREES:
        _assert_disk_matches(tree, BASE_REVISION, subject=f"the report input {tree!r}")


def _source_drift(recorded: dict[str, str], current: dict[str, str]) -> list[str]:
    """The recorded source paths ``current`` no longer holds at their recorded blob.

    The pure source-drift predicate, split from the git queries so it can be exercised on
    synthetic maps. One-directional on purpose: every path the recorded revision contained must be
    current *at that blob*, while a path ``current`` has and ``recorded`` did not is outside the
    frozen source closure and is allowed. A modified path and a removed path both surface here -
    a missing key is ``current.get`` ``None``, which never equals a blob - so one expression states
    both failures.
    """
    return sorted(path for path, blob in recorded.items() if current.get(path) != blob)


def test_the_source_that_computes_the_report_has_not_drifted(
    recorded_revision: str,
) -> None:
    """Source-drift guard: the package that produces the bytes is the revision's own package."""
    recorded = _git_tree(recorded_revision, SOURCE_TREE)
    current = _git_tree("HEAD", SOURCE_TREE)
    assert recorded, f"{recorded_revision} tracks nothing under {SOURCE_TREE!r}"
    # A later, independent analysis module does not retroactively compute this report.
    # Guard every source path the report's recorded revision actually contained;
    # additions elsewhere in the package are outside that frozen source closure.
    drifted = _source_drift(recorded, current)
    assert not drifted, f"the report's recorded source has moved: {drifted[:8]}"
    for path in recorded:
        _assert_disk_matches(
            path, recorded_revision, subject=f"the report's recorded source {path!r}"
        )


def test_the_source_drift_predicate_pins_old_source_and_lets_new_source_through() -> (
    None
):
    """The exact source-drift predicate, on synthetic maps: old paths pinned, later paths free.

    Adversarial rather than illustrative. A *modification* of a recorded path and a *removal* of
    one both fail; an *addition* the recorded revision did not contain is allowed; and the guard
    is not vacuous - a wholly disjoint current map is a full failure, so it cannot pass by the
    recorded set emptying out. The predicate is called directly, so the production guard and this
    row cannot disagree about what drift means.
    """
    recorded = {
        "src/udv_echo_process/analysis/a.py": "aaaa",
        "src/udv_echo_process/analysis/b.py": "bbbb",
        "src/udv_echo_process/analysis/_old.py": "cccc",
    }
    # the recorded revision itself is the identity: no drift
    assert _source_drift(recorded, dict(recorded)) == []
    # a later module the recorded revision did not contain is outside the frozen closure
    added = {**recorded, "src/udv_echo_process/analysis/_later.py": "dddd"}
    assert _source_drift(recorded, added) == []
    # modification of an old path fails, and names that path
    modified = {**recorded, "src/udv_echo_process/analysis/b.py": "BBBB"}
    assert _source_drift(recorded, modified) == ["src/udv_echo_process/analysis/b.py"]
    # removal of an old path fails
    removed = {
        key: value for key, value in recorded.items() if not key.endswith("_old.py")
    }
    assert _source_drift(recorded, removed) == ["src/udv_echo_process/analysis/_old.py"]
    # add + change + remove at once: only the old paths' fate is reported - the addition is not
    mixed = {
        "src/udv_echo_process/analysis/a.py": "aaaa",
        "src/udv_echo_process/analysis/b.py": "BBBB",
        "src/udv_echo_process/analysis/_later.py": "dddd",
    }
    assert _source_drift(recorded, mixed) == [
        "src/udv_echo_process/analysis/_old.py",
        "src/udv_echo_process/analysis/b.py",
    ]
    # non-vacuous: an empty current map is a full failure, not a pass
    assert len(_source_drift(recorded, {})) == len(recorded) == 3


def test_the_disk_drift_predicate_pins_expected_bytes_and_ignores_extra_files(
    tmp_path: Path,
) -> None:
    """The exact disk half of the guard, on a synthetic tree: mutated/absent fail, extra free.

    Built on a scratch directory and git's own blob identity, so it tampers with no repository
    file. A mutated byte, a removed file and a non-canonical rewrite all fail; an added file the
    expected map does not name is outside the closure and is allowed; and a materialised CRLF copy
    is the *same* file by the repository's canonical-LF rule, so it passes rather than failing.
    """
    base = tmp_path / "tree"
    (base / "pkg").mkdir(parents=True)
    kept = base / "pkg" / "kept.py"
    kept.write_bytes(b"print('kept')\n")
    expected = {"pkg/kept.py": _git_blob_sha(kept.read_bytes())}
    assert _disk_drift(base, expected) == []

    # an extra file the recorded tree did not track is outside the closure and allowed
    (base / "pkg" / "later.py").write_bytes(b"print('later')\n")
    assert _disk_drift(base, expected) == []

    # a CRLF-materialised copy is the same file by the canonical-LF rule
    kept.write_bytes(b"print('kept')" + bytes([13, 10]))  # a literal CRLF pair
    assert _disk_drift(base, expected) == []

    # mutated bytes fail, and name the path ...
    kept.write_bytes(b"print('drifted')\n")
    assert _disk_drift(base, expected) == ["pkg/kept.py"]

    # ... and a removed file fails too, on the same expression
    kept.unlink()
    assert _disk_drift(base, expected) == ["pkg/kept.py"]

    # non-vacuous: an expected path never present is a failure, not a pass
    assert _disk_drift(base, {**expected, "pkg/never.py": "deadbeef"}) == [
        "pkg/kept.py",
        "pkg/never.py",
    ]


def test_the_readme_reproduction_command_uses_the_recorded_revision_and_travels(
    committed_report: Path, recorded_revision: str
) -> None:
    """The Reproduce block is the recorded command, and a reader of a clone can run it as written."""
    readme = (committed_report / README_NAME).read_text(encoding="utf-8")
    block = re.search(
        r"^## Reproduce\n\n```bash\n(?P<command>.*?)\n```$",
        readme,
        re.MULTILINE | re.DOTALL,
    )
    assert block, "the README carries no '## Reproduce' bash block"
    lines = block.group("command").splitlines()
    assert len(lines) == 1, lines
    command = lines[0]
    assert command == (
        f"uv run python -m udv_echo_process.cli {REPORT_SUBCOMMAND} "
        f"--analysis-commit {recorded_revision}"
    ), command
    assert f"- analysis revision: `{recorded_revision}`" in readme

    # Remotely usable: `uv run` needs no local environment path, and with no `--report-dir` the
    # writer anchors the plan's relative root at the repository root, so a fresh clone in any
    # directory runs the same command and lands its files in the same tree.
    assert "--report-dir" not in command
    assert not re.search(r"[A-Za-z]:[\\/]", command), command
    assert not any(
        token in command for token in ("\\", "<", ">", "/tmp", "AppData", "Users")
    )
    assert not any(
        token in command.lower() for token in ("scratch", "pytest", "venv", "hermes")
    ), command

    # The revision names a real commit on this branch, so it travels with the pushed branch
    # rather than existing only in the checkout that wrote the report.
    assert _git_holds("cat-file", "-e", f"{recorded_revision}^{{commit}}"), (
        recorded_revision
    )
    assert _git_holds("merge-base", "--is-ancestor", recorded_revision, "HEAD"), (
        f"{recorded_revision} is not an ancestor of HEAD"
    )

    # And the subcommand the command names is wired to the writer's own entry point.
    from udv_echo_process import cli

    commands = getattr(cli, "_COMMANDS", {})
    assert commands.get(REPORT_SUBCOMMAND) is _require_writer().report_main, sorted(
        commands
    )
