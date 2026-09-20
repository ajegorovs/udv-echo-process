"""WP2, TGC and emitting-power axes — the velocity-only screening of both ladders.

Two committed axes ask one question each and neither can be answered from velocity alone: the ``tgc``
folder holds eight base-state recordings whose requested labels run 0 to 40, and the ``em_pow``
folder two, ``low`` and ``high`` (plan §2). The plan's WP2 line for them is deliberately narrow (plan
§4): *depth-resolved dropout, bias and variance only*, with saturation and SNR marked unresolved
because the files carry no echo or energy signal. This module is that screen and nothing more: one
build reads both axes from the ``tgc`` and ``em_pow`` rows of the WP0 manifest (never a filename
list), re-checks the source hashes, the decoded settings, the gate grids and the two TGC cells,
enforces clean OFAT **separately per axis**, and produces one coherent evidence set — the level, pair
and depth tables, the provenance document and the decision figure — from which a setting unusable for
any wider ladder can be screened out.

Three facts shape it (plan §2, and this module refuses rather than reinterprets them); all three are
restated in the provenance document and in the limitations it carries:

- the TGC axis moves **one** decoded cell: op word 23 stays `0` and the reader labels that
  ``ChannelConfig.tgc_mode`` ``uniform``, word 25 stays `255` and decodes to a fixed
  :data:`TGC_END_DB` of 40 dB, and only word 24 (``tgc_start_db``) changes. That is the
  *representation* this axis is screened through, not a validated scalar gain ladder: no echo or
  energy channel exists to show the gain a setting applied, so nothing here calls the key a gain;
- sensitivity is fixed at ``medium`` in every committed row, so that axis is absent from the sweep
  and unidentifiable from it;
- the base state's own level is missing from *both* screened axes — the TGC ladder straddles the
  value the other manifest rows carry, the power ladder straddles ``medium``, and each axis's focus
  pair is the two ladder-adjacent levels that bracket it.

The input binding, the common views, the native-grid metrics, the knot alignment, the committed WP1
screening_threshold reader and the table/caption/figure writers are the shared layer's
(:mod:`udv_echo_process.analysis._native_grid`), driven here with this screen's own axes, key cells,
settings and columns; no second helper module is added. Each axis is selected by decoded
**scientific fingerprint** (:data:`ELIGIBILITY`), never by folder (plan §8.3 step 2, R1/R4): its key
cell is the only setting it may move, so every recording sharing the rest of the fingerprint is
eligible, and the base state neither ladder requests - TGC ≈19.9216 dB, emitting power medium - is
one level realized by both reference recordings (``prf/600.BDD`` and ``res/1-8.BDD``, whichever
folder each sits in). No screened row requests that level, so the committed ladders do not hold it
yet and it is recorded as eligible evidence for the setting-based rebuild of §8.3 step 5. No profile
and no gate is an independent
experimental replicate, the levels carry no acquisition order, one recording per setting is all there
is, and no p-value is produced (plan §3.3). TGC and emitting power only: the resolution, burst and PRF
verdicts belong to their own modules and are not revisited here.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from pydantic import model_validator

from udv_echo_process.analysis import _native_grid as grid
from udv_echo_process.analysis import reference_repeat as wp1
from udv_echo_process.analysis import sweep_inventory as inventory
from udv_echo_process.analysis.sweep_inventory import format_cell
from udv_echo_process.models.base import ValueModel
from udv_echo_process.provenance.models import current_revision

#: The two manifest axes this screen owns, in table order, and the artefacts one command writes.
AXES: tuple[str, ...] = ("tgc", "em_pow")
ARTEFACT = "gain-power-screen"
LEVELS_NAME, PAIRS_NAME, DEPTHS_NAME = (
    "gain-power-levels.csv", "gain-power-pairs.csv", "gain-power-depths.csv")
PROVENANCE_NAME, FIGURE_NAME = "gain-power-screen.provenance.json", "gain-power-screen.png"
FIGURES_DIRNAME, SCREENING_THRESHOLD_NAME = "figures", "reference-repeat.provenance.json"

#: The cell each axis's ladder is keyed by, what it is, and the level each axis does **not** hold. The
#: base state is the dataset README's note of 2026-09-16 — TCG 20, emitting power medium, sensitivity
#: medium; the decoded cell on the manifest's other rows is what this module checks.
KEY_COLUMN: dict[str, str] = {"tgc": "tgc_start_db", "em_pow": "emit_power"}
KEY_LABEL: dict[str, str] = {"tgc": "decoded TGC start", "em_pow": "requested emitting power"}
KEY_UNITS: dict[str, str] = {"tgc": "dB", "em_pow": "declared step"}
BASE_STATE_LABEL: dict[str, str] = {"tgc": "20", "em_pow": "medium"}
#: The instrument's own emitting-power order: this is what a power pair's key gap counts in.
POWER_ORDER: tuple[str, ...] = ("low", "medium", "high")
SENSITIVITY_COLUMN, SENSITIVITY_VALUE = "sensitivity", "medium"

#: The TGC representation this screen must not rename (plan §2): the mode label for op word 23 = 0,
#: the fixed end from word 25 = 255, and the three words the cells come from.
TGC_MODE_LABEL, TGC_END_DB = "uniform", 40.0
TGC_WORDS: dict[str, int] = {"mode": 23, "start": 24, "end": 25}
TGC_CELLS: tuple[str, ...] = ("tgc_start_db", "tgc_end_db")

#: The declared screening margins: a gate blank in more than half the window cannot carry a per-depth
#: effect, and a per-gate robust spread past this multiple of its own axis's median is disproportionate
#: to the ladder. Neither is an instrument flag, and every ratio and blank fraction is published so a
#: reviewer can move either margin and re-read the screen.
DROPOUT_GATE_LIMIT, SPREAD_RATIO_LIMIT = 0.5, 3.0

#: The plan's declared support window, and the settings that must **not** move on each axis: the TGC
#: ladder varies the decoded TGC start only, the power ladder the emitting power only.
PLAN_SUPPORT_MM: tuple[float, float] = (10.163, 96.743)
COUPLED_SETTINGS: dict[str, tuple[str, ...]] = {
    "tgc": ("resolution_mm", "burst_length", "emissions_per_profile", "emit_power", "sensitivity",
            "tgc_mode", "tgc_end_db", "prf_period_us", "sound_speed_ms", "velo_max_ms", "gates"),
    "em_pow": ("resolution_mm", "burst_length", "emissions_per_profile", "sensitivity", "tgc_mode",
               "tgc_start_db", "tgc_end_db", "prf_period_us", "sound_speed_ms", "velo_max_ms",
               "gates")}
#: The manifest cells every decoded recording is re-checked against. The two TGC cells are re-checked
#: by this module, because they are what this screen's key is read through.
VERIFIED_CELLS: tuple[str, ...] = (
    "profiles", "gates", "duration_s", "resolution_mm", "prf_period_us", "burst_length",
    "emissions_per_profile", "emit_power", "sensitivity", "tgc_mode")

#: The setting-based contract of each screened axis (plan §8.3 step 2, R1/R4): the axis's key cell is
#: the only decoded setting it may move, so every recording sharing the rest of the fingerprint -
#: whatever folder its row sits in - is eligible. Both ladders' base state (TGC ≈19.9216 dB, emitting
#: power medium) is realized by neither axis's own rows: the two reference recordings are recorded as
#: its two realizations for the setting-based rebuild of §8.3 step 5.
ELIGIBILITY: dict[str, grid.AxisEligibility] = {
    "tgc": grid.AxisEligibility(axis="tgc", ladder_label=KEY_LABEL["tgc"], varied=("tgc_start_db",)),
    "em_pow": grid.AxisEligibility(axis="em_pow", ladder_label=KEY_LABEL["em_pow"], varied=("emit_power",)),
}

#: Column order of the three tables: the dict rows carry exactly these keys, so table and model cannot
#: drift. ``realizations``/``realization_paths`` name the recordings one level summarises: the shared
#: anchor level (TGC ≈19.9216 dB, emitting power ``medium``) is realized by both reference
#: recordings, and both paths are published rather than collapsed (plan §8.3 step 5).
LEVEL_COLUMNS: tuple[str, ...] = (
    "axis", "relative_path", "requested_label", "realizations", "realization_paths",
    "key_name", "key_value", "tgc_start_db",
    "tgc_end_db", "tgc_mode", "emit_power", "sensitivity", "resolution_mm", "prf_period_us",
    "burst_length", "emissions_per_profile", "gates", "profiles", "duration_s", "profiles_window",
    "gates_in_support", "pitch_mm", "mean_mm_s", "robust_spread_mm_s", "rms_mm_s",
    "zero_fraction", "median_gate_robust_spread_mm_s", "max_gate_robust_spread_mm_s",
    "max_gate_robust_spread_depth_mm", "max_gate_spread_ratio_to_axis_median", "max_gate_std_mm_s",
    "worst_gate_zero_fraction", "worst_gate_zero_fraction_depth_mm",
    "majority_blank_gates", "majority_blank_depth_ranges_mm", "dropout_limited", "spread_limited",
    "screen")
#: The cells after a realization level row's identity, in column order: the aggregator assembles
#: every level row in exactly this order, so a dict row and its table cannot drift.
LEVEL_CELL_ORDER: tuple[str, ...] = LEVEL_COLUMNS[5:]

#: The level cells summarised as the **unweighted mean** over realizations (plan §8.3 step 5): what
#: the level typically measures, and the extent it was measured over. ``gates``/``gates_in_support``
#: stay whole numbers because every realization of one level measures the one native gate grid the
#: level's shared settings give it.
AGGREGATED_CELLS: tuple[str, ...] = (
    "resolution_mm", "prf_period_us", "burst_length", "emissions_per_profile", "gates", "profiles",
    "duration_s", "profiles_window", "gates_in_support", "pitch_mm", "mean_mm_s",
    "robust_spread_mm_s", "rms_mm_s", "zero_fraction", "median_gate_robust_spread_mm_s",
)
#: The level cells that assert an **adverse screening outcome**: the worst realization's value, so no
#: realization's finding is averaged away - a level is dropout- or spread-limited when any of its
#: recordings is, and the count, depth ranges and depth it publishes are that realization's.
WORST_CELLS: tuple[str, ...] = (
    "max_gate_robust_spread_mm_s", "max_gate_robust_spread_depth_mm",
    "max_gate_spread_ratio_to_axis_median", "max_gate_std_mm_s", "worst_gate_zero_fraction",
    "worst_gate_zero_fraction_depth_mm", "majority_blank_gates", "majority_blank_depth_ranges_mm",
)
#: Cells that stay whole numbers: one level keeps one native gate grid.
INTEGRAL_CELLS: tuple[str, ...] = ("gates", "gates_in_support", "majority_blank_gates")
#: The depth-row cells summarised as the unweighted mean over realizations; the gate index, depth,
#: key and window cells are the level's own.
AGGREGATED_DEPTH_CELLS: tuple[str, ...] = (
    "profiles_window", "mean_mm_s", "robust_spread_mm_s", "std_mm_s", "rms_mm_s", "zero_fraction",
)
#: The per-realization cells the provenance document publishes beside each level mean.
REALIZATION_CELLS: tuple[str, ...] = (
    "key_value", "mean_mm_s", "robust_spread_mm_s", "rms_mm_s", "zero_fraction",
    "profiles_window", "gates_in_support", "max_gate_robust_spread_mm_s",
    "max_gate_spread_ratio_to_axis_median", "worst_gate_zero_fraction", "majority_blank_gates",
    "dropout_limited", "spread_limited", "screen",
)
PAIR_COLUMNS: tuple[str, ...] = (
    "axis", "low_path", "low_label", "low_key", "high_path", "high_label", "high_key", "key_gap",
    "knots", "knot_spacing_mm", "max_knot_offset_mm", "mean_signed_difference_mm_s",
    "mean_abs_difference_mm_s", "max_abs_difference_mm_s",
    "max_abs_difference_depth_mm", "knots_above_screening_threshold", "max_abs_difference_over_screening_threshold",
    "depth_ranges_above_screening_threshold_mm", "robust_spread_change_mm_s", "zero_fraction_change",
    "focus_pair")
DEPTH_COLUMNS: tuple[str, ...] = (
    "axis", "relative_path", "requested_label", "key_name", "key_value", "gate_index", "depth_mm",
    "in_plan_window", "profiles_window", "mean_mm_s", "robust_spread_mm_s", "std_mm_s", "rms_mm_s",
    "zero_fraction", "majority_blank")
#: The level-row cells the provenance document repeats per input beside its hash, and the ones the
#: findings' flagged list repeats.
INPUT_CELLS: tuple[str, ...] = (
    "relative_path", "requested_label", "key_value", "tgc_start_db", "tgc_end_db", "tgc_mode",
    "emit_power", "screen", "sensitivity", "resolution_mm", "prf_period_us", "burst_length",
    "emissions_per_profile", "profiles", "gates", "duration_s", "profiles_window",
    "gates_in_support")
FLAGGED_CELLS: tuple[str, ...] = (
    "relative_path", "screen", "zero_fraction", "majority_blank_gates",
    "majority_blank_depth_ranges_mm", "worst_gate_zero_fraction",
    "max_gate_spread_ratio_to_axis_median", "max_gate_robust_spread_mm_s",
    "max_gate_robust_spread_depth_mm")

#: The error class of every message this module raises; the shared helpers raise the same class, so one
#: name covers a helper refusal and a screen refusal.
GainPowerScreenError = grid.NativeGridError
NOMINAL_REVOLUTION_S = wp1.NOMINAL_REVOLUTION_S
DATASET_ROOT, MANIFEST_NAME, REPORT_DIR = (
    inventory.DATASET_ROOT, inventory.MANIFEST_NAME, inventory.REPORT_DIR)


class ScreenInput(wp1.RepeatInput):
    """One screened recording: WP1's manifest-pinned level record plus the two TGC cells."""

    tgc_start_db: float
    tgc_end_db: float


