"""Focused tests for the velocity-only TGC and emitting-power screening (plan ``WP2``).

``analysis.gain_power_screen``, its CLI verb and its four reviewer-visible artefacts did not exist,
so this module failed at import. The tests pin what the screen must not drift on: both axes are the
``tgc`` and ``em_pow`` rows of ``manifest.csv``, never a filename list; each axis keeps its own
common-duration window, common support and clean-OFAT audit; the TGC axis is screened through the
*committed representation* (op word 23 = 0 / ``uniform``, word 25 = 255 / 40 dB, only word 24 moves)
and refused when it moves; the power axis holds that representation fixed; every within-axis pair is
compared to the committed WP1 screening_threshold with the depth ranges where it clears; and the findings state
what velocity-only data cannot say — no echo SNR, no receiver saturation, no safe plateau, no
acoustic energy, and a sensitivity axis that is absent from the sweep.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest

from udv_echo_process.analysis.gain_power_screen import (
    AXES,
    DATASET_ROOT,
    DEPTH_COLUMNS,
    DEPTHS_NAME,
    DROPOUT_GATE_LIMIT,
    FLAGGED_CELLS,
    INPUT_CELLS,
    LEVEL_COLUMNS,
    LEVELS_NAME,
    PAIR_COLUMNS,
    PAIRS_NAME,
    SENSITIVITY_VALUE,
    SPREAD_RATIO_LIMIT,
    TGC_END_DB,
    TGC_MODE_LABEL,
    TGC_WORDS,
    GainPowerScreenError,
    build_gain_power_screen,
    manifest_cell_values,
    require_tgc_representation,
    select_level_rows,
)

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports" / "mixer-sensitivity-analysis"
DATA_ROOT = ROOT / DATASET_ROOT
MANIFEST = REPORT_DIR / "manifest.csv"
ENVELOPE = REPORT_DIR / "reference-repeat.provenance.json"
RELATIVE_MANIFEST = Path("reports/mixer-sensitivity-analysis/manifest.csv")
RELATIVE_ENVELOPE = Path("reports/mixer-sensitivity-analysis/reference-repeat.provenance.json")
COMMIT = "0123456789abcdef0123456789abcdef01234567"  # test-local, never the checkout

TGC_PATHS = tuple(f"tgc/{label}.BDD" for label in ("0", "5", "10", "15", "25", "30", "35", "40"))
#: The two recordings that carry one decoded fingerprint whatever folder they sit in (plan §8.2 R1).
ANCHOR_PATHS = ("prf/600.BDD", "res/1-8.BDD")
#: Every recording the TGC ladder screens: the eight ``tgc`` rows plus the shared anchor level's
#: two recordings, which no ``tgc`` row requests (plan §8.3 step 5).
TGC_INPUTS = ("tgc/0.BDD", "tgc/5.BDD", "tgc/10.BDD", "tgc/15.BDD",
              *ANCHOR_PATHS, "tgc/25.BDD", "tgc/30.BDD", "tgc/35.BDD", "tgc/40.BDD")
#: The decoded TGC start of every level, in ladder order: the eight requested values with the
#: shared anchor's 19.9216 dB between 15 and 25.
TGC_KEYS = (0.156862745098, 4.86274509804, 9.88235294118, 14.9019607843, 19.9215686275,
            24.9411764706, 29.9607843137, 34.9803921569, 40.0)
POWER_PATHS = ("em_pow/low.BDD", "em_pow/high.BDD")  # declared order, not filename order
#: Every recording the power ladder screens: the two ``em_pow`` rows plus the shared anchor level's
#: two recordings, which realize ``medium`` (plan §8.3 step 5).
POWER_INPUTS = ("em_pow/low.BDD", *ANCHOR_PATHS, "em_pow/high.BDD")
ENVELOPE_MM_S = 19.37008103465545
SUPPORT_MM = (10.162666666666668, 100.81266666666667)
#: The two per-axis common-duration views and the profile count each file contributes to them.
TGC_REVOLUTIONS, TGC_WINDOW_S, TGC_PROFILES = 77, 9.24, 413
POWER_REVOLUTIONS, POWER_WINDOW_S, POWER_PROFILES = 96, 11.52, 515
#: The base state the manifest's other rows carry: a level of each ladder now that both axes
#: screen every eligible level (plan §8.3 step 5).
TGC_BASE_DB, POWER_BASE = 19.9215686275, "medium"
ANCHOR_TGC_PATH, ANCHOR_POWER_PATH = "prf/600.BDD", "prf/600.BDD"
#: The two screened levels, with the numbers the tables carry.
TGC_FLAGGED = ("tgc/0.BDD", "tgc/40.BDD")
TGC_ZERO_FRACTION = {"tgc/0.BDD": 0.243729, "tgc/40.BDD": 0.0387893}
TGC_MAJORITY_BLANK = {"tgc/0.BDD": 10, "tgc/40.BDD": 1}
TGC_BLANK_RANGES = {"tgc/0.BDD": "84.1627..100.813", "tgc/40.BDD": "69.3627..69.3627"}
TGC_SPREAD_RATIO = 4.9697  # tgc/40.BDD's largest per-gate spread / the axis median
WORST_PAIR = ("tgc/30.BDD", "tgc/40.BDD", 47.1038, 73.0627, 2.4318, "73.0627..74.9127")
#: Each axis's focus pair carries its base state: the TGC anchor level (realized by both reference
#: recordings) against the next setting above it, and ``medium`` against ``high``.
FOCUS_TGC = ("prf/600.BDD", "tgc/25.BDD", 15.3951, 0, 0.79479)
FOCUS_POWER = ("prf/600.BDD", "em_pow/high.BDD", 13.3865, 0, 0.69109)
TGC_PAIRS_ABOVE, TGC_PAIRS = 17, 36
POWER_PAIRS_ABOVE, POWER_PAIRS = 0, 3
SCREENED_LEVELS, SCREENED_RECORDINGS = 12, 14


def _raw_words(path: Path, channel: int = 1) -> np.ndarray:
    """Read one channel's 256 op words from the file's own table, independently of the reader."""
    raw = path.read_bytes()
    offset = 548 + 1024 * (channel - 1)
    return np.frombuffer(raw, dtype="<u4", count=256, offset=offset)


def _rows() -> tuple[list[dict[str, str]], list[str]]:
    """The committed manifest's rows and its column order."""
    reader = csv.DictReader(MANIFEST.read_text(encoding="utf-8").splitlines())
    rows = list(reader)
    return rows, list(reader.fieldnames or ())


