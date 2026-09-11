"""Phase 4 artifact-filter tests: the discriminated spec union and ``filter``.

Plan §7.1/§7.2 (the propagation table), §6.3/§6.4 (support semantics), §8.3
(``derive()``), §11 (error text) and the Phase 4 section.

Coverage:

- spec tests: branch parsing, relevant fields, forbidden irrelevant fields and
  every branch invariant (the union has exactly four branches);
- a table-driven pass over every row of the §7.2 propagation table;
- gap segmentation, exact quality OR-ing and "no false FILTERED";
- strict SAVGOL/TV uniformity (the final interval IS checked);
- metadata/acquisition preservation, the operation record and memory ownership;
- synthetic signals first, then the real ``.BDD`` fixtures through a test
  adapter (the reader still returns ``MultiplexedMeasurement`` until phase 6);
- the still-valid numerical assertions transferred from the legacy
  ``tests/test_process_filter.py``.

The 1-sample MEDIAN/MEAN segment behaviour is an owner decision the plan does
not state; see ``test_single_sample_median_segment_is_processed`` for the
recorded deviation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from pydantic import TypeAdapter, ValidationError

from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionIndex,
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    QualityFlag,
    SampleSupport,
    SignalData,
    SignalDescriptor,
    SignalQuantity,
    SupportKind,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.process import (
    FilterSpec,
    MeanFilterSpec,
    MedianFilterSpec,
    SavgolFilterSpec,
    TvFilterSpec,
    filter,
    filter_sequence,
)
from udv_echo_process.provenance import ChannelBundle, source_bundle

FILTERED = int(QualityFlag.FILTERED)
EDGE = int(QualityFlag.EDGE_AFFECTED)
EXTRAPOLATED = int(QualityFlag.EXTRAPOLATED)
OUTLIER = int(QualityFlag.OUTLIER)

REPO = Path(__file__).resolve().parents[1]
ECHO_PATH = REPO / "data" / "echo" / "650.BDD"
FOUR_SENSOR_PATH = REPO / "data" / "4-sensor-velocity" / "200RPM.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")

_ADAPTER = TypeAdapter(FilterSpec)


# ── builders ─────────────────────────────────────────────────────────────


def make_bundle(
    time_s: object,
    values: object,
    *,
    gate_depths: object = None,
    kind: object = None,
    valid: object = None,
    quality: object = None,
    descriptor: SignalDescriptor = _ECHO,
    channel: int = 4,
    config: ChannelConfig | None = None,
    acquisition: AcquisitionIndex | None = None,
) -> ChannelBundle:
    """Build a SOURCE ``ChannelBundle`` from explicit payload arrays."""
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    shape = arr.shape
    if gate_depths is None:
        gate_depths = np.arange(shape[1], dtype=np.float64)
    if kind is None:
        kind = np.full(shape, int(SupportKind.OBSERVED), np.uint8)
    if valid is None:
        valid = np.isfinite(arr)
    if quality is None:
        quality = np.zeros(shape, np.uint32)
    support = SampleSupport(
        kind=np.asarray(kind, np.uint8),
        valid=np.asarray(valid, bool),
        quality=np.asarray(quality, np.uint32),
    )
    data = SignalData(
        time_s=np.asarray(time_s, np.float64),
        gate_depths_mm=np.asarray(gate_depths, np.float64),
        values=arr,
        support=support,
        acquisition=acquisition,
    )
    ref = AcquisitionRef(
        recording_id=recording_id_for(_ASSET_ID),
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    cfg = ChannelConfig() if config is None else config
    return source_bundle(source_artifact(ref, descriptor, cfg, data))


def _arrays(data: SignalData) -> list[np.ndarray]:
    arrays = [data.time_s, data.gate_depths_mm, data.values]
    arrays += [data.support.kind, data.support.valid, data.support.quality]
    if data.acquisition is not None:
        for name in (
            "sample_id",
            "acquisition_time_s",
            "round_id",
            "visit_id",
            "profile_in_visit",
        ):
            arr = getattr(data.acquisition, name)
            if arr is not None:
                arrays.append(arr)
    return arrays


def _plateaus(x: np.ndarray) -> int:
    """Count exact flat plateaus (consecutive equal values) in ``x``."""
    return int(np.count_nonzero(np.diff(np.asarray(x)) == 0))


def _table_bundle() -> ChannelBundle:
    """One synthetic signal whose four gates exercise four table rows.

    row 3 exercises "valid OBSERVED", row 1 "MISSING", row 2 "invalid
    OBSERVED" and row 4/5 the synthetic support kinds.
    """
    time_s = np.arange(8, dtype=np.float64) * 0.1
    values = np.zeros((8, 4), dtype=np.float64)
    kind = np.full((8, 4), int(SupportKind.OBSERVED), np.uint8)
    valid = np.ones((8, 4), dtype=bool)
    quality = np.zeros((8, 4), dtype=np.uint32)

    # gate 0 — valid OBSERVED, one outlier spike (filtered value changes)
    values[:, 0] = [0, 0, 0, 0, 5, 0, 0, 0]

    # gate 1 — valid rows 0..4, then MISSING rows 5..7 (a boundary)
    values[:, 1] = [2, 2, 2, 2, 2, np.nan, np.nan, np.nan]
    kind[5:, 1] = int(SupportKind.MISSING)
    valid[5:, 1] = False

    # gate 2 — one invalid OBSERVED cell at row 3 (a boundary)
    values[:, 2] = [3, 3, 3, np.nan, 3, 3, 3, 3]
    valid[3, 2] = False
    quality[3, 2] = OUTLIER

    # gate 3 — EXTRAPOLATED rows 0..2, INTERPOLATED rows 3..7
    values[:, 3] = 4.0
    kind[0:3, 3] = int(SupportKind.EXTRAPOLATED)
    kind[3:8, 3] = int(SupportKind.INTERPOLATED)
    quality[0:3, 3] = EXTRAPOLATED

    return make_bundle(time_s, values, kind=kind, valid=valid, quality=quality)


MEDIAN3 = MedianFilterSpec(window=3, max_gap_s=1.0)


# ── spec: branch parsing, fields and invariants ──────────────────────────


class TestFilterSpecBranches:
    def test_union_has_exactly_the_four_documented_branches(self):
        schema = _ADAPTER.core_schema
        assert schema["type"] == "tagged-union"
        assert schema["discriminator"] == "method"
        assert set(schema["choices"]) == {"median", "mean", "savgol", "tv"}
        minimal = {
            "median": {"method": "median", "window": 1, "max_gap_s": 0.04},
            "mean": {"method": "mean", "window": 1, "max_gap_s": 0.04},
            "savgol": {
                "method": "savgol",
                "window": 3,
                "polyorder": 1,
                "max_gap_s": 0.04,
            },
            "tv": {
                "method": "tv",
                "weight": 1.0,
                "iterations": 1,
                "max_gap_s": 0.04,
            },
        }
        expected = {
            "median": MedianFilterSpec,
            "mean": MeanFilterSpec,
            "savgol": SavgolFilterSpec,
            "tv": TvFilterSpec,
        }
        for tag, payload in minimal.items():
            assert type(_ADAPTER.validate_python(payload)) is expected[tag]

    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            ({"method": "median", "window": 5, "max_gap_s": 0.04}, MedianFilterSpec),
            ({"method": "mean", "window": 4, "max_gap_s": 0.04}, MeanFilterSpec),
            (
                {
                    "method": "savgol",
                    "window": 5,
                    "polyorder": 2,
                    "max_gap_s": 0.04,
                },
                SavgolFilterSpec,
            ),
            (
                {
                    "method": "tv",
                    "weight": 0.5,
                    "iterations": 50,
                    "max_gap_s": 0.04,
                },
                TvFilterSpec,
            ),
        ],
    )
    def test_each_branch_parses_with_its_relevant_fields(self, payload, expected):
        spec = _ADAPTER.validate_python(payload)
        assert type(spec) is expected
        assert spec.method == payload["method"]
        for field, value in payload.items():
            assert getattr(spec, field) == value

    def test_median_fields_are_relevant_only(self):
        spec = MedianFilterSpec(window=1, max_gap_s=0.5)
        assert set(MedianFilterSpec.model_fields) == {"method", "window", "max_gap_s"}
        assert spec.window == 1

    def test_mean_fields_are_relevant_only(self):
        assert set(MeanFilterSpec.model_fields) == {"method", "window", "max_gap_s"}

    def test_savgol_fields_carry_a_uniform_tolerance_default(self):
        spec = SavgolFilterSpec(window=3, polyorder=1, max_gap_s=0.5)
        assert set(SavgolFilterSpec.model_fields) == {
            "method",
            "window",
            "polyorder",
            "max_gap_s",
            "uniform_rtol",
        }
        assert spec.uniform_rtol == 0.01

    def test_tv_fields_carry_a_uniform_tolerance_default(self):
        spec = TvFilterSpec(weight=0.5, iterations=50, max_gap_s=0.5)
        assert set(TvFilterSpec.model_fields) == {
            "method",
            "weight",
            "iterations",
            "max_gap_s",
            "uniform_rtol",
        }
        assert spec.uniform_rtol == 0.01

    def test_discriminator_field_is_required(self):
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"window": 5, "max_gap_s": 0.04})

    def test_unknown_method_is_rejected(self):
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python({"method": "fourier", "window": 5})

    @pytest.mark.parametrize(
        "payload",
        [
            {"method": "median", "window": 5, "max_gap_s": 0.04, "weight": 1.0},
            {"method": "median", "window": 5, "max_gap_s": 0.04, "polyorder": 2},
            {"method": "mean", "window": 5, "max_gap_s": 0.04, "iterations": 10},
            {
                "method": "savgol",
                "window": 5,
                "polyorder": 2,
                "max_gap_s": 0.04,
                "weight": 1.0,
            },
            {
                "method": "tv",
                "weight": 1.0,
                "iterations": 10,
                "max_gap_s": 0.04,
                "polyorder": 2,
            },
        ],
        ids=[
            "median-weight",
            "median-polyorder",
            "mean-iterations",
            "savgol-weight",
            "tv-polyorder",
        ],
    )
    def test_irrelevant_fields_are_forbidden(self, payload):
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(payload)

    def test_irrelevant_field_is_forbidden_on_direct_construction(self):
        with pytest.raises(ValidationError):
            MedianFilterSpec(window=5, max_gap_s=0.04, weight=1.0)

    @pytest.mark.parametrize("window", [0, -1, 2, 4])
    def test_median_window_must_be_odd_and_positive(self, window):
        with pytest.raises(ValidationError):
            MedianFilterSpec(window=window, max_gap_s=0.04)

    def test_median_window_one_is_valid(self):
        assert MedianFilterSpec(window=1, max_gap_s=0.04).window == 1

    @pytest.mark.parametrize("window", [0, -1])
    def test_mean_window_must_be_positive(self, window):
        with pytest.raises(ValidationError):
            MeanFilterSpec(window=window, max_gap_s=0.04)

    def test_mean_window_may_be_even(self):
        assert MeanFilterSpec(window=4, max_gap_s=0.04).window == 4

    @pytest.mark.parametrize("window", [1, 2, 0, -1, 4])
    def test_savgol_window_is_odd_and_at_least_three(self, window):
        with pytest.raises(ValidationError):
            SavgolFilterSpec(window=window, polyorder=1, max_gap_s=0.04)

    @pytest.mark.parametrize("polyorder", [-1, 3, 4])
    def test_savgol_polyorder_must_be_below_window(self, polyorder):
        with pytest.raises(ValidationError):
            SavgolFilterSpec(window=3, polyorder=polyorder, max_gap_s=0.04)

    def test_savgol_polyorder_may_be_zero(self):
        spec = SavgolFilterSpec(window=3, polyorder=0, max_gap_s=0.04)
        assert spec.polyorder == 0

    @pytest.mark.parametrize("value", [-0.01, 0.051, 1.0])
    def test_savgol_uniform_rtol_is_capped_at_five_percent(self, value):
        with pytest.raises(ValidationError):
            SavgolFilterSpec(window=3, polyorder=1, max_gap_s=0.04, uniform_rtol=value)

    def test_savgol_uniform_rtol_accepts_the_closed_range(self):
        assert (
            SavgolFilterSpec(
                window=3, polyorder=1, max_gap_s=0.04, uniform_rtol=0.0
            ).uniform_rtol
            == 0.0
        )
        assert (
            SavgolFilterSpec(
                window=3, polyorder=1, max_gap_s=0.04, uniform_rtol=0.05
            ).uniform_rtol
            == 0.05
        )

    @pytest.mark.parametrize("weight", [0.0, -0.1])
    def test_tv_weight_must_be_positive(self, weight):
        with pytest.raises(ValidationError):
            TvFilterSpec(weight=weight, iterations=10, max_gap_s=0.04)

    @pytest.mark.parametrize("iterations", [0, -2])
    def test_tv_iterations_must_be_positive(self, iterations):
        with pytest.raises(ValidationError):
            TvFilterSpec(weight=1.0, iterations=iterations, max_gap_s=0.04)

    @pytest.mark.parametrize("value", [-0.01, 0.051])
    def test_tv_uniform_rtol_is_capped_at_five_percent(self, value):
        with pytest.raises(ValidationError):
            TvFilterSpec(weight=1.0, iterations=10, max_gap_s=0.04, uniform_rtol=value)

    @pytest.mark.parametrize("branch", [MedianFilterSpec, MeanFilterSpec])
    def test_max_gap_s_must_be_positive(self, branch):
        with pytest.raises(ValidationError):
            branch(window=1, max_gap_s=0.0)

    @pytest.mark.parametrize("field", ["window", "max_gap_s"])
    def test_required_fields_are_required(self, field):
        payload = {"method": "median", "window": 5, "max_gap_s": 0.04}
        del payload[field]
        with pytest.raises(ValidationError):
            _ADAPTER.validate_python(payload)

    def test_no_bundled_all_method_parameter_bag_remains(self):
        import udv_echo_process

        assert not hasattr(udv_echo_process, "FilterParams")
        assert not hasattr(udv_echo_process, "FilterMethod")


# ── §7.2 propagation table, row by row ──────────────────────────────────


class TestPropagationTable:
    @pytest.fixture()
    def filtered(self) -> ChannelBundle:
        return filter(_table_bundle(), MEDIAN3)

    def test_row_valid_observed_filters_the_value_and_flags_it(self, filtered):
        data = filtered.artifact.data
        # the spike at gate 0 / row 4 is removed by the window-3 median
        assert data.values[4, 0] == pytest.approx(0.0)
        assert data.support.kind[4, 0] == int(SupportKind.OBSERVED)
        assert data.support.valid[4, 0]
        assert data.support.quality[4, 0] == FILTERED

    def test_row_missing_is_unchanged_and_a_boundary(self, filtered):
        data = filtered.artifact.data
        for row in (5, 6, 7):
            assert np.isnan(data.values[row, 1])
            assert data.support.kind[row, 1] == int(SupportKind.MISSING)
            assert not data.support.valid[row, 1]
            assert data.support.quality[row, 1] == 0

    def test_row_invalid_observed_keeps_its_reason_and_is_a_boundary(self, filtered):
        data = filtered.artifact.data
        assert np.isnan(data.values[3, 2])
        assert data.support.kind[3, 2] == int(SupportKind.OBSERVED)
        assert not data.support.valid[3, 2]
        assert data.support.quality[3, 2] == OUTLIER  # unchanged, not FILTERED

    def test_row_valid_interpolated_keeps_its_kind(self, filtered):
        data = filtered.artifact.data
        for row in (3, 4, 5, 6):
            assert data.values[row, 3] == pytest.approx(4.0)
            assert data.support.kind[row, 3] == int(SupportKind.INTERPOLATED)
            assert data.support.quality[row, 3] == FILTERED

    def test_row_valid_extrapolated_keeps_its_kind_and_flag(self, filtered):
        data = filtered.artifact.data
        for row in (1, 2):
            assert data.values[row, 3] == pytest.approx(4.0)
            assert data.support.kind[row, 3] == int(SupportKind.EXTRAPOLATED)
            assert data.support.quality[row, 3] == FILTERED | EXTRAPOLATED

    def test_quality_bits_are_exactly_the_input_or_the_added_flags(self, filtered):
        source = _table_bundle().artifact.data
        out = filtered.artifact.data
        expected = source.support.quality.astype(np.uint32).copy()
        expected[0:8, 0] |= FILTERED  # gate 0: one 8-row segment
        expected[0, 0] |= EDGE
        expected[7, 0] |= EDGE
        expected[0:5, 1] |= FILTERED  # gate 1: segment [0, 5)
        expected[0, 1] |= EDGE
        expected[4, 1] |= EDGE
        expected[0:3, 2] |= FILTERED  # gate 2: segments [0, 3) and [4, 8)
        expected[0, 2] |= EDGE
        expected[2, 2] |= EDGE
        expected[4:8, 2] |= FILTERED
        expected[4, 2] |= EDGE
        expected[7, 2] |= EDGE
        expected[0:8, 3] |= FILTERED  # gate 3: one 8-row segment
        expected[0, 3] |= EDGE
        expected[7, 3] |= EDGE
        assert np.array_equal(out.support.quality, expected)

    def test_edge_affected_marks_exactly_the_clipped_edge_cells(self, filtered):
        quality = filtered.artifact.data.support.quality
        edge = (quality & EDGE) != 0
        # gate 0: window 3 on an 8-row segment -> rows 0 and 7 only
        assert list(np.flatnonzero(edge[:, 0])) == [0, 7]
        # gate 1: window 3 on a 5-row segment -> rows 0 and 4 only
        assert list(np.flatnonzero(edge[:, 1])) == [0, 4]

    def test_support_kinds_and_validity_are_preserved_everywhere(self, filtered):
        source = _table_bundle().artifact.data
        out = filtered.artifact.data
        assert np.array_equal(out.support.kind, source.support.kind)
        assert np.array_equal(out.support.valid, source.support.valid)

    def test_tv_uses_no_padded_edge_context(self):
        # Interpretation of "where the method uses padded/truncated edge
        # context": TV solves the whole segment with natural boundary
        # differences and has no window, so it adds no EDGE_AFFECTED (unlike
        # the windowed MEDIAN/MEAN/SAVGOL kernels).
        time_s = np.arange(20, dtype=np.float64) * 0.1
        bundle = make_bundle(time_s, np.linspace(0.0, 1.0, 20))
        out = filter(
            bundle, TvFilterSpec(weight=0.5, iterations=50, max_gap_s=1.0)
        ).artifact.data
        assert np.count_nonzero(out.support.quality & EDGE) == 0
        assert np.array_equal(
            out.support.quality, np.full((20, 1), FILTERED, np.uint32)
        )

    def test_row_too_short_segment_is_copied_unchanged(self):
        # TV minimum is 2: an isolated valid row is not processed ...
        time_s = np.array([0.0, 0.1, 0.2, 0.3])
        values = np.array([[1.0], [np.nan], [np.nan], [4.0]])
        valid = np.array([[True], [False], [False], [True]])
        quality = np.zeros((4, 1), np.uint32)
        quality[1:3, 0] = OUTLIER
        bundle = make_bundle(time_s, values, valid=valid, quality=quality)
        out = filter(bundle, TvFilterSpec(weight=1.0, iterations=20, max_gap_s=1.0))
        data = out.artifact.data
        assert data.values[0, 0] == pytest.approx(1.0)
        assert data.values[3, 0] == pytest.approx(4.0)
        assert data.support.quality[0, 0] == 0  # never falsely FILTERED
        assert data.support.quality[3, 0] == 0
        assert np.isnan(data.values[1, 0])
        assert data.support.quality[1, 0] == OUTLIER

    def test_row_too_short_is_not_uniformity_checked(self):
        # A 3-row non-uniform segment is below SAVGOL's window: copied
        # unchanged, and the strict uniformity rule is not applied to it.
        time_s = np.array([0.0, 0.1, 0.5])
        bundle = make_bundle(time_s, np.array([1.0, 2.0, 3.0]))
        out = filter(bundle, SavgolFilterSpec(window=5, polyorder=2, max_gap_s=10.0))
        data = out.artifact.data
        assert np.allclose(data.values[:, 0], [1.0, 2.0, 3.0])
        assert np.array_equal(data.support.quality, np.zeros((3, 1), np.uint32))

    def test_single_sample_median_segment_is_processed(self):
        # DEVIATION (recorded): the plan does not state a MEDIAN/MEAN minimum
        # and the owner decided they have none, so a 1-sample segment is a
        # valid, processed segment: the (clipped) window leaves the value
        # unchanged but the cell is FILTERED (and EDGE_AFFECTED, since the
        # nearest-edge window was truncated). The alternative reading -- treat
        # it as too short and leave the quality untouched -- would contradict
        # "MEDIAN/MEAN have NO global minimum".
        time_s = np.array([0.0, 0.1, 0.2])
        values = np.array([[1.0], [np.nan], [3.0]])
        valid = np.array([[True], [False], [True]])
        quality = np.array([[0], [OUTLIER], [0]], np.uint32)
        bundle = make_bundle(time_s, values, valid=valid, quality=quality)
        out = filter(bundle, MedianFilterSpec(window=5, max_gap_s=1.0))
        data = out.artifact.data
        assert data.values[0, 0] == pytest.approx(1.0)
        assert data.values[2, 0] == pytest.approx(3.0)
        assert data.support.valid[0, 0] and data.support.valid[2, 0]
        assert data.support.quality[0, 0] == FILTERED | EDGE
        assert data.support.quality[2, 0] == FILTERED | EDGE

    def test_no_missing_row_ever_becomes_filtered(self, filtered):
        source = _table_bundle().artifact.data
        out = filtered.artifact.data
        missing = source.support.kind == int(SupportKind.MISSING)
        invalid = (~source.support.valid) & (
            source.support.kind == int(SupportKind.OBSERVED)
        )
        assert np.array_equal(
            out.support.quality[missing], np.zeros(int(missing.sum()), np.uint32)
        )
        assert np.array_equal(
            out.support.quality[invalid], source.support.quality[invalid]
        )


# ── gap segmentation ─────────────────────────────────────────────────────


class TestGapSegmentation:
    def test_gap_over_max_gap_s_splits_the_segment(self):
        time_s = np.array([0.0, 0.1, 0.2, 5.0, 5.1, 5.2])
        values = np.array([0.0, 0.0, 0.0, 9.0, 9.0, 9.0])
        bundle = make_bundle(time_s, values)
        out = filter(bundle, MeanFilterSpec(window=3, max_gap_s=1.0))
        assert np.allclose(out.artifact.data.values[:, 0], [0, 0, 0, 9, 9, 9])

    def test_a_large_enough_max_gap_s_lets_the_window_cross(self):
        time_s = np.array([0.0, 0.1, 0.2, 5.0, 5.1, 5.2])
        values = np.array([0.0, 0.0, 0.0, 9.0, 9.0, 9.0])
        bundle = make_bundle(time_s, values)
        out = filter(bundle, MeanFilterSpec(window=3, max_gap_s=10.0))
        assert np.allclose(out.artifact.data.values[:, 0], [0, 0, 3, 6, 9, 9])

    def test_an_invalid_cell_does_not_leak_into_a_valid_segment(self):
        time_s = np.arange(6, dtype=np.float64) * 0.1
        values = np.array([[0.0], [0.0], [0.0], [0.0], [0.0], [np.nan]])
        valid = np.array([[True], [True], [True], [True], [True], [False]])
        quality = np.array([[0], [0], [0], [0], [0], [OUTLIER]], np.uint32)
        bundle = make_bundle(time_s, values, valid=valid, quality=quality)
        out = filter(bundle, MeanFilterSpec(window=3, max_gap_s=1.0))
        # row 4 is the last valid row before a boundary; a crossing window
        # would average the 10_000 invalid neighbour
        assert out.artifact.data.values[4, 0] == pytest.approx(0.0)
        assert out.artifact.data.support.quality[4, 0] == FILTERED | EDGE

    def test_edge_marks_follow_each_segment(self):
        time_s = np.array([0.0, 0.1, 0.2, 5.0, 5.1, 5.2])
        values = np.array([0.0, 0.0, 0.0, 9.0, 9.0, 9.0])
        bundle = make_bundle(time_s, values)
        out = filter(bundle, MeanFilterSpec(window=3, max_gap_s=1.0))
        quality = out.artifact.data.support.quality[:, 0]
        assert list(np.flatnonzero((quality & EDGE) != 0)) == [0, 2, 3, 5]
        assert np.array_equal(quality & FILTERED, np.full(6, FILTERED, np.uint32))


# ── strict SAVGOL/TV uniformity ──────────────────────────────────────────


class TestUniformity:
    def test_savgol_rejects_a_non_uniform_segment_with_a_full_diagnostic(self):
        time_s = np.array([0.0, 0.1, 0.2, 0.5, 0.6, 0.7])
        bundle = make_bundle(time_s, np.ones(6))
        with pytest.raises(ValueError) as excinfo:
            filter(bundle, SavgolFilterSpec(window=3, polyorder=1, max_gap_s=10.0))
        text = str(excinfo.value)
        assert "filter.savgol" in text
        assert "channel 4" in text
        assert "segment rows [0, 6)" in text
        assert "median dt=0.1" in text
        assert "worst dt=0.3" in text
        assert "uniform_rtol=0.01" in text

    def test_tv_rejects_a_non_uniform_segment(self):
        time_s = np.array([0.0, 0.1, 0.2, 0.5, 0.6, 0.7])
        bundle = make_bundle(time_s, np.ones(6))
        with pytest.raises(ValueError, match="filter.tv"):
            filter(
                bundle,
                TvFilterSpec(weight=0.5, iterations=20, max_gap_s=10.0),
            )

    def test_the_final_interval_is_checked_not_excluded(self):
        # The superseded legacy rule ignored the last interval (`dt[:-1]`).
        # This signal differs ONLY in its final interval, so it must raise.
        time_s = np.array([0.0, 0.1, 0.2, 0.3, 3.0])
        bundle = make_bundle(time_s, np.ones(5))
        with pytest.raises(ValueError) as excinfo:
            filter(bundle, SavgolFilterSpec(window=3, polyorder=1, max_gap_s=10.0))
        text = str(excinfo.value)
        assert "segment rows [0, 5)" in text
        assert "worst dt=2.7" in text
        assert "row 3->4" in text

    def test_the_final_interval_is_checked_for_tv_too(self):
        time_s = np.array([0.0, 0.1, 0.2, 0.3, 3.0])
        bundle = make_bundle(time_s, np.ones(5))
        with pytest.raises(ValueError, match="worst dt=2.7"):
            filter(bundle, TvFilterSpec(weight=0.5, iterations=20, max_gap_s=10.0))

    def test_splitting_at_max_gap_s_removes_the_non_uniformity(self):
        time_s = np.array([0.0, 0.1, 0.2, 0.3, 3.0])
        bundle = make_bundle(time_s, np.ones(5))
        # the 2.7 s gap > max_gap_s, so the tail becomes a too-short segment
        out = filter(bundle, SavgolFilterSpec(window=3, polyorder=1, max_gap_s=1.0))
        data = out.artifact.data
        assert np.allclose(data.values[0:4, 0], 1.0)
        assert data.values[4, 0] == pytest.approx(1.0)  # copied unchanged
        assert data.support.quality[4, 0] == 0  # not FILTERED

    def test_a_uniform_segment_passes(self):
        time_s = np.arange(10, dtype=np.float64) * 0.1
        bundle = make_bundle(time_s, np.linspace(0.0, 1.0, 10))
        out = filter(bundle, SavgolFilterSpec(window=5, polyorder=2, max_gap_s=1.0))
        assert np.isfinite(out.artifact.data.values).all()

    def test_uniform_rtol_is_honoured_per_spec(self):
        # one 3% interval: above the 1% default, inside the 5% cap
        time_s = np.array([0.0, 0.1, 0.2, 0.303, 0.403])
        bundle = make_bundle(time_s, np.ones(5))
        with pytest.raises(ValueError):
            filter(
                bundle,
                SavgolFilterSpec(window=3, polyorder=1, max_gap_s=10.0),
            )
        relaxed = filter(
            bundle,
            SavgolFilterSpec(window=3, polyorder=1, max_gap_s=10.0, uniform_rtol=0.05),
        )
        assert np.isfinite(relaxed.artifact.data.values).all()


# ── metadata, operation record and memory ownership ──────────────────────


class TestBundleContract:
    def test_metadata_and_acquisition_are_preserved(self):
        time_s = np.arange(8, dtype=np.float64) * 0.1
        acquisition = AcquisitionIndex(
            sample_id=np.arange(8, dtype=np.int64),
            acquisition_time_s=time_s,
        )
        config = ChannelConfig(n_gates=1, sound_speed_ms=1480.0)
        bundle = make_bundle(
            time_s,
            [0.0, 0.0, 0.0, 0.0, 5.0, 0.0, 0.0, 0.0],
            config=config,
            acquisition=acquisition,
        )
        out = filter(bundle, MEDIAN3)
        assert out.artifact.acquisition == bundle.artifact.acquisition
        assert out.artifact.descriptor == bundle.artifact.descriptor
        assert out.artifact.config == config
        assert np.array_equal(out.artifact.data.time_s, bundle.artifact.data.time_s)
        assert np.array_equal(
            out.artifact.data.gate_depths_mm, bundle.artifact.data.gate_depths_mm
        )
        assert np.array_equal(
            out.artifact.data.acquisition.sample_id, acquisition.sample_id
        )
        assert not np.shares_memory(
            out.artifact.data.acquisition.sample_id, acquisition.sample_id
        )

    def test_the_operation_record_is_complete(self):
        bundle = _table_bundle()
        out = filter(bundle, MEDIAN3)
        assert len(out.graph.operations) == 1
        record = out.graph.operations[0]
        assert record.kind == "filter.median"
        assert record.schema_version == 1
        assert record.parents == (bundle.artifact.artifact_id,)
        assert record.params_json == '{"max_gap_s":1.0,"method":"median","window":3}'
        assert record.implementation.callable == (
            "udv_echo_process.process.filter.filter"
        )
        assert out.graph.root_artifacts == (bundle.artifact.artifact_id,)
        assert len(out.graph.derivations) == 1

    @pytest.mark.parametrize(
        ("spec", "kind", "params_json"),
        [
            (
                MedianFilterSpec(window=3, max_gap_s=1.0),
                "filter.median",
                '{"max_gap_s":1.0,"method":"median","window":3}',
            ),
            (
                MeanFilterSpec(window=3, max_gap_s=1.0),
                "filter.mean",
                '{"max_gap_s":1.0,"method":"mean","window":3}',
            ),
            (
                SavgolFilterSpec(window=3, polyorder=2, max_gap_s=1.0),
                "filter.savgol",
                (
                    '{"max_gap_s":1.0,"method":"savgol","polyorder":2,'
                    '"uniform_rtol":0.01,"window":3}'
                ),
            ),
            (
                TvFilterSpec(weight=0.5, iterations=50, max_gap_s=1.0),
                "filter.tv",
                (
                    '{"iterations":50,"max_gap_s":1.0,"method":"tv",'
                    '"uniform_rtol":0.01,"weight":0.5}'
                ),
            ),
        ],
        ids=["median", "mean", "savgol", "tv"],
    )
    def test_every_branch_registers_its_kind(self, spec, kind, params_json):
        out = filter(_table_bundle(), spec)
        record = out.graph.operations[0]
        assert record.kind == kind
        assert record.params_json == params_json

    def test_the_parent_bundle_is_never_mutated(self):
        bundle = _table_bundle()
        before_values = bundle.artifact.data.values.copy()
        before_quality = bundle.artifact.data.support.quality.copy()
        before_graph = bundle.graph
        filter(bundle, MEDIAN3)
        assert np.array_equal(
            bundle.artifact.data.values, before_values, equal_nan=True
        )
        assert np.array_equal(bundle.artifact.data.support.quality, before_quality)
        assert bundle.graph == before_graph
        assert bundle.graph.operations == ()

    def test_output_arrays_are_owned_and_share_no_memory_with_the_parent(self):
        bundle = _table_bundle()
        out = filter(bundle, MEDIAN3)
        source = _arrays(bundle.artifact.data)
        produced = _arrays(out.artifact.data)
        for parent_array in source:
            for out_array in produced:
                assert not np.shares_memory(parent_array, out_array)
        for out_array in produced:
            assert out_array.flags["OWNDATA"]
            assert out_array.flags["C_CONTIGUOUS"]
            assert not out_array.flags["WRITEABLE"]

    def test_equal_inputs_produce_equal_ids(self):
        bundle = _table_bundle()
        first = filter(bundle, MEDIAN3)
        second = filter(bundle, MEDIAN3)
        assert first.artifact.artifact_id == second.artifact.artifact_id
        assert (
            first.graph.operations[0].operation_id
            == second.graph.operations[0].operation_id
        )
        changed = filter(bundle, MedianFilterSpec(window=5, max_gap_s=1.0))
        assert changed.artifact.artifact_id != first.artifact.artifact_id
        assert (
            changed.graph.operations[0].operation_id
            != first.graph.operations[0].operation_id
        )

    def test_a_derived_bundle_chains(self):
        bundle = _table_bundle()
        once = filter(bundle, MEDIAN3)
        twice = filter(once, MeanFilterSpec(window=3, max_gap_s=1.0))
        assert len(twice.graph.operations) == 2
        assert twice.graph.operations[-1].parents == (once.artifact.artifact_id,)
        assert bundle.artifact.artifact_id in twice.graph.root_artifacts


# ── transferred legacy numerical assertions ──────────────────────────────


def _series_bundle(f: np.ndarray, t: np.ndarray | None = None) -> ChannelBundle:
    if t is None:
        t = np.linspace(0.0, 10.0, f.shape[0])
    return make_bundle(t, f)


def _step(n: int = 200, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    return np.concatenate([np.full(n // 2, lo), np.full(n - n // 2, hi)])


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def _tv(weight: float = 0.5) -> TvFilterSpec:
    return TvFilterSpec(weight=weight, iterations=200, max_gap_s=1.0)


class TestTransferredNumerics:
    def test_median_removes_outlier_spike_and_preserves_the_step(self):
        t = np.linspace(0.0, 10.0, 200)
        f = _step()
        f[30] = 5.0
        out = filter(
            _series_bundle(f, t), MedianFilterSpec(window=5, max_gap_s=1.0)
        ).artifact.data.values[:, 0]
        assert out[30] == pytest.approx(0.0, abs=1e-9)
        assert (out[100] - out[99]) > 0.9

    def test_mean_reduces_gaussian_noise(self):
        rng = np.random.default_rng(0)
        f = np.full(400, 1.0) + rng.normal(0, 0.2, 400)
        out = filter(
            _series_bundle(f), MeanFilterSpec(window=9, max_gap_s=1.0)
        ).artifact.data.values[:, 0]
        assert np.std(out - 1.0) < 0.5 * np.std(f - 1.0)

    def test_savgol_has_no_median_stair_step(self):
        rng = np.random.default_rng(0)
        n = 200
        t = np.linspace(0.0, 10.0, n)
        true = 0.5 + 2.0 * (t / t[-1]) ** 2
        f = true + rng.normal(0, 0.15, n)
        bundle = _series_bundle(f, t)
        median = filter(
            bundle, MedianFilterSpec(window=9, max_gap_s=1.0)
        ).artifact.data.values[:, 0]
        savgol = filter(
            bundle, SavgolFilterSpec(window=9, polyorder=2, max_gap_s=1.0)
        ).artifact.data.values[:, 0]
        lo, hi = 20, n - 20
        assert _rmse(savgol, true) < _rmse(f, true)
        # the median's order statistic leaves exact flat plateaus (its
        # stair-step, ~60-75 over this seeded signal); savgol leaves none
        assert _plateaus(median) >= 60
        assert _plateaus(savgol) == 0
        assert _plateaus(median[lo:hi]) >= 55

    def test_tv_keeps_a_clean_step_near_identity(self):
        out = filter(_series_bundle(_step()), _tv(1.0)).artifact.data.values[:, 0]
        assert np.allclose(out, _step(), atol=0.2)

    def test_tv_reduces_noise_and_keeps_the_edge(self):
        rng = np.random.default_rng(0)
        true = _step()
        f = true + rng.normal(0, 0.2, 200)
        out = filter(_series_bundle(f), _tv(0.5)).artifact.data.values[:, 0]
        assert np.std(out - true) < 0.55 * np.std(f - true)
        assert (out[100] - out[99]) > 0.7

    def test_heavier_tv_weight_smooths_more(self):
        rng = np.random.default_rng(0)
        f = _step() + rng.normal(0, 0.2, 200)
        bundle = _series_bundle(f)
        light = filter(bundle, _tv(0.1)).artifact.data.values[:, 0]
        heavy = filter(bundle, _tv(2.0)).artifact.data.values[:, 0]
        assert float(np.sum(np.abs(np.diff(heavy)))) < float(
            np.sum(np.abs(np.diff(light)))
        )

    def test_gates_are_filtered_independently(self):
        rng = np.random.default_rng(0)
        true = _step()
        noisy = np.full(200, 5.0) + rng.normal(0, 0.3, 200)
        bundle = _series_bundle(np.column_stack([true, noisy]))
        out = filter(bundle, _tv(0.5)).artifact.data.values
        assert np.allclose(out[:, 0], true, atol=0.2)
        assert np.std(out[:, 1] - 5.0) < 0.5 * np.std(noisy - 5.0)

    def test_filter_is_reappliable_and_bounded(self):
        rng = np.random.default_rng(0)
        bundle = _series_bundle(_step() + rng.normal(0, 0.2, 200))
        first = filter(bundle, _tv(0.5))
        second = filter(first, _tv(0.5))
        assert isinstance(second, ChannelBundle)
        assert np.array_equal(second.artifact.data.time_s, first.artifact.data.time_s)
        assert np.isfinite(second.artifact.data.values).all()
        delta = np.max(np.abs(second.artifact.data.values - first.artifact.data.values))
        assert float(delta) < 0.3

    def test_filter_sequence_equals_a_manual_fold(self):
        rng = np.random.default_rng(0)
        bundle = _series_bundle(_step() + rng.normal(0, 0.2, 200))
        specs = [
            MedianFilterSpec(window=3, max_gap_s=1.0),
            MeanFilterSpec(window=7, max_gap_s=1.0),
        ]
        direct = filter_sequence(bundle, specs)
        folded = filter(filter(bundle, specs[0]), specs[1])
        assert np.allclose(direct.artifact.data.values, folded.artifact.data.values)
        assert direct.artifact.artifact_id == folded.artifact.artifact_id
        assert len(direct.graph.operations) == 2

    def test_filter_sequence_of_nothing_returns_the_bundle(self):
        bundle = _series_bundle(_step())
        assert filter_sequence(bundle, []) is bundle

    def test_sequence_order_matters(self):
        f = _step()
        f[30] = 5.0
        bundle = _series_bundle(f)
        median_first = [
            MedianFilterSpec(window=3, max_gap_s=1.0),
            MeanFilterSpec(window=9, max_gap_s=1.0),
        ]
        mean_first = list(reversed(median_first))
        a = filter_sequence(bundle, median_first).artifact.data.values[:, 0]
        b = filter_sequence(bundle, mean_first).artifact.data.values[:, 0]
        assert float(np.max(a[0:95])) < 0.1
        assert float(np.max(b[0:95])) > 0.3


# ── real .BDD fixtures through the test adapter ──────────────────────────


def _fixture_bundle(
    path: Path, channel: int, descriptor: SignalDescriptor
) -> ChannelBundle:
    """TEST ADAPTER: ``MultiplexedMeasurement`` -> source ``ChannelBundle``.

    The ``.BDD`` reader still returns ``MultiplexedMeasurement`` until phase 6,
    so the test builds the phase-1..3 source artifact itself. Every fixture
    value is finite and every time strictly increasing (verified), so an
    all-``OBSERVED`` ``observed_signal`` is correct. No round/visit ids are
    invented -- the format cannot prove them.
    """
    measurement = load(path)
    series = measurement.by_channel()[channel]
    asset_id = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    acquisition = AcquisitionRef(
        recording_id=recording_id_for(asset_id),
        source_asset_id=asset_id,
        channel=ChannelKey(device_channel=channel),
    )
    data = observed_signal(series.time_s, series.gate_depths_mm, series.values)
    return source_bundle(source_artifact(acquisition, descriptor, series.config, data))


@pytest.fixture(scope="module")
def echo_bundle() -> ChannelBundle:
    return _fixture_bundle(ECHO_PATH, 4, _ECHO)


@pytest.fixture(scope="module")
def four_sensor_bundle() -> ChannelBundle:
    return _fixture_bundle(FOUR_SENSOR_PATH, 6, _VELOCITY)


class TestRealFixtures:
    def test_echo_median_and_mean(self, echo_bundle):
        median = filter(
            echo_bundle, MedianFilterSpec(window=5, max_gap_s=0.004)
        ).artifact.data
        mean = filter(
            echo_bundle, MeanFilterSpec(window=5, max_gap_s=0.004)
        ).artifact.data
        assert median.values.shape == echo_bundle.artifact.data.values.shape
        assert np.array_equal(median.time_s, echo_bundle.artifact.data.time_s)
        assert np.array_equal(
            median.support.kind, echo_bundle.artifact.data.support.kind
        )
        assert np.isfinite(median.values).all() and np.isfinite(mean.values).all()
        # every cell of the echo channel is a valid observation, so every cell
        # is FILTERED; window 5 on one segment per gate also marks the first
        # and last two rows of each of the 26 gates EDGE_AFFECTED
        assert np.array_equal(
            median.support.quality & FILTERED,
            np.full(median.values.shape, FILTERED, np.uint32),
        )
        assert set(np.unique(median.support.quality)) <= {
            FILTERED,
            FILTERED | EDGE,
        }
        assert np.count_nonzero(median.support.quality & EDGE) == 26 * 4

    def test_echo_savgol_and_tv_reject_the_default_tolerance(self, echo_bundle):
        # the echo cadence alternates 3.1/3.2 ms (~3.1% spread), above the
        # default uniform_rtol=0.01
        with pytest.raises(ValueError, match="filter.savgol"):
            filter(
                echo_bundle,
                SavgolFilterSpec(window=5, polyorder=2, max_gap_s=0.004),
            )
        with pytest.raises(ValueError, match="filter.tv"):
            filter(
                echo_bundle,
                TvFilterSpec(weight=1.0, iterations=20, max_gap_s=0.004),
            )

    def test_echo_savgol_and_tv_pass_at_the_tolerance_that_holds(self, echo_bundle):
        # 3.1 vs 3.2 ms is 3.1% < 5%, the plan's cap, so the echo whole series
        # is truly uniform only at uniform_rtol >= ~0.032
        savgol = filter(
            echo_bundle,
            SavgolFilterSpec(window=5, polyorder=2, max_gap_s=0.004, uniform_rtol=0.05),
        ).artifact.data
        tv = filter(
            echo_bundle,
            TvFilterSpec(weight=1.0, iterations=20, max_gap_s=0.004, uniform_rtol=0.05),
        ).artifact.data
        assert np.isfinite(savgol.values).all() and np.isfinite(tv.values).all()

    def test_four_sensor_max_gap_segments_split_at_the_round_boundaries(
        self, four_sensor_bundle
    ):
        # intra-round cadence is 25.4 ms (0.4% jitter); the inter-round gaps
        # exceed 40 ms, so max_gap_s=0.040 yields 100 uniform 4-row segments
        out = filter(
            four_sensor_bundle, MedianFilterSpec(window=3, max_gap_s=0.040)
        ).artifact.data
        assert np.isfinite(out.values).all()
        edge = (out.support.quality & EDGE) != 0
        assert np.count_nonzero(edge[:, 0]) == 200  # 100 segments x 2 edges
        assert np.array_equal(
            out.support.quality[:, 0] & FILTERED,
            np.full(out.values.shape[0], FILTERED, np.uint32),
        )

    def test_four_sensor_savgol_and_tv_pass_per_segment(self, four_sensor_bundle):
        # each 4-row segment is uniform to 0.4%, far inside the default 1%
        savgol = filter(
            four_sensor_bundle,
            SavgolFilterSpec(window=3, polyorder=2, max_gap_s=0.040),
        ).artifact.data
        tv = filter(
            four_sensor_bundle,
            TvFilterSpec(weight=0.5, iterations=50, max_gap_s=0.040),
        ).artifact.data
        assert np.isfinite(savgol.values).all() and np.isfinite(tv.values).all()

    def test_four_sensor_whole_series_is_still_rejected_at_the_cap(
        self, four_sensor_bundle
    ):
        # one segment (max_gap_s=1.0) has 0.36 s round gaps: the 5% cap cannot
        # rescue it, so the strict rule raises rather than silently skipping
        with pytest.raises(ValueError, match="not truly uniform"):
            filter(
                four_sensor_bundle,
                TvFilterSpec(
                    weight=0.5, iterations=50, max_gap_s=1.0, uniform_rtol=0.05
                ),
            )
