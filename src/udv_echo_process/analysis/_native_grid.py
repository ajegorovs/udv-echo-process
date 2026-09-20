"""Axis-agnostic native-grid, axis-input and pairwise support for the WP2 axes.

Shared by :mod:`udv_echo_process.analysis.resolution_ladder` and
:mod:`udv_echo_process.analysis.burst_ladder`, and by the PRF and TGC/power axes of
the same plan when they land. Nothing here knows which manifest axis it serves or what
a row's key column is called: the callers name their axis, their ladder and their key,
and hand this module decoded grids.

What it carries: the scientific-fingerprint layer (:data:`FINGERPRINT_FIELDS`,
:data:`DERIVED_FINGERPRINT_CELLS`, :class:`AxisEligibility`, :class:`LevelGroup`,
:func:`level_groups`), the axis-input layer (:func:`read_decoded_level`,
:func:`requested_axis_rows`, :func:`select_axis_rows`, :func:`require_clean_ofat`), the
common views (:func:`window`, :func:`common_support`), the native-grid metrics
(:func:`level_metrics`, :func:`spatial_gradient`, :func:`correlation_length`), the
pairwise alignment (:func:`align_on_knots`, :func:`depth_ranges`), the committed WP1
screening_threshold and temporal-floor readers (:func:`read_screening_threshold`,
:func:`read_temporal_floor`), the ladder shape (:func:`largest_step`, :func:`knees`)
and the deterministic writers (:func:`csv_text`, :func:`wrap_caption`,
:func:`write_text_artefacts`, :func:`panel_figure`).

An axis selects its recordings by their **decoded scientific settings**, never by the
folder they sit in: :class:`AxisEligibility` declares which fingerprint fields that
axis's key may move *and* which fall out of it as derived, every recording agreeing on
the rest is eligible, and recordings sharing one decoded key are the *realizations* of
one level rather than a duplicate-key refusal (plan §8.3 steps 2 and 5).

``NativeGridError`` is the error class every consumer re-exports under its own name
(``ResolutionLadderError``, ``BurstLadderError``), so a caller catches a helper refusal
and an axis refusal with one name.
"""

from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis.reference_repeat import gate_metrics
from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.io import load
from udv_echo_process.models.base import ValueModel
from udv_echo_process.models.channel_config import ChannelConfig


class GradientStats(ValueModel):
    """Native-grid gate-to-gate gradient of one level's supported mean profile:
    ``|Δ mean| / pitch`` in mm/s per mm on the level's own grid, at the interval midpoint.
    """

    pitch_mm: float
    intervals: int
    median_abs_mm_s_per_mm: float
    max_abs_mm_s_per_mm: float
    max_depth_mm: float


class CorrelationStats(ValueModel):
    """Native-grid spatial correlation length of the same mean profile: the first
    lag whose normalized native autocovariance falls below 1/e, or the lag cap (a lower bound)
    when it does not.
    """

    pitch_mm: float
    floor: float
    length_mm: float
    lag_max_mm: float
    lag_cap_gates: int
    reaches_floor: bool


class ScreeningThresholdBinding(ValueModel):
    """The committed sole-pair observed-discrepancy screening threshold an axis screens against:
    ``value_mm_s`` is the largest absolute per-gate mean difference of the only same-settings
    repeat: the screening threshold every mean-profile effect is compared with. It does not bound
    repeatability and does not bound uncontrolled drift.
    """

    path: str
    source_sha256: str
    metric: str
    units: str
    value_mm_s: float
    gate_index: int
    depth_mm: float
    median_abs_mean_difference_mm_s: float
    scope: str
    role: str = (
        "decision threshold: an effect smaller than this bound is not "
        "distinguishable from repeat-plus-drift"
    )


class NativeGridError(ValueError):
    """A WP2 axis input is not the ladder the plan describes: a manifest, a
    recording, a committed WP1 artefact or a pair the axis cannot bind. The command turns it into
    a non-zero exit naming the reason, never a traceback.
    """


class DecodedLevel(NamedTuple):
    """One manifest-selected recording: its manifest-pinned row, arrays and decoded cells.

    ``pitch_mm`` is the recording's own realised pitch; ``observed`` holds the decoded value of
    every :data:`DECODED_CELLS` key, which the row's cells are re-checked against.
    """

    relative_path: str
    axis: str
    requested_label: str
    source_sha256: str
    pitch_mm: float
    config: ChannelConfig
    values: np.ndarray
    time_s: np.ndarray
    depths: np.ndarray
    observed: dict[str, object]


class LevelMetrics(NamedTuple):
    """One level's common-window numbers on its own native grid.

    ``per_gate`` holds WP1's distributions over the whole window; ``mask`` is the supported-gate
    mask, and ``means``/``supported`` are those numbers restricted to it.
    """

    profiles_window: int
    supported_gates: int
    per_gate: dict[str, np.ndarray]
    mask: np.ndarray
    means: np.ndarray
    supported: np.ndarray
    gradient: GradientStats
    correlation: CorrelationStats


class KnotAlignment(NamedTuple):
    """Two levels aligned on the coarser participant's own knots: ``absolute`` is the
    per-knot ``|sampled - knot|``, ``flagged`` the knots clearing the threshold, ``worst`` the
    largest one, ``offset_mm`` the largest gate offset used.
    """

    knots: np.ndarray
    indices: np.ndarray
    absolute: np.ndarray
    flagged: np.ndarray
    worst: int
    offset_mm: float
    sampled_variance: float


CORRELATION_FLOOR = 1.0 / math.e

#: The plan's stated common physical support, with the tolerance its wording allows.
GRID_UNIFORMITY_RTOL = 1e-6
TOLERANCE_S = 1e-9

#: The WP1 screening_threshold metric every axis compares to, as its provenance records it.
SCREENING_THRESHOLD_METRIC = "max_gate_abs_mean_difference_mm_s"

#: A recording's **scientific fingerprint**: the independent decoded configuration settings the
#: WP0 inventory publishes, in manifest column order (plan §8.3 step 2, R4). The shape, duration
#: and depth support, the velocity range and the data-quality counters are deliberately absent -
#: they are the observation extent, and two realizations of one decoded level may differ in them.
FINGERPRINT_FIELDS: tuple[str, ...] = (
    "emit_freq_khz",
    "prf_period_us",
    "burst_length",
    "emissions_per_profile",
    "emit_power",
    "sensitivity",
    "resolution_mm",
    "sampling_volume_index",
    "sound_speed_ms",
    "doppler_angle_deg",
    "tgc_mode",
    "tgc_start_db",
    "tgc_end_db",
    "skipped_profiles",
)