def _replace(rows, relative: str, **cells: str):
    """The rows with one relative path's cells replaced."""
    return [{**row, **cells} if row["relative_path"] == relative else row for row in rows]


def _inventory(tmp_path: Path, change, name: str = "inventory.csv") -> Path:
    """A manifest copied into ``tmp_path`` with ``change(rows)`` applied."""
    rows, columns = _rows()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(change(rows))
    path = tmp_path / name
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    return path


def _rebound_screening_threshold(tmp_path: Path, manifest: Path) -> Path:
    """The committed WP1 screening_threshold re-bound to a copied manifest's own hash."""
    document = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    document["manifest"]["sha256"] = f"sha256:{hashlib.sha256(manifest.read_bytes()).hexdigest()}"
    path = tmp_path / "reference-repeat.provenance.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def screen():
    return build_gain_power_screen(DATASET_ROOT, RELATIVE_MANIFEST, RELATIVE_ENVELOPE,
                                   analysis_commit=COMMIT)


@pytest.fixture(scope="module")
def axis_rows(screen):
    return {axis.axis: axis for axis in screen.axes}


@pytest.fixture(scope="module")
def findings(screen):
    from udv_echo_process.analysis.gain_power_screen import provenance_document

    return provenance_document(screen)["findings"]


@pytest.fixture(scope="module")
def artefact_dir(tmp_path_factory):
    from udv_echo_process.analysis.gain_power_screen import write_gain_power_screen

    directory = tmp_path_factory.mktemp("gain-power-screen")
    write_gain_power_screen(DATASET_ROOT, directory, manifest_path=RELATIVE_MANIFEST,
                            screening_threshold_path=RELATIVE_ENVELOPE, analysis_commit=COMMIT)
    return directory


# --------------------------------------------------------------------------- module surface


def test_the_screen_declares_both_axes_and_their_artefacts() -> None:
    from udv_echo_process.analysis import gain_power_screen as module

    assert AXES == ("tgc", "em_pow")
    assert (module.LEVELS_NAME, module.PAIRS_NAME, module.DEPTHS_NAME) == (
        LEVELS_NAME, PAIRS_NAME, DEPTHS_NAME)
    assert module.PROVENANCE_NAME == "gain-power-screen.provenance.json"
    assert module.FIGURE_NAME == "gain-power-screen.png"
    assert len(LEVEL_COLUMNS) == len(set(LEVEL_COLUMNS)) == 38
    assert len(PAIR_COLUMNS) == len(set(PAIR_COLUMNS)) == 21
    assert len(DEPTH_COLUMNS) == len(set(DEPTH_COLUMNS)) == 15
    assert set(INPUT_CELLS) <= set(LEVEL_COLUMNS)
    assert set(FLAGGED_CELLS) <= set(LEVEL_COLUMNS)
    assert (DROPOUT_GATE_LIMIT, SPREAD_RATIO_LIMIT, TGC_END_DB) == (0.5, 3.0, 40.0)
    assert TGC_WORDS == {"mode": 23, "start": 24, "end": 25}
    assert module.MANIFEST_NAME == "manifest.csv"


# --------------------------------------------------------------------------- axis selection


def test_each_axis_is_selected_from_the_manifest_never_a_filename_list(tmp_path) -> None:
    rows = {axis: select_level_rows(RELATIVE_MANIFEST, axis) for axis in AXES}
    assert tuple(row["relative_path"] for row in rows["tgc"]) == TGC_PATHS
    # ``select_level_rows`` is the axis's own request; the ladder itself holds every eligible
    # level (plan §8.3 step 5).
    assert tuple(float(row["tgc_start_db"]) for row in rows["tgc"]) == (
        TGC_KEYS[:4] + TGC_KEYS[5:])
    assert tuple(row["relative_path"] for row in rows["em_pow"]) == POWER_PATHS
    assert tuple(row["emit_power"] for row in rows["em_pow"]) == ("low", "high")
    assert {row["axis"] for row in rows["tgc"]} == {"tgc"}
    assert {row["axis"] for row in rows["em_pow"]} == {"em_pow"}

    without = _inventory(tmp_path, lambda body: [
        row for row in body if row["axis"] != "tgc"])
    with pytest.raises(GainPowerScreenError, match="tgc"):
        select_level_rows(without, "tgc")
    undecoded = _inventory(tmp_path, lambda body: _replace(body, TGC_PATHS[0], decode_error="boom"))
    with pytest.raises(GainPowerScreenError, match="decode_error"):
        select_level_rows(undecoded, "tgc")
    doubled = _inventory(tmp_path, lambda body: [
        *body, next(row for row in body if row["relative_path"] == TGC_PATHS[0])])
    with pytest.raises(GainPowerScreenError, match="exactly one row for"):
        select_level_rows(doubled, "tgc")
    for cell, value in (("tgc_start_db", ""), ("tgc_start_db", "NaN")):
        broken = _inventory(
            tmp_path, lambda body, c=cell, v=value: _replace(body, TGC_PATHS[1], **{c: v}))
        with pytest.raises(GainPowerScreenError, match="empty|finite|decoded"):
            select_level_rows(broken, "tgc")

    with pytest.raises(GainPowerScreenError, match="not one of the screened axes"):
        select_level_rows(RELATIVE_MANIFEST, "res")
    with pytest.raises(GainPowerScreenError, match="cannot read the manifest"):
        select_level_rows(REPORT_DIR / "absent.csv", "tgc")
    # A decode refusal is per row: the other axis keeps selecting.
    hurts_power = _inventory(
        tmp_path, lambda body: _replace(body, POWER_PATHS[0], decode_error="boom"),
        name="power-decoded.csv")
    with pytest.raises(GainPowerScreenError, match="decode_error"):
        select_level_rows(hurts_power, "em_pow")
    assert len(select_level_rows(hurts_power, "tgc")) == len(TGC_PATHS)


def test_an_unknown_power_label_is_refused_rather_than_ordered() -> None:
    import io

    from udv_echo_process.analysis import gain_power_screen as module

    text = MANIFEST.read_text(encoding="utf-8")
    rows = list(csv.DictReader(text.splitlines()))
    columns = list(rows[0])
    for row in rows:
        if row["axis"] == "em_pow":
            row["emit_power"] = "turbo"
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    bad = REPORT_DIR / "tmp-power-labels.csv"
    bad.write_text(buffer.getvalue(), encoding="utf-8", newline="")
    try:
        with pytest.raises(GainPowerScreenError, match="instrument's own"):
            select_level_rows(bad, "em_pow")
    finally:
        bad.unlink()
    assert module.POWER_ORDER == ("low", "medium", "high")


