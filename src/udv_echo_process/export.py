"""Terminal-result JSON/CSV/NPZ export boundary (absorption plan §4, D4).

The retiring ``udv-analysis`` package wrote one run's terminal products as a
long-form profile CSV, a profile NPZ, a JSON summary plus a run manifest and a
cache fingerprint (its ``outputs.py``/``handoff.py``). This module absorbs **the
output shape only** (plan §4): it writes a fixed, versioned result set for the
terminal products this repo already owns —
:class:`~udv_echo_process.models.states.OperatingStateDetection` and
:class:`~udv_echo_process.models.profiles.RobustVelocityProfiles` — for one
channel. It is deliberately *not* a storage or provenance plane (plan D4, §5):

- there is no manifest, no cache fingerprint, no legacy/``v1`` reader and no
  ``ArtifactGraph``/store-1 involvement — bundle persistence stays in
  :mod:`udv_echo_process.storage`;
- nothing here mutates the bundle, the detection, the profiles or their
  provenance graph, and no artifact or operation id is created;
- the only paths that appear *inside* a written artifact are the bare, relative
  filenames of the set's own members (never a machine-absolute path).

The set has exactly three files, written under a caller-supplied directory:

``terminal_result.json``
    strict, finite JSON: the artifact/descriptor/geometry scalars, both settings
    blocks, the state-detection interval metadata, the units, the deviation
    definition and the relative filenames of the other members. It is serialized
    with ``allow_nan=False``, so a non-finite number is an error rather than an
    invalid JSON ``NaN``/``Infinity`` token.
``velocity_profiles.csv``
    long form, one row per retained state x depth gate, UTF-8 with an explicit
    ``\\n`` newline: state/interval identity, gate index, depth in mm, median in
    mm/s, **unscaled** median absolute deviation in mm/s, retained/input counts,
    the typed gate status and the explicit deviation definition. A cell whose
    statistic is legitimately absent (an ``empty_envelope`` gate) is written as
    the empty token :data:`CSV_EMPTY_VALUE`, never as ``nan`` text.
``terminal_arrays.npz``
    the ndarray payload, loadable with ``allow_pickle=False``: gate depths,
    profile times, retained state numbers, the ``(state, gate)`` median and MAD
    arrays, retained/input counts, the detector's ``variability`` and
    ``change_signal`` traces and the transition indices. IEEE ``NaN`` is
    retained here and means exactly an ``empty_envelope`` gate
    (``retained_sample_count == 0``); the CSV member records the same fact as an
    empty field.

The write is prepare-then-replace. The whole set is cross-checked and every
member's bytes are serialized before any file is created, then every member is
staged to a sibling temporary file before the first target is touched, so a
rejected input or a staging failure leaves the caller's directory untouched and
no partial member bytes behind. The final step is a per-member ``os.replace``
loop: each rename is atomic on its own, but replacing the *set* is **not** a
transaction — if the loop fails partway (for example a later rename fails), the
members already renamed hold the new bytes while the remaining ones still hold
the previous files, so the directory can be left holding a mixed set. That is
deliberate: there is no rollback/backup machinery, and the staged temporary
files are removed on the way out. There is no CLI and no TOML (plan D3).

The returned :class:`TerminalResultExport` is a narrow typed record of the
written paths; filesystem paths never enter a domain result model.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import model_validator

from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.identity import SignalQuantity
from udv_echo_process.models.profiles import RobustGateStatus, RobustVelocityProfiles
from udv_echo_process.models.states import (
    OperatingStateDetection,
    OperatingStateInterval,
)
from udv_echo_process.provenance import ChannelBundle

__all__ = [
    "ARRAYS_NPZ_FILENAME",
    "CSV_COLUMNS",
    "CSV_EMPTY_VALUE",
    "PROFILES_CSV_FILENAME",
    "RESULT_JSON_FILENAME",
    "TERMINAL_RESULT_SCHEMA",
    "TerminalResultExport",
    "TerminalResultExportError",
    "export_terminal_results",
]

#: The result set's own JSON schema name: one literal type and its single value,
#: so the export record's ``schema_name`` field cannot hold any other string.
TerminalResultSchemaName = Literal["udv-echo-process/terminal-result/v1"]

#: Versioned name of the result set's own JSON schema (not a run manifest).
TERMINAL_RESULT_SCHEMA: TerminalResultSchemaName = "udv-echo-process/terminal-result/v1"

#: Fixed on-disk member names. The JSON member names these relatively.
RESULT_JSON_FILENAME = "terminal_result.json"
PROFILES_CSV_FILENAME = "velocity_profiles.csv"
ARRAYS_NPZ_FILENAME = "terminal_arrays.npz"

#: The explicit CSV token for a legitimately absent statistic (an empty envelope).
CSV_EMPTY_VALUE = ""

#: Long-form profile CSV columns, in fixed order.
CSV_COLUMNS = (
    "state_number",
    "interval_number",
    "interval_start_index",
    "interval_stop_index_exclusive",
    "state_start_time_s",
    "state_end_time_s",
    "gate_index",
    "depth_mm",
    "median_velocity_mm_s",
    "mad_velocity_mm_s",
    "retained_sample_count",
    "input_sample_count",
    "gate_status",
    "deviation_definition",
)


class TerminalResultExportError(ValueError):
    """The inputs do not form a coherent exportable terminal result set."""


class TerminalResultExport(ValueModel):
    """The written terminal-result set, as concrete filesystem paths.

    A narrow export record — deliberately outside ``models/`` so no domain
    result carries a filesystem ``Path``. It is frozen, forbids extra fields and
    validates that the three members share one directory and its fixed names.
    """

    schema_name: TerminalResultSchemaName = TERMINAL_RESULT_SCHEMA
    directory: Path
    result_json: Path
    profiles_csv: Path
    arrays_npz: Path

    @model_validator(mode="after")
    def _check_members_are_canonical(self) -> TerminalResultExport:
        expected = (
            ("result_json", RESULT_JSON_FILENAME),
            ("profiles_csv", PROFILES_CSV_FILENAME),
            ("arrays_npz", ARRAYS_NPZ_FILENAME),
        )
        for field_name, filename in expected:
            path = getattr(self, field_name)
            if path.name != filename or path.parent != self.directory:
                raise ValueError(
                    f"{field_name} must be {self.directory / filename}, got {path}"
                )
        return self


def export_terminal_results(
    bundle: ChannelBundle,
    detection: OperatingStateDetection,
    profiles: RobustVelocityProfiles,
    *,
    directory: str | Path,
) -> TerminalResultExport:
    """Write the terminal-result JSON/CSV/NPZ set for one channel.

    Cross-checks the inputs as a coherent set (the bundle artifact, the
    detection and the profiles must name the same artifact and descriptor and
    agree on the ``(profile, gate)`` geometry, the retained states and their
    interval boundaries) and serializes every member before touching the
    filesystem. Nothing is mutated and no provenance/artifact id is created
    (plan D4).

    Args:
        bundle: the per-channel source bundle the results were computed from.
        detection: the operating-state detection of that same artifact.
        profiles: the robust velocity profiles of that same artifact; its
            retained states select the CSV rows.
        directory: the directory to write into; created when absent. Existing
            members are replaced one at a time (each rename atomic; the set as a
            whole is not transactional).

    Returns:
        A :class:`TerminalResultExport` naming the three written files.

    Raises:
        TypeError: an argument is not the expected type.
        TerminalResultExportError: the inputs disagree on artifact, descriptor,
            geometry or retained states, or the metadata is not strict finite
            JSON.
        OSError: for a filesystem failure while staging or replacing a member.
    """
    target = Path(directory)
    kept, depths, times = _cross_check(bundle, detection, profiles)
    metadata = _result_metadata(bundle, detection, profiles, kept, depths, times)
    payloads = {
        RESULT_JSON_FILENAME: _json_bytes(metadata),
        PROFILES_CSV_FILENAME: _csv_bytes(profiles, kept, depths),
        ARRAYS_NPZ_FILENAME: _npz_bytes(
            _npz_arrays(bundle, detection, profiles, depths, times)
        ),
    }
    target.mkdir(parents=True, exist_ok=True)
    _write_set(target, payloads)
    return TerminalResultExport(
        directory=target,
        result_json=target / RESULT_JSON_FILENAME,
        profiles_csv=target / PROFILES_CSV_FILENAME,
        arrays_npz=target / ARRAYS_NPZ_FILENAME,
    )


def _cross_check(
    bundle: object,
    detection: object,
    profiles: object,
) -> tuple[tuple[OperatingStateInterval, ...], np.ndarray, np.ndarray]:
    """Return ``(kept intervals, gate depths, profile times)`` or refuse.

    The narrowest boundary that proves the three objects describe one channel:
    equal artifact ids, an equal axial-velocity descriptor, matching payload and
    gate/profile axes, and retained state numbers / intervals / input counts that
    agree exactly with the detection's kept intervals. The interval comparison is
    what binds the result to *one* detection: the counts alone are not unique.
    """
    if not isinstance(bundle, ChannelBundle):
        raise TypeError(
            f"export_terminal_results expects a ChannelBundle, got "
            f"{type(bundle).__name__}"
        )
    if not isinstance(detection, OperatingStateDetection):
        raise TypeError(
            f"export_terminal_results expects an OperatingStateDetection, got "
            f"{type(detection).__name__}"
        )
    if not isinstance(profiles, RobustVelocityProfiles):
        raise TypeError(
            f"export_terminal_results expects a RobustVelocityProfiles, got "
            f"{type(profiles).__name__}"
        )

    artifact = bundle.artifact
    if artifact.descriptor != detection.descriptor:
        raise TerminalResultExportError(
            "the bundle artifact and the detection must describe the same "
            f"channel: descriptor {artifact.descriptor.model_dump()!r} vs "
            f"{detection.descriptor.model_dump()!r}"
        )
    if artifact.descriptor != profiles.descriptor:
        raise TerminalResultExportError(
            "the bundle artifact and the profiles must describe the same "
            f"channel: descriptor {artifact.descriptor.model_dump()!r} vs "
            f"{profiles.descriptor.model_dump()!r}"
        )
    for label, found in (
        ("detection", detection.artifact_id),
        ("profiles artifact", profiles.artifact_id),
        ("profiles detection artifact", profiles.detection_artifact_id),
    ):
        if found != artifact.artifact_id:
            raise TerminalResultExportError(
                "every result must name the bundle's artifact: bundle is "
                f"{artifact.artifact_id!r} but {label} is {found!r}"
            )
    if artifact.descriptor.quantity is not SignalQuantity.AXIAL_VELOCITY:
        raise TerminalResultExportError(
            "terminal-result export is defined for an axial-velocity channel, "
            f"got {artifact.descriptor.quantity.value!r}"
        )

    values = artifact.data.values
    expected_shape = (detection.profile_count, detection.gate_count)
    if values.shape != expected_shape:
        raise TerminalResultExportError(
            "the payload shape must match the detection's profile x gate "
            f"geometry: payload is {values.shape}, detection is {expected_shape}"
        )
    if profiles.gate_count != detection.gate_count:
        raise TerminalResultExportError(
            "the profiles and the detection must agree on the gate axis: "
            f"profiles have {profiles.gate_count}, detection has "
            f"{detection.gate_count}"
        )
    depths = artifact.data.gate_depths_mm
    if depths.shape != (detection.gate_count,):
        raise TerminalResultExportError(
            "gate_depths_mm must have one entry per gate: expected "
            f"({detection.gate_count},), got {depths.shape}"
        )
    times = artifact.data.time_s
    if times.shape != (detection.profile_count,):
        raise TerminalResultExportError(
            "time_s must have one entry per profile: expected "
            f"({detection.profile_count},), got {times.shape}"
        )

    kept = tuple(interval for interval in detection.intervals if interval.kept)
    state_numbers = tuple(interval.state_number for interval in kept)
    if state_numbers != profiles.state_numbers:
        raise TerminalResultExportError(
            "the profiles' state_numbers must be the detection's retained "
            f"states in order: detection has {state_numbers}, profiles have "
            f"{profiles.state_numbers}"
        )
    if profiles.retained_intervals != kept:
        raise TerminalResultExportError(
            "the profiles' retained_intervals must be exactly the detection's "
            "kept intervals, boundaries included (artifact_id, state_numbers "
            "and input_sample_count alone cannot tell two detections of one "
            "artifact apart when a shifted transition preserves every count): "
            "detection has "
            f"{[(i.start_index, i.stop_index_exclusive) for i in kept]}, "
            "profiles have "
            f"{[(i.start_index, i.stop_index_exclusive) for i in profiles.retained_intervals]}"
        )
    expected_profile_shape = (len(kept), detection.gate_count)
    for field_name in (
        "median_velocity_mm_s",
        "median_absolute_deviation_mm_s",
        "retained_sample_count",
    ):
        shape = getattr(profiles, field_name).shape
        if shape != expected_profile_shape:
            raise TerminalResultExportError(
                f"{field_name} must have shape {expected_profile_shape} "
                f"(retained state x gate), got {shape}"
            )
    inputs = tuple(int(count) for count in profiles.input_sample_count)
    interval_counts = tuple(interval.profile_count for interval in kept)
    if inputs != interval_counts:
        raise TerminalResultExportError(
            "input_sample_count must be the retained states' profile counts: "
            f"detection has {interval_counts}, profiles have {inputs}"
        )
    return kept, depths, times


def _result_metadata(
    bundle: ChannelBundle,
    detection: OperatingStateDetection,
    profiles: RobustVelocityProfiles,
    kept: tuple[OperatingStateInterval, ...],
    depths: np.ndarray,
    times: np.ndarray,
) -> dict[str, object]:
    """Build the JSON metadata object in a deterministic field order."""
    artifact = bundle.artifact
    descriptor = artifact.descriptor
    acquisition = artifact.acquisition
    return {
        "schema": TERMINAL_RESULT_SCHEMA,
        "artifact": {
            "artifact_id": artifact.artifact_id,
            "recording_id": acquisition.recording_id,
            "source_asset_id": acquisition.source_asset_id,
            "device_channel": acquisition.channel.device_channel,
            "descriptor": descriptor.model_dump(mode="json"),
        },
        "geometry": {
            "profile_count": detection.profile_count,
            "gate_count": detection.gate_count,
            "state_count": len(kept),
            "time_step_s": detection.time_step_s,
            "gate_spacing_mm": detection.gate_spacing_mm,
            "time_range_s": [float(times[0]), float(times[-1])],
            "depth_range_mm": [float(depths[0]), float(depths[-1])],
        },
        "units": {"time": "s", "depth": "mm", "velocity": "mm/s", "deviation": "mm/s"},
        "deviation_definition": profiles.deviation_definition,
        "csv_empty_value": CSV_EMPTY_VALUE,
        "state_detection": {
            "mode": detection.mode.value,
            "settings": detection.settings.model_dump(mode="json"),
            "base_threshold": detection.base_threshold,
            "applied_threshold": detection.applied_threshold,
            "peak_prominence": detection.peak_prominence,
            "intervals": [
                interval.model_dump(mode="json") for interval in detection.intervals
            ],
        },
        "profiles": {
            "settings": profiles.settings.model_dump(mode="json"),
            "state_numbers": list(profiles.state_numbers),
        },
        "files": {
            "result_json": RESULT_JSON_FILENAME,
            "profiles_csv": PROFILES_CSV_FILENAME,
            "arrays_npz": ARRAYS_NPZ_FILENAME,
        },
    }


def _finite_text(value: float, *, empty_ok: bool = False) -> str:
    """Round-trippable decimal text, refusing a non-finite value by default.

    ``empty_ok`` is passed only where the caller has *already* established that
    the statistic is legitimately absent — the median/deviation cell of an
    ``empty_envelope`` gate, whose ``NaN`` the result model pins to that status.
    Everywhere else (depths, interval times, a non-empty statistic) a
    non-finite value is an error rather than a silently empty field, so the
    generic "non-finite becomes empty" masking cannot hide a real defect.
    """
    number = float(value)
    if not math.isfinite(number):
        if not empty_ok:
            raise TerminalResultExportError(
                "a finite value is required for this CSV cell, got "
                f"{number!r}; only an established empty_envelope statistic is "
                f"written as the empty token {CSV_EMPTY_VALUE!r}"
            )
        return CSV_EMPTY_VALUE
    return format(number, ".17g")


def _json_bytes(payload: object) -> bytes:
    """Serialize strict, finite, UTF-8 JSON with a trailing newline."""
    try:
        text = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    except ValueError as exc:
        raise TerminalResultExportError(
            f"terminal-result metadata is not strict finite JSON: {exc}"
        ) from exc
    return (text + "\n").encode("utf-8")


def _csv_bytes(
    profiles: RobustVelocityProfiles,
    kept: tuple[OperatingStateInterval, ...],
    depths: np.ndarray,
) -> bytes:
    """Serialize the long-form profile rows (state-major, gate order)."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    median = profiles.median_velocity_mm_s
    deviation = profiles.median_absolute_deviation_mm_s
    retained = profiles.retained_sample_count
    inputs = profiles.input_sample_count
    statuses = profiles.gate_status
    for row, (state_number, interval) in enumerate(
        zip(profiles.state_numbers, kept, strict=True)
    ):
        for gate in range(profiles.gate_count):
            absent = statuses[row][gate] is RobustGateStatus.EMPTY_ENVELOPE
            writer.writerow(
                [
                    str(state_number),
                    str(interval.interval_number),
                    str(interval.start_index),
                    str(interval.stop_index_exclusive),
                    _finite_text(interval.start_time_s),
                    _finite_text(interval.end_time_s),
                    str(gate),
                    _finite_text(float(depths[gate])),
                    _finite_text(float(median[row, gate]), empty_ok=absent),
                    _finite_text(float(deviation[row, gate]), empty_ok=absent),
                    str(int(retained[row, gate])),
                    str(int(inputs[row])),
                    statuses[row][gate].value,
                    profiles.deviation_definition,
                ]
            )
    return buffer.getvalue().encode("utf-8")


