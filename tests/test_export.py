"""Terminal-result JSON/CSV/NPZ export boundary (absorption plan §4, D4).

Coverage:

- the exact CSV column set/order and the unit-bearing names, one row per
  retained state x gate in state-major/gate order with the interval identity;
- strict JSON: ``json.loads(..., parse_constant=reject)`` must never fire, no
  ``NaN``/``Infinity`` token appears, and no absolute path leaks in;
- NPZ loadable with ``allow_pickle=False`` and every array equal to the source
  result/detection arrays, in a fixed key order;
- legitimate empty-envelope NaNs: strict JSON metadata, the explicit empty CSV
  token, and retained IEEE NaN in the NPZ;
- deterministic second export (byte-identical JSON/CSV/NPZ across runs and
  idempotent over the same directory);
- mismatch refusal (artifact ids, descriptor, geometry, retained states and
  retained interval boundaries — two detections of one artifact that share
  state numbers and counts but not boundaries must be refused) with no partial
  write left behind, plus the type contract and a schema_name pinned to the one
  versioned literal;
- the write's honest failure modes: staging is all-or-nothing, but the
  per-member replace loop is not a transaction (a failure after the first rename
  leaves that member replaced, the rest unchanged, and no staged temp behind),
  and a non-finite value outside an ``empty_envelope`` gate is refused rather
  than masked as the empty CSV token;
- no mutation of the bundle, the detection, the profiles or their graph;
- the narrow returned :class:`TerminalResultExport` record and that the module
  stays outside bundle storage and the provenance graph.

Real fixture: ``data/4-sensor-velocity/200RPM.BDD`` channel 6 (the archived
steady 200 RPM velocity recording).
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

import udv_echo_process.export as export_module
from udv_echo_process.analysis.profiles import extract_robust_profiles
from udv_echo_process.analysis.states import detect_operating_states
from udv_echo_process.export import (
    ARRAYS_NPZ_FILENAME,
    CSV_COLUMNS,
    CSV_EMPTY_VALUE,
    PROFILES_CSV_FILENAME,
    RESULT_JSON_FILENAME,
    TERMINAL_RESULT_SCHEMA,
    TerminalResultExport,
    TerminalResultExportError,
    export_terminal_results,
)
from udv_echo_process.io import load
from udv_echo_process.models import (
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    OperatingStateDetection,
    OperatingStateInterval,
    SignalDescriptor,
    SignalQuantity,
    StateDetectionMode,
    StateDetectionSettings,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.models.profiles import (
    RobustGateStatus,
    RobustProfileSettings,
    RobustVelocityProfiles,
)
from udv_echo_process.provenance import ChannelBundle, select_channel, source_bundle

REPO = Path(__file__).resolve().parents[1]
FOUR_SENSOR = REPO / "data" / "4-sensor-velocity" / "200RPM.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_OTHER_ASSET_ID = "sha256:" + "2" * 64
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_SINGLE = StateDetectionSettings(mode=StateDetectionMode.SINGLE)


# ── builders ─────────────────────────────────────────────────────────────


def _bundle(
    field: object,
    *,
    time_s: object = None,
    gate_depths: object = None,
    channel: int = 6,
    descriptor: SignalDescriptor = _VELOCITY,
    asset_id: str = _ASSET_ID,
    data: object = None,
) -> ChannelBundle:
    """Build a SOURCE ``ChannelBundle`` for one velocity payload."""
    if data is None:
        arr = np.asarray(field, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr[:, None]
        rows, gates = arr.shape
        if time_s is None:
            time_s = np.arange(rows, dtype=np.float64) * 0.1
        if gate_depths is None:
            gate_depths = np.linspace(10.0, 50.0, gates)
        data = observed_signal(time_s, gate_depths, arr)
    ref = AcquisitionRef(
        recording_id=recording_id_for(asset_id),
        source_asset_id=asset_id,
        channel=ChannelKey(device_channel=channel),
    )
    return source_bundle(source_artifact(ref, descriptor, ChannelConfig(), data))


def _detect(
    field: object, **over: object
) -> tuple[ChannelBundle, OperatingStateDetection]:
    """Build a bundle and its own detection (the supported input pair)."""
    bundle = _bundle(field, **over)
    return bundle, detect_operating_states(bundle, _SINGLE)


def _detection_with_spans(
    bundle: ChannelBundle, spans: list[tuple[int, int]]
) -> OperatingStateDetection:
    """An AUTO detection over ``bundle`` with explicit half-open spans.

    Builds a valid detection whose kept/dropped intervals are exactly the
    supplied spans, so two detections of *one* artifact can be made to keep the
    same state numbers and profile counts while their boundaries differ — the
    pair that ``artifact_id`` + counts alone cannot distinguish.
    """
    total, gates = bundle.artifact.data.values.shape
    settings = StateDetectionSettings()  # AUTO; minimum_relative_duration 0.03
    intervals: list[OperatingStateInterval] = []
    state_number = 0
    for position, (start, stop) in enumerate(spans, start=1):
        count = stop - start
        retained = count > settings.minimum_relative_duration * total
        if retained:
            state_number += 1
        intervals.append(
            OperatingStateInterval(
                interval_number=position,
                state_number=state_number if retained else None,
                kept=retained,
                start_index=start,
                stop_index_exclusive=stop,
                profile_count=count,
                relative_duration=count / total,
                start_time_s=0.1 * start,
                end_time_s=0.1 * (stop - 1),
                duration_s=0.1 * count,
            )
        )
    covered = np.zeros(total, dtype=bool)
    for start, stop in spans:
        covered[start:stop] = True
    return OperatingStateDetection(
        mode=StateDetectionMode.AUTO,
        settings=settings,
        artifact_id=bundle.artifact.artifact_id,
        descriptor=bundle.artifact.descriptor,
        profile_count=total,
        gate_count=gates,
        time_step_s=0.1,
        gate_spacing_mm=1.0,
        transition_indices=np.flatnonzero(~covered).astype(np.int64),
        intervals=tuple(intervals),
        variability=np.zeros(total, dtype=np.float64),
        change_signal=np.zeros(total, dtype=np.float64),
        base_threshold=1.0,
        applied_threshold=0.5,
        peak_prominence=0.0,
    )


def _reject_constant(token: str) -> object:
    raise AssertionError(f"non-finite JSON token {token!r} appeared")


def _read_rows(path: Path) -> list[list[str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def _empty_envelope_set() -> tuple[
    ChannelBundle, OperatingStateDetection, RobustVelocityProfiles
]:
    """A synthetic set whose profiles are all ``empty_envelope`` gates."""
    rng = np.random.default_rng(7)
    walk = np.column_stack(
        [
            np.cumsum(rng.normal(size=200)) * 10,
            np.cumsum(rng.normal(size=200)) * 10,
        ]
    )
    bundle, detection = _detect(walk)
    profiles = extract_robust_profiles(
        bundle,
        detection,
        RobustProfileSettings(
            lower_quantile=0.499,
            upper_quantile=0.501,
            fail_on_sparse_envelope=False,
        ),
    )
    return bundle, detection, profiles


@pytest.fixture(scope="module")
def four_sensor() -> ChannelBundle:
    return select_channel(load(FOUR_SENSOR), ChannelKey(device_channel=6))


@pytest.fixture(scope="module")
def fixture_results(
    four_sensor: ChannelBundle,
) -> tuple[OperatingStateDetection, RobustVelocityProfiles]:
    detection = detect_operating_states(four_sensor)
    return detection, extract_robust_profiles(four_sensor, detection)


@pytest.fixture(scope="module")
def fixture_export(
    four_sensor: ChannelBundle,
    fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[TerminalResultExport, Path]:
    detection, profiles = fixture_results
    directory = tmp_path_factory.mktemp("export-fixture")
    record = export_terminal_results(
        four_sensor, detection, profiles, directory=directory
    )
    return record, directory


# ── exact CSV ────────────────────────────────────────────────────────────


class TestCsvContract:
    def test_header_is_the_exact_ordered_column_set(self, fixture_export) -> None:
        record, _ = fixture_export
        rows = _read_rows(record.profiles_csv)
        assert rows[0] == list(CSV_COLUMNS)

    def test_one_row_per_retained_state_and_gate_in_order(
        self,
        four_sensor: ChannelBundle,
        fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
        fixture_export,
    ) -> None:
        record, _ = fixture_export
        detection, profiles = fixture_results
        rows = _read_rows(record.profiles_csv)[1:]
        states = len(profiles.state_numbers)
        gates = profiles.gate_count
        assert len(rows) == states * gates
        depths = four_sensor.artifact.data.gate_depths_mm
        for index, row in enumerate(rows):
            state = index // gates
            gate = index % gates
            assert row[0] == str(profiles.state_numbers[state])
            assert row[6] == str(gate)
            assert float(row[7]) == float(depths[gate])
        assert detection.gate_count == gates

    def test_interval_identity_matches_the_detection(
        self,
        fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
        fixture_export,
    ) -> None:
        record, _ = fixture_export
        detection, profiles = fixture_results
        kept = [interval for interval in detection.intervals if interval.kept]
        rows = _read_rows(record.profiles_csv)[1:]
        for row_index, interval in enumerate(kept):
            row = rows[row_index * profiles.gate_count]
            assert row[1] == str(interval.interval_number)
            assert row[2] == str(interval.start_index)
            assert row[3] == str(interval.stop_index_exclusive)
            assert float(row[4]) == interval.start_time_s
            assert float(row[5]) == interval.end_time_s

    def test_statistics_counts_status_and_definition_columns(
        self,
        fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
        fixture_export,
    ) -> None:
        record, _ = fixture_export
        _, profiles = fixture_results
        rows = _read_rows(record.profiles_csv)[1:]
        for state, row in enumerate(
            [
                rows[state * profiles.gate_count : (state + 1) * profiles.gate_count]
                for state in range(len(profiles.state_numbers))
            ]
        ):
            for gate, cell in enumerate(row):
                assert float(cell[8]) == profiles.median_velocity_mm_s[state, gate]
                assert (
                    float(cell[9])
                    == profiles.median_absolute_deviation_mm_s[state, gate]
                )
                assert int(cell[10]) == int(profiles.retained_sample_count[state, gate])
                assert int(cell[11]) == int(profiles.input_sample_count[state])
                assert cell[12] == profiles.gate_status[state][gate].value
                assert cell[13] == "unscaled_median_absolute_deviation"

    def test_units_appear_in_the_header_and_the_json(self, fixture_export) -> None:
        record, _ = fixture_export
        assert "depth_mm" in CSV_COLUMNS
        assert "median_velocity_mm_s" in CSV_COLUMNS
        assert "mad_velocity_mm_s" in CSV_COLUMNS
        payload = json.loads(record.result_json.read_text(encoding="utf-8"))
        assert payload["units"] == {
            "time": "s",
            "depth": "mm",
            "velocity": "mm/s",
            "deviation": "mm/s",
        }

    def test_values_round_trip_to_seventeen_significant_digits(
        self,
        fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
        fixture_export,
    ) -> None:
        record, _ = fixture_export
        _, profiles = fixture_results
        rows = _read_rows(record.profiles_csv)[1:]
        assert float(rows[0][8]) == float(profiles.median_velocity_mm_s[0, 0])
        assert format(float(profiles.median_velocity_mm_s[0, 0]), ".17g") == rows[0][8]


# ── strict JSON ──────────────────────────────────────────────────────────


class TestStrictJson:
    def test_parses_with_a_rejecting_parse_constant(self, fixture_export) -> None:
        record, _ = fixture_export
        text = record.result_json.read_text(encoding="utf-8")
        payload = json.loads(text, parse_constant=_reject_constant)
        assert "NaN" not in text
        assert "Infinity" not in text
        assert isinstance(payload, dict)

    def test_schema_is_versioned_and_not_a_manifest(self, fixture_export) -> None:
        record, _ = fixture_export
        payload = json.loads(record.result_json.read_text(encoding="utf-8"))
        assert payload["schema"] == TERMINAL_RESULT_SCHEMA
        assert "manifest" not in json.dumps(payload)
        assert record.schema_name == TERMINAL_RESULT_SCHEMA

    def test_names_only_relative_members_and_no_local_path(
        self, fixture_export, tmp_path: Path
    ) -> None:
        record, directory = fixture_export
        text = record.result_json.read_text(encoding="utf-8")
        payload = json.loads(text)
        assert payload["files"] == {
            "result_json": RESULT_JSON_FILENAME,
            "profiles_csv": PROFILES_CSV_FILENAME,
            "arrays_npz": ARRAYS_NPZ_FILENAME,
        }
        for name in payload["files"].values():
            assert "/" not in name and "\\" not in name
        assert str(directory) not in text
        assert str(tmp_path) not in text

    def test_metadata_matches_the_detection_and_profiles(
        self,
        four_sensor: ChannelBundle,
        fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
        fixture_export,
    ) -> None:
        record, _ = fixture_export
        detection, profiles = fixture_results
        payload = json.loads(record.result_json.read_text(encoding="utf-8"))
        assert payload["artifact"]["artifact_id"] == four_sensor.artifact.artifact_id
        assert payload["artifact"]["device_channel"] == 6
        assert payload["deviation_definition"] == profiles.deviation_definition
        assert payload["geometry"]["profile_count"] == detection.profile_count
        assert payload["geometry"]["gate_count"] == detection.gate_count
        assert payload["geometry"]["state_count"] == len(profiles.state_numbers)
        assert payload["profiles"]["state_numbers"] == list(profiles.state_numbers)
        assert payload["profiles"]["settings"] == profiles.settings.model_dump(
            mode="json"
        )
        assert payload["state_detection"]["intervals"] == [
            interval.model_dump(mode="json") for interval in detection.intervals
        ]


# ── NPZ ──────────────────────────────────────────────────────────────────


class TestNpzContract:
    def test_loads_without_pickle_and_arrays_match(
        self,
        four_sensor: ChannelBundle,
        fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
        fixture_export,
    ) -> None:
        record, _ = fixture_export
        detection, profiles = fixture_results
        data = four_sensor.artifact.data
        with np.load(record.arrays_npz, allow_pickle=False) as arrays:
            assert arrays.files == [
                "gate_depths_mm",
                "profile_time_s",
                "state_numbers",
                "median_velocity_mm_s",
                "median_absolute_deviation_mm_s",
                "retained_sample_count",
                "input_sample_count",
                "variability",
                "change_signal",
                "transition_indices",
            ]
            np.testing.assert_array_equal(arrays["gate_depths_mm"], data.gate_depths_mm)
            np.testing.assert_array_equal(arrays["profile_time_s"], data.time_s)
            np.testing.assert_array_equal(
                arrays["state_numbers"],
                np.asarray(profiles.state_numbers, dtype=np.int64),
            )
            np.testing.assert_array_equal(
                arrays["median_velocity_mm_s"], profiles.median_velocity_mm_s
            )
            np.testing.assert_array_equal(
                arrays["median_absolute_deviation_mm_s"],
                profiles.median_absolute_deviation_mm_s,
            )
            np.testing.assert_array_equal(
                arrays["retained_sample_count"], profiles.retained_sample_count
            )
            np.testing.assert_array_equal(
                arrays["input_sample_count"], profiles.input_sample_count
            )
            np.testing.assert_array_equal(arrays["variability"], detection.variability)
            np.testing.assert_array_equal(
                arrays["change_signal"], detection.change_signal
            )
            np.testing.assert_array_equal(
                arrays["transition_indices"], detection.transition_indices
            )


# ── empty envelope ───────────────────────────────────────────────────────


class TestEmptyEnvelope:
    def test_metadata_stays_strict_and_csv_uses_the_empty_token(
        self, tmp_path: Path
    ) -> None:
        bundle, detection, profiles = _empty_envelope_set()
        assert {status.value for row in profiles.gate_status for status in row} == {
            "empty_envelope"
        }
        record = export_terminal_results(
            bundle, detection, profiles, directory=tmp_path / "empty"
        )
        text = record.result_json.read_text(encoding="utf-8")
        json.loads(text, parse_constant=_reject_constant)
        assert "NaN" not in text

        rows = _read_rows(record.profiles_csv)[1:]
        assert len(rows) == profiles.gate_count
        for row in rows:
            assert row[8] == CSV_EMPTY_VALUE
            assert row[9] == CSV_EMPTY_VALUE
            assert row[10] == "0"
            assert row[12] == "empty_envelope"

    def test_npz_retains_ieee_nan_with_documented_meaning(self, tmp_path: Path) -> None:
        bundle, detection, profiles = _empty_envelope_set()
        record = export_terminal_results(
            bundle, detection, profiles, directory=tmp_path / "empty"
        )
        with np.load(record.arrays_npz, allow_pickle=False) as arrays:
            assert np.isnan(arrays["median_velocity_mm_s"]).all()
            assert np.isnan(arrays["median_absolute_deviation_mm_s"]).all()
            assert (arrays["retained_sample_count"] == 0).all()
            assert (arrays["input_sample_count"] > 0).all()


# ── determinism ──────────────────────────────────────────────────────────


class TestDeterminism:
    def test_second_export_is_byte_identical(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(21)
        bundle, detection = _detect(rng.normal(size=(60, 4)) * 3 + 20)
        profiles = extract_robust_profiles(bundle, detection)
        first = export_terminal_results(
            bundle, detection, profiles, directory=tmp_path / "a"
        )
        second = export_terminal_results(
            bundle, detection, profiles, directory=tmp_path / "b"
        )
        for name in (RESULT_JSON_FILENAME, PROFILES_CSV_FILENAME, ARRAYS_NPZ_FILENAME):
            assert (tmp_path / "a" / name).read_bytes() == (
                tmp_path / "b" / name
            ).read_bytes(), name
        assert first.schema_name == second.schema_name

    def test_reexport_over_the_same_directory_is_idempotent(
        self, tmp_path: Path
    ) -> None:
        rng = np.random.default_rng(21)
        bundle, detection = _detect(rng.normal(size=(60, 4)) * 3 + 20)
        profiles = extract_robust_profiles(bundle, detection)
        record = export_terminal_results(
            bundle, detection, profiles, directory=tmp_path / "same"
        )
        before = {
            name: (tmp_path / "same" / name).read_bytes()
            for name in (
                RESULT_JSON_FILENAME,
                PROFILES_CSV_FILENAME,
                ARRAYS_NPZ_FILENAME,
            )
        }
        # deterministic ordering/content: no temp file survives
        assert sorted(p.name for p in (tmp_path / "same").iterdir()) == sorted(
            [ARRAYS_NPZ_FILENAME, PROFILES_CSV_FILENAME, RESULT_JSON_FILENAME]
        )
        record = export_terminal_results(
            bundle, detection, profiles, directory=tmp_path / "same"
        )
        after = {name: (tmp_path / "same" / name).read_bytes() for name in before}
        assert before == after
        assert record.profiles_csv.name == PROFILES_CSV_FILENAME


# ── refusal ──────────────────────────────────────────────────────────────


class TestRefusal:
    def test_wrong_types_are_type_errors(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 3), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        with pytest.raises(TypeError):
            export_terminal_results("nope", detection, profiles, directory=tmp_path)
        with pytest.raises(TypeError):
            export_terminal_results(bundle, "nope", profiles, directory=tmp_path)
        with pytest.raises(TypeError):
            export_terminal_results(bundle, detection, "nope", directory=tmp_path)

    def test_detection_of_another_artifact_is_refused(self, tmp_path: Path) -> None:
        bundle = _bundle(np.full((30, 4), 7.0))
        other = _bundle(np.full((30, 4), 7.0), channel=7, asset_id=_OTHER_ASSET_ID)
        detection = detect_operating_states(other, _SINGLE)
        profiles = extract_robust_profiles(other, detection)
        target = tmp_path / "refused"
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, detection, profiles, directory=target)
        assert "artifact" in str(excinfo.value)
        assert not target.exists()

    def test_profiles_for_another_artifact_are_refused(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        forged = profiles.model_copy(update={"artifact_id": _OTHER_ASSET_ID})
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, detection, forged, directory=tmp_path)
        assert "artifact" in str(excinfo.value)

    def test_descriptor_mismatch_is_refused(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        forged = profiles.model_copy(update={"descriptor": _ECHO})
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, detection, forged, directory=tmp_path)
        assert "descriptor" in str(excinfo.value)

    def test_gate_axis_mismatch_is_refused(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        forged = detection.model_copy(update={"gate_count": 5})
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, forged, profiles, directory=tmp_path)
        assert "geometry" in str(excinfo.value)

    def test_profile_axis_mismatch_is_refused(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        forged = detection.model_copy(update={"profile_count": 31})
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, forged, profiles, directory=tmp_path)
        assert "geometry" in str(excinfo.value)

    def test_state_number_mismatch_is_refused(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        forged = profiles.model_copy(update={"state_numbers": (2,)})
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, detection, forged, directory=tmp_path)
        assert "state_numbers" in str(excinfo.value)

    def test_input_count_mismatch_is_refused(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        forged = profiles.model_copy(
            update={"input_sample_count": np.array([999], dtype=np.int64)}
        )
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, detection, forged, directory=tmp_path)
        assert "input_sample_count" in str(excinfo.value)

    def test_detection_with_different_interval_boundaries_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Same artifact, same state numbers, same counts — different spans.

        ``artifact_id`` + ``state_numbers`` + ``input_sample_count`` cannot tell
        these two detections apart, so export must compare the retained
        intervals themselves and refuse the mislabeled CSV.
        """
        rng = np.random.default_rng(3)
        bundle = _bundle(rng.normal(size=(100, 3)) * 3 + 20)
        first = _detection_with_spans(bundle, [(0, 1), (1, 51), (51, 54), (54, 100)])
        second = _detection_with_spans(bundle, [(0, 2), (2, 52), (52, 54), (54, 100)])
        kept_first = tuple(i for i in first.intervals if i.kept)
        kept_second = tuple(i for i in second.intervals if i.kept)
        assert [i.state_number for i in kept_first] == [
            i.state_number for i in kept_second
        ]
        assert [i.profile_count for i in kept_first] == [
            i.profile_count for i in kept_second
        ]
        assert [(i.start_index, i.stop_index_exclusive) for i in kept_first] != [
            (i.start_index, i.stop_index_exclusive) for i in kept_second
        ]

        profiles = extract_robust_profiles(bundle, first)
        target = tmp_path / "boundaries"
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, second, profiles, directory=target)
        assert "retained_intervals" in str(excinfo.value)
        assert not target.exists()
        # the detection the rows were actually sliced from is accepted
        export_terminal_results(bundle, first, profiles, directory=target)

    def test_non_finite_statistic_outside_an_empty_envelope_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A non-finite value is an error, not a silent empty CSV cell.

        Only a gate whose ``gate_status`` is ``empty_envelope`` has a
        legitimately absent statistic; a NaN anywhere else (here forged past
        model validation) must not be masked as the empty token.
        """
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        assert all(
            status is not RobustGateStatus.EMPTY_ENVELOPE
            for row in profiles.gate_status
            for status in row
        )
        forged = profiles.model_copy(
            update={"median_velocity_mm_s": np.full((1, 4), np.nan)}
        )
        target = tmp_path / "masked"
        with pytest.raises(TerminalResultExportError) as excinfo:
            export_terminal_results(bundle, detection, forged, directory=target)
        assert "finite" in str(excinfo.value)
        assert not target.exists()


# ── no mutation ──────────────────────────────────────────────────────────


class TestNoMutation:
    def test_export_does_not_touch_its_inputs(self, tmp_path: Path) -> None:
        rng = np.random.default_rng(5)
        bundle, detection = _detect(rng.normal(size=(60, 4)) * 3 + 20)
        profiles = extract_robust_profiles(bundle, detection)
        values_before = bundle.artifact.data.values.copy()
        quality_before = bundle.artifact.data.support.quality.copy()
        graph_before = bundle.graph
        artifact_id_before = bundle.artifact.artifact_id
        variability_before = detection.variability.copy()
        change_before = detection.change_signal.copy()
        median_before = profiles.median_velocity_mm_s.copy()
        retained_before = profiles.retained_sample_count.copy()
        settings_before = profiles.settings

        export_terminal_results(bundle, detection, profiles, directory=tmp_path / "out")

        assert np.array_equal(
            bundle.artifact.data.values, values_before, equal_nan=True
        )
        assert np.array_equal(bundle.artifact.data.support.quality, quality_before)
        assert bundle.graph is graph_before
        assert bundle.graph.operations == ()
        assert bundle.artifact.artifact_id == artifact_id_before
        assert np.array_equal(detection.variability, variability_before)
        assert np.array_equal(detection.change_signal, change_before)
        assert np.array_equal(
            profiles.median_velocity_mm_s, median_before, equal_nan=True
        )
        assert np.array_equal(profiles.retained_sample_count, retained_before)
        assert profiles.settings == settings_before


# ── return record + write hygiene ────────────────────────────────────────


class TestReturnRecord:
    def test_names_the_three_written_members(self, fixture_export) -> None:
        record, directory = fixture_export
        assert record.directory == directory
        assert record.result_json == directory / RESULT_JSON_FILENAME
        assert record.profiles_csv == directory / PROFILES_CSV_FILENAME
        assert record.arrays_npz == directory / ARRAYS_NPZ_FILENAME
        for path in (record.result_json, record.profiles_csv, record.arrays_npz):
            assert path.is_file()

    def test_is_frozen(self, fixture_export) -> None:
        record, _ = fixture_export
        with pytest.raises(ValidationError):
            record.result_json = Path("/tmp/other.json")  # type: ignore[misc]

    def test_rejects_a_non_canonical_member(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError):
            TerminalResultExport(
                directory=tmp_path,
                result_json=tmp_path / "other.json",
                profiles_csv=tmp_path / PROFILES_CSV_FILENAME,
                arrays_npz=tmp_path / ARRAYS_NPZ_FILENAME,
            )

    def test_schema_name_is_pinned_to_the_one_versioned_literal(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(ValidationError):
            TerminalResultExport(
                schema_name="udv-echo-process/terminal-result/v2",  # type: ignore[arg-type]
                directory=tmp_path,
                result_json=tmp_path / RESULT_JSON_FILENAME,
                profiles_csv=tmp_path / PROFILES_CSV_FILENAME,
                arrays_npz=tmp_path / ARRAYS_NPZ_FILENAME,
            )
        record = TerminalResultExport(
            directory=tmp_path,
            result_json=tmp_path / RESULT_JSON_FILENAME,
            profiles_csv=tmp_path / PROFILES_CSV_FILENAME,
            arrays_npz=tmp_path / ARRAYS_NPZ_FILENAME,
        )
        assert record.schema_name == TERMINAL_RESULT_SCHEMA

    def test_creates_a_missing_directory(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        target = tmp_path / "nested" / "deep"
        record = export_terminal_results(bundle, detection, profiles, directory=target)
        assert target.is_dir()
        assert record.result_json.is_file()


class TestWriteHygiene:
    def test_explicit_utf8_and_newlines(self, fixture_export) -> None:
        record, _ = fixture_export
        json_bytes = record.result_json.read_bytes()
        csv_bytes = record.profiles_csv.read_bytes()
        assert json_bytes.endswith(b"\n")
        assert json_bytes.decode("utf-8")
        assert csv_bytes.endswith(b"\n")
        assert b"\r" not in csv_bytes
        assert csv_bytes.decode("utf-8")

    def test_existing_members_are_replaced(self, tmp_path: Path) -> None:
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        target = tmp_path / "replace"
        target.mkdir()
        for name in (RESULT_JSON_FILENAME, PROFILES_CSV_FILENAME, ARRAYS_NPZ_FILENAME):
            (target / name).write_text("stale", encoding="utf-8")
        record = export_terminal_results(bundle, detection, profiles, directory=target)
        assert json.loads(record.result_json.read_text(encoding="utf-8"))["schema"] == (
            TERMINAL_RESULT_SCHEMA
        )
        assert record.profiles_csv.read_text(encoding="utf-8").splitlines()[0] == (
            ",".join(CSV_COLUMNS)
        )
        with np.load(record.arrays_npz, allow_pickle=False) as arrays:
            assert "median_velocity_mm_s" in arrays.files

    def test_a_failed_member_replacement_leaves_earlier_members_replaced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The set is staged as a whole but replaced member by member.

        There is no rollback: the rename that landed stays landed, the members
        after it still hold the previous files, and every staged temporary file
        is cleaned up.
        """
        bundle, detection = _detect(np.full((30, 4), 7.0))
        profiles = extract_robust_profiles(bundle, detection)
        target = tmp_path / "member-wise"
        target.mkdir()
        for name in (RESULT_JSON_FILENAME, PROFILES_CSV_FILENAME, ARRAYS_NPZ_FILENAME):
            (target / name).write_text("stale", encoding="utf-8")

        real_replace = os.replace
        calls = {"count": 0}

        def flaky_replace(
            source: str | os.PathLike[str], destination: str | os.PathLike[str]
        ) -> None:
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("simulated failure on the second member")
            real_replace(source, destination)

        monkeypatch.setattr(export_module.os, "replace", flaky_replace)
        with pytest.raises(OSError):
            export_terminal_results(bundle, detection, profiles, directory=target)

        landed = json.loads((target / RESULT_JSON_FILENAME).read_text(encoding="utf-8"))
        assert landed["schema"] == TERMINAL_RESULT_SCHEMA
        assert (target / PROFILES_CSV_FILENAME).read_text(encoding="utf-8") == "stale"
        assert (target / ARRAYS_NPZ_FILENAME).read_text(encoding="utf-8") == "stale"
        assert sorted(p.name for p in target.iterdir()) == sorted(
            [ARRAYS_NPZ_FILENAME, PROFILES_CSV_FILENAME, RESULT_JSON_FILENAME]
        )