# --------------------------------------------------------------------------- refusals


def test_build_refuses_a_stale_hash_a_stale_cell_and_an_unbound_screening_threshold(tmp_path) -> None:
    wrong = _inventory(tmp_path, lambda body: _replace(body, "tgc/0.BDD", source_sha256="0" * 64))
    with pytest.raises(GainPowerScreenError, match="sha256 mismatch"):
        build_gain_power_screen(DATA_ROOT, wrong, _rebound_screening_threshold(tmp_path, wrong),
                                analysis_commit=COMMIT)

    # A cell the screen is keyed by or holds fixed must not be stale against the decoder.
    for changed, reason in (
        ({"tgc_start_db": "9.8823529412"}, "does not match the decoded"),
        ({"tgc_end_db": "39.9"}, "does not match the decoded"),
        ({"gates": "49"}, "does not match the decoded"),
    ):
        stale = _inventory(
            tmp_path,
            lambda body, c=changed: _replace(body, "tgc/10.BDD", **c), name="cell.csv")
        with pytest.raises(GainPowerScreenError, match=reason):
            build_gain_power_screen(DATA_ROOT, stale, _rebound_screening_threshold(tmp_path, stale),
                                    analysis_commit=COMMIT)

    with pytest.raises(GainPowerScreenError, match="cannot read the WP1 screening_threshold"):
        build_gain_power_screen(DATA_ROOT, RELATIVE_MANIFEST, tmp_path / "absent.json",
                                analysis_commit=COMMIT)
    # The committed screening_threshold records the committed manifest's hash: another inventory may not
    # borrow its threshold.
    changed = _inventory(tmp_path, lambda body: _replace(body, "tgc/10.BDD", gates="49"),
                         name="other.csv")
    with pytest.raises(GainPowerScreenError, match="records manifest"):
        build_gain_power_screen(DATA_ROOT, changed, RELATIVE_ENVELOPE, analysis_commit=COMMIT)
    moved = _inventory(tmp_path, lambda body: _replace(body, "em_pow/high.BDD", sensitivity="high"),
                       name="moved.csv")
    # Every cell the screen holds fixed is re-checked against the decode, so a moved sensitivity
    # is refused by the comparison before the sweep-level sensitivity statement could run.
    with pytest.raises(GainPowerScreenError, match="does not match the decoded"):
        build_gain_power_screen(DATA_ROOT, moved, _rebound_screening_threshold(tmp_path, moved),
                                analysis_commit=COMMIT)


def test_each_axis_is_a_clean_ofat_ladder_on_its_own_key(screen) -> None:
    """A coupled setting is refused per axis; the axis's own key is the only thing that moves."""
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis import gain_power_screen as module

    tgc = next(axis for axis in screen.axes if axis.axis == "tgc")
    power = next(axis for axis in screen.axes if axis.axis == "em_pow")
    assert "emit_power" in module.COUPLED_SETTINGS["tgc"]
    assert "tgc_start_db" not in module.COUPLED_SETTINGS["tgc"]
    assert "tgc_start_db" in module.COUPLED_SETTINGS["em_pow"]
    assert "emit_power" not in module.COUPLED_SETTINGS["em_pow"]
    for axis in (tgc, power):
        grid.require_clean_ofat(list(axis.inputs), module.COUPLED_SETTINGS[axis.axis],
                                axis_label=f"{axis.axis}-only")
    assert len({entry.sensitivity for entry in [*tgc.inputs, *power.inputs]}) == 1
    coupled = [*tgc.inputs]
    coupled[-1] = coupled[-1].model_copy(update={"burst_length": 12})
    with pytest.raises(GainPowerScreenError, match="also differ"):
        grid.require_clean_ofat(coupled, module.COUPLED_SETTINGS["tgc"], axis_label="tgc-only")
    borrowed = [*tgc.inputs]
    borrowed[-1] = borrowed[-1].model_copy(update={"tgc_start_db": 4.0})
    with pytest.raises(GainPowerScreenError, match="also differ"):
        grid.require_clean_ofat(borrowed, module.COUPLED_SETTINGS["em_pow"],
                                axis_label="em_pow-only")


# --------------------------------------------------------------------------- TGC representation


def test_the_tgc_axis_keeps_its_committed_representation_and_refuses_a_moved_word() -> None:
    words = {path: _raw_words(DATA_ROOT / path) for path in TGC_PATHS + POWER_PATHS}
    assert {int(word[TGC_WORDS["mode"]]) for word in words.values()} == {0}       # word 23
    assert {int(word[TGC_WORDS["end"]]) for word in words.values()} == {255}      # word 25
    moved = [int(word[TGC_WORDS["start"]]) for word in words.values()]            # word 24
    assert len(set(moved[: len(TGC_PATHS)])) == len(TGC_PATHS)   # one value per TGC level
    assert len(set(moved[len(TGC_PATHS):])) == 1                 # both power levels hold one value
    assert TGC_MODE_LABEL == "uniform"

    require_tgc_representation("uniform", TGC_END_DB, where="tgc/0.BDD")
    with pytest.raises(GainPowerScreenError, match="op word 23"):
        require_tgc_representation("slope", TGC_END_DB, where="tgc/0.BDD")
    with pytest.raises(GainPowerScreenError, match="op word 25"):
        require_tgc_representation("uniform", 39.0, where="tgc/0.BDD")
    with pytest.raises(GainPowerScreenError, match="op word 25"):
        require_tgc_representation("uniform", None, where="tgc/0.BDD")


def test_every_screened_level_carries_the_uniform_mode_and_the_fixed_end(screen) -> None:
    for axis in screen.axes:
        for row in axis.levels:
            assert row["tgc_mode"] == TGC_MODE_LABEL
            assert row["tgc_end_db"] == TGC_END_DB


def test_the_power_axis_holds_the_tgc_cells_and_only_its_own_key_moves(axis_rows) -> None:
    power = axis_rows["em_pow"]
    assert [row["emit_power"] for row in power.levels] == ["low", "medium", "high"]
    for cell in ("tgc_start_db", "tgc_end_db", "tgc_mode", "sensitivity", "resolution_mm",
                 "prf_period_us", "burst_length", "emissions_per_profile", "gates"):
        assert len({row[cell] for row in power.levels}) == 1, cell
    assert {row["tgc_start_db"] for row in power.levels} == {19.92156862745098}
    # The medium level's primary is the reference recording that realizes it, so its label is
    # that recording's own request rather than one of this axis's.
    assert [row["requested_label"] for row in power.levels] == ["low", "600", "high"]
    assert [row["key_value"] for row in power.levels] == ["low", "medium", "high"]


