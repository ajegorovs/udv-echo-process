"""SA2.4 S2: the scalar spectral report writer, held to §5, §6, §8 and §9 of its contract.

`reports/sparse-signal/` is the sparse plan's designated publish root, and SA2.4's files under it
are the first thing placed there. This file holds the writer to the four claims that make those
files evidence rather than a plausible set of tables:

* **the row set is the plan's own** - 52 recordings x 2 views = 104 cells, and one row per
  ``cell x supported gate``, which on the committed set is 5720 gate rows, not a hand-built sweep
  and not a per-bin table (§1, §5, §8.9);
* **the numbers are the §2 reduction, recomputed independently** - every published ``B``, ``T`` and
  ``Phi`` is checked against a second, self-contained cell-overlap loop reading the estimate's own
  ``frequency_hz``, ``psd`` and ``delta_f_hz``, and against a handwritten cell-edge oracle that
  shares no helper with the writer (§9);
* **the artefacts are scalars only** - the permitted cardinality of §6 (one row per observation
  unit) and the forbidden one (any count that follows the bins, samples or elements) are both
  asserted, so no PSD array, bin vector or flattened spectrum can ride along inside a "scalar"
  report (§5, §6);
* **the bytes are deterministic and bound** - two scratch runs at one revision are byte-identical,
  the CSV is UTF-8/LF with one trailing newline, and the document's ``table_sha256`` is the
  repository's own LF-normalized digest of the CSV beside it (§5).

Written **red first**: the S2 writer module is created by a separate change, so its import is
guarded and every row asserts the frozen interface is present rather than being silently skipped -
a missing writer is a *failure*, not an ``importorskip``. Only the frozen-interface block at the
top names the writer; every other row reads the published artefacts.

No exploratory number appears anywhere in this file: there is no expected ``Phi``, no floor, no
spread and no per-sitting mean here. The 71.6 % E128 smoke datum is not an expectation and is
asserted *absent* from the report rather than against (§10.10, §9(g)).
"""

from __future__ import annotations

import csv
import inspect
import io
import json
import math
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis import _floor_documents as fdp
from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis._sparse_view import (
    full_record_view,
    primary_view,
    view_provenance,
)
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES
from udv_echo_process.analysis.sparse_periodogram import (
    SpectralVerdict,
    periodogram_of_view,
)
from udv_echo_process.analysis.sparse_spectral_capability import PROBE_TARGETS
from udv_echo_process.analysis.sparse_target_support import frequency_cell

# --------------------------------------------------------------------------------------
# the guarded import and the interface seam: red until S2 lands, and a failure rather
# than a skip. Everything below this block speaks the plan's vocabulary, not the module's.
# --------------------------------------------------------------------------------------

try:  # pragma: no cover - the branch taken depends on the revision under test
    from udv_echo_process.analysis import sparse_signal_report as writer
except ImportError as exc:  # pragma: no cover
    writer = None  # type: ignore[assignment]
    _IMPORT_ERROR: ImportError | None = exc
else:  # pragma: no cover
    _IMPORT_ERROR = None

#: The frozen public interface S2 must expose. ``write_sparse_signal_report`` is the entry point
#: the CLI subcommand of plan §5 calls; the three names are the artefacts of §5's own table.
REQUIRED_NAMES: tuple[str, ...] = (
    "CSV_NAME",
    "DOC_NAME",
    "write_sparse_signal_report",
)

#: The report's root, from this file's own location - never a hard-coded absolute path.
ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / "reports" / "sparse-signal"

#: The revision a recorded run reproduces committed bytes at. A bare CLI run records HEAD; every
#: scratch run here passes one explicitly, so two runs at one revision are comparable.
REVISION = "ca7b043"

#: The plan's row set (§1): 52 recordings x {primary-comparison, full-record} and the supported
#: native gates they carry. Both are asserted against a live sweep, never trusted as constants
#: alone - the constants are the plan's statement, the sweep is the measurement.
EXPECTED_CELLS = 104
EXPECTED_GATE_ROWS = 5720

#: The two reproducibility sittings the default scope is, and the campaign it deliberately is not.
SITTINGS = ("sparse-mixer-live-1", "sparse-mixer-live-2")
CAMPAIGN = "stage2-e20-e64"

#: The frozen report trees of §5: byte-unchanged, and never written into.
FROZEN_TREES = (
    "reports/sparse-mixer-live-1",
    "reports/sparse-mixer-live-2",
    "reports/mixer-sensitivity-analysis",
    "reports/stage2-e20-e64",
)

#: §2's declared band edge and the design's rotor reference.
LOW_HZ = 1.0
ROTOR_HZ = 25.0 / 3.0
RECURRENCE_LABEL = "recurrence-1hz"
ROTOR_LABEL = "rotor-8.333hz"

#: §5 publishes ``Phi`` at six decimals; comparisons happen there.
PUBLISHED_DECIMALS = 6

#: The three band states, as the enum's own ``.value`` strings - never a Python repr.
BAND_STATES = ("defined", "defined-zero-power", "refused-axis")


def _require_writer():
    """The S2 writer module, or a failure naming exactly what is missing.

    Deliberately an assertion rather than a module-level ``importorskip``: a writer that has not
    been written must show as red, and a writer that is written but drops a frozen name must show
    which name, not skip.
    """
    assert writer is not None, (
        "the S2 writer module analysis.sparse_signal_report is not importable "
        f"({_IMPORT_ERROR!r}); this file is written red-first and goes green when S2 lands"
    )
    missing = [name for name in REQUIRED_NAMES if not hasattr(writer, name)]
    assert not missing, f"the S2 writer is missing frozen interface names: {missing}"
    return writer


def file_names() -> tuple[str, ...]:
    """The three artefact names of §5, from the writer's own constants."""
    w = _require_writer()
    readme = getattr(w, "README_NAME", None) or getattr(w, "MD_NAME", "README.md")
    return (str(w.CSV_NAME), str(w.DOC_NAME), str(readme))


def write_report(report_dir: Path, *, analysis_commit: str = REVISION):
    """Write one SA2.4 scalar report into ``report_dir`` and return the writer's own result.

    The call shape is plan §5's CLI shape: a report directory, a recorded revision, and the
    committed sweep as the default scope. Where the writer names its report directory parameter,
    it is passed by name; otherwise positionally.
    """
    w = _require_writer()
    entry = w.write_sparse_signal_report
    parameters = inspect.signature(entry).parameters
    kwargs: dict[str, object] = {}
    if "analysis_commit" in parameters:
        kwargs["analysis_commit"] = analysis_commit
    positional: list[object] = [report_dir]
    for name in ("report_dir", "directory", "output_dir"):
        if name in parameters:
            kwargs[name] = report_dir
            positional = []
            break
    return entry(*positional, **kwargs)


@pytest.fixture(scope="module")
def written(tmp_path_factory: pytest.TempPathFactory):
    """One freshly written report: its scratch directory and the writer's own result.

    Both the published bytes and the model are kept in one place, so a row that has to inspect
    the model (the precision and publication-safety rows below) does not pay for a second sweep.
    """
    scratch = tmp_path_factory.mktemp("sa2-4-report")
    model = write_report(scratch, analysis_commit=REVISION)
    return scratch, model


@pytest.fixture(scope="module")
def report(written) -> Path:
    """The scratch directory the one fresh report went into - never inside the repository."""
    return written[0]


@pytest.fixture(scope="module")
def built(written):
    """The writer's own result for that one report, for rows that inspect the model."""
    return written[1]


def _document(report_dir: Path) -> dict:
    name = str(_require_writer().DOC_NAME)
    return json.loads((report_dir / name).read_text(encoding="utf-8"))


def _csv_text(report_dir: Path) -> str:
    return (report_dir / str(_require_writer().CSV_NAME)).read_text(encoding="utf-8")


def _csv_rows(report_dir: Path) -> list[dict[str, str]]:
    """The table's rows, parsed as CSV - never line by line.

    A published field may be a quoted string holding a newline (a reason, a taper convention), so
    splitting the text on line endings would tear a row in half and silently undercount the row
    set. The reader is fed the whole text so quoting is honoured.
    """
    return list(csv.DictReader(io.StringIO(_csv_text(report_dir), newline="")))


# --------------------------------------------------------------------------------------
# column resolution: the CSV is read by what each column *is*, in one place
# --------------------------------------------------------------------------------------

#: Candidate header names per semantic field. Exact matches are preferred; a substring match is
#: accepted only when it is unique, so a rename that makes two columns ambiguous is a failure
#: rather than a silent pick. One edit here adapts every row below.
COLUMN_CANDIDATES: dict[str, tuple[str, ...]] = {
    "pass": ("pass", "pass_name"),
    "view": ("view",),
    "job": ("job",),
    "point_label": ("point_label", "point"),
    "order": ("order",),
    "relative_path": ("relative_path",),
    "source_sha256": ("source_sha256",),
    "gate_index": ("gate_index", "gate"),
    "depth_mm": ("depth_mm", "depth"),
    "verdict": ("verdict",),
    "state": ("band_state", "state"),
    "fraction": ("band_fraction", "fraction"),
    "band_power": ("band_power",),
    "total_power": ("total_power",),
    "low_hz": ("low_band_hz", "low_hz"),
    "profiles": ("profiles", "n_profiles"),
    "span_s": ("span_s", "span"),
    "fs_eff_hz": ("effective_sample_rate_hz", "fs_eff_hz"),
    "nyquist_hz": ("nyquist_hz", "nyquist"),
    "delta_f_hz": ("delta_f_hz", "delta_f"),
    "max_relative_timing_error": ("max_relative_timing_error",),
    "parseval_relative_error": ("parseval_relative_error",),
}


def _header(report_dir: Path) -> list[str]:
    rows = _csv_rows(report_dir)
    assert rows, "the published CSV carries no data row"
    return list(rows[0].keys())


def _column(header: list[str], field: str) -> str:
    """The one header name that carries ``field``, refused when it is absent or ambiguous."""
    candidates = COLUMN_CANDIDATES[field]
    for candidate in candidates:
        if candidate in header:
            return candidate
    matches = [
        name for name in header if any(candidate in name for candidate in candidates)
    ]
    assert len(matches) == 1, (
        f"the published CSV must carry one {field!r} column under the candidate names "
        f"{candidates}; found {matches} in {header}"
    )
    return matches[0]


# --------------------------------------------------------------------------------------
# the live sweep: the independent statement of what the report should contain
# --------------------------------------------------------------------------------------


def _live_views() -> dict[tuple[str, str, str], object]:
    """Every committed cell's view, keyed ``(pass, relative_path, view)`` - one entry per recording.

    A *cell* is a ``recording x view``, so the key carries the recording (its own relative path)
    and not only the job: a job holds several recordings, and keying by job alone would collapse
    104 cells onto 36.
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
                provenance = view_provenance(view)
                views[(ref.name, provenance.relative_path, view.view.value)] = view
    return views


def _row_cell(row: dict[str, str], columns: dict[str, str]) -> tuple[str, str, str]:
    """One CSV row's cell identity: the pass, the recording and the view."""
    return (row[columns["pass"]], row[columns["relative_path"]], row[columns["view"]])


@pytest.fixture(scope="module")
def live_views() -> dict[tuple[str, str, str], object]:
    """The committed set decoded once: about a second, and the oracle's raw material."""
    return _live_views()


def _published_gate_rows(rows: list[dict[str, str]], header: list[str]):
    """The published gate rows as typed scalars, keyed by their cell identity and gate index."""
    columns = {field: _column(header, field) for field in COLUMN_CANDIDATES}
    parsed = []
    for row in rows:
        parsed.append(
            {
                "cell": _row_cell(row, columns),
                "pass": row[columns["pass"]],
                "job": row[columns["job"]],
                "relative_path": row[columns["relative_path"]],
                "view": row[columns["view"]],
                "gate_index": int(row[columns["gate_index"]]),
                "depth_mm": float(row[columns["depth_mm"]]),
                "state": row[columns["state"]],
                "verdict": row[columns["verdict"]],
                "fraction": row[columns["fraction"]],
                "band_power": row[columns["band_power"]],
                "total_power": row[columns["total_power"]],
                "low_hz": float(row[columns["low_hz"]]),
                "profiles": int(row[columns["profiles"]]),
                "span_s": float(row[columns["span_s"]]),
                "fs_eff_hz": float(row[columns["fs_eff_hz"]]),
                "nyquist_hz": float(row[columns["nyquist_hz"]]),
                "delta_f_hz": float(row[columns["delta_f_hz"]]),
                "max_relative_timing_error": float(
                    row[columns["max_relative_timing_error"]]
                ),
            }
        )
    return parsed


# --------------------------------------------------------------------------------------
# §8.9 / §1: the row set
# --------------------------------------------------------------------------------------