class TestBoundary:
    def test_module_stays_outside_storage_and_provenance(self) -> None:
        assert set(export_module.__all__) == {
            "ARRAYS_NPZ_FILENAME",
            "CSV_COLUMNS",
            "CSV_EMPTY_VALUE",
            "PROFILES_CSV_FILENAME",
            "RESULT_JSON_FILENAME",
            "TERMINAL_RESULT_SCHEMA",
            "TerminalResultExport",
            "TerminalResultExportError",
            "export_terminal_results",
        }
        for forbidden in (
            "ArtifactGraph",
            "ArtifactBundle",
            "OperationRecord",
            "store_bundle",
            "load_bundle",
            "BundleManifestV1",
            "stable_id",
            "derived_artifact_id",
        ):
            assert not hasattr(export_module, forbidden), forbidden
        declared = {name.lower() for name in export_module.__all__}
        assert not any("manifest" in name for name in declared)
        assert not any("cache" in name for name in declared)

    def test_empty_envelope_status_is_the_only_nan_source(self) -> None:
        _bundle, detection, profiles = _empty_envelope_set()
        assert profiles.gate_status[0][0] is RobustGateStatus.EMPTY_ENVELOPE
        assert isinstance(detection, OperatingStateDetection)


class TestRealFixture:
    def test_exporting_the_committed_recording(
        self,
        four_sensor: ChannelBundle,
        fixture_results: tuple[OperatingStateDetection, RobustVelocityProfiles],
        fixture_export,
    ) -> None:
        record, _ = fixture_export
        detection, profiles = fixture_results
        assert four_sensor.artifact.descriptor == _VELOCITY
        rows = _read_rows(record.profiles_csv)
        assert len(rows) == profiles.gate_count + 1
        payload = json.loads(record.result_json.read_text(encoding="utf-8"))
        assert payload["geometry"]["gate_count"] == 55
        assert payload["geometry"]["profile_count"] == 400
        with np.load(record.arrays_npz, allow_pickle=False) as arrays:
            assert arrays["median_velocity_mm_s"].shape == (1, 55)
            assert np.isfinite(arrays["median_velocity_mm_s"]).all()
            assert (
                arrays["retained_sample_count"] <= arrays["input_sample_count"][:, None]
            ).all()
        assert detection.mode.value == "auto"