# --------------------------------------------------------------------------- common views


def test_the_two_axes_keep_their_own_common_window_and_support(axis_rows) -> None:
    tgc, power = axis_rows["tgc"], axis_rows["em_pow"]
    assert (tgc.common["revolutions"], tgc.common["window_s"]) == (TGC_REVOLUTIONS, TGC_WINDOW_S)
    assert (power.common["revolutions"], power.common["window_s"]) == (
        POWER_REVOLUTIONS, POWER_WINDOW_S)
    for axis, profiles in ((tgc, TGC_PROFILES), (power, POWER_PROFILES)):
        assert {row["profiles_window"] for row in axis.levels} == {profiles}
        assert {row["gates_in_support"] for row in axis.levels} == {50}
        assert (axis.common["support_min_mm"], axis.common["support_max_mm"]) == SUPPORT_MM
        assert axis.common["contains_plan_window"] is True
        assert len(axis.depths) == 50 * len(axis.levels)
    assert tgc.common["levels"] == 9 and power.common["levels"] == 3


# --------------------------------------------------------------------------- levels and depths


def test_the_level_rows_report_dropout_bias_and_spread_with_their_screening(axis_rows) -> None:
    tgc = axis_rows["tgc"]
    flagged = [row["relative_path"] for row in tgc.levels if row["screen"] != "usable"]
    assert tuple(flagged) == TGC_FLAGGED
    by_path = {row["relative_path"]: row for row in tgc.levels}
    for path, zero in TGC_ZERO_FRACTION.items():
        assert by_path[path]["zero_fraction"] == pytest.approx(zero, rel=1e-4)
        assert by_path[path]["majority_blank_gates"] == TGC_MAJORITY_BLANK[path]
        assert by_path[path]["majority_blank_depth_ranges_mm"] == TGC_BLANK_RANGES[path]
    assert by_path["tgc/0.BDD"]["screen"] == "dropout-limited"
    assert by_path["tgc/40.BDD"]["screen"] == "dropout- and spread-limited"
    assert by_path["tgc/40.BDD"]["max_gate_spread_ratio_to_axis_median"] == pytest.approx(
        TGC_SPREAD_RATIO, rel=1e-4)
    assert by_path["tgc/40.BDD"]["max_gate_robust_spread_mm_s"] == pytest.approx(148.1166, rel=1e-4)
    assert by_path["tgc/40.BDD"]["max_gate_robust_spread_depth_mm"] == pytest.approx(73.0627)
    assert by_path["tgc/0.BDD"]["worst_gate_zero_fraction"] == pytest.approx(0.8111, rel=1e-3)
    assert axis_rows["em_pow"].screen["flagged_paths"] == []
    for axis in axis_rows.values():
        for row in axis.levels:
            assert row["dropout_limited"] is (row["screen"] != "usable")
            assert row["robust_spread_mm_s"] >= 0.0 and row["rms_mm_s"] > 0.0


def test_the_depth_rows_carry_dropout_and_spread_at_every_supported_gate(axis_rows) -> None:
    tgc = axis_rows["tgc"]
    rows = [row for row in tgc.depths if row["relative_path"] == "tgc/0.BDD"]
    assert len(rows) == 50 and [row["gate_index"] for row in rows] == list(range(50))
    assert rows[0]["depth_mm"] == SUPPORT_MM[0] and rows[-1]["depth_mm"] == pytest.approx(
        SUPPORT_MM[1])
    inside = [row for row in rows if row["in_plan_window"]]
    assert len(inside) == 46  # the plan's 10.163-96.743 mm window inside this 100.8 mm support
    assert max(row["zero_fraction"] for row in rows) == pytest.approx(0.8111, rel=1e-3)
    assert sum(1 for row in rows if row["majority_blank"]) == TGC_MAJORITY_BLANK["tgc/0.BDD"]
    last = rows[-1]
    assert last["majority_blank"] is True and last["zero_fraction"] > DROPOUT_GATE_LIMIT
    assert all(row["profiles_window"] == TGC_PROFILES for row in rows)
    assert all(row["std_mm_s"] >= 0.0 and row["robust_spread_mm_s"] >= 0.0 for row in rows)


# --------------------------------------------------------------------------- pairs


def test_every_pair_is_compared_to_the_committed_screening_threshold_and_its_depth_ranges(screen) -> None:
    tgc = next(axis for axis in screen.axes if axis.axis == "tgc")
    low_path, high_path, absolute, depth, ratio, ranges = WORST_PAIR
    worst = max(tgc.pairs, key=lambda row: row["max_abs_difference_mm_s"])
    assert (worst["low_path"], worst["high_path"]) == (low_path, high_path)
    assert worst["max_abs_difference_mm_s"] == pytest.approx(absolute, rel=1e-4)
    assert worst["max_abs_difference_depth_mm"] == pytest.approx(depth)
    assert worst["max_abs_difference_over_screening_threshold"] == pytest.approx(ratio, rel=1e-4)
    assert worst["depth_ranges_above_screening_threshold_mm"] == ranges
    assert worst["knots_above_screening_threshold"] == 2 and worst["knots"] == 50
    assert worst["max_knot_offset_mm"] == 0.0  # identical 1.85 mm grids: no resampling anywhere
    clearing = [row for row in tgc.pairs if row["knots_above_screening_threshold"]]
    assert len(clearing) == TGC_PAIRS_ABOVE and len(tgc.pairs) == TGC_PAIRS
    assert all(row["max_abs_difference_over_screening_threshold"] <= ratio for row in tgc.pairs)
    assert all(
        row["mean_abs_difference_mm_s"] <= row["max_abs_difference_mm_s"] for row in tgc.pairs
    )
    assert screen.screening_threshold.value_mm_s == ENVELOPE_MM_S