#: Decoded cells that *follow* from the fingerprint rather than standing beside it: the PRF in Hz
#: and the reader's ±Nyquist velocity (``c / (4 f0 T_prf)``). An axis whose key defines them names
#: them in :attr:`AxisEligibility.derived`, and they then leave that axis's identity.
DERIVED_FINGERPRINT_CELLS: tuple[str, ...] = ("prf_hz", "velo_max_ms")

#: What was *recorded* rather than how the instrument was configured: published beside the
#: fingerprint (the two reference recordings differ here and nowhere else), never compared as part
#: of it.
OBSERVATION_EXTENT_CELLS: tuple[str, ...] = (
    "profiles",
    "gates",
    "duration_s",
    "depth_min_mm",
    "depth_max_mm",
)

#: Every decoded cell the WP0 inventory publishes for a recording, in row-column order: shape and
#: timing, the depth support and the acquisition settings (R4 - a fingerprint cell an axis does not
#: re-check cannot be compared). An axis re-checks the cells it depends on; the full set is the
#: default.
DECODED_CELLS: tuple[str, ...] = (
    "profiles",
    "gates",
    "duration_s",
    "depth_min_mm",
    "depth_max_mm",
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
)


def sha256_file(path: Path) -> str:
    """The SHA-256 of a file's bytes, hex, as the WP0 manifest records it.
    """
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observed_cells(
    values: np.ndarray, time_s: np.ndarray, depths: np.ndarray, config: ChannelConfig
) -> dict[str, object]:
    """The decoded value of every :data:`DECODED_CELLS` key, ready to be compared
    with the manifest's cells, so every axis compares like for like.
    """
    return {
        "profiles": int(values.shape[0]),
        "gates": int(values.shape[1]),
        "duration_s": float(time_s[-1] - time_s[0]),
        "depth_min_mm": float(depths[0]),
        "depth_max_mm": float(np.max(depths)),
        "emit_freq_khz": config.source_freq_khz,
        "prf_period_us": 1e6 / float(config.pulse_repetition_freq_hz),
        "prf_hz": config.pulse_repetition_freq_hz,
        "burst_length": config.burst_length,
        "emissions_per_profile": config.emissions_per_profile,
        "emit_power": config.emit_power,
        "sensitivity": config.sensitivity,
        "resolution_mm": config.resolution_mm,
        "sampling_volume_index": config.sampling_volume_index,
        "sound_speed_ms": config.sound_speed_ms,
        "doppler_angle_deg": config.doppler_angle_deg,
        "velo_max_ms": config.velo_max_ms,
        "tgc_mode": config.tgc_mode,
        "tgc_start_db": config.tgc_start_db,
        "tgc_end_db": config.tgc_end_db,
        "skipped_profiles": config.skipped_profiles,
    }


def canonical_cell(cell: object) -> str:
    """One manifest cell as it compares: empty stays empty, a number becomes the number it is
    (``1.85`` and ``1.850000000000`` are one setting), and a label passes through stripped.
    """
    text = str("" if cell is None else cell).strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    return format_cell(number)


def _is_decoded_cell(cell: str) -> bool:
    """True when a cell is a usable decoded setting: non-empty, and finite when it is numeric.
    """
    if not cell:
        return False
    try:
        number = float(cell)
    except ValueError:
        return True
    return math.isfinite(number)


def fingerprint_cells(row: Mapping[str, str]) -> dict[str, str]:
    """One row's full scientific fingerprint: every :data:`FINGERPRINT_FIELDS` cell beside the
    :data:`DERIVED_FINGERPRINT_CELLS` that follow from them.

    Strict on purpose: the fingerprint of a recording an axis *uses* is read from decoded settings,
    so a blank or non-finite cell is refused by name rather than compared as text (plan §8.3 step 2).
    """
    return {
        field: decoded_fingerprint_cell(row, field)
        for field in FINGERPRINT_FIELDS + DERIVED_FINGERPRINT_CELLS
    }


def decoded_fingerprint_cell(row: Mapping[str, str], field: str) -> str:
    """One cell of a row's fingerprint, refused when it is empty or not a finite decoded setting.
    """
    cell = canonical_cell(row.get(field))
    if not _is_decoded_cell(cell):
        raise NativeGridError(
            f"{row.get('relative_path') or '?'}: manifest {field}={row.get(field)!r} is empty or "
            "not a finite decoded setting; a scientific fingerprint is read from decoded settings, "
            "never from a blank or non-numeric cell"
        )
    return cell


def observation_text(row: Mapping[str, str]) -> dict[str, str]:
    """The row's observation extent as it recorded it: shape, duration and depth support, which
    two realizations of one decoded level may differ in (plan §2).
    """
    return {cell: canonical_cell(row.get(cell)) for cell in OBSERVATION_EXTENT_CELLS}


class AxisEligibility(ValueModel):
    """One axis's declared setting-based contract (plan §8.3 step 2, R1/R4): the fingerprint fields
    its key is allowed to move (``varied``), the derived cells that follow from that key
    (``derived``) and, by exclusion, the ``identity_fields`` every eligible recording must share
    whatever folder it sits in.

    The contract is declared data, never a folder name: it is what lets ``prf/600.BDD`` realize the
    resolution axis's 1.850 mm level and ``res/1-8.BDD`` the PRF axis's 600 µs level.
    """

    axis: str
    ladder_label: str
    varied: tuple[str, ...]
    derived: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_the_contract_is_declared_over_the_fingerprint(self) -> AxisEligibility:
        if not self.varied:
            raise ValueError(f"the {self.axis} contract must name at least one varied field")
        for field in self.varied:
            if field not in FINGERPRINT_FIELDS:
                raise ValueError(
                    f"{field!r} is not a fingerprint field: {list(FINGERPRINT_FIELDS)}"
                )
        for field in self.derived:
            if field not in DERIVED_FINGERPRINT_CELLS:
                raise ValueError(
                    f"{field!r} is not a derived fingerprint cell: "
                    f"{list(DERIVED_FINGERPRINT_CELLS)}"
                )
        return self

    @property
    def identity_fields(self) -> tuple[str, ...]:
        """The settings every eligible recording must share: the fingerprint and its derived cells
        minus whatever this axis is allowed to move.
        """
        moved = set(self.varied) | set(self.derived)
        return tuple(
            field for field in FINGERPRINT_FIELDS + DERIVED_FINGERPRINT_CELLS if field not in moved
        )