LevelInput = ScreenInput


class ScreenAxis(ValueModel):
    """One screened axis: its rows, its two common views, its screening result, the level it does not
    hold and the TGC words its key is read through. ``levels``/``pairs``/``depths`` are dict rows
    keyed by the declared column tuples, so a table and its model cannot drift.
    """

    axis: str
    inputs: tuple[ScreenInput, ...]
    eligibility: grid.AxisEligibility
    groups: tuple[grid.LevelGroup, ...]
    #: One row per realization, in input order: the per-recording numbers every level mean was
    #: aggregated from (plan §8.3 step 5).
    realizations: tuple[dict[str, object], ...] = ()
    levels: tuple[dict[str, object], ...]
    pairs: tuple[dict[str, object], ...]
    depths: tuple[dict[str, object], ...]
    common: dict[str, object]
    screen: dict[str, object]
    base_state: dict[str, object]
    tgc_representation: dict[str, object]

    @model_validator(mode="after")
    def _check_the_axis_is_internally_consistent(self) -> ScreenAxis:
        for columns, rows in ((LEVEL_COLUMNS, self.levels), (PAIR_COLUMNS, self.pairs),
                              (DEPTH_COLUMNS, self.depths)):
            if any(tuple(row) != columns for row in rows):
                raise ValueError("a row must carry exactly the declared columns")
        if self.eligibility.axis != self.axis:
            raise ValueError(
                f"the {self.axis} axis carries the {self.eligibility.axis} eligibility contract")
        if [group.primary_path for group in self.groups] != [
            r["relative_path"] for r in self.levels
        ]:
            raise ValueError(
                "the axis must be exactly the eligible decoded levels, in order")
        for group, row in zip(self.groups, self.levels, strict=False):
            if ";".join(group.realization_paths) != row["realization_paths"]:
                raise ValueError(
                    f"{row['relative_path']}: the level must name exactly the realizations the "
                    "selection grouped with it")
        if [entry.relative_path for entry in self.inputs] != [
            path for group in self.groups for path in group.realization_paths
        ]:
            raise ValueError(
                "every realization of every level must appear exactly once, in level order")
        if self.realizations and [row["relative_path"] for row in self.realizations] != [
            entry.relative_path for entry in self.inputs
        ]:
            raise ValueError(
                "the per-realization rows must cover every recording once, in input order")
        positions = [_key_position(self.axis, row["key_value"]) for row in self.levels]
        if any(b <= a for a, b in itertools.pairwise(positions)):
            raise ValueError("levels must be ordered by increasing key")
        expected = len(self.levels) * (len(self.levels) - 1) // 2
        if len(self.pairs) != expected:
            raise ValueError(f"expected every unordered pair ({expected}), got {len(self.pairs)}")
        if sum(1 for row in self.pairs if row["focus_pair"]) != 1:
            raise ValueError("exactly one pair must be the base-state focus pair")
        counts: dict[str, int] = {}
        for row in self.depths:
            counts[str(row["relative_path"])] = counts.get(str(row["relative_path"]), 0) + 1
        if sorted(counts) != sorted(str(row["relative_path"]) for row in self.levels):
            raise ValueError("every depth row must belong to one of the axis's levels")
        for level in self.levels:
            if counts[str(level["relative_path"])] != level["gates_in_support"]:
                raise ValueError("every level needs one depth row per supported gate")
        return self


class GainPowerScreen(ValueModel):
    """The velocity-only TGC/power screen: both axes, one evidence set, one threshold. ``screening_threshold`` is
    the committed WP1 screening threshold both axes are measured against; ``sensitivity`` records that the axis is
    absent from the sweep.
    """

    dataset_root: str
    manifest_path: str
    manifest_sha256: str
    screening_threshold: grid.ScreeningThresholdBinding
    analysis_commit: str | None = None
    axes: tuple[ScreenAxis, ...]
    sensitivity: dict[str, object]

    @model_validator(mode="after")
    def _check_the_screen_is_coherent(self) -> GainPowerScreen:
        if tuple(axis.axis for axis in self.axes) != AXES:
            raise ValueError(f"the screen must carry both axes in order {list(AXES)}")
        if self.screening_threshold.value_mm_s <= 0.0:
            raise ValueError("the repeatability screening_threshold must be positive")
        if tuple(self.sensitivity.get("values_in_manifest", ())) != (SENSITIVITY_VALUE,):
            raise ValueError("this screen is only truthful where sensitivity is fixed at medium")
        return self


def _key_position(axis: str, key: object) -> float:
    """The key's position on its axis's declared order: the decoded TGC start in dB, or the
    instrument's own ``low`` < ``medium`` < ``high`` step."""
    if axis == "tgc":
        try:
            return float(key)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise GainPowerScreenError(
                f"the TGC axis is ordered by a decoded TGC start in dB, got {key!r}") from None
    label = str(key)
    if label not in POWER_ORDER:
        raise GainPowerScreenError(
            f"the power axis is ordered by the instrument's own {list(POWER_ORDER)} steps, got "
            f"emit_power={label!r}")
    return float(POWER_ORDER.index(label))


def _key_text(value: object) -> str:
    """A key as the statements quote it: a decoded number in general form, a label as it stands."""
    return f"{value:g}" if isinstance(value, float) else str(value)


def _key_of(axis: str, row: Mapping[str, str], manifest_path: Path) -> object:
    """The row's decoded key, read from the manifest cell and re-checked against the decode by
    :func:`_read_level` — never taken from a filename."""
    cell = KEY_COLUMN[axis]
    value = (row.get(cell) or "").strip()
    if not value:
        raise GainPowerScreenError(
            f"{row.get('relative_path')}: manifest {cell} is empty in {manifest_path}; the {axis} "
            "ladder is ordered by its decoded key, never by a filename")
    if axis != "tgc":
        return value
    try:
        number = float(value)
    except ValueError:
        raise GainPowerScreenError(
            f"{row.get('relative_path')}: manifest {cell}={value!r} is not a decoded TGC start in dB"
        ) from None
    if not math.isfinite(number):
        raise GainPowerScreenError(
            f"{row.get('relative_path')}: manifest {cell}={value!r} is not finite")
    return number


def require_tgc_representation(mode: object, end_db: object, *, where: str) -> None:
    """Refuse a recording whose TGC words are not the committed representation (plan §2): op word 23
    is ``0``, the reader labels it ``uniform``, and word 25 is ``255`` / 40 dB. A recording where
    either moved has moved a setting this screen's key does not describe.
    """
    if mode != TGC_MODE_LABEL:
        raise GainPowerScreenError(
            f"{where}: the reader labels TGC op word {TGC_WORDS['mode']} as {mode!r}, not "
            f"{TGC_MODE_LABEL!r}; that representation is what this screen's key is read through and "
            "it must be settled before any output")
    if not isinstance(end_db, (int, float)) or float(end_db) != TGC_END_DB:
        raise GainPowerScreenError(
            f"{where}: TGC op word {TGC_WORDS['end']} decodes to {end_db!r} dB, not the fixed "
            f"{TGC_END_DB:g} dB; only word {TGC_WORDS['start']} may move on this axis")