def test_each_axis_reports_the_pair_that_carries_the_base_state(screen, axis_rows) -> None:
    tgc, power = axis_rows["tgc"], axis_rows["em_pow"]
    for axis, expected in ((tgc, FOCUS_TGC), (power, FOCUS_POWER)):
        focus = next(row for row in axis.pairs if row["focus_pair"])
        low_path, high_path, absolute, knots, ratio = expected
        assert (focus["low_path"], focus["high_path"]) == (low_path, high_path)
        assert focus["max_abs_difference_mm_s"] == pytest.approx(absolute, rel=1e-4)
        assert focus["knots_above_screening_threshold"] == knots
        assert focus["max_abs_difference_over_screening_threshold"] == pytest.approx(ratio, rel=1e-4)
    # The base state is a level of both ladders now (§8.3 step 5): the shared anchor is realized
    # by the two reference recordings, so the focus pair carries it as its lower member.
    assert tgc.base_state["decoded_key"] == "19.9215686275"
    assert tgc.base_state["in_ladder"] is True
    assert tgc.base_state["focus_pair_kind"] == "base_state_is_a_level"
    assert tuple(tgc.base_state["straddling_pair"]) == FOCUS_TGC[:2]
    assert power.base_state["decoded_key"] == POWER_BASE
    assert power.base_state["in_ladder"] is True
    assert power.base_state["focus_pair_kind"] == "base_state_is_a_level"
    assert tuple(power.base_state["straddling_pair"]) == FOCUS_POWER[:2]
    assert [row["focus_pair"] for row in power.pairs] == [False, False, True]


def test_the_key_gap_counts_in_the_axis_own_declared_order(screen) -> None:
    tgc = next(axis for axis in screen.axes if axis.axis == "tgc")
    focus = next(row for row in tgc.pairs if row["focus_pair"])
    # The focus pair carries the shared anchor level (19.9216 dB) and the next setting above it.
    assert focus["key_gap"] == pytest.approx(24.941176470588236 - 19.9215686275)
    power = next(axis for axis in screen.axes if axis.axis == "em_pow")
    assert power.pairs[0]["key_gap"] == 1.0  # low -> medium
    assert power.pairs[-1]["key_gap"] == 1.0  # medium -> high: one step either side of the base


# --------------------------------------------------------------------------- findings


def test_the_screen_says_what_velocity_only_cannot_say(findings, screen) -> None:
    velocity = findings["velocity_only"]
    assert set(velocity["not_inferred"]) == {
        "echo SNR", "receiver saturation", "a safe plateau", "acoustic energy",
        "the gain a TGC or emitting-power setting applied"}
    assert "one axial-velocity channel per file" in velocity["channels"]
    measured = " ".join(velocity["measured"])
    assert "dropout" in measured and "bias" in measured and "spread" in measured
    sensitivity = findings["sensitivity"]
    assert sensitivity["values_in_manifest"] == (SENSITIVITY_VALUE,)
    assert sensitivity["rows_in_manifest"] == 40 and sensitivity["levels_screened"] == SCREENED_LEVELS
    assert sensitivity["axis_present"] is False and sensitivity["identifiable"] is False
    assert screen.sensitivity["values_in_manifest"] == (SENSITIVITY_VALUE,)
    assert manifest_cell_values(RELATIVE_MANIFEST, "sensitivity") == (SENSITIVITY_VALUE,)
    assert manifest_cell_values(RELATIVE_MANIFEST, "tgc_mode") == (TGC_MODE_LABEL,)
    assert manifest_cell_values(RELATIVE_MANIFEST, "tgc_end_db") == ("40",)
    text = " ".join(findings["limitations"]) + " " + velocity["statement"]
    for claim in ("echo SNR", "receiver saturation", "a safe plateau", "acoustic energy",
                  "no p-value is produced"):
        assert claim in text
    # The coverage claim is the count that is true: most levels carry one recording and only the
    # shared anchor level carries two, which is repeat evidence and not replicated axis coverage.
    assert "two realizations" in " ".join(findings["limitations"])
    assert TGC_MODE_LABEL in text and "word 23" in text and "word 25" in text and "word 24" in text


def test_the_diagnostic_verdict_asks_for_one_measurement_not_a_ladder(findings) -> None:
    diagnostic = findings["diagnostic"]
    assert diagnostic["justified"] is True
    assert diagnostic["wider_ladder_justified"] is False
    assert diagnostic["outcome_claimed"] is False
    assert diagnostic["flagged_levels"] == 2
    assert diagnostic["pairs_above_screening_threshold"] == TGC_PAIRS_ABOVE
    assert set(diagnostic["focus_pair_ratios"]) == set(AXES)
    assert "echo/energy" in diagnostic["statement"]
    assert "does not predict that diagnostic's outcome" in diagnostic["statement"]
    summary = findings["screen_summary"]
    assert (summary["levels"], summary["pairs"], summary["levels_flagged"]) == (
        SCREENED_LEVELS, TGC_PAIRS + POWER_PAIRS, 2)
    realizations = summary["realizations"]
    assert realizations["recordings"] == SCREENED_RECORDINGS
    assert realizations["multi_realization_levels"] == [
        {"axis": axis, "relative_path": ANCHOR_PATHS[0], "realization_paths": list(ANCHOR_PATHS)}
        for axis in ("tgc", "em_pow")]
    assert [row["relative_path"] for row in summary["flagged"]] == list(TGC_FLAGGED)
    assert findings["axes"]["tgc"]["effect_gate"]["pairs"] == TGC_PAIRS
    assert findings["axes"]["em_pow"]["effect_gate"]["knots_above_screening_threshold"] == 0


def test_provenance_records_bindings_definitions_views_and_the_caption(screen) -> None:
    from udv_echo_process.analysis.gain_power_screen import provenance_document

    document = provenance_document(screen)
    digest = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert document["artefact"] == "gain-power-screen"
    assert document["analysis_commit"] == COMMIT
    assert document["axes"] == list(AXES)
    assert document["manifest"]["sha256"] == f"sha256:{digest}"
    assert document["screening_threshold"]["value_mm_s"] == ENVELOPE_MM_S
    assert document["sensitivity"]["values_in_manifest"] == (SENSITIVITY_VALUE,)
    assert [block["axis"] for block in document["axis_blocks"]] == list(AXES)
    assert [block["key"]["column"] for block in document["axis_blocks"]] == [
        "tgc_start_db", "emit_power"]
    assert document["axis_blocks"][0]["key"]["values"] == pytest.approx(list(TGC_KEYS))
    assert document["axis_blocks"][0]["audited_constants"]["tgc_mode"] == TGC_MODE_LABEL
    assert document["axis_blocks"][0]["tgc_representation"]["key_cell"] == "tgc_start_db"
    assert document["axis_blocks"][0]["views"]["alignment"]["upsampled"] is False
    assert document["axis_blocks"][0]["views"]["depths"]["rows"] == 50 * 9
    assert set(document["definitions"]) >= {
        "key", "tgc_representation", "difference", "screening_threshold", "velocity_only", "base_state"}
    assert document["tables"]["levels"]["rows"] == SCREENED_LEVELS
    assert document["tables"]["pairs"]["rows"] == TGC_PAIRS + POWER_PAIRS
    assert document["tables"]["depths"]["rows"] == 50 * SCREENED_LEVELS
    assert document["figure"]["path"] == "figures/gain-power-screen.png"
    assert len(document["figure"]["panels"]) == 2
    assert "gain-power-screen --analysis-commit" in document["regeneration"]["command"]
    caption = document["figure"]["caption"]
    for token in (COMMIT, "19.37", "gain-power-screen", TGC_MODE_LABEL, "medium",
                  "op word 23"):
        assert token in caption
    assert document["findings"]["screening_threshold"]["value_mm_s"] == ENVELOPE_MM_S