class LevelRealization(ValueModel):
    """One recording that realizes a decoded level: its own path and hash, the folder that
    requested it, its full fingerprint and its observation extent. Never collapsed into another
    realization's path (plan §8.3 step 2).
    """

    relative_path: str
    requested_axis: str
    requested_label: str
    source_sha256: str
    own_axis: bool
    fingerprint: dict[str, str]
    extent: dict[str, str]


class LevelGroup(ValueModel):
    """One decoded level of one axis: its key (the varied cells), the identity every realization
    shares, and every recording that realizes it, in manifest order.

    ``in_ladder`` is True when the axis itself requested at least one realization. The committed
    ladders are still built from those requested levels; a level realized only elsewhere is recorded
    here - with both of the reference recordings when they share it - for the setting-based rebuild
    of plan §8.3 step 5 rather than silently dropped.
    """

    axis: str
    ladder_label: str
    key_fields: tuple[str, ...]
    key: tuple[str, ...]
    key_display: str
    identity: dict[str, str]
    primary_path: str
    realizations: tuple[LevelRealization, ...]
    in_ladder: bool

    @model_validator(mode="after")
    def _check_the_group_holds_its_primary_and_one_key(self) -> LevelGroup:
        if self.key_fields != tuple(
            field for field in self.key_fields if field in FINGERPRINT_FIELDS
        ) or not self.key_fields:
            raise ValueError("a level is keyed by at least one fingerprint field")
        if len(self.key) != len(self.key_fields):
            raise ValueError(
                f"{len(self.key_fields)} key field(s) need {len(self.key_fields)} key value(s), "
                f"got {len(self.key)}"
            )
        paths = [item.relative_path for item in self.realizations]
        if not paths or len(set(paths)) != len(paths):
            raise ValueError("a level holds at least one distinct realization per recording")
        if self.primary_path not in paths:
            raise ValueError(f"the primary {self.primary_path!r} must be one of the realizations")
        if self.in_ladder != any(item.own_axis for item in self.realizations):
            raise ValueError("a level is in the ladder exactly when the axis requested one of it")
        return self

    @property
    def realization_paths(self) -> tuple[str, ...]:
        """Every recording realizing this level, in manifest order.
        """
        return tuple(item.relative_path for item in self.realizations)

    @property
    def requested_paths(self) -> tuple[str, ...]:
        """The realizations this axis itself requested.
        """
        return tuple(item.relative_path for item in self.realizations if item.own_axis)


def read_decoded_level(
    dataset_root: Path, row: Mapping[str, str], *, cells: Sequence[str] = DECODED_CELLS
) -> DecodedLevel:
    """Decode one manifest-selected recording and bind it to its row.

    Refuses a row without a usable path or file, bytes that do not reproduce the recorded hash, a
    payload that is not one 2-D axial-velocity channel in ``mm/s``, NaNs, a grid that is not the
    recording's own uniform increasing grid at its recorded pitch, and any cell in ``cells`` that
    disagrees with the decoded value: a stale inventory must not be analysed by one axis and
    caught by another.
    """
    relative = row.get("relative_path") or ""
    path = Path(dataset_root) / relative
    if not relative or not path.is_file():
        raise NativeGridError(f"manifest row {relative!r} is not a file at {path}")
    actual = sha256_file(path)
    recorded = (row.get("source_sha256") or "").strip()
    if recorded != actual:
        raise NativeGridError(
            f"source sha256 mismatch for {relative}: manifest records {recorded!r}, "
            f"file hashes to {actual!r}"
        )
    recording = load(path).recording
    if recording.source_asset.content_sha256 != actual:
        raise NativeGridError(
            f"{relative}: the reader's content hash "
            f"{recording.source_asset.content_sha256!r} is not the file hash {actual!r}"
        )
    if len(recording.streams) != 1:
        raise NativeGridError(
            f"{relative}: expected exactly one channel stream, found {len(recording.streams)}"
        )
    stream = recording.streams[0]
    values = np.asarray(stream.data.values, dtype=float)
    time_s = np.asarray(stream.data.time_s, dtype=float)
    depths = np.asarray(stream.data.gate_depths_mm, dtype=float)
    if stream.descriptor.unit != "mm/s" or values.ndim != 2:
        raise NativeGridError(
            f"{relative}: expected a 2-D axial-velocity array in mm/s, got {values.ndim}-D "
            f"in {stream.descriptor.unit!r}"
        )
    if np.count_nonzero(np.isnan(values)):
        raise NativeGridError(f"{relative}: the velocity array carries NaNs")
    config = stream.config
    observed = observed_cells(values, time_s, depths, config)
    for cell in cells:
        if (row.get(cell) or "") != format_cell(observed[cell]):
            raise NativeGridError(
                f"{relative}: manifest {cell}={row.get(cell)!r} does not match the decoded "
                f"{cell}={format_cell(observed[cell])!r}; the comparison must not run on a "
                "stale inventory"
            )
    if depths.size < 2:
        raise NativeGridError(f"{relative}: the gate grid holds {depths.size} gate(s)")
    steps = np.diff(depths)
    pitch = float(steps.mean())
    if not np.all(steps > 0.0) or not math.isfinite(pitch) or pitch <= 0.0:
        raise NativeGridError(
            f"{relative}: the native gate depths must increase strictly, got steps including "
            f"{steps.min()!r}"
        )
    deviation = float(np.abs(steps - pitch).max())
    if deviation > GRID_UNIFORMITY_RTOL * pitch:
        raise NativeGridError(
            f"{relative}: the native gate grid is not uniform: steps deviate by "
            f"{deviation:.3g} mm from the {pitch:g} mm mean pitch"
        )
    if not math.isclose(pitch, float(config.resolution_mm), rel_tol=1e-6):
        raise NativeGridError(
            f"{relative}: the decoded gate pitch {pitch!r} is not the manifest's "
            f"resolution_mm {config.resolution_mm!r}"
        )
    return DecodedLevel(
        relative_path=relative,
        axis=row.get("axis") or "",
        requested_label=row.get("requested_label") or "",
        source_sha256=actual,
        pitch_mm=pitch,
        config=config,
        values=values,
        time_s=time_s,
        depths=depths,
        observed=observed,
    )