def _screen_verdict(blanked: bool, spread_out: bool) -> str:
    """The screen's word for a level, from the two declared margins and nothing else."""
    if blanked and spread_out:
        return "dropout- and spread-limited"
    return "dropout-limited" if blanked else ("spread-limited" if spread_out else "usable")


def select_level_rows(manifest_path: Path, axis: str) -> tuple[dict[str, str], ...]:
    """The representative row of every level the axis itself requested, by decoded key then path.

    The selection, ordering and refusals are the shared axis-input layer's, driven with this axis's
    own contract; a same-settings recording sitting in another folder is eligible
    (:func:`level_groups`) but is not one of this axis's requested levels, so it does not redefine
    the committed ladder on its own.
    """
    path = Path(manifest_path)
    if axis not in AXES:
        raise GainPowerScreenError(f"{axis!r} is not one of the screened axes {list(AXES)}")
    return grid.select_axis_rows(
        path, eligibility=ELIGIBILITY[axis], order_key=_order_key(axis, path),
        order_label=KEY_LABEL[axis])


def _order_key(axis: str, manifest_path: Path):
    """This axis's ordering key: its decoded key's position on the axis's declared order.
    """
    return lambda row: _key_position(axis, _key_of(axis, row, manifest_path))


def level_groups(manifest_path: Path, axis: str) -> tuple[grid.LevelGroup, ...]:
    """Every eligible level of one screened axis with all its realizations, by decoded key then path.

    The base state neither ladder requests - TGC ≈19.9216 dB for ``tgc``, emitting power ``medium``
    for ``em_pow`` - is one decoded level realized by ``prf/600.BDD`` and ``res/1-8.BDD``, whichever
    folder each sits in (plan §8.3 step 2, R1). The setting-based rebuild of §8.3 step 5 joins it and
    renders the realizations into the provenance.
    """
    path = Path(manifest_path)
    if axis not in AXES:
        raise GainPowerScreenError(f"{axis!r} is not one of the screened axes {list(AXES)}")
    return grid.level_groups(
        path, eligibility=ELIGIBILITY[axis], order_key=_order_key(axis, path),
        order_label=KEY_LABEL[axis])


