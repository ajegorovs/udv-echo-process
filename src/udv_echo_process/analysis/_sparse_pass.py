"""The sparse pass, decoded once — the loader WP1 and WP2 both read.

The two measurement slices that follow WP0 must agree with the frozen table about
*what* is measured before they can disagree about *what it means*: the same primary
window (the designed 12 s), the same common physical support, the same per-gate
distributional metrics, and the same recording→point binding. This module is that
agreement, implemented once.

It adds no science and no artefact. It reuses, unchanged:

- :mod:`udv_echo_process.analysis.sparse_inventory` — the frozen WP0 module's public
  binding and decoding (:func:`~sparse_inventory.identify_pass`,
  :func:`~sparse_inventory.read_job_records`, :func:`~sparse_inventory.bind_recordings`,
  :func:`~sparse_inventory.decode_point`, :func:`~sparse_inventory.common_window_s`)
  and its three refusals per point (the acquisition layer's own decode, the declared
  words, the retired target), so a slice cannot see a point the table rejected;
- :mod:`udv_echo_process.analysis._native_grid` — ``window`` (the leading
  ``window_s`` cut by the stored timestamps), ``common_support`` and ``in_support``;
- :func:`udv_echo_process.analysis.reference_repeat.gate_metrics` — the per-gate
  ``mean`` / ``median`` / ``iqr`` / ``rms`` / ``zero_fraction`` the table's
  ``supported_*`` cells are aggregates of.

The window and the support are *not* recomputed by a slice, and a slice may not
substitute its own: the floors WP1 and WP2 produce are only comparable with each
other, with the table, and with WP3/WP4's contrasts if all of them cut the same
interval and mask the same gates.

No scientific effect is measured here either — this is the shared precondition.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import NamedTuple

import numpy as np

from udv_echo_process.analysis._native_grid import (
    common_support,
    in_support,
    window,
)
from udv_echo_process.analysis.reference_repeat import gate_metrics
from udv_echo_process.analysis.sparse_inventory import (
    DATASET_ROOT,
    PLAN_PATH,
    DecodedPoint,
    PlannedJobRecord,
    SparseIngestError,
    bind_recordings,
    common_window_s,
    decode_point,
    identify_pass,
    read_job_records,
    require_declared_settings,
    require_reader_agrees_with_the_log,
    require_retired_target,
)

#: The pass's five scientific jobs and the four reference jobs, as the plan names
#: them. ``KIND_SCIENTIFIC`` is the kind of a job whose rows are a new condition.
SCIENTIFIC_JOBS: tuple[str, ...] = (
    "burst-4",
    "burst-18",
    "emissions-8",
    "emissions-64",
    "emissions-128",
)
REFERENCE_JOBS: tuple[str, ...] = (
    "common-reference-1",
    "common-reference-2",
    "common-reference-3",
    "common-reference-4",
)

#: The two label prefixes the pass uses: the controls bracket the scientific rows.
CONTROL_PREFIX = "ctrl-"


class PassDecoding(NamedTuple):
    """Every committed recording of the pass, decoded, with the two shared views.

    ``points`` is in acquisition order (the plan's step order, then each job's key
    order), which is what makes the pass's drift reconstructible: the historical
    sweep could not recover order from its files and had to bound drift instead.
    """

    dataset_root: Path
    plan: object
    run: dict[str, object]
    records: tuple[PlannedJobRecord, ...]
    points: tuple[DecodedPoint, ...]
    window_s: float
    window_revolutions: int
    support_mm: tuple[float, float]
    plan_fingerprint: str

    def by_label(self, label: str) -> DecodedPoint:
        """The one decoded point whose label is ``label``, or a refusal naming it."""
        matches = [point for point in self.points if point.binding.point.label == label]
        if len(matches) != 1:
            raise SparseIngestError(
                f"the pass holds {len(matches)} recordings labelled {label!r}, "
                "expected exactly one"
            )
        return matches[0]

    def of_job(self, job: str) -> tuple[DecodedPoint, ...]:
        """Every decoded point of one job, in acquisition order."""
        return tuple(point for point in self.points if point.binding.job.job == job)

    def of_kind(self, kind: str) -> tuple[DecodedPoint, ...]:
        """Every decoded point of the jobs of one kind (``scientific``/``common-reference``)."""
        return tuple(point for point in self.points if point.binding.job.kind == kind)


def decode_pass(
    dataset_root: Path = DATASET_ROOT,
    *,
    plan_path: Path = PLAN_PATH,
    plan_name: str | None = None,
) -> PassDecoding:
    """Bind and decode every committed recording of the pass, or refuse by name.

    ``plan_name`` names the pass record inside the dataset root and defaults to the plan's
    own name, so a later pass reuses this loader (and every refusal below) unchanged.

    Raises:
        SparseIngestError: for any condition the frozen WP0 ingest refuses — a pass whose
            plan, record and fingerprint do not agree (the same pass-level identity check
            ``build_sparse_ingest`` runs, taken from the shared ``identify_pass``), a
            recording no planned point claims (or the reverse), a decode that disagrees with
            the acquisition layer's own, a stored word that is not the declared setting, or a
            log whose planned target has been rewritten. Measuring a point the table refused
            is the one thing a slice may not do.
    """
    root = Path(dataset_root)
    # The pass's whole identity, from the same helper the ingest takes it from: this
    # loader must not be able to decode a pass combination the frozen table would refuse,
    # because a notebook holding the recordings directly is now a primary reader.
    plan, run, name = identify_pass(root, plan_path=plan_path, plan_name=plan_name)
    records = read_job_records(root, plan, run)
    bindings = bind_recordings(root, records)

    points: list[DecodedPoint] = []
    for binding in bindings:
        result = decode_point(root / binding.relative_path, binding)
        if isinstance(result, str):
            raise SparseIngestError(
                f"{binding.relative_path}: the frozen ingest reports a decode failure "
                f"({result}); this slice measures only points the table accepted"
            )
        require_reader_agrees_with_the_log(result)
        require_declared_settings(result)
        require_retired_target(result, plan_name=name)
        points.append(result)

    # The binding walk returns the recordings in discovery order; the pass's own order
    # is the one its record assigned, and every drift statement depends on it.
    points.sort(key=lambda point: int(point.binding.order))
    spans = [float(point.time_s[-1] - point.time_s[0]) for point in points]
    window_s = common_window_s(spans)
    support = common_support(
        [(float(point.depths[0]), float(np.max(point.depths))) for point in points]
    )
    return PassDecoding(
        dataset_root=root,
        plan=plan,
        run=run,
        records=records,
        points=tuple(points),
        window_s=window_s,
        window_revolutions=round(window_s / (60.0 / 500.0)),
        support_mm=support,
        plan_fingerprint=str(plan.plan_fingerprint),
    )


def primary_window(point: DecodedPoint, window_s: float) -> np.ndarray:
    """One recording's primary window: the leading ``window_s``, cut by its own stamps.

    Returns the ``(profiles, gates)`` block the shared views are computed on, so the
    two slices, the table and the later work packages all cut the same interval.
    """
    return window(point.values, point.time_s, window_s)


def support_mask(point: DecodedPoint, support_mm: tuple[float, float]) -> np.ndarray:
    """The native gates of one recording that lie inside the common physical support."""
    return in_support(point.depths, support_mm)


def supported_gates(point: DecodedPoint, support_mm: tuple[float, float]) -> np.ndarray:
    """The gate depths a slice may compare: inside the support, on the native grid."""
    mask = support_mask(point, support_mm)
    depths = np.asarray(point.depths, dtype=float)[mask]
    if depths.size == 0:
        raise SparseIngestError(
            f"{point.relative_path}: no native gate lies inside the common support "
            f"{support_mm}; this point cannot enter a depth-resolved comparison"
        )
    return depths


def gate_statistics(
    point: DecodedPoint,
    *,
    window_s: float,
    support_mm: tuple[float, float],
) -> dict[str, np.ndarray]:
    """Per-gate statistics of one recording, masked to the common support.

    The names are :func:`gate_metrics`'s (``mean``, ``median``, ``iqr``, ``rms``,
    ``zero_fraction``); the arrays are one entry per *supported* gate, in the
    recording's native depth order.
    """
    block = primary_window(point, window_s)
    metrics = gate_metrics(block)
    mask = support_mask(point, support_mm)
    return {name: values[mask] for name, values in metrics.items()}


def supported_mean_of(
    point: DecodedPoint, *, window_s: float, support_mm: tuple[float, float], name: str
) -> float:
    """The unweighted mean of one per-gate statistic across the supported gates.

    This is the reduction the frozen table's ``supported_*`` cells use, restated here
    so a slice's scalar summary is the table's own number and not a second definition.
    """
    metrics = gate_statistics(point, window_s=window_s, support_mm=support_mm)
    if name not in metrics:
        raise SparseIngestError(
            f"unknown gate statistic {name!r}; the table's are "
            f"{sorted(gate_metrics(np.zeros((2, 2))))}"
        )
    values = np.asarray(metrics[name], dtype=float)
    total = float(np.sum(values))
    if not math.isfinite(total):
        raise SparseIngestError(
            f"{point.relative_path}: the {name!r} statistic is not finite "
            f"({total!r}); a NaN point must not enter a floor"
        )
    return total / values.size