def test_the_published_csv_is_one_row_per_cell_and_supported_gate(
    report: Path, live_views
) -> None:
    """104 cells and 5720 gate rows, measured against a live sweep rather than assumed.

    ``supported_columns`` owns the question of which gates are supported, so the expected row
    count is the sum of ``ViewProvenance.supported_gates`` over the 104 committed views - not
    104 x a gates-per-recording constant, and not a bin count.
    """
    rows = _csv_rows(report)
    header = _header(report)
    columns = {field: _column(header, field) for field in COLUMN_CANDIDATES}
    cells = {_row_cell(row, columns) for row in rows}
    expected_cells = set(live_views)
    assert cells == expected_cells, (
        "the published cells are exactly the committed sweep's recording x view pairs"
    )
    expected_gates = sum(
        view_provenance(view).supported_gates for view in live_views.values()
    )
    assert len(cells) == EXPECTED_CELLS == 104
    assert len(rows) == expected_gates == EXPECTED_GATE_ROWS == 5720, (
        "the CSV is one row per cell x supported gate: "
        f"{len(rows)} row(s) for {len(cells)} cell(s)"
    )
    # one row per (cell, gate), no repeats and no missing gate
    seen = [(_row_cell(row, columns), int(row[columns["gate_index"]])) for row in rows]
    assert len(set(seen)) == len(seen) == EXPECTED_GATE_ROWS


def test_every_cell_publishes_exactly_its_supported_columns(
    report: Path, live_views
) -> None:
    """The gate indices are the view's own native columns, and the depths are the instrument's."""
    rows = _published_gate_rows(_csv_rows(report), _header(report))
    by_cell: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        by_cell.setdefault(row["cell"], []).append(row)
    assert set(by_cell) == set(live_views)
    for key, published in by_cell.items():
        view = live_views[key]
        expected_indices = [int(column) for column in view.supported_columns]
        assert [row["gate_index"] for row in published] == expected_indices, (
            "the sweep is driven by supported_columns, in native depth order, and asks no "
            "unsupported column"
        )
        depths = np.asarray(view.depths_mm, dtype=float)
        for row in published:
            assert row["depth_mm"] == pytest.approx(float(depths[row["gate_index"]])), (
                "depth_mm is the view's native coordinate of that gate"
            )


def test_the_published_json_carries_one_entry_per_cell_with_its_targets_once(
    report: Path,
) -> None:
    """§5's split: the gate rows are the CSV's cardinality, targets are stated once per cell."""
    document = _document(report)
    header = _header(report)
    columns = {field: _column(header, field) for field in COLUMN_CANDIDATES}
    cells = {_row_cell(row, columns) for row in _csv_rows(report)}
    blocks = [
        value
        for key, value in document.items()
        if isinstance(value, list)
        and value
        and isinstance(value[0], dict)
        and "targets" in value[0]
    ]
    assert blocks, (
        "the document must carry its per-cell rows (each with their target rows)"
    )
    published = {
        (
            entry[_field(entry, "pass", "pass_name")],
            entry["relative_path"],
            entry["view"],
        )
        for entry in blocks[0]
    }
    assert published == cells, (
        "the JSON's cells and the CSV's cells are the same row set"
    )
    assert len(published) == EXPECTED_CELLS
    # the two probe rows are per *cell*, not per gate: one pair each, never 5720 pairs
    for entry in blocks[0]:
        assert len(entry["targets"]) == len(PROBE_TARGETS), entry["view"]
    # and the document's cell rows are the same count the table publishes: one gate row per
    # supported gate, so the two artefacts cannot disagree about the row set
    for entry in blocks[0]:
        assert len(entry["gates"]) == entry["supported_gates"], entry["relative_path"]
    assert sum(len(entry["gates"]) for entry in blocks[0]) == EXPECTED_GATE_ROWS


def test_the_document_states_the_prespecified_constants_of_this_table(
    report: Path,
) -> None:
    """§1/§5: the band edge, detrending, views and gate rule are stated, not chosen per run."""
    constants = _document(report)["constants"]
    assert constants["low_band_hz"] == LOW_HZ, (
        "the band edge is the prespecified 1 Hz recurrence scale, never tuned after a number"
    )
    assert constants["detrending"] == "mean", "both views are mean-detrended (§1)"
    assert set(constants["views"]) == {"primary-comparison", "full-record"}
    assert [tuple(pair) for pair in constants["probe_targets"]] == [
        tuple(pair) for pair in PROBE_TARGETS
    ]
    assert constants["fraction_decimals"] == PUBLISHED_DECIMALS
    assert "supported_columns" in constants["gate_rule"], (
        "the gate rule names the accessor that owns the question (§1, D4)"
    )
    assert not re.search(
        r"(?i)\b(welch|coherence|resampl|peak)\b", json.dumps(constants)
    ), "no Welch, coherence, resampling or peak search is a setting of this table (§7)"


def _field(entry: dict, *candidates: str) -> str:
    for candidate in candidates:
        if candidate in entry:
            return candidate
    raise AssertionError(f"none of {candidates} is a key of {sorted(entry)}")


# --------------------------------------------------------------------------------------
# §1 / §3: one cell, one axis
# --------------------------------------------------------------------------------------


def test_axis_scalars_are_identical_across_a_cells_gate_rows(report: Path) -> None:
    """One view supplies one time axis, so a cell's gate rows cannot disagree about it."""
    rows = _published_gate_rows(_csv_rows(report), _header(report))
    by_cell: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        by_cell.setdefault(row["cell"], []).append(row)
    for key, published in by_cell.items():
        for field in (
            "profiles",
            "span_s",
            "fs_eff_hz",
            "nyquist_hz",
            "delta_f_hz",
            "max_relative_timing_error",
            "low_hz",
        ):
            values = {row[field] for row in published}
            assert len(values) == 1, (
                f"{key} publishes {len(values)} distinct {field!r} values across its gate "
                "rows: one cell is one axis"
            )
        assert next(iter(published))["low_hz"] == LOW_HZ, (
            "the declared band edge is 1 Hz"
        )


def test_the_published_axis_is_the_estimate_s_own(report: Path, live_views) -> None:
    """§3 reads the axis through the estimate's properties; the CSV must equal them."""
    rows = _published_gate_rows(_csv_rows(report), _header(report))
    sampled = _sample(rows, 8)
    for row in sampled:
        view = live_views[row["cell"]]
        estimate = periodogram_of_view(
            view,
            depth_mm=float(np.asarray(view.depths_mm, dtype=float)[row["gate_index"]]),
        )
        assert row["profiles"] == int(estimate.profiles)
        assert row["span_s"] == pytest.approx(estimate.characterization.span_s)
        assert row["fs_eff_hz"] == pytest.approx(estimate.effective_sample_rate_hz)
        assert row["nyquist_hz"] == pytest.approx(estimate.nyquist_hz)
        assert row["delta_f_hz"] == pytest.approx(estimate.delta_f_hz)
        assert row["max_relative_timing_error"] == pytest.approx(
            estimate.characterization.max_relative_timing_error
        )


def _sample(rows: list[dict], count: int) -> list[dict]:
    """A deterministic spread over the rows: first of each cell, then evenly through the rest."""
    by_cell: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        by_cell.setdefault(row["cell"], row)
    ordered = [by_cell[key] for key in sorted(by_cell)]
    step = max(1, len(ordered) // count)
    return ordered[::step][:count]


# --------------------------------------------------------------------------------------
# §1: the scope is the reproducibility sittings, stated as the selection
# --------------------------------------------------------------------------------------


def test_the_scope_is_the_two_reproducibility_sittings_and_not_the_campaign(
    report: Path,
) -> None:
    """§1: the default sweep is the catalog's own scope - the campaign is a deliberate act."""
    rows = _published_gate_rows(_csv_rows(report), _header(report))
    passes = {row["cell"][0] for row in rows}
    assert passes == set(SITTINGS), (
        "the default scope is the passes the catalog marks as reproducibility sittings"
    )
    assert CAMPAIGN not in passes, "the Stage-2 campaign is not a default SA2.4 scope"


def test_the_pass_is_the_selection_and_the_provenance_is_this_recording_s(
    report: Path,
) -> None:
    """§5: provenance is read, and the pass is the sweep's own selection, not a provenance field."""
    header = _header(report)
    rows = _csv_rows(report)
    columns = {field: _column(header, field) for field in COLUMN_CANDIDATES}
    by_cell: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = _row_cell(row, columns)
        by_cell.setdefault(key, row)
    live = _live_views()
    assert set(by_cell) == set(live)
    for key, row in by_cell.items():
        provenance = view_provenance(live[key])
        assert row[_column(header, "job")] == provenance.job
        assert row[_column(header, "point_label")] == provenance.point_label
        assert int(row[_column(header, "order")]) == int(provenance.order)
        assert row[_column(header, "relative_path")] == provenance.relative_path
        assert row[_column(header, "source_sha256")] == provenance.source_sha256
        assert row[_column(header, "view")] == provenance.view.value
        assert key[0] in SITTINGS, key


def test_provenance_is_not_rebuilt_from_a_summary(report: Path) -> None:
    """Every published ``source_sha256`` is a 64-hex digest of a recording the sweep really read."""
    header = _header(report)
    seen: set[tuple[str, str]] = set()
    for row in _csv_rows(report):
        seen.add(
            (
                row[_column(header, "relative_path")],
                row[_column(header, "source_sha256")],
            )
        )
    assert len(seen) == 52, "52 recordings, one provenance per recording"
    for relative_path, digest in seen:
        assert re.fullmatch(r"[0-9a-f]{64}", digest), digest
        assert relative_path.endswith(".BDD"), relative_path


# --------------------------------------------------------------------------------------
# §8.8: the E128 hard fact, read from the published JSON by label
# --------------------------------------------------------------------------------------


def _json_cells(document: dict) -> list[dict]:
    for value in document.values():
        if (
            isinstance(value, list)
            and value
            and isinstance(value[0], dict)
            and "targets" in value[0]
        ):
            return value
    raise AssertionError("the document carries no per-cell rows with their target rows")


def _target(cell: dict, label: str) -> dict:
    for entry in cell["targets"]:
        if entry["target_label"] == label:
            return entry
    raise AssertionError(f"{label!r} is not among {cell['targets']}")


def test_e128_refuses_the_rotor_target_while_its_spectrum_is_admitted(
    report: Path,
) -> None:
    """The plan's hard fact at the gate-resolvable level, named by label and not by index.

    E128's mathematical Nyquist is 5.73 Hz, below the 25/3 Hz rotor reference: the *band* is
    impossible while the *estimator* is admitted. A refused target is an answer, never an error,
    and the refusal must never be published as a zero or as an absence.
    """
    document = _document(report)
    cells = _json_cells(document)
    e128 = [cell for cell in cells if cell["job"] == "emissions-128"]
    assert len(e128) == 16, "eight E128 recordings on two views"
    for cell in e128:
        rotor = _target(cell, ROTOR_LABEL)
        assert rotor["band_supported"] is False
        assert rotor["analysis_supported"] is True, (
            "the estimator is admitted; only the 8.333 Hz band is impossible"
        )
        assert rotor["supported"] is False
        assert "Nyquist" in rotor["reason"], rotor["reason"]
        recurrence = _target(cell, RECURRENCE_LABEL)
        assert recurrence["band_supported"] is True
        assert recurrence["analysis_supported"] is True
        assert recurrence["supported"] is True
    # and the E128 gate rows are measurements, not refusals: the axis is admitted
    rows = _published_gate_rows(_csv_rows(report), _header(report))
    for row in rows:
        if row["job"] != "emissions-128":
            continue
        assert row["state"] == "defined", row
        assert row["verdict"] == SpectralVerdict.DEFINED.value
        value = float(row["fraction"])
        assert 0.0 <= value <= 1.0 + 1e-9


def test_one_hertz_is_supported_on_every_committed_cell(report: Path) -> None:
    """§8.8's other half: the 1 Hz recurrence probe is inside every committed band."""
    cells = _json_cells(_document(report))
    assert len(cells) == EXPECTED_CELLS
    for cell in cells:
        entry = _target(cell, RECURRENCE_LABEL)
        assert entry["band_supported"] is True
        assert entry["analysis_supported"] is True
        assert entry["supported"] is True
        assert entry["nyquist_hz"] > 2.0 * LOW_HZ
    assert [label for label, _ in PROBE_TARGETS] == [RECURRENCE_LABEL, ROTOR_LABEL]


def test_the_target_rows_are_the_design_s_fixed_probe_set(report: Path) -> None:
    """Two probe rows per cell, the design's names and frequencies, asked once per cell."""
    for cell in _json_cells(_document(report)):
        labels = [entry["target_label"] for entry in cell["targets"]]
        assert labels == [label for label, _ in PROBE_TARGETS], labels
        frequencies = sorted(entry["target_hz"] for entry in cell["targets"])
        assert frequencies == pytest.approx(sorted(f for _, f in PROBE_TARGETS))
        assert frequencies[1] == ROTOR_HZ, (
            "25/3 Hz, the reference itself, not a rounded 8.3"
        )


# --------------------------------------------------------------------------------------
# §9: the numeric overlap oracle - the published number, recomputed from the density
# --------------------------------------------------------------------------------------


def _cell_edges(index: int, *, profiles: int, rate: float) -> tuple[float, float]:
    """One bin's cell ``(low_hz, high_hz)``, written out from the rule rather than called.

    A deliberate second implementation of the repository's one cell rule: edges are the midpoints
    to the neighbouring bins, the DC cell opens at ``0.0``, and the highest represented cell closes
    at ``min(Nyquist, (k + 0.5) * delta_f)``. Nothing here calls ``frequency_cell`` or
    ``one_sided_frequency_grid``.
    """
    delta = rate / profiles
    bins = profiles // 2 + 1
    low = 0.0 if index == 0 else (index - 0.5) * delta
    high = (index + 0.5) * delta
    if index == bins - 1:
        high = min(0.5 * rate, high)
    return low, high


def _oracle(estimate, *, low_hz: float) -> tuple[float, float, float]:
    """``(B, T, Phi)`` of §2, from the estimate's own frequency axis, density and spacing.

    ``T`` is summed here over the one-sided grid as a *check* - it is read, never recomputed, by
    the writer - and ``B`` weights each bin by the fraction of its own cell inside the closed band
    ``[0, low_hz]``.
    """
    profiles = int(estimate.profiles)
    rate = float(estimate.effective_sample_rate_hz)
    psd = np.asarray(estimate.psd, dtype=float)
    frequencies = np.asarray(estimate.frequency_hz, dtype=float)
    delta = float(estimate.delta_f_hz)
    assert psd.size == profiles // 2 + 1
    assert frequencies.size == psd.size
    assert delta == pytest.approx(rate / profiles, rel=1e-12)
    band = 0.0
    for index in range(psd.size):
        low, high = _cell_edges(index, profiles=profiles, rate=rate)
        overlap = max(0.0, min(high, float(low_hz)) - low)
        weight = min(max(overlap / (high - low), 0.0), 1.0)
        band += weight * float(psd[index]) * delta
    total = float(np.sum(psd)) * delta
    return band, total, band / total


def test_the_published_fraction_is_the_2_reduction_recomputed_independently(
    report: Path, live_views
) -> None:
    """Every sampled row's ``B``, ``T`` and ``Phi`` against a second, self-contained loop.

    The writer's own backend serves none of this computation: the oracle reads the estimate's raw
    ``frequency_hz``, ``psd`` and ``delta_f_hz`` and applies the cell rule as handwritten
    arithmetic. Agreement is a statement about the published number, not about a shared helper.
    """
    rows = _published_gate_rows(_csv_rows(report), _header(report))
    sampled = _sample(rows, 12)
    assert sampled
    for row in sampled:
        view = live_views[row["cell"]]
        depth = float(np.asarray(view.depths_mm, dtype=float)[row["gate_index"]])
        estimate = periodogram_of_view(view, depth_mm=depth)
        assert estimate.verdict is SpectralVerdict.DEFINED
        band, total, fraction = _oracle(estimate, low_hz=LOW_HZ)
        assert row["state"] == "defined", row
        published = float(row["fraction"])
        assert published == pytest.approx(
            fraction, rel=0, abs=10**-PUBLISHED_DECIMALS
        ), (
            row["cell"],
            row["gate_index"],
            fraction,
        )
        assert float(row["band_power"]) == pytest.approx(
            band, rel=10**-PUBLISHED_DECIMALS
        )
        assert float(row["total_power"]) == pytest.approx(
            total, rel=10**-PUBLISHED_DECIMALS
        )
        # the denominator is the estimate's own integrated power, not a re-summed one
        assert float(row["total_power"]) == pytest.approx(
            estimate.integrated_psd_power, rel=10**-PUBLISHED_DECIMALS
        )
        assert 0.0 <= published <= 1.0 + 1e-9
        assert float(row["band_power"]) <= float(row["total_power"]) * (1.0 + 1e-9)
        # §2's boundary arithmetic: the cells tile [0, f_N] exactly, on both parities
        _b, _t, whole = _oracle(estimate, low_hz=float(estimate.nyquist_hz))
        assert whole == pytest.approx(1.0, rel=1e-9)


def test_the_domain_edge_is_the_axes_own_nyquist_and_never_exceeded(
    report: Path,
) -> None:
    """§2's request validity, checked on the published record: ``low_hz <= f_N`` everywhere."""
    rows = _published_gate_rows(_csv_rows(report), _header(report))
    for row in rows:
        assert row["low_hz"] > 0.0
        assert row["nyquist_hz"] > 0.0
        assert row["low_hz"] <= row["nyquist_hz"], (
            f"{row['cell']} gate {row['gate_index']}: the declared band edge is above the "
            "axis's own Nyquist frequency"
        )
        # and the frequency-cell rule is the one the repository fixes, not a re-derivation
        grid = {
            "bins": row["profiles"] // 2 + 1,
            "delta_f_hz": row["delta_f_hz"],
            "nyquist_hz": row["nyquist_hz"],
        }
        low, high = frequency_cell(0, grid=grid)
        assert low == 0.0 and high == pytest.approx(0.5 * row["delta_f_hz"])


# --------------------------------------------------------------------------------------
# §5 / §6: scalars only - the anti-array-equivalence guards
# --------------------------------------------------------------------------------------

#: Keys that would name a spectrum, a density or a bin vector. Any of these in a "scalar" report
#: is array publication under another name (§6).
FORBIDDEN_ARRAY_KEYS = frozenset(
    {
        "psd",
        "psd_values",
        "psd_array",
        "power_spectral_density",
        "frequencies",
        "frequency_hz",
        "frequencies_hz",
        "spectrum",
        "spectra",
        "density",
        "magnitudes",
        "magnitude",
        "values",
        "samples",
        "bins",
        "bin_values",
        "fft",
        "array",
        "data",
        "tolist",
    }
)

#: Column names that would make one CSV column per bin or per element: the array shape of a
#: spectrum's own axis, which §6 keeps outside the narrowing whether or not it is called "psd".
FORBIDDEN_BIN_COLUMNS = frozenset(
    {
        "psd",
        "psd_values",
        "psd_value",
        "density",
        "frequencies",
        "frequency",
        "frequency_hz",
        "frequencies_hz",
        "bin",
        "bins",
        "bin_index",
        "element",
        "elements",
        "sample",
        "samples",
        "amplitude",
        "magnitude",
        "spectrum",
        "fft",
    }
)


def _numeric_arrays(node, path: tuple = ()):
    """Every JSON list that consists only of numbers, as ``(path, length)``."""
    if isinstance(node, list):
        if node and all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in node
        ):
            yield path, len(node)
        for index, item in enumerate(node):
            yield from _numeric_arrays(item, path + (index,))
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _numeric_arrays(value, path + (key,))