def _manifest_rows(manifest_path: Path) -> list[dict[str, str]]:
    """Every committed manifest row, or a named refusal: the whole inventory, never one file."""
    path = Path(manifest_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GainPowerScreenError(f"cannot read the manifest {path}: {exc}") from exc
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise GainPowerScreenError(f"the manifest {path} holds no rows")
    return rows


def manifest_cell_values(manifest_path: Path, column: str) -> tuple[str, ...]:
    """Every distinct value of one manifest column, over the whole committed inventory — for the two
    statements this screen makes about the sweep rather than about its own ladder."""
    rows = _manifest_rows(Path(manifest_path))
    if column not in rows[0]:
        raise GainPowerScreenError(f"the manifest {manifest_path} holds no {column!r} column")
    return tuple(sorted({(row.get(column) or "").strip() for row in rows}))


def _read_level(
    dataset_root: Path, row: dict[str, str]
) -> tuple[LevelInput, np.ndarray, np.ndarray, np.ndarray]:
    """Decode one manifest-selected level, returning ``(entry, values, time_s, depths)``: every shared
    cell is re-checked by the shared axis-input layer, and the two TGC cells here, because a stale
    ``tgc_start_db`` cell would silently redefine what the ladder is ordered by.
    """
    level = grid.read_decoded_level(Path(dataset_root), row, cells=VERIFIED_CELLS)
    config, observed = level.config, level.observed
    cells = {"tgc_start_db": config.tgc_start_db, "tgc_end_db": config.tgc_end_db}
    if not all(isinstance(value, (int, float)) for value in cells.values()):
        raise GainPowerScreenError(
            f"{level.relative_path}: the reader decoded tgc_start_db={config.tgc_start_db!r} / "
            f"tgc_end_db={config.tgc_end_db!r}; the TGC representation must be decoded")
    for cell in TGC_CELLS:
        if (row.get(cell) or "").strip() != format_cell(cells[cell]):
            raise GainPowerScreenError(
                f"{level.relative_path}: manifest {cell}={row.get(cell)!r} does not match the "
                f"decoded {cell}={format_cell(cells[cell])!r}; this screen's key must not rest on a "
                "stale inventory")
    require_tgc_representation(config.tgc_mode, cells["tgc_end_db"], where=level.relative_path)
    return LevelInput(
        relative_path=level.relative_path, axis=level.axis, source_sha256=level.source_sha256,
        requested_label=level.requested_label, profiles=int(level.values.shape[0]), **cells,
        gates=int(level.values.shape[1]), emit_power=str(config.emit_power),
        sensitivity=str(config.sensitivity), tgc_mode=str(config.tgc_mode),
        duration_s=float(observed["duration_s"]), resolution_mm=float(config.resolution_mm),
        sound_speed_ms=float(config.sound_speed_ms), velo_max_ms=float(config.velo_max_ms),
        profile_period_s=float(observed["duration_s"] / (level.time_s.size - 1)),
        depth_min_mm=float(observed["depth_min_mm"]), depth_max_mm=float(observed["depth_max_mm"]),
        prf_period_us=float(observed["prf_period_us"]), burst_length=int(config.burst_length),
        emissions_per_profile=int(config.emissions_per_profile)), \
        level.values, level.time_s, level.depths


def _base_state(
    axis: str, levels: Sequence[Mapping[str, object]], manifest_path: Path
) -> dict[str, object]:
    """The level this axis's own rows do not sample, and the pair the screen focuses on.

    The base state is what the manifest's *other* rows carry in this axis's key column. Where the
    ladder does not hold it - the TGC ladder straddling 19.9216 dB, the power ladder straddling
    ``medium`` - the focus pair is the two ladder-adjacent levels whose keys bracket it. Where the
    ladder *does* hold it (the shared anchor level both reference recordings realize, plan §8.3
    step 5), the focus pair is that level and its ladder-adjacent level above it, so the reference
    condition is compared with the next setting the decision could move to.
    """
    key_column = KEY_COLUMN[axis]
    others = {(row.get(key_column) or "").strip() for row in _manifest_rows(Path(manifest_path))
              if (row.get("axis") or "") != axis}
    others.discard("")
    if len(others) != 1:
        raise GainPowerScreenError(
            f"the manifest's other rows carry {sorted(others)} in {key_column}; the base state must "
            "be one declared value")
    base = others.pop()
    base_cell = grid.canonical_cell(base)
    position = _key_position(axis, base)
    positions = [_key_position(axis, row["key_value"]) for row in levels]
    matches = [
        at for at, row in enumerate(levels)
        if grid.canonical_cell(row["key_value"]) == base_cell
    ]
    if len(matches) > 1:
        raise GainPowerScreenError(
            f"the base state {base!r} is {len(matches)} levels of this axis; a focus pair needs one")
    in_ladder = bool(matches)
    if in_ladder:
        index = matches[0]
        pair = (index, index + 1) if index + 1 < len(positions) else (index - 1, index)
        if pair[0] < 0:
            raise GainPowerScreenError(
                f"the base state {base!r} is the axis's only level; a focus pair needs two")
    else:
        straddle = [index for index in range(len(positions) - 1)
                    if positions[index] <= position <= positions[index + 1]]
        if len(straddle) != 1:
            raise GainPowerScreenError(
                f"the base state {base!r} is bracketed by {len(straddle)} adjacent {axis} pairs; the "
                "focus pair must be unique")
        pair = (straddle[0], straddle[0] + 1)
    index = pair[0]
    return {
        "label": BASE_STATE_LABEL[axis], "decoded_key": base, "in_ladder": in_ladder,
        "focus_pair_kind": "base_state_is_a_level" if in_ladder else "bracketing_levels",
        "straddling_keys": [levels[index]["key_value"], levels[index + 1]["key_value"]],
        "straddling_pair": [str(levels[index]["relative_path"]),
                            str(levels[index + 1]["relative_path"])]}


def _level_row(
    axis: str, entry: LevelInput, metrics: grid.LevelMetrics, depths: np.ndarray,
    axis_median_spread: float
) -> dict[str, object]:
    """One *realization's* row: its common-window numbers and the two screening aggregates.

    From WP1's :func:`gate_metrics` on the common window restricted to the common support. One
    level's row is its realizations' rows under :func:`_aggregate_level_row` (plan §8.3 step 5).
    """
    if axis_median_spread <= 0.0 or not math.isfinite(axis_median_spread):
        raise GainPowerScreenError(
            f"{axis}: the axis's median per-gate robust spread is {axis_median_spread!r}; a spread "
            "ratio needs a positive ladder-wide scale")
    spread, blank = metrics.per_gate["iqr"], metrics.per_gate["zero_fraction"]
    supported, std = np.asarray(depths, dtype=float)[metrics.mask], np.std(
        metrics.supported, axis=0)
    blocked, ratio = blank > DROPOUT_GATE_LIMIT, float(spread.max() / axis_median_spread)
    limited = bool(np.any(blocked))
    return {
        "axis": axis, "relative_path": entry.relative_path,
        "requested_label": entry.requested_label, "realizations": 1,
        "realization_paths": entry.relative_path, "key_name": KEY_COLUMN[axis],
        "key_value": entry.tgc_start_db if axis == "tgc" else entry.emit_power,
        "tgc_start_db": entry.tgc_start_db, "tgc_end_db": entry.tgc_end_db,
        "tgc_mode": entry.tgc_mode, "emit_power": entry.emit_power,
        "sensitivity": entry.sensitivity, "resolution_mm": entry.resolution_mm,
        "prf_period_us": entry.prf_period_us, "burst_length": entry.burst_length,
        "emissions_per_profile": entry.emissions_per_profile, "gates": entry.gates,
        "profiles": entry.profiles, "duration_s": entry.duration_s,
        "profiles_window": metrics.profiles_window, "gates_in_support": metrics.supported_gates,
        "pitch_mm": metrics.gradient.pitch_mm, "mean_mm_s": float(metrics.means.mean()),
        "robust_spread_mm_s": float(
            np.percentile(metrics.means, 75.0) - np.percentile(metrics.means, 25.0)),
        "rms_mm_s": float(np.sqrt(np.mean(np.square(metrics.supported)))),
        "zero_fraction": float(np.count_nonzero(metrics.supported == 0.0) / metrics.supported.size),
        "median_gate_robust_spread_mm_s": float(np.median(spread)),
        "max_gate_robust_spread_mm_s": float(spread.max()),
        "max_gate_robust_spread_depth_mm": float(supported[int(spread.argmax())]),
        "max_gate_spread_ratio_to_axis_median": ratio, "max_gate_std_mm_s": float(std.max()),
        "worst_gate_zero_fraction": float(blank.max()),
        "worst_gate_zero_fraction_depth_mm": float(supported[int(blank.argmax())]),
        "majority_blank_gates": int(np.count_nonzero(blocked)),
        "majority_blank_depth_ranges_mm": grid.depth_ranges(supported, blocked),
        "dropout_limited": limited, "spread_limited": bool(ratio > SPREAD_RATIO_LIMIT),
        "screen": _screen_verdict(limited, ratio > SPREAD_RATIO_LIMIT)}


def _depth_rows(
    axis: str, entry: LevelInput, metrics: grid.LevelMetrics, depths: np.ndarray
) -> tuple[dict[str, object], ...]:
    """One level's depth-resolved rows: dropout, bias and spread at every supported gate, from WP1's
    per-gate distributions over the common window plus the standard deviation about each gate's mean."""
    per_gate = metrics.per_gate
    supported = np.asarray(depths, dtype=float)[metrics.mask]
    indices = np.flatnonzero(np.asarray(metrics.mask, dtype=bool))
    std = np.std(metrics.supported, axis=0)
    key = entry.tgc_start_db if axis == "tgc" else entry.emit_power
    return tuple(
        {"axis": axis, "relative_path": entry.relative_path,
         "requested_label": entry.requested_label, "key_name": KEY_COLUMN[axis], "key_value": key,
         "gate_index": int(indices[at]), "depth_mm": float(depth),
         "in_plan_window": bool(PLAN_SUPPORT_MM[0] <= float(depth) <= PLAN_SUPPORT_MM[1]),
         "profiles_window": metrics.profiles_window,
         "mean_mm_s": float(per_gate["mean"][indices[at]]),
         "robust_spread_mm_s": float(per_gate["iqr"][indices[at]]),
         "std_mm_s": float(std[at]), "rms_mm_s": float(per_gate["rms"][indices[at]]),
         "zero_fraction": float(per_gate["zero_fraction"][indices[at]]),
         "majority_blank": bool(per_gate["zero_fraction"][indices[at]] > DROPOUT_GATE_LIMIT)}
        for at, depth in enumerate(supported))


def _gate_means(
    levels: Sequence[Mapping[str, object]], depths: Sequence[Mapping[str, object]]
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Each level's ``(gate depths, per-gate time mean)``, read back from its own depth rows."""
    return {
        str(level["relative_path"]): (
            np.asarray([r["depth_mm"] for r in depths
                        if r["relative_path"] == level["relative_path"]], dtype=float),
            np.asarray([r["mean_mm_s"] for r in depths
                        if r["relative_path"] == level["relative_path"]], dtype=float))
        for level in levels}


def _pair_row(
    axis: str, low: Mapping[str, object], low_profile: tuple[np.ndarray, np.ndarray],
    high: Mapping[str, object], high_profile: tuple[np.ndarray, np.ndarray], *,
    support: tuple[float, float], screening_threshold: grid.ScreeningThresholdBinding, focus: bool
) -> dict[str, object]:
    """Compare two levels of one axis on the higher key's own knots: the knots are that level's native
    gate depths inside the common support, the lower profile is sampled there by the shared
    nearest-native-gate rule, and the difference is the signed ``low - high`` mm/s."""
    low_depths, low_mean = low_profile
    high_depths, high_mean = high_profile
    aligned = grid.align_on_knots(
        low_depths, low_mean, high_depths, high_mean, path=str(low["relative_path"]),
        support=support, threshold_mm_s=screening_threshold.value_mm_s)
    signed = low_mean[aligned.indices] - high_mean[grid.in_support(high_depths, support)]
    absolute, worst = aligned.absolute, aligned.worst
    return {
        "axis": axis, "low_path": low["relative_path"], "low_label": low["requested_label"],
        "low_key": low["key_value"], "high_path": high["relative_path"],
        "high_label": high["requested_label"], "high_key": high["key_value"],
        "key_gap": _key_position(axis, high["key_value"]) - _key_position(axis, low["key_value"]),
        "knots": int(aligned.knots.size), "knot_spacing_mm": high["pitch_mm"],
        "max_knot_offset_mm": aligned.offset_mm, "mean_signed_difference_mm_s": float(signed.mean()),
        "mean_abs_difference_mm_s": float(absolute.mean()),
        "max_abs_difference_mm_s": float(absolute[worst]),
        "max_abs_difference_depth_mm": float(aligned.knots[worst]),
        "knots_above_screening_threshold": int(np.count_nonzero(aligned.flagged)),
        "max_abs_difference_over_screening_threshold": float(absolute[worst] / screening_threshold.value_mm_s),
        "depth_ranges_above_screening_threshold_mm": grid.depth_ranges(aligned.knots, aligned.flagged),
        "robust_spread_change_mm_s": float(low["robust_spread_mm_s"])
        - float(high["robust_spread_mm_s"]),
        "zero_fraction_change": float(low["zero_fraction"]) - float(high["zero_fraction"]),
        "focus_pair": bool(focus)}


def selected_levels(
    manifest_path: Path, axis: str
) -> tuple[tuple[grid.LevelGroup, tuple[dict[str, str], ...]], ...]:
    """Every eligible level of one screened axis beside the rows of every recording realizing it.

    The ladder is the setting-based selection (plan §8.3 step 5): a decoded key is one level, and a
    recording under another folder that carries the same swept settings - including the shared anchor
    level neither axis's own rows request - realizes it rather than being excluded. Ordered by the
    axis's declared key order, then by the level's primary path.
    """
    path = Path(manifest_path)
    if axis not in AXES:
        raise GainPowerScreenError(f"{axis!r} is not one of the screened axes {list(AXES)}")
    return grid.grouped_level_rows(
        path, eligibility=ELIGIBILITY[axis], order_key=_order_key(axis, path),
        order_label=KEY_LABEL[axis])


def _aggregate_level_row(
    axis: str, group: grid.LevelGroup, rows: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """One decoded level's row: its realizations' rows under this screen's two declared rules.

    Cells describing what the level measures are the unweighted mean over its realizations; cells
    that assert an adverse screening outcome are the worst realization's, so a dropout or a
    disproportionate spread one recording found is never averaged away. The level's ``screen`` word
    is recomputed from those two outcomes, so it cannot disagree with them (plan §8.3 step 5).
    """
    if not rows:
        raise GainPowerScreenError(
            f"{group.primary_path}: the decoded level realises no recording, so it cannot be "
            "screened")
    level = group.primary_path
    primary = next(row for row in rows if row["relative_path"] == level)
    cells: dict[str, object] = {
        cell: grid.aggregate_cell([float(row[cell]) for row in rows], cell=cell, level=level)
        for cell in AGGREGATED_CELLS
    }
    for cell in INTEGRAL_CELLS:
        if cell in cells and not math.isclose(cells[cell], round(cells[cell]), abs_tol=1e-9):
            raise GainPowerScreenError(
                f"{level}: the realizations measure {cells[cell]:g} {cell}; one decoded level keeps "
                "one native gate grid and this screen resamples nothing")
        if cell in cells:
            cells[cell] = round(cells[cell])
    # The two adverse outcomes, each taken from the realization that found it worst, so a dropout
    # or a disproportionate spread one recording found is never averaged away.
    dropout = max(rows, key=lambda row: int(row["majority_blank_gates"]))
    spread = max(rows, key=lambda row: float(row["max_gate_spread_ratio_to_axis_median"]))
    cells["worst_gate_zero_fraction"] = float(dropout["worst_gate_zero_fraction"])
    cells["worst_gate_zero_fraction_depth_mm"] = float(dropout["worst_gate_zero_fraction_depth_mm"])
    cells["majority_blank_gates"] = int(dropout["majority_blank_gates"])
    cells["majority_blank_depth_ranges_mm"] = str(dropout["majority_blank_depth_ranges_mm"])
    cells["max_gate_robust_spread_mm_s"] = float(spread["max_gate_robust_spread_mm_s"])
    cells["max_gate_robust_spread_depth_mm"] = float(spread["max_gate_robust_spread_depth_mm"])
    cells["max_gate_spread_ratio_to_axis_median"] = float(
        spread["max_gate_spread_ratio_to_axis_median"])
    cells["max_gate_std_mm_s"] = float(spread["max_gate_std_mm_s"])
    for cell in ("key_name", "key_value", "tgc_start_db", "tgc_end_db", "tgc_mode", "emit_power",
                 "sensitivity"):
        cells[cell] = primary[cell]
    dropout_limited = any(bool(row["dropout_limited"]) for row in rows)
    spread_limited = any(bool(row["spread_limited"]) for row in rows)
    cells["dropout_limited"] = dropout_limited
    cells["spread_limited"] = spread_limited
    cells["screen"] = _screen_verdict(dropout_limited, spread_limited)
    return {
        "axis": axis, "relative_path": level, "requested_label": primary["requested_label"],
        "realizations": len(rows), "realization_paths": ";".join(group.realization_paths),
        **{cell: cells[cell] for cell in LEVEL_CELL_ORDER},
    }


def _aggregate_depth_rows(
    axis: str, group: grid.LevelGroup, rows: Sequence[Sequence[Mapping[str, object]]]
) -> tuple[dict[str, object], ...]:
    """One level's depth-resolved rows: its realizations' rows under the same two rules.

    Every numeric gate cell is the unweighted mean of the realizations' cells at that gate, while
    ``majority_blank`` is true when **any** realization found that gate majority-blank: the dropout
    each recording saw stays visible at the depth it was seen (plan §8.3 step 5).
    """
    level = group.primary_path
    primary_index = list(group.realization_paths).index(level)
    frame = rows[primary_index]
    if any(len(item) != len(frame) for item in rows):
        raise GainPowerScreenError(
            f"{level}: the realizations' depth rows do not share one native gate grid "
            f"({[len(item) for item in rows]} rows against {len(frame)}); this screen resamples "
            "nothing")
    aggregated: list[dict[str, object]] = []
    for at, reference in enumerate(frame):
        cells = {
            cell: grid.aggregate_cell(
                [float(item[at][cell]) for item in rows], cell=cell, level=level)
            for cell in AGGREGATED_DEPTH_CELLS
        }
        aggregated.append({
            "axis": axis, "relative_path": level, "requested_label": reference["requested_label"],
            "key_name": reference["key_name"], "key_value": reference["key_value"],
            "gate_index": reference["gate_index"], "depth_mm": reference["depth_mm"],
            "in_plan_window": reference["in_plan_window"],
            "profiles_window": round(cells["profiles_window"]),
            "mean_mm_s": cells["mean_mm_s"], "robust_spread_mm_s": cells["robust_spread_mm_s"],
            "std_mm_s": cells["std_mm_s"], "rms_mm_s": cells["rms_mm_s"],
            "zero_fraction": cells["zero_fraction"],
            "majority_blank": any(bool(item[at]["majority_blank"]) for item in rows),
        })
    return tuple(aggregated)


def _axis_levels_and_depths(
    axis: str, manifest_path: Path, decoded, metrics, support, window_s
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    float,
    tuple[dict[str, object], ...],
]:
    """The axis's ladder: every eligible level aggregated, plus its depth rows and axis median.

    Each realization is measured independently first - the axis's median per-gate robust spread is
    its own median over those measurements - and each level is then summarised from its
    realizations (plan §8.3 step 5). The per-realization rows are returned in input order, so the
    provenance document can publish the numbers every level mean was aggregated from.
    """
    axis_median = float(np.median([np.median(own.per_gate["iqr"]) for own in metrics]))
    realization_levels = {
        entry.relative_path: _level_row(axis, entry, own, depths, axis_median)
        for (_group, entry, _values, _time_s, depths), own in zip(decoded, metrics, strict=True)
    }
    realization_depths = {
        entry.relative_path: _depth_rows(axis, entry, own, depths)
        for (_group, entry, _values, _time_s, depths), own in zip(decoded, metrics, strict=True)
    }
    levels: list[dict[str, object]] = []
    depths: list[dict[str, object]] = []
    for group, rows in selected_levels(manifest_path, axis):
        paths = group.realization_paths
        levels.append(_aggregate_level_row(axis, group, [realization_levels[path] for path in paths]))
        depths.extend(
            _aggregate_depth_rows(axis, group, [realization_depths[path] for path in paths]))
    measured = tuple(
        realization_levels[entry.relative_path] for _group, entry, *_rest in decoded
    )
    return tuple(levels), tuple(depths), axis_median, measured


def _build_axis(
    dataset_root: Path, manifest_path: Path, axis: str, screening_threshold: grid.ScreeningThresholdBinding
) -> ScreenAxis:
    """Build one axis: its levels, its pairs, its depth-resolved rows and its screen."""
    selected = selected_levels(manifest_path, axis)  # a missing manifest is refused by name here
    decoded = [
        (group, *_read_level(dataset_root, row)) for group, rows in selected for row in rows
    ]
    entries = [entry for _group, entry, *_rest in decoded]
    grid.require_clean_ofat(entries, COUPLED_SETTINGS[axis], axis_label=f"{axis}-only")
    revolutions = wp1.common_revolution_count([entry.duration_s for entry in entries])
    window_s = revolutions * wp1.NOMINAL_REVOLUTION_S
    support = grid.common_support([(entry.depth_min_mm, entry.depth_max_mm) for entry in entries])
    metrics = [
        grid.level_metrics(e.relative_path, v, t, d, window_s=window_s, support=support)
        for _group, e, v, t, d in decoded
    ]
    levels, depths, axis_median, measured = _axis_levels_and_depths(
        axis, manifest_path, decoded, metrics, support, window_s)
    base = _base_state(axis, levels, manifest_path)
    focus = str(base["straddling_pair"][0]), str(base["straddling_pair"][1])
    means = _gate_means(levels, depths)
    flagged = [row for row in levels if row["screen"] != "usable"]
    return ScreenAxis(
        axis=axis, inputs=tuple(entries), eligibility=ELIGIBILITY[axis],
        groups=tuple(group for group, _rows in selected),
        realizations=measured,
        levels=levels, depths=depths, base_state=base,
        pairs=tuple(
            _pair_row(axis, low, means[str(low["relative_path"])], high,
                      means[str(high["relative_path"])], support=support, screening_threshold=screening_threshold,
                      focus=(str(low["relative_path"]), str(high["relative_path"])) == focus)
            for low, high in itertools.combinations(levels, 2)),
        common={
            "nominal_rpm": wp1.NOMINAL_RPM, "revolution_s": wp1.NOMINAL_REVOLUTION_S, "levels":
            len(levels), "revolutions": revolutions, "window_s": window_s,
            "support_min_mm": support[0], "support_max_mm": support[1],
            "contains_plan_window": support[0] <= PLAN_SUPPORT_MM[0]
            and support[1] >= PLAN_SUPPORT_MM[1],
            "profiles_window": {r["relative_path"]: r["profiles_window"] for r in levels},
            "gates_in_support": {r["relative_path"]: r["gates_in_support"] for r in levels},
            "axis_median_gate_robust_spread_mm_s": axis_median},
        screen={
            "flagged_paths": [r["relative_path"] for r in flagged],
            "levels_dropout_limited": [r["relative_path"] for r in levels if r["dropout_limited"]],
            "levels_spread_limited": [r["relative_path"] for r in levels if r["spread_limited"]],
            "dropout_gate_limit": DROPOUT_GATE_LIMIT, "spread_ratio_limit": SPREAD_RATIO_LIMIT,
            "levels_screened": len(levels), "levels_flagged": len(flagged),
            "axis_median_gate_robust_spread_mm_s": axis_median},
        tgc_representation={
            "mode_word": TGC_WORDS["mode"], "start_word": TGC_WORDS["start"], "key_cell":
            "tgc_start_db", "role": TGC_REPRESENTATION_ROLE, "end_word": TGC_WORDS["end"],
            "mode_label": TGC_MODE_LABEL, "end_db": TGC_END_DB})


def _sensitivity_document(manifest_path: Path) -> dict[str, object]:
    """The sweep-level sensitivity statement: the axis is absent, so it is unidentifiable here."""
    values = manifest_cell_values(manifest_path, SENSITIVITY_COLUMN)
    if values != (SENSITIVITY_VALUE,):
        raise GainPowerScreenError(
            f"the manifest records sensitivity {list(values)}; this screen is the velocity-only "
            f"screening of a sweep whose sensitivity is fixed at {SENSITIVITY_VALUE!r}, and one that "
            "moves it is a different screen")
    return {"column": SENSITIVITY_COLUMN, "values_in_manifest": values,
            "rows_in_manifest": len(_manifest_rows(manifest_path)),
            "axis_present": False, "identifiable": False}


def build_gain_power_screen(
    dataset_root: Path = inventory.DATASET_ROOT,
    manifest_path: Path = inventory.REPORT_DIR / inventory.MANIFEST_NAME,
    screening_threshold_path: Path = inventory.REPORT_DIR / SCREENING_THRESHOLD_NAME,
    *,
    analysis_commit: str | None = None
) -> GainPowerScreen:
    """Build the velocity-only TGC/power screen from the manifest-selected recordings:
    ``analysis_commit`` is the revision to record, ``None`` probes the checkout's short git SHA once.
    A manifest, a WP1 screening_threshold, a coupled setting, a moved TGC word, an absent base-state level or a
    recording that contradicts its row is refused by name before anything is written.
    """
    root, manifest = Path(dataset_root), Path(manifest_path)
    manifest_sha256 = f"sha256:{grid.sha256_file(manifest)}"
    screening_threshold = grid.read_screening_threshold(Path(screening_threshold_path), manifest_sha256)
    axes = tuple(_build_axis(root, manifest, axis, screening_threshold) for axis in AXES)
    return GainPowerScreen(
        dataset_root=root.as_posix(), manifest_path=manifest.as_posix(),
        manifest_sha256=manifest_sha256, screening_threshold=screening_threshold, axes=axes,
        analysis_commit=analysis_commit if analysis_commit is not None else current_revision(),
        sensitivity=_sensitivity_document(manifest) | {
            "levels_screened": sum(len(axis.levels) for axis in axes)})


#: Metric definitions, recorded verbatim in the provenance document (WP0's rule for its tables).
DEFINITIONS: dict[str, str] = {
    "key": "the decoded cell the axis's ladder is ordered and keyed by, re-checked against the manifest cell: tgc_start_db (op word 24) on the TGC axis, the emit_power label on the power axis; never a filename and never a requested label",
    "tgc_representation": "op word 23 stays 0 and the reader labels that mode `uniform`, word 25 stays 255 and decodes to a fixed 40 dB end, and only word 24 / decoded tgc_start_db moves across the eight files: the representation this axis is screened through, not a validated scalar gain ladder",
    "power_gap": "the distance between two power levels along the instrument's declared low < medium < high: low -> high is two steps, with the base state's medium between them",
    "common_duration": "the leading whole nominal 500-RPM revolutions (0.12 s each) that fit every recording of one axis, truncated per file by the recorded timestamps; every distributional metric of that axis uses that window and nothing else",
    "common_support": "the intersection of one axis's decoded depth ranges; every cross-level summary of that axis uses it, and each level keeps its own native gate grid inside it",
    "spread_metrics": "per level, the IQR p75 - p25 across supported gates of the per-gate time means and the RMS about zero in mm/s (not a sigma); per gate in the depth rows, the IQR of that gate's window samples, their standard deviation about the gate's own mean and their RMS about zero",
    "zero_fraction": "samples exactly 0.0 over the common window and support, per gate in the depth rows: the dropout the screen screens on",
    "majority_blank": "a supported gate whose window samples are exactly zero in more than the declared dropout gate limit (0.5) of the profiles: a screening margin, not an instrument flag, and no gate is dropped from any table",
    "spread_ratio": "a level's largest per-gate robust spread divided by its own axis's median per-gate robust spread: the screen's second aggregate, with the declared limit 3.0, and every ratio is published so the margin can be moved",
    "screen": "one word from the two declared margins: usable, dropout-limited, spread-limited, or both; it says a setting cannot carry a wider ladder, never that a gain or a power setting caused the dropout",
    "difference": "signed low - high per-gate time mean at every common knot, mm/s, where low/high are the earlier/later level of that axis's declared key order; a negative value means the earlier level is slower there, and its mean and median over depth are that level's bias relative to the other, never a bias of the flow",
    "screening_threshold": "the committed sole-pair observed-discrepancy screening threshold max_gate_abs_mean_difference_mm_s, read from reference-repeat.provenance.json and pinned to this manifest's hash: the threshold every mean-profile effect is screened against. An effect above or below it is a screening outcome, not proof of a gain or power effect and not a bound on repeatability or uncontrolled drift",
    "depth_table": "one row per level per supported gate: depth, plan-window membership, the window length, and that gate's mean, robust spread, standard deviation, RMS and zero fraction",
    "base_state": "the level each axis's own rows do not sample: the value the manifest's other rows carry in that axis's key column (decoded on the TGC axis, the label on the power axis). Where the ladder holds that level - the shared anchor both reference recordings realize - the focus pair is the base level and the next setting above it; where it does not, the focus pair is the two ladder-adjacent levels whose keys bracket it",
    "realizations": "the recordings that realize one decoded key: the ladder holds every eligible decoded level, so the shared anchor level (TGC ≈19.9216 dB, emitting power medium) is realized by `prf/600.BDD` and `res/1-8.BDD` rather than being absent, one dropped or one standing in for the other; realization_paths names each of them and the provenance document carries each one's own numbers",
    "aggregation": "how one level's numbers are formed from its realizations: " + grid.AGGREGATION_RULE + ". On this screen the cells that assert an adverse screening outcome (the dropout count, the worst zero fraction, the per-gate spread and its ratio) are the worst realization's rather than a mean, and the level's screen word is recomputed from those outcomes",
    "velocity_only": "the files carry one axial-velocity channel in mm/s: dropout, bias and spread only, with echo SNR, receiver saturation, a safe plateau and acoustic energy neither measured nor inferred, and no gate or profile an independent experimental replicate; both panels of the figure carry this document's caption and the generating commit",
}

#: The roles and caveats that travel with every artefact, so they cannot drift between the provenance
#: document and the figure caption.
TGC_REPRESENTATION_ROLE = (
    "the TGC axis moves one decoded cell only: op word 23 stays 0 and the reader labels that mode "
    "`uniform`, word 25 stays 255 and decodes to a fixed 40 dB end, and only word 24 / tgc_start_db "
    "moves, so this is the representation the axis is screened through and not a validated scalar "
    "gain ladder")
SENSITIVITY_ROLE = (
    "sensitivity is fixed at medium in every committed manifest row: the axis is absent from this "
    "sweep and unidentifiable from it")
MIXER_SETPOINT_ROLE = (
    "nominal mixer marker only (500 RPM -> 8.33 Hz, one revolution = 0.12 s): no tachometer in these "
    "files, so the setpoint is not a phase reference")
REPLICATE_ROLE = (
    "one recording per setting and no acquisition order: no gate and no profile is an independent "
    "experimental replicate, a level effect cannot be separated from drift, and no p-value is produced")
VELOCITY_ONLY_ROLE = (
    "these files carry one axial-velocity channel in mm/s and no echo or energy profile, so echo SNR, "
    "receiver saturation, a safe plateau and acoustic energy are neither measured nor inferred here")

#: Panels of the reviewer-visible figure, in order.
FIGURE_PANELS: tuple[str, ...] = (
    ("dropout by depth: every level's per-gate zero fraction against depth with the declared "
     "majority-blank limit (the per-gate robust spread is tabulated in " + DEPTHS_NAME + ")"),
    ("each axis's focus pair against the screening_threshold: the signed low - high per-gate mean difference of "
     "the two levels bracketing the base state's own key, at the shared knots, against the WP1 "
     "screening_threshold band"))


def csv_texts(model: GainPowerScreen) -> dict[str, str]:
    """Render the three tables from the model's own rows, in axis order (LF endings)."""
    return {
        LEVELS_NAME: grid.csv_text(
            LEVEL_COLUMNS, [row for axis in model.axes for row in axis.levels]),
        PAIRS_NAME: grid.csv_text(
            PAIR_COLUMNS, [row for axis in model.axes for row in axis.pairs]),
        DEPTHS_NAME: grid.csv_text(
            DEPTH_COLUMNS, [row for axis in model.axes for row in axis.depths])}


def _axis_findings(screen: ScreenAxis, screening_threshold_mm_s: float) -> dict[str, object]:
    """One axis's screen, its pairs against the screening_threshold, its focus pair and its base state."""
    levels, pairs = screen.levels, screen.pairs
    above = [row for row in pairs if row["knots_above_screening_threshold"]]
    worst = max(pairs, key=lambda row: row["max_abs_difference_mm_s"])
    focus = next(row for row in pairs if row["focus_pair"])
    base = screen.base_state
    dropout = [row for row in levels if row["dropout_limited"]]
    spread = [row for row in levels if row["spread_limited"]]
    key, units = KEY_COLUMN[screen.axis], f" {KEY_UNITS[screen.axis]}".rstrip()
    dropout_text = ", ".join(
        f"{row['relative_path']} with {row['majority_blank_gates']} of {row['gates_in_support']} "
        f"gates covering {row['majority_blank_depth_ranges_mm']} mm at up to "
        f"{row['worst_gate_zero_fraction']:.4g} blank" for row in dropout) or "none"
    spread_text = ", ".join(
        f"{row['relative_path']} at {row['max_gate_spread_ratio_to_axis_median']:.4g}x = "
        f"{row['max_gate_robust_spread_mm_s']:.4g} mm/s at "
        f"{row['max_gate_robust_spread_depth_mm']:.4g} mm" for row in spread) or "none"
    return {
        "screen": {
            "key": key, "levels": len(levels), "levels_flagged": len(dropout) + len(spread),
            "levels_dropout_limited": [row["relative_path"] for row in dropout],
            "levels_spread_limited": [row["relative_path"] for row in spread],
            "dropout_gate_limit": DROPOUT_GATE_LIMIT, "spread_ratio_limit": SPREAD_RATIO_LIMIT,
            "axis_median_gate_robust_spread_mm_s": screen.common[
                "axis_median_gate_robust_spread_mm_s"],
            "statement": (
                f"Screen ({screen.axis}): {len(levels)} levels keyed by {key}{units}, overall dropout "
                f"{min(row['zero_fraction'] for row in levels):.4g}-"
                f"{max(row['zero_fraction'] for row in levels):.4g}; {len(dropout)} carry a gate blank "
                f"above {DROPOUT_GATE_LIMIT:g} of the window ({dropout_text}) and {len(spread)} a "
                f"per-gate spread past {SPREAD_RATIO_LIMIT:g}x the axis median ({spread_text}). A flag "
                "rules a setting out of a wider ladder, not a cause.")},
        "effect_gate": {
            "pairs": len(pairs), "screening_threshold_mm_s": screening_threshold_mm_s, "knots_above_screening_threshold": len(above),
            "pairs_above_screening_threshold": len(above), "clearing_pairs": [
                [row["low_path"], row["high_path"], row["knots_above_screening_threshold"],
                 row["depth_ranges_above_screening_threshold_mm"]] for row in above],
            "max_ratio_to_screening_threshold": worst["max_abs_difference_over_screening_threshold"],
            "max_abs_difference_mm_s": worst["max_abs_difference_mm_s"],
            "max_abs_difference_paths": [worst["low_path"], worst["high_path"]],
            "max_abs_difference_depth_mm": worst["max_abs_difference_depth_mm"],
            "statement": (
                f"Effect gate ({screen.axis}): the largest absolute per-knot mean difference over the "
                f"{len(pairs)} pair(s) is {worst['max_abs_difference_mm_s']:.4g} mm/s "
                f"({worst['low_path']} / {worst['high_path']} at "
                f"{worst['max_abs_difference_depth_mm']:.4g} mm) = "
                f"{worst['max_abs_difference_over_screening_threshold']:.3g} of the {screening_threshold_mm_s:.4g} mm/s WP1 "
                f"screening_threshold; {len(above)} pair(s) clear it somewhere, each with its knots, depth ranges "
                "and bias in the pairs table and in this block.")},
        "focus_pair": {
            "low_path": focus["low_path"], "high_path": focus["high_path"],
            "low_key": focus["low_key"], "high_key": focus["high_key"], "knots": focus["knots"],
            "ratio_to_screening_threshold": focus["max_abs_difference_over_screening_threshold"],
            "knots_above_screening_threshold": focus["knots_above_screening_threshold"],
            "mean_signed_difference_mm_s": focus["mean_signed_difference_mm_s"],
            "max_abs_difference_mm_s": focus["max_abs_difference_mm_s"],
            "max_abs_difference_depth_mm": focus["max_abs_difference_depth_mm"],
            "statement": (
                f"Focus pair ({screen.axis}): "
                + (
                    f"the base state's own {key} ({_key_text(base['decoded_key'])}) "
                    "is a level of this axis, realized by the reference recordings, so the focus "
                    "pair compares it with the next setting above it — "
                    if base["focus_pair_kind"] == "base_state_is_a_level"
                    else f"the base state's own {key} ({_key_text(base['decoded_key'])}) is no level "
                    "of this axis; the levels bracketing it — "
                )
                + f"{focus['low_path']} ({_key_text(focus['low_key'])}) and {focus['high_path']} "
                f"({_key_text(focus['high_key'])}) — differ by at most "
                f"{focus['max_abs_difference_mm_s']:.4g} mm/s at "
                f"{focus['max_abs_difference_depth_mm']:.4g} mm = "
                f"{focus['max_abs_difference_over_screening_threshold']:.3g} of the {screening_threshold_mm_s:.4g} mm/s "
                f"screening_threshold, {focus['knots_above_screening_threshold']} of {focus['knots']} knots above it (mean "
                f"signed {focus['mean_signed_difference_mm_s']:+.4g} mm/s).")},
        "base_state": {
            "label": base["label"], "decoded_key": base["decoded_key"],
            "in_ladder": base["in_ladder"], "focus_pair_kind": base["focus_pair_kind"],
            "straddling_pair": list(base["straddling_pair"]),
            "straddling_keys": list(base["straddling_keys"]),
            "statement": (
                f"Base state ({screen.axis}): the manifest's other rows carry {key} = "
                f"{_key_text(base['decoded_key'])} "
                + (
                    "and this ladder holds it, realized by both reference recordings, so the "
                    "reference condition is one of its levels "
                    if base["in_ladder"]
                    else "and no level of this axis does, so the ladder straddles it "
                )
                + f"at {_key_text(base['straddling_keys'][0])} and "
                f"{_key_text(base['straddling_keys'][1])} "
                f"({base['straddling_pair'][0]} / {base['straddling_pair'][1]}).")}}


def _findings(model: GainPowerScreen) -> dict[str, object]:
    """The plan's TGC/power questions answered from the numbers the tables already carry: every
    statement is composed from those values, and nothing here is a p-value, an acquisition-order
    inference, a claim about echo SNR or saturation, a safe plateau, or another axis's verdict."""
    screening_threshold, sensitivity = model.screening_threshold.value_mm_s, model.sensitivity
    axes = {axis.axis: _axis_findings(axis, screening_threshold) for axis in model.axes}
    levels = [row for axis in model.axes for row in axis.levels]
    pairs = [row for axis in model.axes for row in axis.pairs]
    flagged = [(axis.axis, row) for axis in model.axes for row in axis.levels
               if row["screen"] != "usable"]
    above = sum(f["effect_gate"]["pairs_above_screening_threshold"] for f in axes.values())
    focus = {name: f["focus_pair"] for name, f in axes.items()}
    power, rows = focus["em_pow"], sensitivity["rows_in_manifest"]
    flagged_text = "; ".join(f"{name} {row['relative_path']}: {row['screen']}"
                             for name, row in flagged) or "none"
    base_text = "; ".join(f"{name}: {row['low_key']} and {row['high_key']}"
                          for name, row in focus.items())
    return {
        "screening_threshold": {
            "value_mm_s": screening_threshold, "metric": model.screening_threshold.metric,
            "source_path": model.screening_threshold.path,
            "median_abs_mean_difference_mm_s": model.screening_threshold.median_abs_mean_difference_mm_s,
            "statement": (
                f"Threshold: the committed WP1 screening_threshold {screening_threshold:.6g} mm/s "
                f"({model.screening_threshold.metric}, from {model.screening_threshold.path}) is the "
                "sole-pair observed-discrepancy screening threshold: one observed realization of "
                "same-settings repeatability plus uncontrolled drift, and not a bound on either. "
                "Every mean-profile effect in both axes is screened against it, above or below, "
                "without that outcome proving a gain or power effect.")},
        "axes": axes, "screen_summary": {
            "levels": len(levels), "pairs": len(pairs), "levels_flagged": len(flagged),
            "pairs_above_screening_threshold": above, "flagged": [
                {**{cell: row[cell] for cell in FLAGGED_CELLS}, "axis": name}
                for name, row in flagged],
            "realizations": {
                "rule": grid.AGGREGATION,
                "recordings": sum(len(axis.inputs) for axis in model.axes),
                "multi_realization_levels": [
                    {"axis": axis.axis, "relative_path": group.primary_path,
                     "realization_paths": list(group.realization_paths)}
                    for axis in model.axes for group in axis.groups
                    if len(group.realizations) > 1
                ],
                "statement": (
                    f"Realizations: the {len(levels)} screened levels are the setting-based "
                    f"selection of {sum(len(axis.inputs) for axis in model.axes)} recording(s) — "
                    "every recording whose decoded settings put it at one of these keys, whatever "
                    "folder requested it — so the shared anchor level is present in both axes and "
                    "carries both of the reference recordings. Each level's typical cells are the "
                    "unweighted mean of its realizations' cells; its adverse screening cells are "
                    "the worst realization's, so no recording's dropout is averaged away."),
            },
            "statement": (
                f"Screen: {len(levels)} levels over two axes and {len(pairs)} pairs; {len(flagged)} "
                f"levels are flagged under the two declared margins ({flagged_text}) and {above} of "
                f"the {len(pairs)} pairs clear the screening_threshold anywhere. A flag rules a setting out of a "
                "wider ladder; it is not a statement about gain, power or the flow.")},
        "sensitivity": dict(sensitivity) | {"statement": (
            f"Sensitivity: every one of the {rows} committed manifest rows carries "
            f"{SENSITIVITY_VALUE!r} and neither screened axis varies it, so the axis is absent from "
            "this sweep and its effect is unidentifiable from it.")},
        "velocity_only": {
            "channels": "one axial-velocity channel per file, in mm/s; no echo or energy profile",
            "not_inferred": ["echo SNR", "receiver saturation", "a safe plateau", "acoustic energy",
                             "the gain a TGC or emitting-power setting applied"],
            "measured": [(
                "depth-resolved dropout (the share of window samples exactly 0.0 per gate); bias "
                "(the signed per-gate mean difference between two levels, per knot); variance and "
                "robust spread (per-gate IQR and std, by level and depth)")],
            "statement": (
                "Velocity only: this screen measures dropout, bias and spread and stops there. Echo "
                "SNR, receiver saturation, a safe plateau and acoustic energy are not measurable in "
                "these files and are not inferred, and a dropout or spread anomaly is not attributed "
                "to gain.")},
        "diagnostic": {
            "justified": True, "wider_ladder_justified": False, "outcome_claimed": False,
            "flagged_levels": len(flagged), "pairs_above_screening_threshold": above,
            "focus_pair_ratios": {name: row["ratio_to_screening_threshold"] for name, row in focus.items()},
            "statement": (
                "Diagnostic: the velocity-only evidence justifies exactly one "
                "higher-sensitivity/echo-energy diagnostic before any wider TGC, power or sensitivity "
                f"ladder, and no ladder of its own — {len(flagged)} of the {len(levels)} screened "
                "levels are flagged for a dropout or spread this screen cannot attribute to the gain "
                "rather than the flow, drift or one recording, and sensitivity is fixed at "
                f"{SENSITIVITY_VALUE!r} in all {rows} rows, so an echo/energy measurement is the only "
                "thing that would make that axis identifiable at all. A wider ladder is not justified "
                "first: the TGC representation is unsettled for the very cell a ladder would step, and "
                f"the power axis is unremarkable in velocity ({power['ratio_to_screening_threshold']:.3g} of the "
                f"screening_threshold, {power['knots_above_screening_threshold']} knots above it). This module does not "
                "predict that diagnostic's outcome and claims nothing about what it would show.")},
        "limitations": [
            (f"One recording per setting and no acquisition order: the only repeat is the "
             f"sole-pair observed-discrepancy screening threshold, {screening_threshold:.4g} mm/s "
             f"per gate ({model.screening_threshold.metric}), one observed realization of "
             f"repeatability plus uncontrolled drift and not a bound on either: no level is "
             f"replicated, no p-value is produced and no replicate claim is made."),
            ("Velocity only: " + VELOCITY_ONLY_ROLE + ". A majority-blank gate or a disproportionate "
             "per-gate spread is a property of the recorded velocity array, not evidence that a gain, "
             "a power or the receiver saturated."),
            ("TGC representation: " + TGC_REPRESENTATION_ROLE
             + ". Reading word 24 as a calibrated gain set point is reading something these files do "
             "not establish, and no wider TGC ladder can be designed on that reading."),
            ("Each axis focuses on the pair that carries its base state "
             f"({base_text}), and that state's sensitivity is medium like every other row, so the "
             "screen compares the reference condition from inside its own ladder only where the "
             "shared anchor level is one of its levels. "
             + SENSITIVITY_ROLE + " — no pair in this screen varies it, and its effect on dropout, "
             "bias or spread is not estimable from the committed sweep.")]}


def figure_caption(model: GainPowerScreen) -> str:
    """The caption the committed figure and the provenance document both carry: both axes, both common
    views, the screening_threshold, the screening margins, the focus pairs and the diagnostic sentence, so a
    reader of the figure alone cannot miss the caveats."""
    findings = _findings(model)
    summary, diagnostic = findings["screen_summary"], findings["diagnostic"]
    realizations = summary["realizations"]
    first, second = model.axes
    labels = [", ".join(str(row["requested_label"]) for row in axis.levels) for axis in model.axes]
    return (
        f"{ARTEFACT}: the velocity-only screening of {summary['levels']} committed levels over two "
        f"axes — {first.axis} {len(first.levels)} ({labels[0]}) and {second.axis} "
        f"{len(second.levels)} ({labels[1]}). "
        + realizations["statement"] + " "
        f"Common-duration view per axis: "
        f"{first.common['revolutions']} nominal {first.common['nominal_rpm']:g}-RPM revolutions = "
        f"{first.common['window_s']:.4g} s for {first.axis} and {second.common['revolutions']} = "
        f"{second.common['window_s']:.4g} s for {second.axis}, truncated per file by the recorded "
        f"timestamps. Common support: {first.common['support_min_mm']:.6g}-"
        f"{first.common['support_max_mm']:.6g} mm on each axis's own 1.85 mm grid, which contains the "
        f"plan's declared {PLAN_SUPPORT_MM[0]:g}-{PLAN_SUPPORT_MM[1]:g} mm window; pairs use the "
        "higher key's own gate depths as knots, so nothing is interpolated or upsampled. Threshold: "
        f"the committed WP1 screening_threshold {model.screening_threshold.value_mm_s:.4g} mm/s ({model.screening_threshold.metric}, "
        f"from {model.screening_threshold.path}, {model.screening_threshold.source_sha256[:12]}...). Screening margins: a "
        f"gate blank in more than {DROPOUT_GATE_LIMIT:g} of the window, and a per-gate robust spread "
        f"past {SPREAD_RATIO_LIMIT:g}x the axis's median. {summary['statement']} "
        f"{diagnostic['statement']} Spread and bias by depth are in {DEPTHS_NAME}. "
        f"{MIXER_SETPOINT_ROLE}. {REPLICATE_ROLE}. {TGC_REPRESENTATION_ROLE}. {SENSITIVITY_ROLE}. "
        f"Generated at commit {model.analysis_commit or 'unknown'} from {model.manifest_path} "
        f"({model.manifest_sha256}).")


def _axis_document(axis: ScreenAxis) -> dict[str, object]:
    """One axis's block of the provenance document, keys in a fixed order."""
    common = axis.common
    level_of = {path: group.primary_path for group in axis.groups
                for path in group.realization_paths}
    cells: dict[str, dict[str, object]] = {
        field: {row["relative_path"]: row[field] for row in axis.realizations}
        for field in REALIZATION_CELLS
    }
    return {
        "axis": axis.axis, "tgc_representation": axis.tgc_representation,
        "key": {"column": KEY_COLUMN[axis.axis], "label": KEY_LABEL[axis.axis],
                "units": KEY_UNITS[axis.axis], "values": [row["key_value"] for row in axis.levels]},
        "audited_constants": {"settings": list(COUPLED_SETTINGS[axis.axis]), "tgc_end_db": TGC_END_DB,
                              "tgc_mode": axis.levels[0]["tgc_mode"],
                              "sensitivity": SENSITIVITY_VALUE},
        "base_state": axis.base_state,
        "aggregation": {
            "rule": grid.AGGREGATION, "statement": grid.AGGREGATION_RULE,
            "levels": len(axis.levels), "recordings": len(axis.inputs),
            "multi_realization_levels": [
                {"relative_path": group.primary_path,
                 "realization_paths": list(group.realization_paths)}
                for group in axis.groups if len(group.realizations) > 1
            ],
            "worst_cells": list(WORST_CELLS),
            "worst_cells_rule": (
                "a cell that asserts an adverse screening outcome is the worst realization's "
                "value, not a mean over realizations, so a dropout or a disproportionate spread "
                "one recording found is never averaged away; the level's screen word is recomputed "
                "from those outcomes"),
        },
        "screening": {key: axis.screen[key] for key in (
            "dropout_gate_limit", "spread_ratio_limit", "levels_screened", "levels_flagged",
            "levels_dropout_limited", "levels_spread_limited", "flagged_paths",
            "axis_median_gate_robust_spread_mm_s")},
        "inputs": [
            {**{cell: row[cell] for cell in INPUT_CELLS},
             "relative_path": entry.relative_path,
             "level_path": level_of[entry.relative_path],
             "realizations": next(r["realizations"] for r in axis.levels
                                  if r["relative_path"] == level_of[entry.relative_path]),
             "source_sha256": entry.source_sha256}
            for entry, row in zip(axis.inputs, axis.realizations, strict=True)],
        "levels": [
            grid.level_realizations_document(group, cells, fields=REALIZATION_CELLS)
            for group in axis.groups
        ],
        "views": {
            "time": {
                "common_duration": {key: common[key] for key in (
                    "nominal_rpm", "revolution_s", "revolutions", "window_s", "profiles_window")},
                "rule": ("the largest integer number of nominal revolutions fitting every recording "
                         "of this axis, truncated per file by the recorded timestamps")},
            "depth": {
                "common_support_min_mm": common["support_min_mm"],
                "common_support_max_mm": common["support_max_mm"],
                "plan_declared_mm": list(PLAN_SUPPORT_MM),
                "contains_plan_window": common["contains_plan_window"],
                "gates_in_support": common["gates_in_support"],
                "rule": ("the intersection of this axis's decoded depth ranges; each level keeps its "
                         "own decoded gate grid inside it and nothing is resampled")},
            "alignment": {
                "upsampled": False, "focus_pair": [
                    next(row for row in axis.pairs if row["focus_pair"])[key]
                    for key in ("low_path", "high_path")],
                "max_knot_offset_over_all_pairs_mm": max(row["max_knot_offset_mm"]
                                                         for row in axis.pairs),
                "knot_rule": ("the higher key's native gate depths inside the common support, so the "
                              "knot spacing is never finer than that participant's own grid; the "
                              "lower level is sampled there by its nearest native gate, never "
                              "interpolated")},
            "depths": {"rows": len(axis.depths), "columns": list(DEPTH_COLUMNS)}}}


def provenance_document(model: GainPowerScreen) -> dict[str, object]:
    """The machine-readable record beside the three tables and the figure.

    Keys are inserted in a fixed order, so a regeneration from the same commit is byte-identical.
    """
    tables = ((LEVELS_NAME, LEVEL_COLUMNS, "levels"), (PAIRS_NAME, PAIR_COLUMNS, "pairs"),
              (DEPTHS_NAME, DEPTH_COLUMNS, "depths"))
    return {
        "artefact": ARTEFACT, "axes": list(AXES), "analysis_commit": model.analysis_commit,
        "dataset_root": model.dataset_root, "sensitivity": model.sensitivity,
        "manifest": {"path": model.manifest_path, "sha256": model.manifest_sha256},
        "screening_threshold": dict(model.screening_threshold.model_dump()) | {"source_path": model.screening_threshold.path},
        "axis_blocks": [_axis_document(axis) for axis in model.axes],
        "definitions": dict(DEFINITIONS), "findings": _findings(model),
        "tables": {name: {"path": path, "columns": list(columns),
                          "rows": sum(len(getattr(axis, name)) for axis in model.axes)}
                   for path, columns, name in tables},
        "figure": {"path": f"{FIGURES_DIRNAME}/{FIGURE_NAME}", "caption": figure_caption(model),
                   "panels": list(FIGURE_PANELS)},
        "regeneration": {
            "command": (".venv/Scripts/python.exe -m udv_echo_process.cli gain-power-screen "
                        f"--analysis-commit {model.analysis_commit or '<generator commit>'}"),
            "note": ("pass the recorded analysis_commit to reproduce these artefacts byte for byte; "
                     "the bare command records the current HEAD")}}


def render_figure(model: GainPowerScreen, path: Path, *, dpi: int = 150) -> Path:
    """Write the two-panel screening figure, deterministically, and return it: all 10 levels'
    dropout against depth with the declared majority-blank limit, and each axis's focus pair against
    the WP1 screening_threshold band. The frame is the shared writer's, so this module owns the panels only.
    """
    series = {str(level["relative_path"]): (
        np.asarray([r["depth_mm"] for r in axis.depths
                    if r["relative_path"] == level["relative_path"]], dtype=float),
        np.asarray([r["zero_fraction"] for r in axis.depths
                    if r["relative_path"] == level["relative_path"]], dtype=float))
        for axis in model.axes for level in axis.levels}
    means = {path_: profile for axis in model.axes
             for path_, profile in _gate_means(axis.levels, axis.depths).items()}
    focus_rows = [next(row for row in axis.pairs if row["focus_pair"]) for axis in model.axes]
    screening_threshold_mm_s = model.screening_threshold.value_mm_s
    supports = {axis.axis: (axis.common["support_min_mm"], axis.common["support_max_mm"])
                for axis in model.axes}

    def draw(axes: Sequence[object]) -> None:
        dropout_ax, focus_ax = axes
        dropout_ax.axhline(DROPOUT_GATE_LIMIT, color="#555555", linewidth=0.8, linestyle=":")
        for axis in model.axes:
            for level in axis.levels:
                depths, blank = series[str(level["relative_path"])]
                dropout_ax.plot(depths, blank, linewidth=1.1,
                                label=f"{axis.axis} {level['requested_label']}")
        dropout_ax.set_xlabel("depth from transducer face [mm]")
        dropout_ax.set_ylabel("per-gate zero fraction")
        dropout_ax.grid(alpha=0.2)
        dropout_ax.legend(loc="upper left", fontsize=6.0, ncols=2, framealpha=0.9)
        dropout_ax.set_title(
            f"per-gate dropout against the {DROPOUT_GATE_LIMIT:g} majority-blank limit (dotted); the "
            f"per-gate robust spread is in {DEPTHS_NAME}", fontsize=8.5)
        focus_ax.axvspan(-1.0, 1.0, color="#999999", alpha=0.25, linewidth=0)
        for row in focus_rows:
            low_depths, low_mean = means[row["low_path"]]
            high_depths, high_mean = means[row["high_path"]]
            inside = grid.in_support(high_depths, supports[row["axis"]])
            knots = high_depths[inside]
            signed = low_mean[grid.nearest_gate_indices(low_depths, knots)] - high_mean[inside]
            focus_ax.plot(np.asarray(signed, dtype=float) / screening_threshold_mm_s, knots, linewidth=1.2,
                          label=(f"{row['axis']}: {row['low_label']} - {row['high_label']} "
                                 f"(max {row['max_abs_difference_over_screening_threshold']:.3g})"))
        focus_ax.set_xlim(-1.6, 1.6)
        focus_ax.set_xlabel("signed low - high difference / WP1 screening_threshold")
        focus_ax.set_ylabel("depth from transducer face [mm]")
        focus_ax.invert_yaxis()
        focus_ax.grid(alpha=0.2)
        focus_ax.legend(loc="lower left", fontsize=6.2, framealpha=0.9)
        focus_ax.set_title("focus pairs carrying the base state, against the WP1 screening_threshold band",
                           fontsize=9.5)

    return grid.panel_figure(
        f"{ARTEFACT} — {sum(len(axis.levels) for axis in model.axes)} TGC and emitting-power "
        "settings screened against the WP1 sole-pair observed-discrepancy screening threshold",
        figure_caption(model), draw, path, caption_width=150, dpi=dpi,
        adjust={"top": 0.80, "bottom": 0.36, "wspace": 0.34})


def write_gain_power_screen(
    dataset_root: Path = inventory.DATASET_ROOT,
    report_dir: Path = inventory.REPORT_DIR,
    *,
    manifest_path: Path | None = None,
    screening_threshold_path: Path | None = None,
    analysis_commit: str | None = None
) -> GainPowerScreen:
    """Build the screen and write the four reviewer-visible artefacts: the text artefacts use LF
    endings and the figure is written deterministically, so two runs on the same inputs and commit
    produce identical bytes, and nothing is written when the build raises."""
    directory = Path(report_dir)
    manifest = Path(manifest_path) if manifest_path is not None else directory / MANIFEST_NAME
    screening_threshold = Path(screening_threshold_path) if screening_threshold_path is not None else directory / SCREENING_THRESHOLD_NAME
    model = build_gain_power_screen(dataset_root, manifest, screening_threshold,
                                   analysis_commit=analysis_commit)
    grid.write_text_artefacts(directory, csv_texts(model) | {PROVENANCE_NAME:
        json.dumps(provenance_document(model), indent=2) + "\n"})
    render_figure(model, directory / FIGURES_DIRNAME / FIGURE_NAME)
    return model