def test_the_inputs_block_keeps_every_rechecked_cell_and_the_source_hash(screen) -> None:
    from udv_echo_process.analysis.gain_power_screen import provenance_document

    block = provenance_document(screen)["axis_blocks"][0]
    first = block["inputs"][0]
    assert first["relative_path"] == TGC_PATHS[0]
    assert first["source_sha256"] == hashlib.sha256(
        (DATA_ROOT / TGC_PATHS[0]).read_bytes()).hexdigest()
    assert set(INPUT_CELLS) <= set(first)
    assert first["screen"] == "dropout-limited"
    assert [row["relative_path"] for row in block["inputs"]] == list(TGC_INPUTS)


# --------------------------------------------------------------------------- CLI and artefacts


def test_cli_writes_the_four_artefacts_and_the_committed_ones_regenerate(
    artefact_dir, tmp_path, capsys
) -> None:
    from udv_echo_process.cli import _COMMANDS, gain_power_screen_main

    assert _COMMANDS["gain-power-screen"] is gain_power_screen_main
    names = (LEVELS_NAME, PAIRS_NAME, DEPTHS_NAME)
    for name in names:
        body = (artefact_dir / name).read_bytes()
        assert body.startswith((b"axis,relative_path", b"axis,low_path"))
        assert b"\r\n" not in body
    rows = {name: (artefact_dir / name).read_text(encoding="utf-8").splitlines()
            for name in names}
    assert len(rows[LEVELS_NAME]) == SCREENED_LEVELS + 1
    assert len(rows[PAIRS_NAME]) == TGC_PAIRS + POWER_PAIRS + 1
    assert len(rows[DEPTHS_NAME]) == 50 * SCREENED_LEVELS + 1
    provenance = json.loads((artefact_dir / "gain-power-screen.provenance.json").read_text())
    assert provenance["analysis_commit"] == COMMIT
    assert (artefact_dir / "figures" / "gain-power-screen.png").is_file()

    second = tmp_path / "again"
    with pytest.raises(SystemExit) as exit_info:
        gain_power_screen_main([
            "--dataset-root", DATASET_ROOT.as_posix(), "--report-dir", second.as_posix(),
            "--manifest", RELATIVE_MANIFEST.as_posix(), "--screening-threshold", RELATIVE_ENVELOPE.as_posix(),
            "--analysis-commit", COMMIT])
    assert exit_info.value.code == 0
    printed = capsys.readouterr().out
    assert "tgc     :" in printed and "flagged ['tgc/0.BDD', 'tgc/40.BDD']" in printed
    assert "diagnostic: justified=True wider_ladder_justified=False outcome_claimed=False" in printed
    for name in (*names, "gain-power-screen.provenance.json"):
        assert (second / name).read_bytes() == (artefact_dir / name).read_bytes()
    assert (second / "figures" / "gain-power-screen.png").read_bytes() == (
        artefact_dir / "figures" / "gain-power-screen.png").read_bytes()
    for name in names:
        assert (REPORT_DIR / name).read_bytes() == (artefact_dir / name).read_bytes()


def test_cli_refuses_a_stale_or_coupled_inventory_with_named_reasons(tmp_path, capsys) -> None:
    from udv_echo_process.cli import gain_power_screen_main

    stale = _inventory(tmp_path, lambda body: _replace(body, "em_pow/high.BDD", source_sha256="0" * 64))
    screening_threshold = _rebound_screening_threshold(tmp_path, stale)
    out = tmp_path / "report"
    with pytest.raises(SystemExit) as exit_info:
        gain_power_screen_main([
            "--dataset-root", DATASET_ROOT.as_posix(), "--report-dir", out.as_posix(),
            "--manifest", stale.as_posix(), "--screening-threshold", screening_threshold.as_posix(),
            "--analysis-commit", COMMIT])
    assert exit_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("udv-gain-power-screen: source sha256 mismatch")
    assert "em_pow/high.BDD" in captured.err
    assert not (out / LEVELS_NAME).exists() and not out.exists()


def test_the_report_paths_are_line_ending_pinned() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "reports/mixer-sensitivity-analysis/*.csv text eol=lf" in attributes
    assert "reports/mixer-sensitivity-analysis/*.json text eol=lf" in attributes
    assert "reports/mixer-sensitivity-analysis/figures/*.png binary" in attributes
    for name in (MANIFEST, REPORT_DIR / "reference-repeat.provenance.json"):
        assert b"\r\n" not in name.read_bytes()


# --------------------------------------------------------------------------- fingerprint


#: The two recordings that carry one decoded fingerprint whatever folder they sit in: the dataset's
#: one repeated setting, which neither screened ladder holds as a requested level.
ANCHOR_PATHS = ("prf/600.BDD", "res/1-8.BDD")


def _perturbed_cell(field: str, current: str) -> str:
    """A value of one cell that is not the committed one and is still a decoded setting."""
    if field in ("emit_power", "sensitivity", "tgc_mode"):
        return "changed"
    return f"{float(current) + 1.0:g}"


def _cell_of(relative: str, field: str) -> str:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return next(r for r in csv.DictReader(handle) if r["relative_path"] == relative)[field]