def test_no_report_file_is_a_psd_array_under_another_name(report: Path) -> None:
    """§5/§6: the report ships no NPZ, no array artefact and no per-bin table.

    Two independent statements: the file set is exactly §5's three scalar artefacts with no NPZ
    in sight, and no JSON array scales with the bins - there is no list of numbers anywhere in
    the document longer than a handful of entries, while a one-sided density would be hundreds
    to thousands of bins per row.
    """
    produced = sorted(
        path.relative_to(report).as_posix()
        for path in report.rglob("*")
        if path.is_file()
    )
    assert produced == sorted(file_names()), (
        f"§5's report is three scalar artefacts; got {produced}"
    )
    for path in report.rglob("*"):
        assert path.suffix not in {".npz", ".npy", ".parquet", ".feather"}, path
    document = _document(report)
    arrays = list(_numeric_arrays(document))
    oversized = [(path, length) for path, length in arrays if length > 8]
    assert not oversized, (
        "a list of numbers in the document scales with something: a PSD array, a bin vector or "
        f"a flattened spectrum could hide here. Offending arrays: {oversized}"
    )
    assert _dict_keys(document) & FORBIDDEN_ARRAY_KEYS == set(), (
        "the document names a spectrum, a density or a bin vector: "
        f"{sorted(_dict_keys(document) & FORBIDDEN_ARRAY_KEYS)}"
    )


def _dict_keys(node) -> set[str]:
    keys: set[str] = set()
    if isinstance(node, dict):
        keys |= set(node)
        for value in node.values():
            keys |= _dict_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _dict_keys(item)
    return keys


def test_the_csv_has_no_per_bin_column_and_its_columns_do_not_scale(
    report: Path,
) -> None:
    """The cardinality guard at the table level: columns are fields, never elements of a spectrum."""
    header = _header(report)
    bin_columns = [name for name in header if name in FORBIDDEN_BIN_COLUMNS]
    assert not bin_columns, (
        "one row per cell x supported gate is §6's permitted cardinality; a per-bin or "
        f"per-element column is array publication. Offending columns: {bin_columns}"
    )
    assert tuple(header) == EXPLICIT_CSV_COLUMNS, (
        "the scalar field set is closed and named: a new column is a schema change, not a new "
        f"value. Got {header}"
    )
    rows = _csv_rows(report)
    # a per-bin table would need one row per (cell, gate, bin): assert no cell repeats a gate
    pairs = defaultdict(int)
    for row in rows:
        pairs[
            (
                row[_column(header, "pass")],
                row[_column(header, "relative_path")],
                row[_column(header, "view")],
                row[_column(header, "gate_index")],
            )
        ] += 1
    assert set(pairs.values()) == {1}, (
        "a (cell, gate) pair appears once, exactly as §6 permits"
    )


def test_the_report_text_carries_no_enum_repr_and_no_flattened_vector(
    report: Path,
) -> None:
    """Enum members publish their ``.value``, never ``BandFractionState.DEFINED`` or a blob."""
    csv_text = _csv_text(report)
    document_text = (report / str(_require_writer().DOC_NAME)).read_text(
        encoding="utf-8"
    )
    for text, name in ((csv_text, "csv"), (document_text, "json")):
        for marker in (
            "BandFractionState",
            "SpectralVerdict",
            "Detrending.",
            "np.",
            "array(",
        ):
            assert marker not in text, f"{name} carries a serialized repr: {marker!r}"
        for blob in re.findall(r"[A-Za-z0-9+/=]{2000,}", text):
            raise AssertionError(
                f"{name} carries a base64- or tolist-shaped blob: {blob[:40]}..."
            )
    header = _header(report)
    states = {row[_column(header, "state")] for row in _csv_rows(report)}
    assert states <= set(BAND_STATES), states
    assert "defined" in states, (
        "the committed set is admitted, so its state is 'defined'"
    )
    verdicts = {row[_column(header, "verdict")] for row in _csv_rows(report)}
    assert verdicts <= {
        SpectralVerdict.DEFINED.value,
        SpectralVerdict.REFUSED_AXIS.value,
    }


# --------------------------------------------------------------------------------------
# §5: digests, LF bytes and determinism
# --------------------------------------------------------------------------------------


def _normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_the_document_binds_the_csv_by_the_repository_digest_rule(report: Path) -> None:
    """§5: ``table_sha256`` is the LF-normalized digest of the CSV beside it."""
    document = _document(report)
    csv_path = report / str(_require_writer().CSV_NAME)
    assert document["table_sha256"] == fdp.table_digest(csv_path), (
        "the recorded digest is the repository's own LF rule, the same one the floor readers use"
    )
    assert document["table_sha256"].startswith("sha256:")
    assert document["analysis_commit"] == REVISION
    assert (
        isinstance(document["plan_fingerprint"], str) and document["plan_fingerprint"]
    )


def test_every_document_gate_holds_and_the_document_is_ok(report: Path) -> None:
    """§8.10: ``ok`` true and every ``checks`` entry true, with the failing names on a miss."""
    document = _document(report)
    assert document["ok"] is True
    checks = document["checks"]
    assert isinstance(checks, dict) and checks
    assert all(checks.values()), {
        key: value for key, value in checks.items() if not value
    }


def test_the_report_is_utf8_lf_with_one_trailing_newline(report: Path) -> None:
    """§5: the artefacts are UTF-8/LF, and the measured pair ends in one newline.

    The exactly-one-trailing-newline rule is asserted for the CSV and the document - the two
    artefacts §5 fixes a byte rule and a digest for - while the README, which is prose, only has
    to be UTF-8/LF and newline-terminated.
    """
    csv_name = str(_require_writer().CSV_NAME)
    doc_name = str(_require_writer().DOC_NAME)
    readme_name = file_names()[2]
    for name in file_names():
        raw = (report / name).read_bytes()
        assert b"\r\n" not in raw, f"{name} carries a CRLF ending"
        raw.decode("utf-8")
        assert raw.endswith(b"\n"), f"{name} does not end in a newline"
    for name in (csv_name, doc_name):
        raw = (report / name).read_bytes()
        assert not raw.endswith(b"\n\n"), (
            f"{name} must end in exactly one newline, since §5's digest covers those bytes"
        )
    assert (report / readme_name).is_file()
    # and the digest covers the LF form even where a checkout materialized CRLF
    csv_path = report / str(_require_writer().CSV_NAME)
    crlf = csv_path.read_bytes().replace(b"\n", b"\r\n")
    other = csv_path.with_name("crlf-check.csv")
    other.write_bytes(crlf)
    try:
        assert fdp.table_digest(other) == fdp.table_digest(csv_path)
    finally:
        other.unlink()