def requested_axis_rows(
    manifest_path: Path, axis: str, *, ladder_label: str
) -> tuple[dict[str, str], ...]:
    """Every manifest row the *axis itself* requested, in file order.

    The axis's own request is bound to the WP0 manifest, never to a hand-maintained filename list,
    and this is the request - not the eligibility rule: whether a recording may realize one of the
    axis's levels is decided by the decoded fingerprint (plan §8.3 step 2), so a same-settings file
    recorded under another folder is still eligible. Refuses a missing or unreadable manifest, an
    axis the inventory holds no rows for, a row without a relative path, and a repeated path.
    """
    path = Path(manifest_path)
    rows = _manifest_rows(path)
    selected = [row for row in rows if (row.get("axis") or "") == axis]
    if not selected:
        raise NativeGridError(
            f"manifest {path} holds no {axis} rows; the {ladder_label} ladder is selected "
            "from the WP0 inventory, never from a filename list"
        )
    counts: dict[str, int] = {}
    for row in selected:
        relative = (row.get("relative_path") or "").strip()
        if not relative:
            raise NativeGridError(
                f"manifest {path} holds a {axis} row without a relative_path"
            )
        counts[relative] = counts.get(relative, 0) + 1
    for relative, count in counts.items():
        if count != 1:
            raise NativeGridError(
                f"manifest {path} must hold exactly one row for {relative!r}, found {count}"
            )
    return tuple(selected)