def _npz_arrays(
    bundle: ChannelBundle,
    detection: OperatingStateDetection,
    profiles: RobustVelocityProfiles,
    depths: np.ndarray,
    times: np.ndarray,
) -> dict[str, np.ndarray]:
    """Assemble the NPZ members in a fixed key order."""
    return {
        "gate_depths_mm": depths,
        "profile_time_s": times,
        "state_numbers": np.asarray(profiles.state_numbers, dtype=np.int64),
        "median_velocity_mm_s": profiles.median_velocity_mm_s,
        "median_absolute_deviation_mm_s": profiles.median_absolute_deviation_mm_s,
        "retained_sample_count": profiles.retained_sample_count,
        "input_sample_count": profiles.input_sample_count,
        "variability": detection.variability,
        "change_signal": detection.change_signal,
        "transition_indices": detection.transition_indices,
    }


def _npz_bytes(arrays: Mapping[str, np.ndarray]) -> bytes:
    """Serialize the ndarray payload as a picklable-disabled ``.npz``."""
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    return buffer.getvalue()


def _write_set(directory: Path, payloads: Mapping[str, bytes]) -> None:
    """Stage every member, then atomically replace each target in turn.

    All members are written to sibling temporary files before the first target
    is replaced, so a serialization or staging failure leaves the caller's
    directory untouched and no partial member behind. The replace loop itself is
    *not* a transaction: each ``os.replace`` is atomic on its own, but a failure
    after some renames have landed leaves those members holding the new bytes
    and the remaining ones holding the previous files (a mixed set). The staged
    temporary files are unlinked on the way out; nothing is rolled back.
    """
    staged: list[tuple[str, Path]] = []
    try:
        for name, raw in payloads.items():
            descriptor, temporary = tempfile.mkstemp(
                dir=directory, prefix=f".{name}.", suffix=".tmp"
            )
            temporary_path = Path(temporary)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
            except BaseException:
                temporary_path.unlink(missing_ok=True)
                raise
            staged.append((name, temporary_path))
        for name, temporary_path in staged:
            os.replace(temporary_path, directory / name)
    except BaseException:
        for _, temporary_path in staged:
            temporary_path.unlink(missing_ok=True)
        raise