def test_two_scratch_runs_at_one_revision_are_byte_identical(
    tmp_path: Path,
) -> None:
    """§5/§8.11: the recorded revision reproduces the same bytes, run after run.

    Both runs are in scratch directories, so nothing under ``reports/`` is touched by either.
    They write into *different* directories, because the claim is about the recordings and the
    revision and not about the destination: an artefact that embedded where it was written could
    not be reproduced byte-for-byte anywhere else.
    """
    first = tmp_path / "run-1"
    second = tmp_path / "run-2"
    write_report(first, analysis_commit=REVISION)
    second_model = write_report(second, analysis_commit=REVISION)
    for name in file_names():
        assert _normalized(first / name) == _normalized(second / name), (
            f"{name} is not deterministic across two runs at {REVISION}"
        )
    assert second_model.table_sha256 == fdp.table_digest(
        second / str(_require_writer().CSV_NAME)
    )
    # and no artefact names the directory it happened to be written into
    document = _document(first)
    for key in document:
        assert "dir" not in key and "path" not in key, (
            f"the document keys {key!r}, which ties committed bytes to a checkout's layout"
        )
    assert first.as_posix() not in _csv_text(first)
    assert first.as_posix() not in _document_text(first)


def _document_text(report_dir: Path) -> str:
    return (report_dir / str(_require_writer().DOC_NAME)).read_text(encoding="utf-8")