def test_the_fingerprint_covers_the_decoded_configuration_and_leaves_the_extent_out() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    for cell in ("emit_freq_khz", "doppler_angle_deg", "tgc_start_db", "tgc_end_db",
                 "sampling_volume_index", "skipped_profiles"):
        assert cell in grid.FINGERPRINT_FIELDS, cell
        assert cell in grid.DECODED_CELLS, cell
    assert grid.DERIVED_FINGERPRINT_CELLS == ("prf_hz", "velo_max_ms")
    for cell in ("profiles", "duration_s"):
        assert cell in grid.OBSERVATION_EXTENT_CELLS
        assert cell not in grid.FINGERPRINT_FIELDS
    assert not set(grid.OBSERVATION_EXTENT_CELLS) & set(grid.FINGERPRINT_FIELDS)


def test_the_reader_publishes_every_fingerprint_cell_the_manifest_records() -> None:
    from udv_echo_process.analysis import _native_grid as grid

    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        row = next(r for r in csv.DictReader(handle) if r["relative_path"] == ANCHOR_PATHS[0])
    decoded = grid.read_decoded_level(
        DATA_ROOT, row, cells=grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS
    )
    for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
        assert grid.canonical_cell(row[field]) == grid.canonical_cell(
            grid.format_cell(decoded.observed[field])
        ), field


def test_each_axis_contract_holds_every_fingerprint_field_but_its_own_key() -> None:
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis import gain_power_screen as module

    eligibility = module.ELIGIBILITY
    assert tuple(sorted(eligibility)) == tuple(sorted(AXES))
    assert eligibility["tgc"].varied == ("tgc_start_db",)
    assert eligibility["em_pow"].varied == ("emit_power",)
    assert eligibility["tgc"].derived == eligibility["em_pow"].derived == ()
    every = set(grid.FINGERPRINT_FIELDS) | set(grid.DERIVED_FINGERPRINT_CELLS)
    for axis, key in (("tgc", "tgc_start_db"), ("em_pow", "emit_power")):
        contract = eligibility[axis]
        assert (contract.axis, contract.ladder_label) == (axis, module.KEY_LABEL[axis])
        assert set(contract.identity_fields) == every - {key}
        assert key not in contract.identity_fields
        assert "sensitivity" in contract.identity_fields
        assert "emit_power" in contract.identity_fields or key == "emit_power"


def test_the_committed_anchor_is_one_level_of_both_screened_axes() -> None:
    """R1: the level neither ladder requests is still one decoded level, realized by both files."""
    from udv_echo_process.analysis.gain_power_screen import level_groups

    for axis in AXES:
        anchor = next(g for g in level_groups(RELATIVE_MANIFEST, axis) if len(g.realizations) > 1)
        assert anchor.realization_paths == ANCHOR_PATHS, axis
        assert anchor.primary_path == ANCHOR_PATHS[0], axis
        assert anchor.in_ladder is False, axis  # the setting-based rebuild joins it (§8.3 step 5)
        assert [r.own_axis for r in anchor.realizations] == [False, False], axis
        assert anchor.realizations[0].fingerprint == anchor.realizations[1].fingerprint, axis
        assert anchor.realizations[0].extent["duration_s"] != (
            anchor.realizations[1].extent["duration_s"]
        ), axis
        # Every other level is realized by exactly one recording on the committed inventory.
        assert all(
            len(g.realizations) == 1
            for g in level_groups(RELATIVE_MANIFEST, axis)
            if g.key != anchor.key
        ), axis


def test_every_fingerprint_field_is_allowlisted_or_changes_the_row_s_fingerprint(
    tmp_path,
) -> None:
    """R4/R1, both screened axes: perturbing each field either changes identity or is allowlisted."""
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis.gain_power_screen import ELIGIBILITY, level_groups

    for axis, key in (("tgc", "tgc_start_db"), ("em_pow", "emit_power")):
        allowed = set(ELIGIBILITY[axis].varied) | set(ELIGIBILITY[axis].derived)
        assert allowed == {key}
        for field in grid.FINGERPRINT_FIELDS + grid.DERIVED_FINGERPRINT_CELLS:
            current = _cell_of(ANCHOR_PATHS[0], field)
            # The power axis's own key has to stay one of the instrument's declared steps to be
            # orderable at all; every other cell just has to move off its committed value.
            value = "high" if field == "emit_power" and current != "high" else (
                _perturbed_cell(field, current))
            manifest = _inventory(
                tmp_path,
                lambda body, f=field, v=value: _replace(body, ANCHOR_PATHS[0], **{f: v}),
                name=f"fingerprint-{axis}-{field}.csv")
            groups = level_groups(manifest, axis)
            at = next(group for group in groups if ANCHOR_PATHS[1] in group.realization_paths)
            eligible = {path for group in groups for path in group.realization_paths}
            assert ANCHOR_PATHS[0] not in at.realization_paths, (axis, field)
            if field in allowed:
                # Allowlisted: the recording moves to the level its own key names and stays eligible.
                assert ANCHOR_PATHS[0] in eligible, (axis, field)
            else:
                assert ANCHOR_PATHS[0] not in eligible, (axis, field)
                assert at.realization_paths == (ANCHOR_PATHS[1],), (axis, field)


def test_two_recordings_at_one_decoded_key_are_two_realizations_not_a_refusal(tmp_path) -> None:
    """R1: the old duplicate-key refusal was the defect - one decoded level, two named files."""
    from udv_echo_process.analysis.gain_power_screen import level_groups

    collapsed = _inventory(
        tmp_path,
        lambda body: _replace(body, TGC_PATHS[1], tgc_start_db="9.88235294118"),
        name="collapsed-tgc.csv")
    at = next(group for group in level_groups(collapsed, "tgc") if group.key == ("9.88235294118",))
    assert at.realization_paths == (TGC_PATHS[2], TGC_PATHS[1])  # manifest order, both named
    assert at.primary_path == TGC_PATHS[2]
    assert at.in_ladder is True
    assert len(select_level_rows(collapsed, "tgc")) == len(TGC_PATHS) - 1