def _manifest_rows(manifest_path: Path) -> tuple[dict[str, str], ...]:
    """Every manifest row, or a named refusal: the whole inventory, never one file.
    """
    path = Path(manifest_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise NativeGridError(f"cannot read the manifest {path}: {exc}") from exc
    return tuple(csv.DictReader(text.splitlines()))


def _require_decoded_row(row: Mapping[str, str]) -> None:
    """Refuse a row the inventory recorded as undecoded: a ladder is built from decoded recordings.
    """
    if row.get("decode_error"):
        raise NativeGridError(
            f"{row['relative_path']}: the manifest records "
            f"decode_error={row['decode_error']!r}; a ladder must be selected from "
            "decoded recordings"
        )


def key_cells(eligibility: AxisEligibility, row: Mapping[str, str]) -> tuple[str, ...]:
    """One row's decoded level key: the varied cells, refused when a cell is not a decoded setting.
    """
    return tuple(
        decoded_fingerprint_cell(row, field) for field in eligibility.varied
    )


def identity_text(eligibility: AxisEligibility, row: Mapping[str, str]) -> tuple[str, ...]:
    """The row's identity as it compares: the values of every ``identity_fields`` cell, in contract
    order. A blank cell stays blank and so matches no decoded identity.
    """
    return tuple(canonical_cell(row.get(field)) for field in eligibility.identity_fields)


def _level_groups_and_rows(
    manifest_path: Path,
    *,
    eligibility: AxisEligibility,
    order_key: Callable[[Mapping[str, str]], float],
    order_label: str,
) -> tuple[tuple[LevelGroup, ...], dict[str, dict[str, str]]]:
    """The grouping both public readers share: every eligible decoded level, and every row by path.

    The axis's own requested rows anchor the identity: they must carry one scientific fingerprint
    apart from the varied fields, and every manifest row agreeing with them on the identity is
    eligible whatever folder it sits in. Eligible rows sharing one key are the realizations of one
    level; the level's primary is the first realization the axis itself requested, or the first in
    manifest order for a level only another folder requested.
    """
    rows = _manifest_rows(Path(manifest_path))
    requested = requested_axis_rows(
        manifest_path, eligibility.axis, ladder_label=eligibility.ladder_label
    )
    for row in requested:
        _require_decoded_row(row)
        # The axis's own key first, so a requested row without a usable key is refused in the
        # axis's own terms (a pitch, a cycle count) rather than as a bare fingerprint cell.
        order_key(row)
    anchor = requested[0]
    anchor_fingerprint = fingerprint_cells(anchor)
    anchor_identity = {field: anchor_fingerprint[field] for field in eligibility.identity_fields}
    for row in requested[1:]:
        cells = fingerprint_cells(row)
        moved = sorted(
            field for field in eligibility.identity_fields if cells[field] != anchor_identity[field]
        )
        if moved:
            field = moved[0]
            raise NativeGridError(
                f"{row['relative_path']}: manifest {field}={row.get(field)!r} does not match the "
                f"decoded {field}={anchor_identity[field]!r} the {eligibility.ladder_label} ladder "
                f"holds ({anchor['relative_path']}); the {eligibility.axis} rows must share one "
                f"scientific fingerprint apart from {list(eligibility.varied)}, and this ladder "
                f"varies only its {order_label}"
            )
    wanted = identity_text(eligibility, anchor)
    eligible = [row for row in rows if identity_text(eligibility, row) == wanted]
    for row in eligible:
        _require_decoded_row(row)
    members: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for row in eligible:
        members.setdefault(key_cells(eligibility, row), []).append(row)
    requested_paths = {row["relative_path"] for row in requested}
    groups: list[LevelGroup] = []
    for key, sharing in members.items():
        primary = next(
            (row for row in sharing if row["relative_path"] in requested_paths), sharing[0]
        )
        groups.append(
            LevelGroup(
                axis=eligibility.axis,
                ladder_label=eligibility.ladder_label,
                key_fields=eligibility.varied,
                key=key,
                key_display=", ".join(
                    f"{field}={value}"
                    for field, value in zip(eligibility.varied, key, strict=True)
                ),
                identity=dict(anchor_identity),
                primary_path=primary["relative_path"],
                realizations=tuple(
                    LevelRealization(
                        relative_path=row["relative_path"],
                        requested_axis=row.get("axis") or "",
                        requested_label=row.get("requested_label") or "",
                        source_sha256=row.get("source_sha256") or "",
                        own_axis=row["relative_path"] in requested_paths,
                        fingerprint={
                            field: canonical_cell(row.get(field))
                            for field in FINGERPRINT_FIELDS + DERIVED_FINGERPRINT_CELLS
                        },
                        extent=observation_text(row),
                    )
                    for row in sharing
                ),
                in_ladder=any(row["relative_path"] in requested_paths for row in sharing),
            )
        )
    by_path = {row["relative_path"]: row for row in rows}
    return (
        tuple(
            sorted(
                groups,
                key=lambda group: (order_key(by_path[group.primary_path]), group.primary_path),
            )
        ),
        by_path,
    )


def level_groups(
    manifest_path: Path,
    *,
    eligibility: AxisEligibility,
    order_key: Callable[[Mapping[str, str]], float],
    order_label: str,
) -> tuple[LevelGroup, ...]:
    """Every eligible decoded level of one axis, ordered by its decoded key then by path.

    Eligibility is the decoded scientific fingerprint, never the folder a row sits in
    (plan §8.3 step 2, R1): every recording agreeing with the axis's own rows on the non-varied
    fields realizes the level its key names, and a level realized by two recordings is one level
    with two named realizations, not a duplicate key to refuse.
    """
    return _level_groups_and_rows(
        Path(manifest_path),
        eligibility=eligibility,
        order_key=order_key,
        order_label=order_label,
    )[0]


def select_axis_rows(
    manifest_path: Path,
    *,
    eligibility: AxisEligibility,
    order_key: Callable[[Mapping[str, str]], float],
    order_label: str,
) -> tuple[dict[str, str], ...]:
    """The representative row of every level the axis itself requested, by decoded key then path.

    ``order_key`` reads the row's own quantity (a cycle count, a pitch) and raises when that cell is
    unusable; ``order_label`` names the quantity in the refusals, because a ladder is ordered by its
    decoded key, never by a filename. One level is one row here - the recordings sharing that level's
    decoded key are its realizations (:func:`level_groups`), kept as separate named paths and handed
    to the setting-based rebuild of plan §8.3 step 5 rather than refused.
    """
    groups, by_path = _level_groups_and_rows(
        Path(manifest_path),
        eligibility=eligibility,
        order_key=order_key,
        order_label=order_label,
    )
    return tuple(by_path[group.primary_path] for group in groups if group.in_ladder)


def require_clean_ofat(
    entries: Sequence[object], settings: Sequence[str], *, axis_label: str
) -> None:
    """Refuse a ladder in which a setting other than the varied one moved.

    Decoded settings are compared, never folder names (plan §2): the first entry is the baseline
    and every later one must agree with it on all ``settings``.
    """
    for entry in entries[1:]:
        moved = sorted(
            setting
            for setting in settings
            if getattr(entry, setting) != getattr(entries[0], setting)
        )
        if moved:
            raise NativeGridError(
                f"{entries[0].relative_path} and {entry.relative_path} are not a "
                f"{axis_label} OFAT ladder: {moved} also differ"
            )


def read_manifest_pinned_document(
    path: Path, manifest_sha256: str, what: str
) -> dict[str, object]:
    """Read a committed artefact and refuse one generated against another manifest.

    The WP1 artefacts carry the WP0 manifest they were measured against, and that cell is
    re-checked: a threshold or floor measured on another inventory must not supply one silently.
    """
    target = Path(path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NativeGridError(f"cannot read the {what} {target}: {exc}") from exc
    recorded = str(((document.get("manifest") or {}).get("sha256")) or "")
    if recorded != manifest_sha256:
        raise NativeGridError(
            f"the {what} {target} records manifest {recorded or '<none>'}, the ladder is "
            f"built from {manifest_sha256}; it must come from the same inventory"
        )
    return document


def read_screening_threshold(screening_threshold_path: Path, manifest_sha256: str) -> ScreeningThresholdBinding:
    """Read the committed sole-pair observed-discrepancy screening threshold and pin it to this manifest.

    The threshold is *read*, not recomputed: the comparison must use the number the WP1 gate
    declared. Refuses a missing document, one from another manifest, another metric, or a value
    that is not positive and finite.
    """
    path = Path(screening_threshold_path)
    document = read_manifest_pinned_document(path, manifest_sha256, "WP1 screening_threshold")
    screening_threshold = document.get("screening_threshold") or {}
    metric = str(screening_threshold.get("metric") or "")
    if metric != SCREENING_THRESHOLD_METRIC:
        raise NativeGridError(
            f"the WP1 screening_threshold {path} records metric {metric!r}, expected "
            f"{SCREENING_THRESHOLD_METRIC!r}"
        )
    value = float(screening_threshold.get("value_mm_s") or 0.0)
    if not math.isfinite(value) or value <= 0.0:
        raise NativeGridError(
            f"the WP1 screening_threshold {path} records value_mm_s="
            f"{screening_threshold.get('value_mm_s')!r}; the threshold must be positive"
        )
    return ScreeningThresholdBinding(
        path=path.as_posix(),
        source_sha256=sha256_file(path),
        metric=metric,
        units=str(screening_threshold.get("units") or "mm/s"),
        value_mm_s=value,
        gate_index=int(screening_threshold.get("gate_index") or 0),
        depth_mm=float(screening_threshold.get("depth_mm") or 0.0),
        median_abs_mean_difference_mm_s=float(
            screening_threshold.get("median_abs_mean_difference_mm_s") or 0.0
        ),
        scope=str(
            screening_threshold.get("scope")
            or "sole-pair observed-discrepancy screening threshold: one observed realization of repeatability plus uncontrolled drift, screened and not a bound on either"
        ),
    )


def bin_cell_edges(frequency_hz: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    """Left and right edge of every bin's own cell, in the grid's frequency units.

    A bin's cell runs from the midpoint to its previous neighbour to the midpoint to its next one,
    so the cells partition the frequency axis however the bins are spaced. Clipping them to a band
    therefore integrates over exactly that band - including a band narrower than one bin, which
    keeps its share of the bin rather than losing it to a bin count.
    """
    frequency = np.asarray(frequency_hz, dtype=float)
    if frequency.ndim != 1 or frequency.size < 2:
        raise NativeGridError(
            f"a frequency grid needs at least two bins to carry widths, got shape {frequency.shape}"
        )
    if not np.all(np.isfinite(frequency)):
        raise NativeGridError("a frequency grid must be finite to carry widths")
    if np.any(np.diff(frequency) <= 0.0):
        raise NativeGridError(
            "the frequency grid must be strictly increasing to be integrated over; a repeated or "
            "descending bin carries no width"
        )
    left = np.empty(frequency.size)
    right = np.empty(frequency.size)
    left[1:] = right[:-1] = 0.5 * (frequency[:-1] + frequency[1:])
    left[0] = frequency[0] - 0.5 * (frequency[1] - frequency[0])
    right[-1] = frequency[-1] + 0.5 * (frequency[-1] - frequency[-2])
    return left, right


def integrate_density(
    frequency_hz: Sequence[float], density: Sequence[float], band: tuple[float, float] | None = None
) -> float:
    """Integrate a spectral density over frequency, in the density's own units times Hz.

    A density is a per-hertz quantity, so its integral over frequency is power and every term must
    carry that bin's *actual* width - the midpoint rule over the cells of
    :func:`bin_cell_edges`, clipped to ``band`` when one is given. Summing the density values alone
    counts bins instead of integrating over them, so one spectrum represented on two different
    grids would return two different powers. Refuses a grid with no width to integrate over and a
    band that reaches outside the grid's own coverage, where the clipped cells no longer tile it.
    """
    frequency = np.asarray(frequency_hz, dtype=float)
    values = np.asarray(density, dtype=float)
    if frequency.ndim != 1 or values.shape != frequency.shape:
        raise NativeGridError(
            f"a spectral integral needs one frequency per density value, got shapes "
            f"{frequency.shape} and {values.shape}"
        )
    if not np.all(np.isfinite(values)):
        raise NativeGridError("a spectral integral needs finite densities")
    left, right = bin_cell_edges(frequency)
    low, high = (left[0], right[-1]) if band is None else (float(band[0]), float(band[1]))
    if not (math.isfinite(low) and math.isfinite(high) and low < high):
        raise NativeGridError(f"the integrated band must be finite and increasing, got ({low}, {high})")
    if low < left[0] - TOLERANCE_S or high > right[-1] + TOLERANCE_S:
        raise NativeGridError(
            f"the band [{low:.6g}, {high:.6g}] Hz reaches outside the frequency grid's own coverage "
            f"[{left[0]:.6g}, {right[-1]:.6g}] Hz; the bins there cannot measure it"
        )
    width = np.clip(np.minimum(right, high) - np.maximum(left, low), 0.0, None)
    return float(np.sum(values * width))


def band_density(
    frequency_hz: Sequence[float], density: Sequence[float], band: tuple[float, float]
) -> float:
    """Mean spectral density in ``band``: the power in the band over that band's width.

    The power is :func:`integrate_density` over the band, each bin contributing its own cell
    clipped to it, so a level's band mean is the integral of its own spectrum over the band divided
    by the band's width and two representations of one spectrum on different grids agree.
    """
    return integrate_density(frequency_hz, density, band) / (float(band[1]) - float(band[0]))


def psd_band_summary(
    frequency_hz: Sequence[float],
    density: Sequence[float],
    band: tuple[float, float],
    *,
    hf_above_hz: float,
) -> dict[str, float]:
    """The bandwidth summary of one ensemble PSD inside ``band``: the power-weighted
    mean frequency, the RMS spread about it and the share of in-band power above ``hf_above_hz`` —
    the same three numbers for a level's curve and the committed WP1 curves. Every moment is
    integrated over the actual frequency grid (:func:`integrate_density`), so the summary depends on
    the spectrum rather than on how densely it was sampled, and it refuses a band that carries no
    power.
    """
    frequency = np.asarray(frequency_hz, dtype=float)
    values = np.asarray(density, dtype=float)
    total = integrate_density(frequency, values, band)
    if not math.isfinite(total) or total <= 0.0:
        raise NativeGridError(f"the ensemble PSD carries no power in {band} Hz")
    centroid = integrate_density(frequency, frequency * values, band) / total
    if hf_above_hz <= band[0]:
        hf_share = 1.0
    elif hf_above_hz >= band[1]:
        hf_share = 0.0
    else:
        hf_share = float(1.0 - integrate_density(frequency, values, (band[0], hf_above_hz)) / total)
    return {
        "centroid_hz": centroid,
        "bandwidth_hz": float(
            math.sqrt(integrate_density(frequency, (frequency - centroid) ** 2 * values, band) / total)
        ),
        "hf_share": hf_share,
    }


def read_temporal_floor(
    screening_threshold_path: Path,
    manifest_sha256: str,
    *,
    band_hz: tuple[float, float],
    hf_above_hz: float,
) -> dict[str, object]:
    """The temporal repeat floor the committed WP1 curves record.

    Both recordings are summarised with the same :func:`psd_band_summary` the axis levels use, so
    their difference is comparable to a difference across a ladder. Refuses a missing document,
    one from another manifest, one without two temporal series, or curves with no power in the
    band.
    """
    path = Path(screening_threshold_path)
    document = read_manifest_pinned_document(path, manifest_sha256, "WP1 screening_threshold")
    temporal = document.get("views", {}).get("temporal") or {}
    series = temporal.get("series") or []
    if len(series) != 2:
        raise NativeGridError(
            f"the WP1 screening_threshold {path} records {len(series)} temporal series; the floor "
            "needs two"
        )
    summaries = [
        psd_band_summary(
            item["psd"]["frequency_hz"], item["psd"]["mean_mm2_s2_per_hz"], band_hz,
            hf_above_hz=hf_above_hz,
        )
        for item in series
    ]
    lags = [float(item["acf"]["e_folding_lag_s"]) for item in series]
    floor: dict[str, object] = {
        "source_path": path.as_posix(), "source_sha256": sha256_file(path),
        "manifest_sha256": manifest_sha256,
        "source_paths": [str(item["relative_path"]) for item in series],
        "source_hashes": [str(item["source_sha256"]) for item in series],
        "profile_period_s": float(temporal.get("profile_period_s") or 0.0),
        "band_hz": list(band_hz),
        "band_max_abs_level_difference_db": float(
            temporal.get("band_max_abs_level_difference_db") or 0.0
        ),
        "e_folding_lag_s": lags, "e_folding_lag_difference_s": abs(lags[0] - lags[1]),
        "role": "sole-pair observed-discrepancy screening threshold: one observed realization of repeatability plus uncontrolled drift, screened and not a bound on either (temporal)",
    }
    for name in ("hf_share", "centroid_hz", "bandwidth_hz"):
        pair = [float(item[name]) for item in summaries]
        floor[name] = pair
        floor[f"{name}_difference"] = abs(pair[0] - pair[1])
    return floor



def window(
    values: np.ndarray, time_s: np.ndarray, window_s: float
) -> np.ndarray:
    """The leading ``window_s`` of a recording, cut by the recorded timestamps, so every
    level is cut at the same *duration* though their profile counts differ (plan §3.1).
    """
    return values[time_s <= time_s[0] + window_s + TOLERANCE_S]


def common_support(ranges: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """The intersection of the given ``(depth_min_mm, depth_max_mm)`` ranges, refused
    when a range is not finite and increasing or the intersection is empty (plan §3.2).
    """
    if not ranges:
        raise NativeGridError("common_support needs at least one depth range")
    for low, high in ranges:
        if not (math.isfinite(low) and math.isfinite(high) and low < high):
            raise NativeGridError(
                f"every depth range must be finite and increasing, got ({low}, {high})"
            )
    low = max(first for first, _ in ranges)
    high = min(second for _, second in ranges)
    if not low < high:
        raise NativeGridError(
            f"no common physical support: the depth ranges overlap on nothing better "
            f"than [{low}, {high}] mm"
        )
    return float(low), float(high)


def in_support(depths: np.ndarray, support: tuple[float, float]) -> np.ndarray:
    """Boolean mask of the native gates inside the common physical support.
    """
    return (depths >= support[0] - TOLERANCE_S) & (depths <= support[1] + TOLERANCE_S)


def nearest_gate_indices(grid: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Index of the nearest entry of ``grid`` for every value in ``targets``.

    The only alignment here: a finer profile is *sampled* at the coarser knots, so an offset never
    exceeds half the finer grid's own pitch.
    """
    values = np.asarray(grid, dtype=float).reshape(-1)
    wanted = np.asarray(targets, dtype=float).reshape(-1)
    if values.size == 0:
        raise NativeGridError("nearest_gate_indices needs a non-empty grid")
    if wanted.size == 0:
        return np.empty(0, dtype=int)
    if values.size == 1:
        return np.zeros(wanted.size, dtype=int)
    return np.abs(values[None, :] - wanted[:, None]).argmin(axis=1).astype(int)


def grid_and_profile(
    depths_mm: np.ndarray, profile_mm_s: np.ndarray
) -> tuple[np.ndarray, np.ndarray, float]:
    """Validate one native grid and its profile; return both and the pitch.
    """
    depths = np.asarray(depths_mm, dtype=float).reshape(-1)
    profile = np.asarray(profile_mm_s, dtype=float).reshape(-1)
    if depths.size != profile.size:
        raise NativeGridError(
            f"the depth grid ({depths.size}) and the profile ({profile.size}) must "
            "hold one entry per gate"
        )
    if depths.size < 2:
        raise NativeGridError(
            f"at least two gates are needed for a native spatial metric, got "
            f"{depths.size}"
        )
    if not (np.all(np.isfinite(depths)) and np.all(np.isfinite(profile))):
        raise NativeGridError("the native grid and its profile must be finite")
    steps = np.diff(depths)
    pitch = float(steps.mean())
    if not np.all(steps > 0.0) or not math.isfinite(pitch) or pitch <= 0.0:
        raise NativeGridError(
            f"the native gate pitch must be positive and increasing, got steps "
            f"including {steps.min()!r}"
        )
    deviation = float(np.abs(steps - pitch).max())
    if deviation > GRID_UNIFORMITY_RTOL * pitch:
        raise NativeGridError(
            f"the native gate grid is not uniform: steps deviate by {deviation:.3g} mm "
            f"from the {pitch:g} mm mean pitch"
        )
    return depths, profile, pitch


def level_metrics(
    relative_path: str,
    values: np.ndarray,
    time_s: np.ndarray,
    depths: np.ndarray,
    *,
    window_s: float,
    support: tuple[float, float],
) -> LevelMetrics:
    """One level's common-window numbers, on its own native grid.

    The distributional metrics are WP1's :func:`gate_metrics`; both spatial metrics are computed on
    the supported native grid, *before* any cross-level alignment. Refuses fewer than two gates in
    the common support.
    """
    view = window(values, time_s, window_s)
    mask = in_support(depths, support)
    supported_gates = int(np.count_nonzero(mask))
    if supported_gates < 2:
        raise NativeGridError(
            f"{relative_path}: {supported_gates} gate(s) fall inside the common "
            f"support [{support[0]:g}, {support[1]:g}] mm; the spatial metrics need two"
        )
    per_gate = gate_metrics(view)
    means = per_gate["mean"][mask]
    return LevelMetrics(
        profiles_window=int(view.shape[0]),
        supported_gates=supported_gates,
        per_gate=per_gate,
        mask=mask,
        means=means,
        supported=view[:, mask],
        gradient=spatial_gradient(depths[mask], means),
        correlation=correlation_length(depths[mask], means),
    )


def spatial_gradient(depths_mm: np.ndarray, profile_mm_s: np.ndarray) -> GradientStats:
    """Native-grid gate-to-gate gradient of one depth-resolved mean profile:
    ``|mean[k + 1] - mean[k]| / pitch``, at the interval midpoint, before any alignment — a
    relative-spread statement, not a shear-rate measurement.
    """
    depths, profile, pitch = grid_and_profile(depths_mm, profile_mm_s)
    gradient = np.abs(np.diff(profile)) / pitch
    worst = int(np.argmax(gradient))
    return GradientStats(
        pitch_mm=pitch,
        intervals=int(gradient.size),
        median_abs_mm_s_per_mm=float(np.median(gradient)),
        max_abs_mm_s_per_mm=float(gradient[worst]),
        max_depth_mm=float(0.5 * (depths[worst] + depths[worst + 1])),
    )


def correlation_length(
    depths_mm: np.ndarray, profile_mm_s: np.ndarray
) -> CorrelationStats:
    """Native-grid spatial correlation length of one depth-resolved mean profile.

    The mean-removed profile's biased normalized autocovariance is evaluated on its own grid up to
    half the profile; the length is the first lag below 1/e.
    """
    _depths, profile, pitch = grid_and_profile(depths_mm, profile_mm_s)
    centred = profile - profile.mean()
    variance = float(np.mean(np.square(centred)))
    if variance == 0.0:
        raise NativeGridError(
            "a constant mean profile has no spatial correlation length: this gate "
            "grid resolves no variation"
        )
    autocovariance = (
        np.correlate(centred, centred, mode="full")[centred.size - 1 :]
        / (centred.size * variance)
    )
    cap = (centred.size - 1) // 2
    below = np.flatnonzero(autocovariance[: cap + 1] < CORRELATION_FLOOR)
    lag = int(below[0]) if below.size else cap
    return CorrelationStats(
        pitch_mm=pitch,
        floor=float(CORRELATION_FLOOR),
        length_mm=float(lag * pitch),
        lag_max_mm=float(cap * pitch),
        lag_cap_gates=cap,
        reaches_floor=bool(below.size),
    )


def align_on_knots(
    sampled_depths_mm: np.ndarray,
    sampled_mean_mm_s: np.ndarray,
    knot_depths_mm: np.ndarray,
    knot_mean_mm_s: np.ndarray,
    *,
    path: str,
    support: tuple[float, float],
    threshold_mm_s: float,
) -> KnotAlignment:
    """Align two profiles on the *knot* participant's own native gate depths.

    The knots are those depths inside the common support, so their spacing is the knot
    participant's pitch; the sampled participant is read there by its nearest native gate: no
    interpolation, no upsampling. Refuses fewer than two knots, or a sampled profile whose
    supported values are constant.
    """
    sampled_depths = np.asarray(sampled_depths_mm, dtype=float)
    knot_depths = np.asarray(knot_depths_mm, dtype=float)
    inside = in_support(knot_depths, support)
    knots = knot_depths[inside]
    if knots.size < 2:
        raise NativeGridError(
            f"{path}: {knots.size} knot(s) fall inside the common support "
            f"[{support[0]:g}, {support[1]:g}] mm; a pair needs two"
        )
    sampled_mean = np.asarray(sampled_mean_mm_s, dtype=float)
    variance = float(np.var(sampled_mean[in_support(sampled_depths, support)]))
    if variance == 0.0:
        raise NativeGridError(
            f"{path}: the supported mean profile is constant; the pair difference is "
            "undefined"
        )
    indices = nearest_gate_indices(sampled_depths, knots)
    difference = sampled_mean[indices] - np.asarray(knot_mean_mm_s, dtype=float)[inside]
    absolute = np.abs(difference)
    return KnotAlignment(
        knots=knots,
        indices=indices,
        absolute=absolute,
        flagged=absolute > threshold_mm_s,
        worst=int(np.argmax(absolute)),
        offset_mm=float(np.abs(sampled_depths[indices] - knots).max()),
        sampled_variance=variance,
    )


def depth_ranges(knots: np.ndarray, flagged: np.ndarray) -> str:
    """Depth ranges of the flagged knots as ``low..high``, runs joined by ``"; "``:
    each range names the first and last flagged knot of one contiguous run of the knot grid.
    """
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, is_flagged in enumerate(bool(flag) for flag in flagged):
        if is_flagged and start is None:
            start = index
        elif not is_flagged and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, flagged.size - 1))
    return "; ".join(f"{knots[low]:.6g}..{knots[high]:.6g}" for low, high in runs)


def csv_text(columns: Sequence[str], rows: Sequence[Mapping[str, object]]) -> str:
    """Render rows as CSV text (LF endings, one trailing newline).
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=list(columns), lineterminator="\n", extrasaction="raise"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: format_cell(row[column]) for column in columns})
    return buffer.getvalue()


def wrap_caption(text: str, width: int = 168) -> str:
    """Wrap the caption into the figure's footnote without breaking words.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        if not current:
            current = word
        elif len(current) + len(word) + 1 <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def largest_step(
    metric: str, cycles: Sequence[int], values: Sequence[float]
) -> dict[str, object]:
    """The largest one-step change of one metric along a ladder (the discrete knee).

    Returns that step's cycle count, the value there, the signed change, the net change and whether
    the sequence falls at every step: no smoothing, and no knee for a sequence that does not fall.
    Refuses fewer than two levels or a value count that does not match.
    """
    counts = [int(value) for value in cycles]
    numbers = [float(value) for value in values]
    if len(counts) < 2 or len(numbers) != len(counts):
        raise NativeGridError(
            f"a knee needs at least two levels with one value each, got {len(counts)} cycle "
            f"counts and {len(numbers)} values"
        )
    steps = [b - a for a, b in itertools.pairwise(numbers)]
    worst = max(range(len(steps)), key=lambda index: (abs(steps[index]), -index))
    return {
        "metric": metric, "cycles": counts, "knee_cycles": counts[worst + 1],
        "knee_value": numbers[worst + 1], "knee_change": steps[worst],
        "net_change": numbers[-1] - numbers[0],
        "monotone_decreasing": bool(all(step < 0.0 for step in steps)),
    }


def knees(
    levels: Sequence[Mapping[str, object]], metrics: Sequence[str]
) -> dict[str, dict[str, object]]:
    """One knee per named metric of a ladder, each carrying its own statement.
    """
    counts = [row["cycles"] for row in levels]
    reported: dict[str, dict[str, object]] = {}
    for name in metrics:
        row = largest_step(name, counts, [level[name] for level in levels])
        outcome = "falls" if row["monotone_decreasing"] else "does not fall monotonically"
        row["statement"] = (
            f"{name}: largest one-step change {row['knee_change']:+.4g} across {counts[0]}-"
            f"{counts[-1]} cycles, reached at {row['knee_cycles']} cycles (value "
            f"{row['knee_value']:.4g}), net {row['net_change']:+.4g}; the sequence {outcome}"
        )
        reported[name] = row
    return reported


def write_text_artefacts(directory: Path, documents: Mapping[str, str]) -> None:
    """Write LF-only text artefacts into ``directory``, creating it first, in the
    mapping's order, so a refused build leaves no half-artefact behind.
    """
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    for name, text in documents.items():
        (target / name).write_text(text, encoding="utf-8", newline="")


def panel_figure(
    suptitle: str,
    caption: str,
    draw: Callable[[Sequence[object]], None],
    path: Path,
    *,
    adjust: Mapping[str, float],
    caption_width: int = 168,
    dpi: int = 150,
) -> Path:
    """Write one deterministic two-panel figure and return its path.

    The frame is fixed: two 12.0 x 5.4 in panels, one suptitle, the wrapped caption in monospace at
    the bottom-left (a figure never travels without its caveats), the subplot margins and the PNG
    write. ``draw`` receives the two axes and paints the panels, which is the only part an axis
    owns.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(12.0, 5.4), dpi=dpi)
    draw(axes)
    figure.suptitle(suptitle, fontsize=11, y=0.975)
    figure.text(
        0.008,
        0.008,
        wrap_caption(caption, width=caption_width),
        fontsize=5.2,
        va="bottom",
        ha="left",
        family="monospace",
    )
    figure.subplots_adjust(**adjust)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(target, dpi=dpi)
    plt.close(figure)
    return target