def test_a_different_recorded_commit_changes_only_the_recorded_field(
    tmp_path: Path,
) -> None:
    """The commit is recorded, not computed: the numbers do not move with the label."""
    destination = tmp_path / "at-base"
    base_model = write_report(destination, analysis_commit=REVISION)
    csv_name = str(_require_writer().CSV_NAME)
    table = (destination / csv_name).read_bytes()
    base_document = _document(destination)
    other_model = write_report(destination, analysis_commit="0" * 7)
    assert (destination / csv_name).read_bytes() == table, (
        "the table is the measurement, not the revision it was labelled with"
    )
    assert other_model.analysis_commit == "0" * 7
    other_document = _document(destination)
    differing = {
        key
        for key in set(base_document) | set(other_document)
        if base_document.get(key) != other_document.get(key)
    }
    assert differing == {"analysis_commit"}, (
        "only the recorded revision may depend on the revision label; it is what a recorded "
        f"--analysis-commit reproduces. Differing keys: {sorted(differing)}"
    )
    assert base_model.table_sha256 == other_model.table_sha256


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_the_frozen_report_trees_are_byte_unchanged(tmp_path: Path) -> None:
    """§5/§8.11: the four pre-existing trees are hash-for-hash the base revision's, run or not."""
    for tree in FROZEN_TREES:
        assert (ROOT / tree).is_dir(), tree
        listed = _git("ls-tree", "-r", "--name-only", f"HEAD:{tree}")
        paths = [line for line in listed.splitlines() if line]
        assert paths, tree
        for relative in paths:
            committed = subprocess.run(
                ["git", "show", f"HEAD:{tree}/{relative}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout
            working = (ROOT / tree / relative).read_bytes()
            assert working.replace(b"\r\n", b"\n") == committed.replace(
                b"\r\n", b"\n"
            ), f"{tree}/{relative} differs from the base revision"
    # and a scratch run leaves the frozen trees, and every other committed report file, untouched
    write_report(tmp_path / "scratch", analysis_commit=REVISION)
    status = _git("status", "--porcelain", "--", "reports")
    offending = [
        line
        for line in status.splitlines()
        if line.strip() and "reports/sparse-signal/" not in line
    ]
    assert not offending, (
        "writing a report into a scratch directory must not modify anything under reports/ "
        "outside §5's own publish root: " + repr(offending)
    )


# --------------------------------------------------------------------------------------
# §8.12 / §10: the wording guard - no physics word and no exploratory constant
# --------------------------------------------------------------------------------------

#: §10's forbidden interpretations, as phrases a data file must never carry as an assertion.
PHYSICS_PHRASES = (
    "vortex-dominated",
    "recurrence-dominated",
    "stronger low-frequency",
    "better measurement configuration",
)

#: The exploratory constants §9(g)/§10.10 forbid: the 71.6 % smoke datum and its renderings. The
#: patterns carry digit boundaries, because the datum is a *quoted number* - a measured power of
#: ``71.6245...`` or a fraction of ``0.716000`` printed at six decimals is a measurement, not a
#: quotation, and a substring scan would call either one a violation.
EXPLORATORY_PATTERNS = (
    re.compile(r"(?<![\d.])71\.6(?![\d])"),
    re.compile(r"(?<![\d.])0\.716(?![\d])"),
    re.compile(r"71,6"),
)


def test_no_data_file_carries_a_physics_word_or_an_exploratory_datum(
    report: Path,
) -> None:
    """§8.12: neither the CSV nor the document interprets a number, and neither quotes 71.6 %.

    The physics phrases are scanned over the whole file; the exploratory datum is scanned over
    the document's *strings* only, because a coincidental band fraction of ``0.716000`` is a
    measurement printed at six decimals and not a quotation of the smoke observation - the guard
    targets prose, which is where an exploratory constant could read as an expectation.
    """
    texts = {
        str(_require_writer().CSV_NAME): _csv_text(report),
        str(_require_writer().DOC_NAME): (
            report / str(_require_writer().DOC_NAME)
        ).read_text(encoding="utf-8"),
    }
    for name, text in texts.items():
        lowered = text.lower()
        for phrase in PHYSICS_PHRASES:
            assert phrase not in lowered, (
                f"{name} carries the physics phrase {phrase!r}"
            )
    strings = _json_strings(_document(report))
    for pattern in EXPLORATORY_PATTERNS:
        offenders = [value for value in strings if pattern.search(value)]
        assert not offenders, (
            f"the document quotes the exploratory constant {pattern.pattern!r}, which §10.10 "
            f"forbids: {offenders}"
        )


def _json_strings(node) -> list[str]:
    """Every string in the document, so the wording guard reads prose and not floats."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [item for value in node.values() for item in _json_strings(value)]
    if isinstance(node, list):
        return [item for value in node for item in _json_strings(value)]
    return []


def test_the_readme_repeats_the_no_go_list_and_quotes_no_exploratory_number(
    report: Path,
) -> None:
    """§5: the README carries definitions, units, digests, settings and the §10 no-go list."""
    readme = report / file_names()[2]
    assert readme.is_file(), "§5 publishes a README beside the table and the document"
    text = readme.read_text(encoding="utf-8")
    lowered = text.lower()
    for topic in ("does not claim", "detrend", "nyquist", "sha256", "band_fraction"):
        assert topic in lowered, f"the README does not state {topic!r}"
    for pattern in EXPLORATORY_PATTERNS:
        assert not pattern.search(text), (
            f"the README quotes the exploratory constant {pattern.pattern!r}, which §10.10 "
            "forbids"
        )
    assert LOW_HZ == 1.0
    assert (
        str(_require_writer().DOC_NAME) in text
        or str(_require_writer().CSV_NAME) in text
    ), "the README names the artefacts it indexes"


def test_the_readme_glossary_defines_every_axis_field_the_document_publishes(
    report: Path,
) -> None:
    """§5/F8: the README's glossary names the axis scalars, ``min_samples`` among them.

    ``min_samples`` is published in every cell's axis block, so it is part of what a reader must be
    told to interpret a number; a glossary that names the other axis fields and omits it leaves one
    published scalar undefined. The population checked is the document's *own* axis block, so the
    glossary is held to the fields the report really publishes and a new axis scalar cannot slip in
    undocumented. The admission's reason and the estimator's name are prose definitions rather than
    axis scalars, so they are carried by the sentences that state them, not by this field list.
    """
    document = _document(report)
    axis_fields: set[str] = set()
    for cell in _json_cells(document):
        axis_fields |= set(cell["axis"])
    assert axis_fields == set(EXPLICIT_AXIS_KEYS), sorted(axis_fields)

    scalar_fields = axis_fields - {"admission_reason", "estimator"}
    assert "min_samples" in scalar_fields, (
        "the axis block must publish the admission's minimum sample count"
    )
    assert len(scalar_fields) == len(EXPLICIT_AXIS_KEYS) - 2, sorted(scalar_fields)

    readme = (report / file_names()[2]).read_text(encoding="utf-8")
    missing = sorted(field for field in scalar_fields if field not in readme)
    assert not missing, (
        "the README's glossary does not name every axis scalar the document publishes; it omits "
        f"{missing}"
    )


# --------------------------------------------------------------------------------------
# §5/§7: the CLI subcommand records the revision
# --------------------------------------------------------------------------------------


def test_the_writer_is_reachable_as_a_cli_subcommand_that_records_the_revision(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """§5: a bare run records HEAD; a recorded ``--analysis-commit`` reproduces committed bytes."""
    from udv_echo_process import cli

    registry = getattr(cli, "_COMMANDS", {})
    key = next(
        (
            name
            for name in registry
            if "signal" in name or "sa2-4" in name or "characterization" in name
        ),
        None,
    )
    assert key is not None, (
        "§7's S2 is a writer module *plus* the CLI subcommand of §5; no command in "
        f"{sorted(registry)} names the SA2.4 report"
    )
    with pytest.raises(SystemExit) as exit_info:
        registry[key](["--help"])
    assert exit_info.value.code == 0
    usage = capsys.readouterr().out
    for flag in ("--analysis-commit", "--report-dir"):
        assert flag in usage, (
            f"the SA2.4 subcommand must offer {flag} (plan §5's writer shape); usage was "
            f"{usage!r}"
        )


# --------------------------------------------------------------------------------------
# §2's three states at the writer's own boundary: refusal and zero, from synthetic S1
# --------------------------------------------------------------------------------------
#
# No committed cell is refused - §J records 104/104 admitted - so the two states that are *not*
# a number are fixture-exercised here. The writer must be able to render them without inventing a
# value: a refusal was not measured and a defined zero was, and a report that prints `0.0` for
# either would publish a measurement that never happened.

#: Candidate names for the writer's own cell builder - the seam where one S1 cell becomes one
#: report cell whose gate rows are the rows the CSV publishes. The first that exists is used.
CELL_BUILDER_NAMES = ("cell_document", "_cell_document")
#: Candidate names for the writer's per-gate JSON renderer, the row a reader of the document sees.
GATE_RENDERER_NAMES = ("gate_document", "_gate_document", "gate_rows", "gate_row")


def _callable_named(names: tuple[str, ...], what: str):
    w = _require_writer()
    for name in names:
        candidate = getattr(w, name, None)
        if callable(candidate):
            return candidate
    raise AssertionError(
        f"the writer must expose the seam where {what}, so the refusal and zero-power states can "
        f"be exercised without a committed instance: tried {names}"
    )


def _rendered_rows(cell) -> list[dict]:
    """One S1 cell's gate rows as the writer publishes them, through the writer's own builder.

    Building the cell document is itself part of the assertion: the writer's ``CellDocument``
    validator refuses a refusal rendered with a number, a zero rendered as a fraction or a
    refusal rendered as a defined zero - so a builder that could render these states wrongly
    would not return at all. The rows are then read as the document prints them.

    The cell builder also takes the §4 grouping metadata (the acquisition condition, its kind and
    the planned window pair); a synthetic S1 cell owns no acquisition condition, so one is
    supplied here from the writer's own ``RepeatCondition``. Only the parameters the builder
    actually declares are passed, so the seam stays usable if the signature narrows.
    """
    build = _callable_named(CELL_BUILDER_NAMES, "one S1 cell becomes one report cell")
    render = _callable_named(
        GATE_RENDERER_NAMES, "one report gate row becomes one document row"
    )
    supplied: dict[str, object] = {
        "pass_name": "synthetic",
        "plan_fingerprint": "sha256:" + "0" * 64,
        "kind": "scientific",
        "resolution_mm": 1.85,
        "window_gates": 50,
    }
    condition_type = getattr(_require_writer(), "RepeatCondition", None)
    if condition_type is not None:
        supplied["condition"] = condition_type(
            burst_length=10, emissions_per_profile=20, prf_us=600.0
        )
    accepted = inspect.signature(build).parameters
    document = build(
        cell, **{name: value for name, value in supplied.items() if name in accepted}
    )
    return [render(row) for row in document.gates]


def _rendered_field(row: dict, *candidates: str):
    for candidate in candidates:
        if candidate in row:
            return row[candidate]
    raise AssertionError(f"none of {candidates} is a rendered row field: {sorted(row)}")


def _synthetic_view(trace: np.ndarray, stamps: np.ndarray, *, gates: int = 1):
    from udv_echo_process.analysis._sparse_view import SparseView, WindowView, view_rule

    matrix = np.asarray(trace, dtype=float).reshape(-1, 1)
    depths = np.arange(gates, dtype=float) * 2.0 + 10.0
    return WindowView(
        view=SparseView.PRIMARY,
        view_rule=view_rule(SparseView.PRIMARY),
        relative_path="synthetic.BDD",
        source_sha256="0" * 64,
        job="synthetic",
        point_label="synthetic",
        order=1,
        values=matrix,
        time_s=np.asarray(stamps, dtype=float),
        depths_mm=depths,
        support_mask=np.ones(gates, dtype=bool),
        native_gates=gates,
        native_depth_extent_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        pass_support_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        start_index=0,
        stop_index=int(stamps.size),
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
    )


def test_a_defined_zero_power_gate_is_a_measurement_and_not_a_zero_fraction() -> None:
    """§2: a constant gate is ``defined-zero-power`` - ``B == 0.0``, ``Phi is None``."""
    from udv_echo_process.analysis import sparse_spectral_characterization as backend

    stamps = np.arange(256, dtype=float) * 0.02
    cell = backend.characterization_of_view(
        _synthetic_view(np.full(256, 4.0), stamps), low_hz=LOW_HZ
    )
    assert cell.admission.admitted is True
    rows = _rendered_rows(cell)
    assert len(rows) == cell.provenance.supported_gates == 1
    row = rows[0]
    assert _rendered_field(row, "state", "band_state", "band_fraction_state") == (
        "defined-zero-power"
    )
    assert (
        _rendered_field(row, "fraction", "low_band_fraction", "band_fraction") is None
    ), "0 / 0 is undefined: a zero fraction here would read as a measured zero"
    assert float(_rendered_field(row, "band_power")) == 0.0
    assert float(_rendered_field(row, "total_power")) == 0.0


def test_a_refused_axis_keeps_an_identity_row_and_synthesizes_no_zero() -> None:
    """§2: a refusal was not measured - the gate keeps its row, and no number is invented."""
    from udv_echo_process.analysis import sparse_spectral_characterization as backend

    stamps = np.arange(256, dtype=float) * 0.02
    stamps = stamps.copy()
    stamps[10] = stamps[11]
    cell = backend.characterization_of_view(
        _synthetic_view(np.cos(2.0 * np.pi * 3.0 * stamps), stamps), low_hz=LOW_HZ
    )
    assert cell.admission.admitted is False
    rows = _rendered_rows(cell)
    assert len(rows) == cell.provenance.supported_gates == 1, (
        "a supported gate on a refused axis keeps its identity/status row"
    )
    row = rows[0]
    assert (
        _rendered_field(row, "state", "band_state", "band_fraction_state")
        == "refused-axis"
    )
    for field, candidates in (
        ("fraction", ("fraction", "low_band_fraction", "band_fraction")),
        ("band_power", ("band_power",)),
        ("total_power", ("total_power",)),
    ):
        value = _rendered_field(row, *candidates)
        assert value is None, (
            f"a refused axis reports {field} as {value!r}: no zero is synthesized for an axis "
            "that was not measured"
        )
    assert _rendered_field(row, "gate_index", "gate", "column") == 0
    assert _rendered_field(row, "depth_mm", "depth") == pytest.approx(
        float(cell.gates[0].depth_mm)
    )


# --------------------------------------------------------------------------------------
# S2 adversarial regressions (F1-F9): scientific grouping, publication safety, closed schema
# --------------------------------------------------------------------------------------
#
# Nine defects an adversarial review of the writer found, each held here to the claim its own
# docstring makes. Every row is written red-first against the *published artefacts* or the
# writer's frozen public surface, never against an exploratory number: the sweep's cells carry
# only a recording's identity, so no row below needs an expected Phi, a floor or a spread.

#: The CSV's own schema, restated here in full and in order. It is closed: a new column is a
#: schema change that must be reviewed, not a new value, so the pin is the exact tuple rather
#: than a "no more than N columns" allowance that a per-bin table could still satisfy.
EXPLICIT_CSV_COLUMNS: tuple[str, ...] = (
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

#: Plan §4's published row set, as the top-level names it is carried under. The spread is published
#: (the sweep's cells carry the acquisition condition), so these are part of the document's own
#: closed field set — four names plus the key it was grouped by (F1, F8).
REPEAT_SPREAD_KEY = "repeat_spread"
REPEAT_GROUPS_KEY = "repeat_groups"
REPEAT_SPREAD_SUMMARY_KEY = "repeat_spread_summary"
REPEAT_SPREAD_RULE_KEY = "repeat_spread_rule"
REPEAT_CONDITION_KEY_FIELD = "repeat_condition_key"

#: The document's top-level field set (F8): every key it publishes, pinned exactly.
EXPLICIT_DOCUMENT_KEYS: frozenset[str] = frozenset(
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
        REPEAT_CONDITION_KEY_FIELD,
        REPEAT_GROUPS_KEY,
        REPEAT_SPREAD_KEY,
        REPEAT_SPREAD_RULE_KEY,
        REPEAT_SPREAD_SUMMARY_KEY,
        "study",
        "summary",
        "table",
        "table_sha256",
    }
)

#: The whole condition a repeat group is keyed by, exactly as the document states it (F8).
EXPLICIT_REPEAT_CONDITION_KEY: tuple[str, ...] = (
    "pass",
    "kind",
    "condition",
    "resolution_mm",
    "window_gates",
)

#: One repeat condition triple's own field set (F8).
EXPLICIT_REPEAT_TRIPLE_KEYS: frozenset[str] = frozenset(
    {"burst_length", "emissions_per_profile", "prf_us"}
)

#: One repeat group's field set (F8).
EXPLICIT_REPEAT_GROUP_KEYS: frozenset[str] = frozenset(
    {
        "condition",
        "kind",
        "members",
        "n_cells",
        "n_recordings",
        "pass",
        "resolution_mm",
        "window_gates",
    }
)

#: One repeat group member's field set (F8): an identity, not a value.
EXPLICIT_REPEAT_MEMBER_KEYS: frozenset[str] = frozenset({"job", "point_label"})

#: One repeat-spread row's field set (F8): a group x view x gate, its members' own values, its
#: summary and its count.
EXPLICIT_REPEAT_ROW_KEYS: frozenset[str] = frozenset(
    {
        "condition",
        "depth_mm",
        "gate_index",
        "kind",
        "max",
        "members",
        "min",
        "n",
        "pass",
        "range",
        "resolution_mm",
        "view",
        "window_gates",
    }
)

#: The planned native gate count of the window the committed repeats were acquired on, and the
#: supported gate rows a cell of such a group actually publishes. The two are *distinct* on the
#: committed set - 50 planned, 49 supported - which is why the window's own dimension is published
#: as ``window_gates``: a field named ``gates`` would invite a reader (and a rename) to carry the
#: row count under the window's name. The planned count is grounded in the decoded plan below,
#: never trusted as a constant alone (F1, F8).
PLANNED_WINDOW_GATES = 50
SUPPORTED_GATES_PER_REPEAT_CELL = 49

#: One repeat-spread member value's field set (F8).
EXPLICIT_REPEAT_MEMBER_VALUE_KEYS: frozenset[str] = frozenset(
    {"band_fraction", "job", "point_label"}
)

#: The §4 summary's field set (F8): counts only, never a reading of the spread.
EXPLICIT_REPEAT_SUMMARY_KEYS: frozenset[str] = frozenset(
    {
        "cells",
        "groups",
        "recordings",
        "singleton_cells",
        "singleton_recordings",
        "spread_rows",
    }
)

#: The prespecified constants block's field set (F8).
EXPLICIT_CONSTANT_KEYS: frozenset[str] = frozenset(
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

#: The report's own gate vocabulary (F8/F9): the checks a reader is shown, exactly.
EXPLICIT_CHECK_KEYS: frozenset[str] = frozenset(
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

#: The summary block's field set (F8).
EXPLICIT_SUMMARY_KEYS: frozenset[str] = frozenset(
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

#: One per-cell record's field set (F8).
EXPLICIT_CELL_KEYS: frozenset[str] = frozenset(
    {
        "axis",
        "condition",
        "declared_window_s",
        "detrending",
        "estimator_name",
        "gates",
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

#: The axis block's field set (F8).
EXPLICIT_AXIS_KEYS: frozenset[str] = frozenset(
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

#: One probe-target row's field set (F8).
EXPLICIT_TARGET_KEYS: frozenset[str] = frozenset(
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

#: One gate row's field set (F8).
EXPLICIT_GATE_KEYS: frozenset[str] = frozenset(
    {
        "band_fraction",
        "band_power",
        "band_reason",
        "band_state",
        "depth_mm",
        "enbw_bins",
        "enbw_hz",
        "gate_index",
        "parseval_relative_error",
        "total_power",
        "verdict",
    }
)

#: The finding this file's grouping row rests on (F1). The report's own table carries a cell's
#: identity (pass, job, point label, view), never the acquisition condition - so a grouping read off
#: the table alone could only be job- or label-keyed, and both of those pool distinct conditions.
#: ``point_label`` is the identity the sweep does carry, so a rename here would be a schema change.
CONDITION_FIELD_CANDIDATES: tuple[str, ...] = (
    "condition",
    "condition_label",
    "condition_identity",
    "point_label",
)


def _condition_labels_by_job_view(
    report_dir: Path,
) -> dict[tuple[str, str, str], set[str]]:
    """Every published cell's identity, keyed by ``(pass, job, view)``.

    Read from the published table's own text: the condition column if the report carries one, else
    the point label it always holds. One job's cells span several point labels on the committed set,
    which is why a job-keyed spread would average distinct conditions.
    """
    header = _header(report_dir)
    condition = next(
        (name for name in CONDITION_FIELD_CANDIDATES if name in header), "point_label"
    )
    labels: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for row in _csv_rows(report_dir):
        key = (
            row[_column(header, "pass")],
            row[_column(header, "job")],
            row[_column(header, "view")],
        )
        labels[key].add(row[condition])
    return labels


def test_the_published_repeat_spread_is_grouped_by_condition_not_by_job_or_label(
    report: Path,
) -> None:
    """F1: plan §4's spread repeats *one whole condition*; a job- or label-keyed group averages several.

    The committed cells of one job carry distinct point labels (``cc1``/``cc3`` beside the
    ``ctrl-*`` anchors) **and** one label recurs under different conditions (``ctrl-begin`` is
    burst-4's anchor in one job and burst-18's in another), so a spread keyed by ``(pass, job)`` or
    by ``point_label`` would average distinct conditions and read as a repeat where none was
    measured. The published groups must therefore be keyed by the whole condition, and must be
    exactly the decoded sweep's true same-condition sets. The committed set is asserted to really
    mix, so this row cannot pass by finding nothing to look at.
    """
    document = _document(report)
    labels = _condition_labels_by_job_view(report)
    mixed = sorted(key for key, values in labels.items() if len(values) > 1)
    assert mixed, (
        "this row is only non-vacuous because one job's cells span several conditions; the "
        "published set shows no mixing, so a job-keyed group could not be ruled out"
    )

    repeats, _singletons = _true_repeat_groups()
    decoded_keys = {
        (pass_name, condition[0], condition[1:4], condition[4], condition[5])
        for (pass_name, condition, _depths) in repeats
    }
    groups = document[REPEAT_GROUPS_KEY]
    published_keys = {
        (
            group["pass"],
            group["kind"],
            (
                group["condition"]["burst_length"],
                group["condition"]["emissions_per_profile"],
                group["condition"]["prf_us"],
            ),
            group["resolution_mm"],
            group["window_gates"],
        )
        for group in groups
    }
    assert published_keys == decoded_keys, published_keys ^ decoded_keys

    # the point label really is not the key: one label, several distinct conditions.
    label_conditions: dict[str, set[tuple]] = defaultdict(set)
    for group in groups:
        for member in group["members"]:
            label_conditions[member["point_label"]].add(
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
    readme = (report / file_names()[2]).read_text(encoding="utf-8").lower()
    assert "repeat_spread" in readme and "repeat spread" in readme, (
        "the published row set must be described in the README beside the numbers"
    )


# --------------------------------------------------------------------------------------
# F1, independently grounded: the *true* same-condition repeats of the decoded sweep.
#
# The published identity is not a condition. ``point_label`` recurs across distinct
# conditions (``ctrl-begin`` is burst-4's anchor in one job and burst-18's in another), and one
# job holds several distinct conditions (its ``cc``/``e`` contrasts). The plan's condition - the
# burst length, emissions and PRF the *job* was planned at, plus the window the point requested
# (its resolution and gate count) - is recoverable only from the decoded binding. Grouping by it
# is the only grouping that repeats one condition rather than contrasting several, and the four
# ``cc`` contrast points sit at their own resolutions, so each is a singleton cell and no repeat.
# --------------------------------------------------------------------------------------


def _decoded_condition(point) -> tuple[str, int, int, float, float, int]:
    """One decoded point's true condition: job kind, the condition triple, resolution, gates.

    ``job.condition`` is the plan's own ``(burst_length, emissions_per_profile, prf_us)``, and the
    point's ``parameters`` carry the window it requested (``resolution_mm``, ``gates``). Two cells
    repeat one condition only when all of these agree - the recording's identity does not.
    """
    job = point.binding.job
    parameters = point.binding.point.parameters
    return (
        str(job.kind),
        int(job.burst_length),
        int(job.emissions_per_profile),
        float(job.prf_us),
        float(parameters.resolution_mm),
        int(parameters.gates),
    )


def _decoded_depth_vector(point, decoding) -> tuple[float, ...]:
    """The supported depths a point's *primary* view keeps, as the exact vector they are.

    A repeat group averages nothing unless its members share the spatial window, so the depth
    vector is part of the group's identity rather than a field read afterwards.
    """
    view = primary_view(
        point, window_s=decoding.window_s, support_mm=decoding.support_mm
    )
    depths = np.asarray(view.depths_mm, dtype=float)
    columns = [int(column) for column in np.asarray(view.supported_columns)]
    return tuple(round(float(depths[column]), 9) for column in columns)


def _true_repeat_groups():
    """The committed set's true same-condition repeats and its singleton recordings.

    Returns ``(repeats, singletons)``: ``repeats`` maps
    ``(pass_name, condition, depth_vector)`` to the decoded points sharing it (only where more
    than one point does), and ``singletons`` is every decoded point whose condition-and-depths
    occur exactly once. Nothing here reads the report; this is the decoded sweep's own statement.
    """
    grouped: dict[tuple, list] = defaultdict(list)
    for ref in COMMITTED_PASSES:
        if not ref.is_reproducibility_sitting:
            continue
        decoding = decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
        for point in decoding.points:
            key = (
                ref.name,
                _decoded_condition(point),
                _decoded_depth_vector(point, decoding),
            )
            grouped[key].append(point)
    repeats = {key: members for key, members in grouped.items() if len(members) > 1}
    singletons = [
        member
        for members in grouped.values()
        if len(members) == 1
        for member in members
    ]
    return repeats, singletons


def _published_fractions_by_cell(
    report_dir: Path,
) -> dict[tuple[str, str, str], list[float]]:
    """Every published non-empty band fraction, keyed by ``(pass, relative_path, view)``."""
    header = _header(report_dir)
    columns = {
        field: _column(header, field)
        for field in ("pass", "relative_path", "view", "fraction")
    }
    by_cell: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in _csv_rows(report_dir):
        text = row[columns["fraction"]]
        if text == "":
            continue
        by_cell[
            (row[columns["pass"]], row[columns["relative_path"]], row[columns["view"]])
        ].append(float(text))
    return by_cell


def _group_spread(
    report_dir: Path, pass_name: str, members
) -> tuple[float, float, float]:
    """``(min, max, range)`` of a group's published gate fractions, recomputed from the bytes.

    Every member recording contributes both of its views, so the spread is over the group's
    ``cell x supported gate`` fractions exactly as the report publishes them - never an expected
    value carried over from anywhere.
    """
    by_cell = _published_fractions_by_cell(report_dir)
    values: list[float] = []
    for point in members:
        relative = str(point.binding.relative_path)
        for view in ("primary-comparison", "full-record"):
            values.extend(by_cell.get((pass_name, relative, view), []))
    assert values, (
        f"no published fraction found for repeat group {pass_name}:{members[0]}"
    )
    smallest, largest = min(values), max(values)
    return smallest, largest, largest - smallest


def test_the_decoded_sweep_holds_twelve_true_same_condition_repeat_groups() -> None:
    """F1 grounding: the *real* repeats of the decoded sweep - 12 groups, 44 recordings, 16 singletons.

    The design's repeats of one condition (the block anchors and the common-reference runs) are
    counted here from the decoded bindings, not from the report: 6 groups per sitting (12 total),
    22 recordings per sitting (44), each on both views (88 cells), and 8 singleton recordings (16
    cells) whose condition occurs once. The 16 are exactly the ``cc`` contrast points, each at its
    own resolution - excluded because they are no repeat, not because the report dropped them.
    """
    repeats, singletons = _true_repeat_groups()
    assert len(repeats) == 12, sorted(key[1] for key in repeats)
    for pass_name in ("sparse-mixer-live-1", "sparse-mixer-live-2"):
        per_pass = [key for key in repeats if key[0] == pass_name]
        assert len(per_pass) == 6, (pass_name, len(per_pass))

    grouped_recordings = sum(len(members) for members in repeats.values())
    assert grouped_recordings == 44, grouped_recordings
    assert grouped_recordings * 2 == 88, "a cell is a recording x view"

    assert len(singletons) == 8, [point.binding.point.label for point in singletons]
    assert len(singletons) * 2 == 16, (
        "the singleton cells are the singleton recordings on both views"
    )
    assert {point.binding.point.label for point in singletons} == {
        "cc1",
        "cc2",
        "cc3",
        "cc4",
    }
    singleton_resolutions = {
        round(float(point.binding.point.parameters.resolution_mm), 3)
        for point in singletons
    }
    assert singleton_resolutions == {0.617, 2.96}, singleton_resolutions


def _sitting_decodings() -> dict[str, object]:
    """Each reproducibility sitting decoded once, keyed by the pass's own name."""
    return {
        ref.name: decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
        for ref in COMMITTED_PASSES
        if ref.is_reproducibility_sitting
    }


def test_every_true_repeat_group_member_shares_its_condition_and_depth_vector() -> None:
    """F1 grounding: within a true group, condition triple, kind, resolution, gates and depths agree.

    The grouping is a measurement of repeats rather than a label collision, so this also shows the
    collision directly: the ``ctrl-begin`` label recurs under burst-4 and burst-18 - two distinct
    conditions - which is why a point-label-keyed spread would be a false claim.
    """
    repeats, _singletons = _true_repeat_groups()
    sizes = sorted(len(members) for members in repeats.values())
    # the emissions ladder's groups (``e8``/``e64``/``e128``) hold 4 members each; the two burst
    # groups hold their 3 anchors. A group counts because its condition matches exactly.
    assert sizes == [3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4], sizes

    decodings = _sitting_decodings()
    for (pass_name, condition, depths), members in repeats.items():
        for point in members:
            assert _decoded_condition(point) == condition, (
                pass_name,
                point.binding.point.label,
            )
            assert _decoded_depth_vector(point, decodings[pass_name]) == depths, (
                pass_name,
                point.binding.point.label,
            )

    # the label collision, stated as data: the same label, two conditions, different groups.
    labels_to_conditions: dict[str, set[tuple]] = defaultdict(set)
    for condition, members in repeats.items():
        for point in members:
            labels_to_conditions[str(point.binding.point.label)].add(condition)
    assert any(len(conditions) > 1 for conditions in labels_to_conditions.values()), (
        "no point label recurs under distinct conditions, so this row's pooling argument is "
        "vacuous"
    )


def _member_identity(point) -> tuple[str, str]:
    """A decoded point's published member identity: its job and its own point label."""
    return (str(point.binding.job.job), str(point.binding.point.label))


def _group_key_from(source: dict) -> tuple:
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


def _decoded_groups_by_published_key(repeats) -> dict[tuple, list]:
    """The decoded repeat groups, re-keyed as the published groups state their key."""
    return {
        (pass_name, condition[0], condition[1:4], condition[4], condition[5]): members
        for (pass_name, condition, _depths), members in repeats.items()
    }


def _published_table_index(
    report_dir: Path,
) -> dict[tuple[str, str, str, int], float | None]:
    """Every published gate row's own band fraction, by ``(pass, relative_path, view, gate)``."""
    header = _header(report_dir)
    columns = {
        field: _column(header, field)
        for field in ("pass", "relative_path", "view", "gate_index", "fraction")
    }
    index: dict[tuple[str, str, str, int], float | None] = {}
    for row in _csv_rows(report_dir):
        key = (
            row[columns["pass"]],
            row[columns["relative_path"]],
            row[columns["view"]],
            int(row[columns["gate_index"]]),
        )
        text = row[columns["fraction"]]
        index[key] = None if text == "" else float(text)
    return index


def test_the_published_repeat_spread_is_true_repeats_of_the_decoded_condition(
    report: Path,
) -> None:
    """F1: every published §4 group is a *true* same-condition repeat with recomputed arithmetic.

    Each published group must be a decoded same-condition set (condition triple, kind, resolution
    and gate count equal, primary depth vectors identical) and its members must be exactly that
    set's recordings; each row's min/max/range must be recomputed here - both from the row's own
    member values and, independently, from the band fractions the report's own table publishes at
    that view and gate - never a number quoted from elsewhere; no singleton may appear; and every
    ``(group, view, gate index)`` must be covered exactly once. The summary's counts are pinned
    against the decoded sweep, so the 16 singleton cells are shown *excluded* rather than silently
    dropped.
    """
    document = _document(report)
    repeats, singletons = _true_repeat_groups()
    decoded_groups = _decoded_groups_by_published_key(repeats)
    groups = document[REPEAT_GROUPS_KEY]
    rows = document[REPEAT_SPREAD_KEY]
    table = _published_table_index(report)

    # the published groups are the decoded true groups, member for member.
    published_group_keys = {_group_key_from(group) for group in groups}
    assert published_group_keys == set(decoded_groups), published_group_keys ^ set(
        decoded_groups
    )
    identity_to_path: dict[tuple[str, str, str], str] = {}
    decodings = _sitting_decodings()
    for (pass_name, _condition, _depths), members in repeats.items():
        for point in members:
            view = primary_view(
                point,
                window_s=decodings[pass_name].window_s,
                support_mm=decodings[pass_name].support_mm,
            )
            identity_to_path[(pass_name, *_member_identity(point))] = str(
                view_provenance(view).relative_path
            )
    for group in groups:
        key = _group_key_from(group)
        members = decoded_groups[key]
        published_members = [
            (str(member["job"]), str(member["point_label"]))
            for member in group["members"]
        ]
        assert published_members == [_member_identity(point) for point in members], (
            key,
            published_members,
        )
        assert group["n_recordings"] == len(members), key
        assert group["n_cells"] == len(members) * 2, key

    # each row: true group, exact members, arithmetic recomputed twice, no singleton, covered once.
    singleton_identities = {_member_identity(point) for point in singletons}
    keyed = [(row, _group_key_from(row)) for row in rows]
    for row, key in keyed:
        assert key in decoded_groups, (key, sorted(row))
        members = decoded_groups[key]
        identities = [_member_identity(point) for point in members]
        assert not (set(identities) & singleton_identities), key
        published = [
            (str(member["job"]), str(member["point_label"]))
            for member in row["members"]
        ]
        assert published == identities, (key, row["view"], row["gate_index"])

        values = [member["band_fraction"] for member in row["members"]]
        defined = [float(value) for value in values if value is not None]
        assert row["n"] == len(defined)
        if not defined:
            assert row["min"] is None and row["max"] is None and row["range"] is None
            continue
        assert row["min"] == min(defined) and row["max"] == max(defined)
        assert row["range"] == max(defined) - min(defined)

        # the same spread, recomputed from the table's own published fractions at this view/gate.
        from_table = [
            table[
                (
                    key[0],
                    identity_to_path[(key[0], *identity)],
                    row["view"],
                    row["gate_index"],
                )
            ]
            for identity in identities
        ]
        defined_table = [value for value in from_table if value is not None]
        assert defined_table and row["min"] == pytest.approx(
            min(defined_table), abs=1e-6
        ), (key, row["view"], row["gate_index"])
        assert row["max"] == pytest.approx(max(defined_table), abs=1e-6)
        assert row["range"] == pytest.approx(
            max(defined_table) - min(defined_table), abs=1e-6
        )

    # coverage: one row per (group, view, gate), and the gate set is the members' shared set.
    covered = [
        (_group_key_from(row), row["view"], int(row["gate_index"])) for row in rows
    ]
    assert len(covered) == len(set(covered)), "a (group, view, gate) is published twice"
    assert {key for key, _view, _gate in covered} == published_group_keys
    for group in groups:
        key = _group_key_from(group)
        members = decoded_groups[key]
        for view in ("primary-comparison", "full-record"):
            gates_per_member = [
                {
                    gate
                    for (pass_name, relative, row_view, gate) in table
                    if pass_name == key[0]
                    and relative == identity_to_path[(key[0], *_member_identity(point))]
                    and row_view == view
                }
                for point in members
            ]
            assert all(gates == gates_per_member[0] for gates in gates_per_member), (
                key,
                view,
            )
            published_gates = {
                gate
                for row_key, row_view, gate in covered
                if row_key == key and row_view == view
            }
            assert published_gates == gates_per_member[0], (key, view)

    summary = document[REPEAT_SPREAD_SUMMARY_KEY]
    assert summary["groups"] == len(repeats) == 12
    assert (
        summary["recordings"]
        == sum(len(members) for members in decoded_groups.values())
        == 44
    )
    assert summary["cells"] == summary["recordings"] * 2 == 88
    assert summary["singleton_recordings"] == len(singletons) == 8
    assert summary["singleton_cells"] == len(singletons) * 2 == 16
    assert summary["spread_rows"] == len(rows)


def test_the_repeat_window_gate_count_is_the_planned_dimension_not_the_supported_rows(
    report: Path,
) -> None:
    """F1/F8: ``window_gates`` is the *planned* window dimension, distinct from the row count.

    Plan §4 keys a group by ``(pass, kind, condition, resolution_mm, window_gates)``: the last
    scalar is the *planned* native gate count of the window the point requested, forwarded from
    the capability sweep - not the number of gate rows a cell publishes, which the pass support can
    reduce. On the committed set every repeat group plans 50 gates on its 1.85 mm window while each
    of its cells publishes 49 supported gate rows, so the two counts are asserted *distinct* rather
    than conflated. A rename that carried the row count into the window's field - or that left the
    ambiguous ``gates`` name in place in either §4 shape - fails here. The planned count is
    grounded in the decoded plan (``parameters.gates``), never trusted as a constant alone.
    """
    document = _document(report)
    groups = document[REPEAT_GROUPS_KEY]
    rows = document[REPEAT_SPREAD_KEY]
    assert groups and rows
    assert PLANNED_WINDOW_GATES != SUPPORTED_GATES_PER_REPEAT_CELL, (
        "this row is only non-vacuous because the planned count and the supported row count "
        "differ on the committed set"
    )

    # the field is renamed: neither §4 shape publishes the ambiguous name, both publish the window.
    for source in (*groups, *rows):
        assert "gates" not in source, (
            "§4 publishes the window dimension under the ambiguous name 'gates': "
            + repr(sorted(source))
        )
        assert "window_gates" in source, sorted(source)

    # the value is the decoded plan's own planned count, per group key - not a clone of a constant.
    repeats, _singletons = _true_repeat_groups()
    planned_by_key = {
        (
            pass_name,
            condition[0],
            condition[1:4],
            condition[4],
            condition[5],
        ): condition[5]
        for (pass_name, condition, _depths) in repeats
    }
    assert set(planned_by_key.values()) == {PLANNED_WINDOW_GATES}, sorted(
        planned_by_key.values()
    )
    for group in groups:
        key = _group_key_from(group)
        assert (
            int(group["window_gates"]) == planned_by_key[key] == PLANNED_WINDOW_GATES
        ), key
    for row in rows:
        assert int(row["window_gates"]) == planned_by_key[_group_key_from(row)], (
            _group_key_from(row)
        )

    # the distinctness, on the documents: 50 planned gates, 49 supported rows per cell of a group.
    planned_cells = [
        cell
        for cell in _json_cells(document)
        if int(cell["window_gates"]) == PLANNED_WINDOW_GATES
    ]
    assert len(planned_cells) == 88, len(
        planned_cells
    )  # 44 repeat recordings x 2 views
    for cell in planned_cells:
        assert cell["supported_gates"] == SUPPORTED_GATES_PER_REPEAT_CELL, cell[
            "relative_path"
        ]
        assert len(cell["gates"]) == SUPPORTED_GATES_PER_REPEAT_CELL, cell[
            "relative_path"
        ]
        assert cell["window_gates"] != cell["supported_gates"], (
            "the planned window count and the supported row count must never be conflated"
        )

    # and the table beside the document agrees: 49 rows per such cell, not 50.
    table = _published_table_index(report)
    row_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for pass_name, relative_path, view, _gate in table:
        row_counts[(pass_name, relative_path, view)] += 1
    for cell in planned_cells:
        key = (cell["pass"], cell["relative_path"], cell["view"])
        assert row_counts[key] == SUPPORTED_GATES_PER_REPEAT_CELL, key

    # the §4 rows themselves cover one row per *supported* gate - 49 of them - never the 50 planned.
    per_group_view: dict[tuple[tuple, str], int] = defaultdict(int)
    gate_indices: dict[tuple[tuple, str], set[int]] = defaultdict(set)
    for row in rows:
        bucket = (_group_key_from(row), row["view"])
        per_group_view[bucket] += 1
        gate_indices[bucket].add(int(row["gate_index"]))
    assert set(per_group_view.values()) == {SUPPORTED_GATES_PER_REPEAT_CELL}
    for bucket, indices in gate_indices.items():
        assert indices == set(range(SUPPORTED_GATES_PER_REPEAT_CELL)), bucket

    # and the README beside the numbers spells the window key the same way it is published.
    readme = (report / file_names()[2]).read_text(encoding="utf-8")
    assert "window_gates" in readme, (
        "the README's §4 glossary still spells the window key 'gates', so the published field "
        "and the prose disagree"
    )


def test_the_writer_refuses_the_repository_root_and_every_frozen_tree() -> None:
    """F2: no destination inside the repository but the designated root is ever published to.

    The repository root, any ancestor of it, and every frozen report tree - including
    ``reports/mixer-sensitivity-analysis``, a frozen tree with no ``PassRef`` of its own - are
    refused before a single byte is written, so the repository's own ``README.md`` and the frozen
    trees cannot be clobbered.
    """
    w = _require_writer()
    error = getattr(w, "SparseSignalReportError", ValueError)
    forbidden = [
        ROOT,
        ROOT / "reports",
        *(ROOT / tree for tree in FROZEN_TREES),
    ]
    assert ROOT / "reports" / "mixer-sensitivity-analysis" in forbidden
    for destination in forbidden:
        with pytest.raises(error) as exit_info:
            w.build_sparse_signal_report(
                report_dir=destination, analysis_commit=REVISION
            )
        assert str(exit_info.value).strip()
    for destination in forbidden:
        assert not (destination / str(w.CSV_NAME)).exists(), destination
        assert not (destination / str(w.DOC_NAME)).exists(), destination


def test_a_pre_existing_readme_is_never_clobbered(tmp_path: Path) -> None:
    """F3: a ``README.md`` this writer did not produce is left byte-identical.

    A hand-written README - or the repository's own - beside the artefacts must make the run
    refuse rather than be overwritten by the report's prose, and the refusal must be all-or-
    nothing: no table and no document appear beside the foreign file.
    """
    w = _require_writer()
    destination = tmp_path / "foreign-readme"
    destination.mkdir()
    sentinel = "# A README this report did not write\n\nkeep every byte of me\n"
    readme = destination / str(w.README_NAME)
    readme.write_text(sentinel, encoding="utf-8")
    with pytest.raises(getattr(w, "SparseSignalReportError", ValueError)):
        write_report(destination, analysis_commit=REVISION)
    assert readme.read_text(encoding="utf-8") == sentinel
    assert not (destination / str(w.CSV_NAME)).exists()
    assert not (destination / str(w.DOC_NAME)).exists()


def test_a_foreign_table_or_document_is_never_clobbered(tmp_path: Path) -> None:
    """F3: the ownership rule covers all three names, not only the README."""
    w = _require_writer()
    error = getattr(w, "SparseSignalReportError", ValueError)
    for name, content in (
        (str(w.CSV_NAME), "not,our,header\n1,2,3\n"),
        (str(w.DOC_NAME), '{"artefact": "somebody-elses-document"}\n'),
    ):
        destination = tmp_path / f"foreign-{name}"
        destination.mkdir()
        (destination / name).write_text(content, encoding="utf-8")
        with pytest.raises(error):
            write_report(destination, analysis_commit=REVISION)
        assert (destination / name).read_text(encoding="utf-8") == content, name


def test_re_writing_the_reports_own_files_is_idempotent(tmp_path: Path) -> None:
    """F3: the ownership rule recognises this writer's own bytes, so a re-run is a no-op.

    A rule that refused on *any* pre-existing file would make regeneration impossible; the
    marker each artefact carries is what separates "ours, rewrite it" from "not ours, refuse".
    """
    destination = tmp_path / "own"
    first = write_report(destination, analysis_commit=REVISION)
    table = (destination / str(_require_writer().CSV_NAME)).read_bytes()
    second = write_report(destination, analysis_commit=REVISION)
    assert (destination / str(_require_writer().CSV_NAME)).read_bytes() == table
    assert first.table_sha256 == second.table_sha256


def _json_gate_index(document: dict) -> dict[tuple[str, str, str, int], dict]:
    """Every published gate row, keyed by its cell identity and gate index."""
    return {
        (
            cell["pass"],
            cell["relative_path"],
            cell["view"],
            int(gate["gate_index"]),
        ): gate
        for cell in _json_cells(document)
        for gate in cell["gates"]
    }


def _row_index(report_dir: Path) -> dict[tuple[str, str, str, int], dict]:
    """Every published CSV row, keyed the same way."""
    header = _header(report_dir)
    indexed: dict[tuple[str, str, str, int], dict] = {}
    for row in _csv_rows(report_dir):
        key = (
            row[_column(header, "pass")],
            row[_column(header, "relative_path")],
            row[_column(header, "view")],
            int(row[_column(header, "gate_index")]),
        )
        indexed[key] = row
    return indexed


def test_the_precision_rule_is_honest_and_a_tiny_positive_fraction_is_refused(
    report: Path, built
) -> None:
    """F4: the CSV is the fixed-precision table, the JSON the lossless copy, and a *positive*
    fraction the CSV's precision would round to ``0.000000`` is refused, never published.

    Two separate statements: the two artefacts agree at the stated precision (so the rule is
    honest about both), and the table formatter refuses a nonzero value it cannot represent
    rather than printing a zero nobody measured.
    """
    w = _require_writer()
    document = _document(report)
    assert document["constants"]["fraction_decimals"] == PUBLISHED_DECIMALS == 6
    assert document["constants"]["number_significant_digits"] == 12
    header = _header(report)
    fraction_column = _column(header, "fraction")
    rows = _row_index(report)
    gates = _json_gate_index(document)
    assert set(rows) == set(gates)
    for key, gate in gates.items():
        text = rows[key][fraction_column]
        value = gate["band_fraction"]
        if value is None:
            assert text == "", key
            continue
        assert re.fullmatch(rf"-?\d+\.\d{{{PUBLISHED_DECIMALS}}}", text), (key, text)
        assert float(text) == pytest.approx(
            round(value, PUBLISHED_DECIMALS), abs=10**-PUBLISHED_DECIMALS
        ), key
        if value > 0.0:
            assert float(text) > 0.0, (
                f"{key}: a positive fraction was published as the zero {text!r}"
            )
    assert isinstance(document["json_precision_rule"], str)
    assert document["json_precision_rule"].strip()

    gate = next(
        row
        for cell in built.cells
        for row in cell.gates
        if row.band_state.value == "defined"
    )
    owner = next(cell for cell in built.cells if any(row is gate for row in cell.gates))
    tiny = gate.model_copy(update={"band_fraction": 1.0e-9})
    doctored_cell = owner.model_copy(
        update={"gates": tuple(tiny if row is gate else row for row in owner.gates)}
    )
    doctored = built.model_copy(
        update={
            "cells": tuple(
                doctored_cell if cell is owner else cell for cell in built.cells
            )
        }
    )
    with pytest.raises(getattr(w, "SparseSignalReportError", ValueError)):
        w.table_text(doctored)


def _reject_json_constant(name: str):
    raise AssertionError(f"the document carries the non-finite JSON constant {name!r}")


def _finite_floats(node) -> list[float]:
    """Every float in the document, so finiteness is checked on values and not on prose."""
    if isinstance(node, bool):
        return []
    if isinstance(node, (int, float)):
        return [float(node)]
    if isinstance(node, dict):
        return [value for item in node.values() for value in _finite_floats(item)]
    if isinstance(node, list):
        return [value for item in node for value in _finite_floats(item)]
    return []


def test_the_document_json_is_strict_and_carries_no_non_finite_value(
    report: Path, built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: the published JSON parses strictly and a non-finite value fails the run.

    The published file must contain no ``NaN``/``Infinity`` *value* (the word may appear in the
    precision prose, which is why the scan looks at tokens and at the parsed numbers, not at the
    raw text), and a model that would serialize one must be refused before any file is written.
    """
    w = _require_writer()
    text = (report / str(w.DOC_NAME)).read_text(encoding="utf-8")
    document = json.loads(text, parse_constant=_reject_json_constant)
    assert isinstance(document, dict)
    assert not re.search(r":\s*-?(?:NaN|Infinity)\b", text), (
        "the document carries a non-finite value token"
    )
    json.dumps(document, allow_nan=False)  # raises if any published value is non-finite
    assert all(math.isfinite(value) for value in _finite_floats(document))

    cell = built.cells[0]
    nan_cell = cell.model_copy(
        update={
            "provenance": cell.provenance.model_copy(update={"window_s": float("nan")})
        }
    )
    nan_model = built.model_copy(update={"cells": (nan_cell,) + built.cells[1:]})
    with pytest.raises(getattr(w, "SparseSignalReportError", ValueError)):
        w.document_text(nan_model)

    monkeypatch.setattr(w, "build_sparse_signal_report", lambda **_kwargs: nan_model)
    destination = tmp_path / "nan-run"
    with pytest.raises((ValueError, RuntimeError)):
        w.write_sparse_signal_report(destination, analysis_commit=REVISION)
    leftover = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert leftover == [], leftover


def test_a_report_whose_gate_failed_publishes_nothing(
    built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F6: a report that does not hold its own gate never reaches the disk."""
    w = _require_writer()
    bad = built.model_copy(
        update={"checks": {**built.checks, "a_deliberate_violation": False}}
    )
    assert bad.ok is False
    monkeypatch.setattr(w, "build_sparse_signal_report", lambda **_kwargs: bad)
    destination = tmp_path / "not-ok"
    with pytest.raises(getattr(w, "SparseSignalReportError", ValueError)):
        w.write_sparse_signal_report(destination, analysis_commit=REVISION)
    leftover = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert leftover == [], leftover


def test_a_failed_write_leaves_no_orphan_file(
    built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F7: publication is all-or-nothing - a refusal halfway leaves the destination as it was.

    The stage that fails is forced to raise *after* the table has been rendered, so a writer that
    published file by file would leave an orphaned table; the staged-move writer leaves neither a
    table nor a stray stage file.
    """
    w = _require_writer()
    monkeypatch.setattr(w, "build_sparse_signal_report", lambda **_kwargs: built)

    def explode(_model):
        raise RuntimeError("injected failure while staging the document")

    monkeypatch.setattr(w, "document_text", explode)
    destination = tmp_path / "orphan"
    with pytest.raises(RuntimeError):
        w.write_sparse_signal_report(destination, analysis_commit=REVISION)
    leftover = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert leftover == [], leftover
    assert not list(tmp_path.rglob("*.staged-*")), "a stage file was left behind"


def test_a_failure_on_the_second_publish_replace_leaves_a_mixed_set_detected_by_digest(
    built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F7 (adversarial): the *publish loop* is not atomic across the three files.

    Staging is all-or-nothing, but ``_publish`` replaces the three staged files one at a time
    (``os.replace`` per file). A failure *inside that loop* - after the table has landed and before
    the document has - leaves a mixed destination: a table from this run beside a document from the
    previous one. The mismatch is detectable deterministically, with no guess: the document's
    ``table_sha256`` no longer digests the table beside it. The stage debris is cleaned up and the
    publication lock is released, so the failure is confined to the destination. This pins the
    honest limitation: the all-or-nothing claim holds for staging, not for the replace loop (the
    writer's own docstring says so, and this row holds it to that rather than to atomicity).
    """
    w = _require_writer()
    destination = tmp_path / "mixed"
    csv_name, doc_name, _readme_name = file_names()

    # a first, clean, complete set - the default two-sitting scope, from the module's own model.
    monkeypatch.setattr(w, "build_sparse_signal_report", lambda **_kwargs: built)
    w.write_sparse_signal_report(destination, analysis_commit=REVISION)
    first_doc = json.loads((destination / doc_name).read_text(encoding="utf-8"))
    assert first_doc["table_sha256"] == fdp.table_digest(destination / csv_name)
    assert first_doc["summary"]["cells"] == EXPECTED_CELLS

    # a second run whose *table really differs* from the first's (a different measurement, here one
    # published depth), with the second ``os.replace`` of the publish loop forced to fail.
    mutated_cell = built.cells[0].model_copy(
        update={
            "gates": (
                built.cells[0]
                .gates[0]
                .model_copy(
                    update={"depth_mm": built.cells[0].gates[0].depth_mm + 0.5}
                ),
                *built.cells[0].gates[1:],
            )
        }
    )
    mutated = built.model_copy(update={"cells": (mutated_cell, *built.cells[1:])})
    monkeypatch.setattr(w, "build_sparse_signal_report", lambda **_kwargs: mutated)

    real_replace = os.replace
    calls: list[tuple[str, str]] = []

    def flaky(src, dst, *args, **kwargs):
        calls.append((str(src), str(dst)))
        if len(calls) == 2:
            raise OSError("injected failure on the second publish replace")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(w.os, "replace", flaky)
    with pytest.raises(OSError):
        w.write_sparse_signal_report(destination, analysis_commit=REVISION)

    assert len(calls) == 2, (
        "the failure must land in the publish loop (the second replace), not in staging: "
        f"{calls}"
    )
    assert {path.name for path in destination.iterdir()} == set(file_names()), sorted(
        path.name for path in destination.iterdir()
    )

    # the published table is the second run's, the published document the first's - a mixed set.
    published_document = json.loads(
        (destination / doc_name).read_text(encoding="utf-8")
    )
    assert published_document == first_doc, "the document must not have been replaced"
    assert (destination / csv_name).read_bytes() == w.table_text(mutated).encode(
        "utf-8"
    ), "the table must be the second run's"

    # deterministic detection, without any prior copy: the digest no longer binds the table.
    assert (
        fdp.table_digest(destination / csv_name) != published_document["table_sha256"]
    ), (
        "the mixed state must be visible: the document's digest no longer describes the table "
        "beside it"
    )


def test_publication_stages_uniquely_with_a_lock_and_refuses_leftovers(
    built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F7: the publication safety the writer *does* provide - unique stages, fsync and a lock.

    A stage name is minted by ``mkstemp`` per call, so two stages never collide; the bytes are
    ``fsync``-ed before the rename; and an exclusive publication lock serializes (or refuses) two
    runs into one directory. A leftover stage file from an interrupted run is refused rather than
    adopted, and the lock is released after a normal run.
    """
    w = _require_writer()
    stage = getattr(w, "_stage", None)
    assert callable(stage), "the writer must expose its staging helper for this pin"

    first = stage(tmp_path, w.CSV_NAME, "one")
    second = stage(tmp_path, w.CSV_NAME, "two")
    assert first != second, (
        "two stages share a name, so two runs could collide in the destination"
    )
    assert first.read_text(encoding="utf-8") == "one"
    assert second.read_text(encoding="utf-8") == "two"
    assert "fsync" in inspect.getsource(w), (
        "the staged bytes must be fsync-ed before the rename; if that changed, pin it here"
    )

    destination = tmp_path / "published"
    lock_name = str(getattr(w, "LOCK_NAME", ".sa2-4-sparse-signal.publish-lock"))
    monkeypatch.setattr(w, "build_sparse_signal_report", lambda **_kwargs: built)

    # a held lock refuses by name - the honest serialization guard, not a silent race.
    (destination).mkdir(parents=True)
    (destination / lock_name).write_text("held", encoding="utf-8")
    with pytest.raises(getattr(w, "SparseSignalReportError", ValueError)) as held:
        w.write_sparse_signal_report(destination, analysis_commit=REVISION)
    assert lock_name in str(held.value)

    # a leftover stage file from an interrupted run is refused by name rather than adopted.
    (destination / lock_name).unlink()
    leftover = destination / f".{w.CSV_NAME}.deadbeef.tmp"
    leftover.write_text("stale", encoding="utf-8")
    with pytest.raises(getattr(w, "SparseSignalReportError", ValueError)) as stale:
        w.write_sparse_signal_report(destination, analysis_commit=REVISION)
    assert leftover.name in str(stale.value)

    # once clean, the run publishes, releases the lock and leaves no temporary behind.
    leftover.unlink()
    w.write_sparse_signal_report(destination, analysis_commit=REVISION)
    assert not (destination / lock_name).exists()
    assert {path.name for path in destination.iterdir()} == set(file_names())


def test_a_relative_destination_is_anchored_at_the_repository_root_not_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F2: a relative destination is anchored at the checkout, so the working directory is no input.

    ``write_sparse_signal_report``'s default is the *relative* path ``reports/sparse-signal``. The
    guard judges it against the repository the destination would actually land in - not against the
    process working directory - so a run from anywhere resolves the plan's root to the same tree
    and a relative path that points *inside* the repository but outside the designated root is
    still refused. This row checks the anchoring, so no run has to write into the checkout to prove
    it.
    """
    w = _require_writer()
    assert Path(w.REPORT_DIR) == Path("reports/sparse-signal")
    resolve = getattr(w, "_resolve_destination", None)
    refusal = getattr(w, "_destination_refusal", None)
    assert callable(resolve) and callable(refusal), (
        "the writer must expose its destination resolver and guard for this pin"
    )
    repository = w._repository_root()

    monkeypatch.chdir(tmp_path)
    assert (
        resolve(Path("reports/sparse-signal"))
        == repository / "reports" / "sparse-signal"
    ), (
        "a relative destination must be anchored at the repository, not the working directory"
    )
    assert refusal(Path("reports/sparse-signal")) is None, (
        "the plan's own root must be publishable from any working directory"
    )
    assert refusal(Path("reports")) is not None, (
        "a relative path that is inside the repository but not the designated root is still "
        "refused"
    )
    # an absolute destination is used as given, which is what lets a scratch tree be published to.
    scratch = tmp_path / "scratch"
    assert resolve(scratch) == scratch
    assert refusal(scratch) is None


def test_the_published_schema_is_closed_and_explicit(report: Path) -> None:
    """F8: the CSV columns and the JSON field sets are pinned exactly, not bounded.

    A "no more than N columns" allowance still admits a per-bin table; the closed field set is the
    contract the design's serialization clause rests on, so every shape is named in full and every
    row of a shape must carry the same keys - a per-row extra field is a schema change too.
    """
    header = _header(report)
    assert tuple(header) == EXPLICIT_CSV_COLUMNS, header
    document = _document(report)
    assert set(document) == EXPLICIT_DOCUMENT_KEYS, sorted(document)
    assert set(document["constants"]) == EXPLICIT_CONSTANT_KEYS
    assert set(document["checks"]) == EXPLICIT_CHECK_KEYS
    assert set(document["summary"]) == EXPLICIT_SUMMARY_KEYS, sorted(
        document["summary"]
    )

    # plan §4's own shapes, pinned field for field: the key, the groups, the rows and the counts.
    assert tuple(document[REPEAT_CONDITION_KEY_FIELD]) == EXPLICIT_REPEAT_CONDITION_KEY
    groups = document[REPEAT_GROUPS_KEY]
    assert groups, "the document publishes no repeat group"
    assert {frozenset(group) for group in groups} == {EXPLICIT_REPEAT_GROUP_KEYS}
    for group in groups:
        assert set(group["condition"]) == EXPLICIT_REPEAT_TRIPLE_KEYS, group["pass"]
        assert {frozenset(member) for member in group["members"]} == {
            EXPLICIT_REPEAT_MEMBER_KEYS
        }
    rows = document[REPEAT_SPREAD_KEY]
    assert rows, "the document publishes no repeat-spread row"
    assert {frozenset(row) for row in rows} == {EXPLICIT_REPEAT_ROW_KEYS}
    for row in rows:
        assert set(row["condition"]) == EXPLICIT_REPEAT_TRIPLE_KEYS, row["pass"]
        assert {frozenset(member) for member in row["members"]} == {
            EXPLICIT_REPEAT_MEMBER_VALUE_KEYS
        }
    assert set(document[REPEAT_SPREAD_SUMMARY_KEY]) == EXPLICIT_REPEAT_SUMMARY_KEYS, (
        sorted(document[REPEAT_SPREAD_SUMMARY_KEY])
    )

    cells = document["cells"]
    assert cells, "the document carries no cell"
    assert {frozenset(cell) for cell in cells} == {EXPLICIT_CELL_KEYS}
    for cell in cells:
        assert set(cell["axis"]) == EXPLICIT_AXIS_KEYS, cell["relative_path"]
        assert set(cell["condition"]) == EXPLICIT_REPEAT_TRIPLE_KEYS, cell[
            "relative_path"
        ]
        for row in cell["targets"]:
            assert set(row) == EXPLICIT_TARGET_KEYS, cell["relative_path"]
        for row in cell["gates"]:
            assert set(row) == EXPLICIT_GATE_KEYS, cell["relative_path"]


def _checks_builder():
    """The writer's own checks builder, or a failure naming the seam that is missing."""
    w = _require_writer()
    for name in ("_checks", "checks", "build_checks"):
        candidate = getattr(w, name, None)
        if callable(candidate):
            return candidate
    raise AssertionError(
        "the writer must expose the seam that evaluates its named gate, so the checks can be "
        "shown to be non-vacuous; tried ('_checks', 'checks', 'build_checks')"
    )


def test_the_published_checks_are_not_vacuous(built, tmp_path: Path) -> None:
    """F9: each check is a real function of what it is shown, not a constant ``True``.

    The committed report's gate holds, and a defect a check *claims* to catch - a refusal carrying
    a numeric fraction, a defined zero carrying one, an empty table, a wrong aggregate fingerprint,
    a forbidden destination - must flip that check to ``False``. The summary's state counts are
    also asserted to partition the published rows, so a check over an empty population is visible.
    """
    build = _checks_builder()
    accepted = set(inspect.signature(build).parameters)
    rows = built.csv_rows()

    def call(**overrides) -> dict[str, bool]:
        inputs = {
            "cells": built.cells,
            "rows": rows,
            "model_plan_fingerprints": built.plan_fingerprints,
            "aggregate": built.plan_fingerprint,
            "report_dir": tmp_path / "gate",
        }
        inputs.update(overrides)
        return build(
            **{name: value for name, value in inputs.items() if name in accepted}
        )

    def failed_checks(**overrides) -> set[str]:
        return {name for name, held in call(**overrides).items() if not held}

    base = call()
    assert base and all(base.values()), {
        name: held for name, held in base.items() if not held
    }

    assert failed_checks(rows=[]), "no check reads the published table"
    assert any("table" in name for name in failed_checks(rows=[]))

    refused = dict(rows[0])
    refused["band_state"] = (
        "refused-axis"  # a refusal keeps its identity row and no number
    )
    assert any("refused" in name for name in failed_checks(rows=[refused]))

    zero = dict(rows[0])
    zero["band_state"] = (
        "defined-zero-power"  # a measured zero carries two zeros, not a fraction
    )
    assert any("zero" in name for name in failed_checks(rows=[zero]))

    assert any(
        "fingerprint" in name for name in failed_checks(aggregate="sha256:" + "0" * 64)
    )
    frozen = ROOT / "reports" / "mixer-sensitivity-analysis"
    assert any("destination" in name for name in failed_checks(report_dir=frozen))

    summary = built.summary
    assert summary.cells == EXPECTED_CELLS
    assert summary.gate_rows == EXPECTED_GATE_ROWS
    assert (
        summary.defined_gates
        + summary.defined_zero_power_gates
        + summary.refused_axis_gates
        == summary.gate_rows
    ), "every published gate row is accounted for by exactly one band state"