def test_the_screen_carries_the_setting_based_selection_beside_its_levels(screen) -> None:
    """Plan §8.3 step 2: the selection is recorded on the model; §8.3 step 5 renders it."""
    from udv_echo_process.analysis import gain_power_screen as module

    for axis in screen.axes:
        requested = select_level_rows(RELATIVE_MANIFEST, axis.axis)
        assert axis.eligibility == module.ELIGIBILITY[axis.axis]
        assert [group.key for group in axis.groups if group.in_ladder] == [
            (str(row[axis.eligibility.varied[0]]),) for row in requested
        ]
        anchor = next(group for group in axis.groups if not group.in_ladder)
        assert all(
            group.key_display == f"{group.key_fields[0]}={group.key[0]}" for group in axis.groups
        )
        assert anchor.realization_paths == ANCHOR_PATHS, axis.axis
        assert anchor.requested_paths == (), axis.axis
        assert anchor.ladder_label == module.KEY_LABEL[axis.axis], axis.axis
        # Step 5: the ladder is the setting-based selection itself, so the shared anchor level is
        # one of the axis's levels with both of the reference recordings behind it.
        assert len(axis.groups) == len(axis.levels) == len(axis.common["profiles_window"])
        assert [row["relative_path"] for row in axis.levels] == [
            group.primary_path for group in axis.groups
        ]
        assert len(axis.pairs) == len(axis.levels) * (len(axis.levels) - 1) // 2
        assert len(axis.inputs) == sum(len(group.realizations) for group in axis.groups)
        level = next(row for row in axis.levels if row["realization_paths"] == ";".join(ANCHOR_PATHS))
        members = [row for row in axis.realizations if row["relative_path"] in ANCHOR_PATHS]
        assert [row["relative_path"] for row in members] == list(ANCHOR_PATHS)
        assert level["realizations"] == 2
        # The level's typical cells are the unweighted mean of its realizations'; its adverse
        # screening cells are the worst realization's, so no dropout is averaged away.
        assert level["mean_mm_s"] == pytest.approx(
            float(np.mean([row["mean_mm_s"] for row in members])))
        assert level["majority_blank_gates"] == max(
            row["majority_blank_gates"] for row in members)
        assert level["dropout_limited"] == any(row["dropout_limited"] for row in members)
        assert level["spread_limited"] == any(row["spread_limited"] for row in members)
    document = module.provenance_document(screen)
    for block in document["axis_blocks"]:
        assert block["aggregation"]["rule"] == (
            "unweighted arithmetic mean over the level's realizations")
        assert block["aggregation"]["recordings"] == len(block["inputs"])
        assert block["levels"][0]["aggregation"] == block["aggregation"]["rule"]
    assert "realizations" in json.dumps(document)


# ------------------------------------------------------------- grouped-realization prose


def test_the_screen_names_the_levels_more_than_one_recording_realizes(screen) -> None:
    """One decoded key carries two recordings on each axis and every other level carries one."""
    from udv_echo_process.analysis import gain_power_screen as module

    assert module.multi_realization_level_keys(screen) == (
        "tgc:tgc_start_db=19.9215686275", "em_pow:emit_power=medium")
    for axis in screen.axes:
        doubled = [group for group in axis.groups if len(group.realizations) > 1]
        assert len(doubled) == 1, axis.axis
        assert doubled[0].in_ladder is False, axis.axis  # no row of this axis requests that key


def test_every_emitted_prose_string_obeys_the_shared_coverage_contract(screen) -> None:
    from udv_echo_process.analysis import _native_grid as grid
    from udv_echo_process.analysis import gain_power_screen as module

    levels = module.multi_realization_level_keys(screen)
    texts = module.realization_prose(screen)
    assert {"definitions.realizations", "findings.screen_summary.realizations.statement",
            "figure.caption"} <= set(texts)
    assert any(label.startswith("findings.limitations[") for label in texts)
    grid.validate_realization_prose(texts, multi_realization_levels=levels)
    grid.validate_realization_prose({"source.__doc__": module.__doc__ or ""},
                                    multi_realization_levels=levels)
    for pattern in grid.SINGULAR_REALIZATION_CLAIMS:
        assert not pattern.search(module.__doc__ or ""), pattern.pattern


def test_a_singular_coverage_claim_in_the_emitted_prose_is_refused(screen) -> None:
    from udv_echo_process.analysis import gain_power_screen as module

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "REPLICATE_ROLE", "one recording per setting, so nothing repeats")
        with pytest.raises(GainPowerScreenError, match="contradicts multi-realization levels"):
            module.figure_caption(screen)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, "DEFINITIONS",
                      module.DEFINITIONS | {"coverage": "no level is replicated"})
        with pytest.raises(GainPowerScreenError, match="contradicts multi-realization levels"):
            module.provenance_document(screen)


def test_the_screen_applies_the_shared_contract_rather_than_its_own_rule(screen) -> None:
    from udv_echo_process.analysis import gain_power_screen as module

    seen: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    shared = module.grid.validate_realization_prose

    def spy(texts, *, multi_realization_levels):
        seen.append((tuple(sorted(texts)), tuple(multi_realization_levels)))
        return shared(texts, multi_realization_levels=multi_realization_levels)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module.grid, "validate_realization_prose", spy)
        document = module.provenance_document(screen)
        caption = module.figure_caption(screen)
    assert seen, "the screen must validate its prose through the shared contract"
    assert {levels for _texts, levels in seen} == {
        ("tgc:tgc_start_db=19.9215686275", "em_pow:emit_power=medium")}
    labels = {label for texts, _levels in seen for label in texts}
    assert {"definitions.tgc_representation", "definitions.realizations",
            "findings.screen_summary.statement", "findings.screen_summary.realizations.statement",
            "findings.diagnostic.statement", "findings.limitations[0]", "figure.caption"} <= labels
    assert document["figure"]["caption"] == caption


def test_the_base_state_prose_separates_a_held_level_from_a_requested_one(screen, findings) -> None:
    """A level the ladder holds is not the same fact as the axis's own rows requesting its key:
    :attr:`grid.LevelGroup.in_ladder` is that request, and the statements must not conflate them."""
    from udv_echo_process.analysis import gain_power_screen as module

    for axis in screen.axes:
        anchor = next(group for group in axis.groups if len(group.realizations) > 1)
        assert anchor.in_ladder is False               # no row of this axis requests the anchor key
        assert axis.base_state["in_ladder"] is True    # yet the setting-based ladder holds it
        assert axis.base_state["straddling_pair"][0] == anchor.primary_path
        low_key = axis.base_state["straddling_keys"][0]
        if axis.axis == "tgc":
            assert float(low_key) == pytest.approx(float(anchor.key[0]))
        else:
            assert low_key == anchor.key[0] == "medium"
        assert len(anchor.realization_paths) == 2
        block = findings["axes"][axis.axis]["base_state"]
        assert block["focus_pair_kind"] == "base_state_is_a_level"
        assert "holds it" in block["statement"]
        assert "no level of this axis does" not in block["statement"]
        assert "straddle" not in block["statement"]
    text = module.__doc__ or ""
    assert "do not hold it yet" not in text
    assert "two realizations" in text
