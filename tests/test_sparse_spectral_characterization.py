"""SA2.4 S1: the scalar spectral characterization backend, held to §2 of its contract.

This file is written **red first**. The S1 module
(``udv_echo_process.analysis.sparse_spectral_characterization``) is created by a separate change,
so its import is guarded and every test row asserts the frozen interface is present rather than
being silently skipped: a missing module is a *failure*, not an ``importorskip``. When S1 lands,
these rows go green without any change to their meaning.

What is asserted here, and only here:

* the one new metric - the low-frequency band power fraction of §2 - is the weighted cell-overlap
  sum it is defined to be, on an even-``N`` and an odd-``N`` grid, with ``Phi = 1`` at the
  boundary ``f_low = Nyquist`` and monotone in ``f_low``;
* tone locality: a low-frequency tone carries nearly all its power inside a 1 Hz band, a
  high-frequency tone none of it - asserted with a deliberately loose lower bound, because the
  band edge cuts a Hann lobe and demanding ``> 0.99`` would be demanding an artefact of leakage;
* the three states never collapse: a constant gate is ``defined-zero-power`` (``Phi is None``,
  ``B == 0.0``), a refused axis is ``refused-axis`` (all numerics ``None``);
* the denominator is **read** from the estimate, never recomputed;
* a malformed band edge raises the typed error, while an *unsupported target* is an answer;
* the sweep is driven by ``supported_columns`` and its count is ``ViewProvenance.supported_gates``;
* the real E128 cell refuses the 8.333 Hz rotor row and supports the 1 Hz band;
* an AST guard proves the module implements no transform, taper, grid or normalization of its own
  and calls neither ``characterize_stamps`` nor ``spectral_admission``.

No committed spectral *shape* is interpreted: the fraction is a descriptive reduction of an
already-published density, and no exploratory number (a floor, a spread, the 71.6 % smoke datum)
appears anywhere in this file.
"""

from __future__ import annotations

import ast
import inspect
import math
import os
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis._sparse_view import (
    SparseView,
    WindowView,
    primary_view,
    view_provenance,
    view_rule,
)
from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES
from udv_echo_process.analysis.sparse_periodogram import (
    SpectralVerdict,
    periodogram_of_view,
)
from udv_echo_process.analysis.sparse_recurrence import Detrending
from udv_echo_process.analysis.sparse_spectral_capability import PROBE_TARGETS
from udv_echo_process.analysis.sparse_spectral_support import one_sided_frequency_grid
from udv_echo_process.analysis.sparse_target_support import frequency_cell

# --------------------------------------------------------------------------------------
# the guarded import: red until S1 lands, and a failure rather than a skip
# --------------------------------------------------------------------------------------

try:  # pragma: no cover - the branch taken depends on the revision under test
    from udv_echo_process.analysis import sparse_spectral_characterization as backend
except ImportError as exc:  # pragma: no cover
    backend = None  # type: ignore[assignment]
    _IMPORT_ERROR: ImportError | None = exc
else:  # pragma: no cover
    _IMPORT_ERROR = None

#: The frozen public interface of S1. Every one of these names must exist on the module.
REQUIRED_NAMES: tuple[str, ...] = (
    "BandFractionState",
    "BandFractionError",
    "LowFrequencyBandFraction",
    "CellSpectralCharacterization",
    "characterization_of_view",
    "low_frequency_power_fraction",
)


def _require_backend():
    """The S1 module, or a failure naming exactly what is missing.

    Deliberately an assertion per test row rather than a module-level ``importorskip``: a
    backend that has not been written must show as red, and a backend that is written but drops
    a frozen name must show which name, not skip.
    """
    assert backend is not None, (
        "the S1 backend module analysis.sparse_spectral_characterization is not importable "
        f"({_IMPORT_ERROR!r}); this file is written red-first and goes green when S1 lands"
    )
    missing = [name for name in REQUIRED_NAMES if not hasattr(backend, name)]
    assert not missing, f"the S1 backend is missing frozen interface names: {missing}"
    return backend


#: The repository root, from this file's own location - never a hard-coded path.
ROOT = Path(__file__).resolve().parents[1]
#: The one module S1 is. ``SA24_BACKEND_PATH`` may point this at another file (e.g. a path that
#: does not exist) to show the AST guard is red when S1 has not been written, exactly as
#: ``SA23_NOTEBOOK`` lets the notebook checks be pointed at an older revision.
BACKEND_MODULE = Path(
    os.environ.get(
        "SA24_BACKEND_PATH",
        ROOT
        / "src"
        / "udv_echo_process"
        / "analysis"
        / "sparse_spectral_characterization.py",
    )
)

#: The synthetic cadence, exactly uniform so the closed-form answers below are exact.
DT_S = 0.02
N_EVEN = 256
N_ODD = 255
#: The recurrence band edge of §2, declared once.
LOW_HZ = 1.0
#: The exact rotor reference.
ROTOR_HZ = 25.0 / 3.0


def _stamps(count: int, *, dt_s: float = DT_S) -> np.ndarray:
    """An exact uniform axis of ``count`` samples."""
    return np.arange(count, dtype=float) * dt_s


def _uniform(count: int, *, dt_s: float = DT_S) -> tuple[np.ndarray, float, float]:
    """``(stamps, fs_eff, delta_f)`` for an exact uniform axis of ``count`` samples."""
    axis = _stamps(count, dt_s=dt_s)
    span = float(axis[-1] - axis[0])
    rate = (count - 1) / span
    return axis, rate, rate / count


def _window(
    traces: np.ndarray | list[np.ndarray],
    time_s: np.ndarray,
    *,
    support_mask: np.ndarray | None = None,
) -> WindowView:
    """The smallest honest labelled view around one or more synthetic gate traces.

    ``traces`` is a single trace (one gate) or one trace per gate column. Built directly rather
    than through the named constructors so a test chooses the stamps and the support, exactly as
    the periodogram tests do.
    """
    stamps = np.asarray(time_s, dtype=float).reshape(-1)
    matrix = np.asarray(traces, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    gates = matrix.shape[1]
    depths = np.arange(gates, dtype=float) * 2.0 + 10.0
    mask = (
        np.ones(gates, dtype=bool)
        if support_mask is None
        else np.asarray(support_mask, bool)
    )
    return WindowView(
        view=SparseView.PRIMARY,
        view_rule=view_rule(SparseView.PRIMARY),
        relative_path="synthetic.BDD",
        source_sha256="0" * 64,
        job="synthetic",
        point_label="synthetic",
        order=1,
        values=matrix,
        time_s=stamps,
        depths_mm=depths,
        support_mask=mask,
        native_gates=gates,
        native_depth_extent_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        pass_support_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        start_index=0,
        stop_index=int(stamps.size),
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
    )


def _tone(
    stamps: np.ndarray, frequency_hz: float, *, amplitude: float = 1.0
) -> np.ndarray:
    """A real cosine at ``frequency_hz`` over ``stamps``."""
    return amplitude * np.cos(2.0 * np.pi * frequency_hz * stamps)


def _estimate(window: WindowView, *, detrending: Detrending = Detrending.MEAN):
    """One gate's periodogram from a synthetic view, at the view's first supported gate."""
    column = int(window.supported_columns[0])
    depth = float(np.asarray(window.depths_mm, dtype=float)[column])
    return periodogram_of_view(window, depth_mm=depth, detrending=detrending)


def _definitely_defined(estimate):
    """An estimate whose axis is admitted, so the tests below measure a defined spectrum."""
    assert estimate.verdict is SpectralVerdict.DEFINED, (
        "the synthetic axis is exactly uniform and must be admitted; a refused one would make "
        f"every fraction below a refusal: {estimate.admission.reason}"
    )
    return estimate


def _fraction_for(trace: np.ndarray, count: int, *, low_hz: float = LOW_HZ, **kwargs):
    """``low_frequency_power_fraction`` of one synthetic trace on an exact uniform axis."""
    b = _require_backend()
    stamps, _rate, _delta = _uniform(count)
    estimate = _definitely_defined(_estimate(_window(trace, stamps, **kwargs)))
    return estimate, b.low_frequency_power_fraction(estimate, low_hz=low_hz)


def _recompute_band_power(estimate, *, low_hz: float) -> tuple[float, float]:
    """The §2 sum written out here, from the estimate's own grid, density and cell rule.

    A second, self-contained loop on purpose: it reads ``estimate.frequency_hz``, ``psd`` and
    ``delta_f_hz`` through the repository's one grid and one cell rule and weights each bin by
    the fraction of its cell inside ``[0, low_hz]``. Nothing in the backend under test serves
    this computation, so agreement is a statement about the number, not about a shared helper.
    """
    grid = one_sided_frequency_grid(
        estimate.profiles, estimate.effective_sample_rate_hz
    )
    delta = float(estimate.delta_f_hz)
    assert float(grid["delta_f_hz"]) == pytest.approx(delta, rel=1e-12)
    assert np.allclose(
        estimate.frequency_hz, grid["frequencies_hz"], rtol=0.0, atol=1e-12
    )
    band = 0.0
    for index in range(int(grid["bins"])):
        low, high = frequency_cell(index, grid=grid)
        width = high - low
        overlap = max(0.0, min(high, float(low_hz)) - low)
        weight = min(max(overlap / width, 0.0), 1.0)
        band += weight * float(estimate.psd[index]) * delta
    return band, float(np.sum(np.asarray(estimate.psd, dtype=float)) * delta)


def _cell_edges(index: int, *, profiles: int, rate: float) -> tuple[float, float]:
    """One bin's cell, ``(low_hz, high_hz)``, written out from the rule rather than called.

    A deliberate second implementation of the one cell rule: the edges are the midpoints to the
    neighbouring bins, the DC cell opens at ``0.0``, and the highest represented cell closes at
    ``min(Nyquist, (k + 0.5) * delta_f)`` - the clip that makes an even grid's top cell end at
    Nyquist and leaves an odd grid's top cell ending at Nyquist anyway, because its top bin sits
    half a bin below it. Nothing here calls ``frequency_cell`` or ``one_sided_frequency_grid``,
    so agreement with the backend is a statement about the arithmetic, not about a shared helper.
    """
    delta = rate / profiles
    bins = profiles // 2 + 1
    low = 0.0 if index == 0 else (index - 0.5) * delta
    high = (index + 0.5) * delta
    if index == bins - 1:
        high = min(0.5 * rate, high)
    return low, high


def _handwritten_band_power(estimate, *, low_hz: float) -> tuple[float, float]:
    """``(B, T)`` of §2, computed from the estimate's own grid as handwritten arithmetic.

    The one-sided grid is the ``N // 2 + 1`` bins ``k * fs_eff / N`` and ``T`` is the sum of the
    density over it; ``B`` weights each bin by the fraction of *its own cell* inside the closed
    band ``[0, low_hz]``. Every edge comes from :func:`_cell_edges`, and the bin count and the
    spacing are derived from the profile count and the effective rate here - not read back from
    the repository's grid builder - so an error shared between that builder and this backend
    cannot hide in both.
    """
    profiles = int(estimate.profiles)
    rate = float(estimate.effective_sample_rate_hz)
    psd = np.asarray(estimate.psd, dtype=float)
    assert psd.size == profiles // 2 + 1, (
        f"a one-sided grid of {profiles} profiles holds {profiles // 2 + 1} bin(s), got {psd.size}"
    )
    delta = rate / profiles
    assert float(estimate.delta_f_hz) == pytest.approx(delta, rel=1e-12)
    band = 0.0
    for index in range(psd.size):
        low, high = _cell_edges(index, profiles=profiles, rate=rate)
        width = high - low
        overlap = max(0.0, min(high, float(low_hz)) - low)
        weight = min(max(overlap / width, 0.0), 1.0)
        band += weight * float(psd[index]) * delta
    return band, float(np.sum(psd)) * delta


# --------------------------------------------------------------------------------------
# the frozen interface
# --------------------------------------------------------------------------------------


def test_the_backend_exposes_the_frozen_public_interface() -> None:
    b = _require_backend()
    for name in REQUIRED_NAMES:
        assert hasattr(b, name), name
    assert issubclass(b.BandFractionError, ValueError), (
        "a malformed band edge is a caller error, and the repository's refusals are ValueError"
    )
    states = {member.value for member in b.BandFractionState}
    assert states == {"defined", "defined-zero-power", "refused-axis"}, (
        "the three state labels of §2 are fixed: a refusal was not measured, a defined zero was"
    )
    # a str Enum, so a report may quote the label and compare it as a string
    assert all(isinstance(member, str) for member in b.BandFractionState)


# --------------------------------------------------------------------------------------
# §2: the boundary f_low = Nyquist, on both parities
# --------------------------------------------------------------------------------------


def test_the_fraction_is_one_at_nyquist_on_both_an_even_and_an_odd_grid() -> None:
    """``f_low = f_N`` is permitted solely as a boundary-arithmetic test: every weight is 1.

    On an even grid the top bin sits at Nyquist; on an odd grid it sits ``delta_f / 2`` below it
    while its cell still reaches Nyquist. Either way the cells tile ``[0, f_N]`` exactly, so the
    band sum *is* the integrated density and the fraction is exactly 1.
    """
    b = _require_backend()
    for count in (N_EVEN, N_ODD):
        stamps, _rate, delta = _uniform(count)
        estimate = _definitely_defined(
            _estimate(_window(_tone(stamps, 3 * delta), stamps))
        )
        fraction = b.low_frequency_power_fraction(estimate, low_hz=estimate.nyquist_hz)
        assert isinstance(fraction, b.LowFrequencyBandFraction)
        assert fraction.state is b.BandFractionState.DEFINED, count
        assert fraction.low_hz == estimate.nyquist_hz
        assert fraction.fraction == pytest.approx(1.0, rel=1e-12), (
            f"the cells tile [0, f_N] exactly, so at f_low = Nyquist every weight is 1 on the "
            f"{'even' if count % 2 == 0 else 'odd'} grid: got {fraction.fraction}"
        )
        assert fraction.band_power == pytest.approx(fraction.total_power, rel=1e-12)


def test_the_fraction_is_non_decreasing_in_the_band_edge() -> None:
    """The weight of a bin only grows as the band widens, so ``Phi`` cannot fall."""
    b = _require_backend()
    for count in (N_EVEN, N_ODD):
        stamps, _rate, delta = _uniform(count)
        trace = _tone(stamps, 3 * delta) + 0.5 * _tone(stamps, 20 * delta)
        estimate = _definitely_defined(_estimate(_window(trace, stamps)))
        edges = [0.5 * delta, 3 * delta, LOW_HZ, 5.0, estimate.nyquist_hz]
        fractions = [
            b.low_frequency_power_fraction(estimate, low_hz=edge).fraction
            for edge in edges
        ]
        assert all(value is not None for value in fractions)
        for earlier, later, lo, hi in zip(fractions, fractions[1:], edges, edges[1:]):
            assert later >= earlier - 1e-12, (count, lo, hi, earlier, later)
        assert fractions[-1] == pytest.approx(1.0, rel=1e-12)


# --------------------------------------------------------------------------------------
# §2: tone locality, with a loose bound because the edge cuts a Hann lobe
# --------------------------------------------------------------------------------------


def test_a_low_frequency_tone_keeps_its_power_in_the_band_and_a_high_one_does_not() -> (
    None
):
    """The one measurement that gives the fraction its meaning, and its honest bound.

    A bin-centred tone is *not* confined to one bin: the periodic Hann puts two thirds of its
    mean square in its own bin and one sixth in each neighbour. At 1 Hz the band edge falls
    inside a neighbour's cell (bin 5's cell, ``[0.879, 1.074] Hz``, is cut at 1.0 Hz), so that
    sixth contributes at the cell-overlap weight rather than in full - the fraction is high but
    *below* one. Asserting ``> 0.99`` would be asserting an artefact of leakage and bin
    placement; the claim is locality, not totality.
    """
    b = _require_backend()
    for count in (N_EVEN, N_ODD):
        stamps, _rate, delta = _uniform(count)
        band_bins = math.floor(LOW_HZ / delta)
        assert band_bins >= 4
        # a low tone whose lobe straddles the 1 Hz edge: locality, not totality
        low = b.low_frequency_power_fraction(
            _definitely_defined(_estimate(_window(_tone(stamps, 4 * delta), stamps))),
            low_hz=LOW_HZ,
        )
        high = b.low_frequency_power_fraction(
            _definitely_defined(_estimate(_window(_tone(stamps, 100 * delta), stamps))),
            low_hz=LOW_HZ,
        )
        assert low.state is b.BandFractionState.DEFINED
        assert high.state is b.BandFractionState.DEFINED
        assert low.fraction > 0.9, (
            f"a tone at {4 * delta:.4f} Hz must sit almost entirely inside the 1 Hz band; got "
            f"{low.fraction} at N={count}"
        )
        assert low.fraction < 1.0, (
            "the band edge cuts the neighbouring Hann lobe's cell, so a tone at 0.78 Hz cannot "
            f"score exactly one; got {low.fraction} at N={count}"
        )
        assert high.fraction == pytest.approx(0.0, abs=1e-12), (
            f"a tone at {100 * delta:.4f} Hz is far above the 1 Hz band and must carry no power "
            f"in it; got {high.fraction} at N={count}"
        )
        assert low.fraction > 100.0 * high.fraction


def test_the_fraction_agrees_with_an_independent_cell_overlap_recomputation() -> None:
    """The number itself, recomputed literally from the published density and the cell rule."""
    b = _require_backend()
    for count in (N_EVEN, N_ODD):
        stamps, _rate, delta = _uniform(count)
        cases = {
            "low": _tone(stamps, 4 * delta),
            "high": _tone(stamps, 100 * delta),
            "mixed": _tone(stamps, 3 * delta) + 0.4 * _tone(stamps, 60 * delta),
        }
        for name, trace in cases.items():
            estimate = _definitely_defined(_estimate(_window(trace, stamps)))
            for edge in (0.5 * delta, LOW_HZ, 3.0, estimate.nyquist_hz):
                fraction = b.low_frequency_power_fraction(estimate, low_hz=edge)
                band, integrated = _recompute_band_power(estimate, low_hz=edge)
                assert fraction.band_power == pytest.approx(
                    band, rel=1e-9, abs=1e-15
                ), (
                    name,
                    count,
                    edge,
                )
                assert fraction.total_power == pytest.approx(integrated, rel=1e-9), (
                    name,
                    count,
                    edge,
                )
                assert fraction.fraction == pytest.approx(
                    band / integrated, rel=1e-9
                ), (
                    name,
                    count,
                    edge,
                )
                assert 0.0 <= fraction.fraction <= 1.0 + 1e-9
                assert fraction.band_power <= fraction.total_power * (1.0 + 1e-9)


def test_the_fraction_agrees_with_a_handwritten_cell_overlap_oracle_on_both_parities() -> (
    None
):
    """The number recomputed from the grid and cell rules as *arithmetic*, not as calls.

    ``_recompute_band_power`` above still calls the repository's own grid builder and cell rule, so
    an error those two share with the backend would be invisible to it. This oracle writes the bin
    positions and the cell edges out from their definition
    (:func:`_cell_edges` / :func:`_handwritten_band_power`) and closes the band at the DC cell and
    the top cell - the two endpoint rules - so an even grid whose top cell is *not* clipped to
    Nyquist and an odd grid whose top cell *is* are both exercised. The DC cell is deliberately
    included by an edge of exactly ``delta_f / 2``, where its whole weight turns on.

    Three traces per parity, over four edges, against the submitted fraction: the comparison is a
    statement about the number, made independently of every helper the backend is allowed to call.
    """
    b = _require_backend()
    for count in (N_EVEN, N_ODD):
        stamps, rate, delta = _uniform(count)
        cases = {
            "low": _tone(stamps, 4 * delta),
            "mixed": _tone(stamps, 3 * delta) + 0.4 * _tone(stamps, 60 * delta),
            "dc": np.full(count, 1.0) + _tone(stamps, 2 * delta),
        }
        for name, trace in cases.items():
            estimate = _definitely_defined(_estimate(_window(trace, stamps)))
            assert int(estimate.profiles) == count
            assert float(estimate.effective_sample_rate_hz) == pytest.approx(
                rate, rel=1e-12
            )
            for edge in (0.5 * delta, LOW_HZ, 2.5 * delta, estimate.nyquist_hz):
                fraction = b.low_frequency_power_fraction(estimate, low_hz=edge)
                band, integrated = _handwritten_band_power(estimate, low_hz=edge)
                assert fraction.band_power == pytest.approx(
                    band, rel=1e-9, abs=1e-15
                ), (name, count, edge)
                assert fraction.total_power == pytest.approx(integrated, rel=1e-9), (
                    name,
                    count,
                    edge,
                )
                assert fraction.fraction == pytest.approx(
                    band / integrated, rel=1e-9
                ), (name, count, edge)
                assert 0.0 <= fraction.fraction <= 1.0 + 1e-9


# --------------------------------------------------------------------------------------
# §2: the three states, never conflated
# --------------------------------------------------------------------------------------


def test_a_constant_trace_is_a_defined_zero_power_and_not_a_refusal_or_a_zero_fraction() -> (
    None
):
    """A constant gate is a *measurement*: it is neither a refusal nor a zero fraction.

    A mean-removed constant is the zero signal, so the density is exactly zero everywhere and
    the integrated power is exactly ``0.0``; ``0 / 0`` is undefined, so the fraction is ``None``
    while the band power is recorded as a *defined zero*. A refusal would be a different
    statement: that no measurement was made.
    """
    b = _require_backend()
    for count in (N_EVEN, N_ODD):
        stamps, _rate, _delta = _uniform(count)
        estimate = _definitely_defined(_estimate(_window(np.full(count, 4.0), stamps)))
        assert estimate.integrated_psd_power == 0.0, (
            "an exactly representable constant is removed exactly, so its integrated density is "
            f"exactly zero, not merely small; got {estimate.integrated_psd_power!r}"
        )
        fraction = b.low_frequency_power_fraction(estimate, low_hz=LOW_HZ)
        assert fraction.state is b.BandFractionState.DEFINED_ZERO_POWER, count
        assert fraction.fraction is None, (
            "0 / 0 is undefined and must not be published as 0.0"
        )
        assert fraction.band_power == 0.0, (
            "a defined zero is recorded as B == 0.0, which is a measurement of zero power"
        )
        assert fraction.total_power == 0.0
        assert fraction.reason and "zero" in fraction.reason.lower(), fraction.reason


def test_a_refused_axis_yields_a_refusal_carrying_no_numeric_fraction() -> None:
    """A duplicated stamp refuses the axis: no ``Phi``, no ``B``, no ``T``, and no zero."""
    b = _require_backend()
    stamps = _stamps(N_EVEN)
    stamps = stamps.copy()
    stamps[10] = stamps[11]
    _s, _rate, delta = _uniform(N_EVEN)
    estimate = _estimate(_window(_tone(stamps, 3 * delta), stamps))
    assert estimate.verdict is SpectralVerdict.REFUSED_AXIS
    fraction = b.low_frequency_power_fraction(estimate, low_hz=LOW_HZ)
    assert fraction.state is b.BandFractionState.REFUSED_AXIS
    assert fraction.fraction is None
    assert fraction.band_power is None, (
        "no band power was computed for a refused axis; a zero would read as a measured zero"
    )
    assert fraction.total_power is None
    assert fraction.low_hz == LOW_HZ, "the request is echoed even on a refusal"
    assert fraction.reason == estimate.admission.reason, (
        "a refusal carries the admission's own reason, not a re-worded one"
    )


# --------------------------------------------------------------------------------------
# §2: request validity is an input check, and an unsupported target is an answer
# --------------------------------------------------------------------------------------


def test_invalid_band_edges_raise_the_typed_error() -> None:
    """Positive, finite and at most Nyquist: everything else is a caller error."""
    b = _require_backend()
    stamps, _rate, delta = _uniform(N_EVEN)
    estimate = _definitely_defined(_estimate(_window(_tone(stamps, 3 * delta), stamps)))
    nyquist = estimate.nyquist_hz
    for bad in (0.0, -1.0, math.nan, math.inf, -math.inf, nyquist * (1.0 + 1e-6)):
        with pytest.raises(b.BandFractionError):
            b.low_frequency_power_fraction(estimate, low_hz=bad)
    # exactly Nyquist is inside the declared domain, not above it
    assert b.low_frequency_power_fraction(estimate, low_hz=nyquist).state is (
        b.BandFractionState.DEFINED
    )


def test_the_denominator_is_the_read_integrated_psd_power_and_not_a_recomputation() -> (
    None
):
    """``T`` is the estimate's own ``integrated_psd_power``, read rather than rebuilt.

    Recomputing ``sum(psd) * delta_f`` would be a second number that could disagree with the
    invariant the estimator checks on construction, so it is not computed: identity equality is
    asserted, and the carried Parseval error is what ties the two powers together.
    """
    b = _require_backend()
    stamps, _rate, delta = _uniform(N_EVEN)
    estimate = _definitely_defined(_estimate(_window(_tone(stamps, 4 * delta), stamps)))
    fraction = b.low_frequency_power_fraction(estimate, low_hz=LOW_HZ)
    assert fraction.total_power == estimate.integrated_psd_power, (
        "the denominator is the estimate's own integrated density, read, not re-summed from psd"
    )
    error = estimate.parseval_relative_error
    assert error is not None
    assert fraction.total_power == pytest.approx(
        estimate.window_normalized_mean_square_power, rel=abs(error) + 1e-12
    ), "the read denominator is the window-normalized mean square the identity relates"


# --------------------------------------------------------------------------------------
# §7: the per-gate sweep, driven by supported_columns
# --------------------------------------------------------------------------------------


def _masked_view() -> WindowView:
    """Four native gates, the last outside the support: a view with an unsupported gate.

    The unsupported column carries a non-finite trace as a tripwire: if the sweep asked it of
    the estimator, the request would fail twice over - once for being outside the support, once
    for the missing value - so a sweep that skipped nothing would be caught either way.
    """
    count = N_EVEN
    stamps = _stamps(count)
    _s, _rate, delta = _uniform(count)
    traces = np.empty((count, 4))
    traces[:, 0] = _tone(stamps, 4 * delta)
    traces[:, 1] = _tone(stamps, 6 * delta)
    traces[:, 2] = _tone(stamps, 2 * delta)
    traces[:, 3] = (
        np.nan
    )  # an unsupported gate: if it were asked of, the estimator would refuse
    return _window(traces, stamps, support_mask=np.array([True, True, True, False]))


def test_the_sweep_is_one_gate_per_supported_column_and_the_count_matches_the_provenance() -> (
    None
):
    b = _require_backend()
    view = _masked_view()
    record = b.characterization_of_view(view, low_hz=LOW_HZ)
    supported = [int(column) for column in view.supported_columns]
    assert [gate.gate_index for gate in record.gates] == supported, (
        "the sweep is driven by supported_columns, in native depth order, and asks no "
        "unsupported column: an unsupported gate would have raised rather than been skipped"
    )
    assert len(record.gates) == view_provenance(view).supported_gates == 3
    depths = np.asarray(view.depths_mm, dtype=float)
    for gate in record.gates:
        assert gate.depth_mm == pytest.approx(float(depths[gate.gate_index])), (
            "depth_mm is the view's native coordinate of that column, not a relabelled index"
        )
        assert gate.verdict is SpectralVerdict.DEFINED


def test_the_sweep_preserves_noncontiguous_native_gate_indices() -> None:
    b = _require_backend()
    count = N_EVEN
    stamps = _stamps(count)
    _s, _rate, delta = _uniform(count)
    traces = np.column_stack(
        [_tone(stamps, 2 * delta), _tone(stamps, 4 * delta), _tone(stamps, 6 * delta)]
    )
    view = _window(traces, stamps, support_mask=np.array([False, True, True]))
    record = b.characterization_of_view(view, low_hz=LOW_HZ)
    assert [gate.gate_index for gate in record.gates] == [1, 2]
    assert len(record.gates) == record.provenance.supported_gates == 2


def test_every_gate_carries_its_own_verdict_and_band_fraction() -> None:
    b = _require_backend()
    view = _masked_view()
    record = b.characterization_of_view(view, low_hz=LOW_HZ)
    for gate in record.gates:
        assert isinstance(gate.band_fraction, b.LowFrequencyBandFraction)
        assert gate.band_fraction.state is b.BandFractionState.DEFINED
        assert gate.band_fraction.low_hz == LOW_HZ
        assert gate.band_fraction.fraction is not None
        assert 0.0 <= gate.band_fraction.fraction <= 1.0 + 1e-9
        assert gate.band_fraction.band_power <= gate.band_fraction.total_power * (
            1.0 + 1e-9
        )
        # each gate's fraction is its own gate's estimate, not the first gate's repeated
        column = int(gate.gate_index)
        depth = float(np.asarray(view.depths_mm, dtype=float)[column])
        estimate = periodogram_of_view(view, depth_mm=depth)
        own = b.low_frequency_power_fraction(estimate, low_hz=LOW_HZ)
        assert gate.band_fraction.fraction == pytest.approx(own.fraction, rel=1e-12)
        assert gate.band_fraction.total_power == own.total_power


def test_characterization_of_view_carries_provenance_settings_targets_and_admission() -> (
    None
):
    b = _require_backend()
    view = _masked_view()
    record = b.characterization_of_view(
        view,
        low_hz=LOW_HZ,
        detrending=Detrending.MEAN,
        quantity="axial_velocity",
        unit="mm/s",
        pass_name="synthetic-pass",
    )
    assert record.provenance == view_provenance(view), (
        "the cell carries SA1's own provenance record, not a second description of the view"
    )
    assert record.pass_name == "synthetic-pass"
    assert record.quantity == "axial_velocity"
    assert record.unit == "mm/s"
    assert record.detrending is Detrending.MEAN
    assert record.low_hz == LOW_HZ
    assert record.admission.admitted is True
    frequencies = [target.target_hz for target in record.targets]
    assert len(record.targets) == 2, "the design's two probe targets, per cell"
    assert any(abs(frequency - LOW_HZ) < 1e-12 for frequency in frequencies)
    assert any(abs(frequency - ROTOR_HZ) < 1e-12 for frequency in frequencies)
    assert all(target.admission is record.admission for target in record.targets), (
        "target rows are asked of this cell's own admission, not a rebuilt one"
    )


def test_a_refused_cell_keeps_identity_rows_with_no_numeric_fraction() -> None:
    b = _require_backend()
    count = N_EVEN
    stamps = _stamps(count)
    stamps = stamps.copy()
    stamps[10] = stamps[11]
    _s, _rate, delta = _uniform(count)
    traces = np.column_stack([_tone(stamps, 4 * delta), _tone(stamps, 2 * delta)])
    view = _window(traces, stamps, support_mask=np.array([True, True]))
    record = b.characterization_of_view(view, low_hz=LOW_HZ)
    assert record.admission.admitted is False
    assert len(record.gates) == int(np.count_nonzero(view.support_mask)) == 2
    for gate in record.gates:
        assert gate.verdict is SpectralVerdict.REFUSED_AXIS
        assert gate.band_fraction.state is b.BandFractionState.REFUSED_AXIS
        assert gate.band_fraction.fraction is None
        assert gate.band_fraction.band_power is None
        assert gate.band_fraction.total_power is None


# --------------------------------------------------------------------------------------
# committed data: the E128 cell's two refusals, one row at a time
# --------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def e128_primary() -> WindowView:
    """The emissions-128 primary-comparison view from a committed reproducibility sitting."""
    for ref in COMMITTED_PASSES:
        if not ref.is_reproducibility_sitting:
            continue
        decoding = decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
        for point in decoding.points:
            view = primary_view(
                point, window_s=decoding.window_s, support_mm=decoding.support_mm
            )
            if view_provenance(view).job == "emissions-128":
                return view
    raise AssertionError(
        "no committed reproducibility sitting holds an emissions-128 recording"
    )


def test_the_emissions_128_cell_refuses_the_rotor_row_and_supports_the_low_band(
    e128_primary: WindowView,
) -> None:
    """The plan's hard fact at the gate-resolvable level: refused band, admitted estimator."""
    b = _require_backend()
    record = b.characterization_of_view(e128_primary, low_hz=LOW_HZ)
    assert record.admission.admitted is True, (
        "the E128 axis is admitted for the estimator; only the 8.333 Hz band is impossible"
    )
    rotor = next(
        target for target in record.targets if abs(target.target_hz - ROTOR_HZ) < 1e-9
    )
    assert rotor.band_supported is False, (
        "asking about 8.333 Hz returns an unsupported answer, never an error"
    )
    assert rotor.analysis_supported is True
    assert "Nyquist" in rotor.reason
    low = next(
        target for target in record.targets if abs(target.target_hz - LOW_HZ) < 1e-9
    )
    assert low.supported is True and low.band_supported is True
    assert len(record.gates) == view_provenance(e128_primary).supported_gates
    for gate in record.gates:
        assert gate.verdict is SpectralVerdict.DEFINED
        assert gate.band_fraction.state is b.BandFractionState.DEFINED
        assert gate.band_fraction.fraction is not None
        assert 0.0 <= gate.band_fraction.fraction <= 1.0 + 1e-9
        assert gate.band_fraction.band_power <= gate.band_fraction.total_power * (
            1.0 + 1e-9
        )


# --------------------------------------------------------------------------------------
# §8.7: the AST guard - S1 adds no estimator of its own
# --------------------------------------------------------------------------------------

#: Transform, taper, grid and normalization names S1 must not *define*: those belong to the
#: modules that already own them. Calls to the shared grid and cell rule are allowed.
FORBIDDEN_DEFINITIONS = frozenset(
    {
        "fft",
        "rfft",
        "irfft",
        "fft2",
        "rfft2",
        "fftn",
        "fftfreq",
        "rfftfreq",
        "fftshift",
        "hann",
        "hanning",
        "hamming",
        "blackman",
        "bartlett",
        "kaiser",
        "get_window",
        "hann_window",
        "welch",
        "periodogram",
        "spectrogram",
        "stft",
        "csd",
        "coherence",
        "cohere",
        "periodic_hann",
        "taper",
        "taper_enbw_bins",
        "enbw",
        "enbw_bins",
        "one_sided_frequency_grid",
        "one_sided_frequencies",
        "windowed_power",
        "normalization_rule",
        "one_sided_rule",
        "spectral_admission",
        "characterize_stamps",
        "characterize_timebase",
    }
)

#: Names S1 must not reference *anywhere*: the transform and taper primitives themselves.
FORBIDDEN_REFERENCES = frozenset(
    {"fft", "rfft", "irfft", "fftfreq", "rfftfreq", "periodic_hann", "taper_enbw_bins"}
)

#: The two backend functions S1 must reach only through ``periodogram_of_view`` and the
#: estimate's own ``admission``, never by calling them itself.
FORBIDDEN_CALLS = frozenset({"characterize_stamps", "spectral_admission"})


def _backend_tree() -> ast.Module:
    assert BACKEND_MODULE.exists(), (
        f"the S1 module {BACKEND_MODULE} has not been written yet; this AST guard is red-first"
    )
    return ast.parse(
        BACKEND_MODULE.read_text(encoding="utf-8"), filename=str(BACKEND_MODULE)
    )


def _defined_names(tree: ast.Module) -> set[str]:
    """Names S1 *implements*: every function or class, and every **module-level** binding.

    Scope matters here. The backend legitimately *carries* the estimator's own convention strings:
    ``normalization_rule = estimate.normalization_rule`` inside a function binds a local whose
    value was read off the estimate, which is the opposite of defining a normalization rule - the
    module computes nothing and restates nothing. So the assignment half of the guard is restricted
    to module scope, where a constant named after one of the estimator's rules would be a genuine
    redefinition of it. Function and class definitions are collected wherever they occur, because a
    helper that computed a taper, a grid or a fold would be an offence at any nesting.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _called_names(tree: ast.Module) -> set[str]:
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    return called


def test_the_ast_guard_flags_an_implementation_but_not_a_carried_local() -> None:
    """A guard that could never fire is not a guard: both directions of the scope rule are pinned.

    ``_defined_names`` splits "implements" from "carries". This shows the population it is applied
    to is not empty - a module-level ``normalization_rule`` constant, or a ``taper`` helper, is
    still an offence - while the verbatim carry the backend performs (``taper_convention =
    estimate.taper_convention`` inside a function) is not, because a local holding a value the
    estimate already owns implements nothing.
    """
    offender = (
        "import numpy as np\n"
        "normalization_rule = 'restated by S1, which it must not do'\n"
        "def taper(count):\n"
        "    return np.hanning(count)\n"
    )
    assert _defined_names(ast.parse(offender)) & FORBIDDEN_DEFINITIONS == {
        "normalization_rule",
        "taper",
    }
    carrier = (
        "def carry(estimate):\n"
        "    taper_convention = estimate.taper_convention\n"
        "    normalization_rule = estimate.normalization_rule\n"
        "    return taper_convention, normalization_rule\n"
    )
    assert not _defined_names(ast.parse(carrier)) & FORBIDDEN_DEFINITIONS, (
        "a function-local holding the estimate's own convention string is a carry, not an "
        "implementation"
    )


def test_the_backend_defines_no_transform_taper_grid_or_normalization_of_its_own() -> (
    None
):
    tree = _backend_tree()
    offenders = sorted(_defined_names(tree) & FORBIDDEN_DEFINITIONS)
    assert not offenders, (
        "S1 adds no estimator: it may call the shared grid and cell rule, but it must not "
        f"define a transform, taper, grid or normalization of its own. Found: {offenders}"
    )
    referenced: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            referenced.add(node.id)
        elif isinstance(node, ast.Attribute):
            referenced.add(node.attr)
    hits = sorted(referenced & FORBIDDEN_REFERENCES)
    assert not hits, (
        "S1 must not touch the transform or taper primitives at all, not even by name: "
        f"Found: {hits}"
    )


def test_the_backend_does_not_call_the_admission_or_the_characterization_directly() -> (
    None
):
    tree = _backend_tree()
    called = _called_names(tree)
    offenders = sorted(called & FORBIDDEN_CALLS)
    assert not offenders, (
        "S1 reads the admission and the characterization off the estimate the estimator "
        "returned; calling those backends itself would be a second admission path. "
        f"Found calls: {offenders}"
    )
    assert "periodogram_of_view" in called, (
        "S1 is the per-gate sweep, so it must call the estimator"
    )


# --------------------------------------------------------------------------------------
# adversarial regressions: refused or degenerate axes, and the model's own consistency
# --------------------------------------------------------------------------------------
#
# These rows are written against the contracts the verifier found broken, not against the
# behaviour that happens to be shipped: each one drives the public function or a ``model_validate``
# of a tampered payload and shows whether the contract holds. A model validator's ``ValueError``
# arrives as pydantic's ``ValidationError``, so a tampered payload is asserted through that type -
# and the claim is the *reason* read back from the error, not merely that something was raised.


def _validation_message(model, payload: dict) -> str:
    """``model_validate`` a tampered payload, require a refusal, and return its reasons."""
    with pytest.raises(ValidationError) as excinfo:
        model.model_validate(payload)
    return " | ".join(str(error.get("msg", "")) for error in excinfo.value.errors())


def _refused_for(message: str, *tokens: str) -> None:
    """The refusal names what it is about, in at least one of ``tokens``."""
    assert any(token in message for token in tokens), (
        f"a refusal must name the quantity it is about; none of {tokens} appears in {message!r}"
    )


def _one_profile_view() -> WindowView:
    """A view holding exactly one profile: no interval, no rate, no Nyquist and no bin spacing."""
    return _window(np.array([2.0]), np.array([0.5]))


def _zero_span_view() -> WindowView:
    """A view whose 64 stored stamps all coincide: a zero span, so no rate is defined either."""
    return _window(np.full(64, 3.0), np.full(64, 0.5))


def _two_gate_view() -> WindowView:
    """A small, admitted, two-gate synthetic view - the control cell for the consistency rows."""
    stamps, _rate, delta = _uniform(N_EVEN)
    return _window(
        np.column_stack([_tone(stamps, 2 * delta), _tone(stamps, 4 * delta)]), stamps
    )


def _refused_axis_with_a_known_nyquist():
    """A duplicated stamp refuses the axis while its positive span still defines a Nyquist."""
    stamps, _rate, delta = _uniform(N_EVEN)
    stamps = stamps.copy()
    stamps[10] = stamps[11]
    estimate = _estimate(_window(_tone(stamps, 3 * delta), stamps))
    assert estimate.verdict is SpectralVerdict.REFUSED_AXIS
    assert estimate.nyquist_hz is not None
    return estimate


def test_a_refused_axis_with_a_known_nyquist_still_refuses_an_edge_above_it() -> None:
    """A refusal is a verdict about measuring, not a licence to skip the request's own domain.

    The axis is refused, but its span still publishes a Nyquist frequency, so an edge above it is
    outside the declared domain exactly as it is on a defined spectrum: the input check is a
    property of the request, not of the estimate's verdict, and it runs before the refusal is
    returned. At Nyquist the request is inside the domain and the refusal is the answer.
    """
    b = _require_backend()
    estimate = _refused_axis_with_a_known_nyquist()
    nyquist = estimate.nyquist_hz
    assert nyquist is not None
    allowed = b.low_frequency_power_fraction(estimate, low_hz=LOW_HZ)
    assert allowed.state is b.BandFractionState.REFUSED_AXIS
    assert allowed.low_hz == LOW_HZ, "the request is echoed even on a refusal"
    assert b.low_frequency_power_fraction(estimate, low_hz=nyquist).state is (
        b.BandFractionState.REFUSED_AXIS
    ), "exactly Nyquist is inside the declared domain, refusal or not"
    for bad in (
        math.nextafter(nyquist, math.inf),
        nyquist * (1.0 + 1e-6),
        nyquist * 2.0,
    ):
        with pytest.raises(b.BandFractionError):
            b.low_frequency_power_fraction(estimate, low_hz=bad)


def test_the_band_edge_is_a_strict_bound_at_the_known_nyquist() -> None:
    """One representable float above Nyquist is above it: no relative slack on the domain edge.

    The tolerance the §2 invariants are checked to is a slack on an *arithmetic identity* of a
    computed fraction; it is not a licence to accept a band edge the declared domain excludes. The
    smallest step above Nyquist is a real counterexample, so it must be refused rather than
    skate past a ``(1 + 1e-9)`` multiplier.
    """
    b = _require_backend()
    stamps, _rate, delta = _uniform(N_EVEN)
    estimate = _definitely_defined(_estimate(_window(_tone(stamps, 3 * delta), stamps)))
    nyquist = estimate.nyquist_hz
    assert nyquist is not None
    assert b.low_frequency_power_fraction(estimate, low_hz=nyquist).state is (
        b.BandFractionState.DEFINED
    ), "exactly Nyquist is permitted, and yields a fraction of one"
    for above in (math.nextafter(nyquist, math.inf), nyquist * (1.0 + 1e-12)):
        assert above > nyquist
        with pytest.raises(b.BandFractionError):
            b.low_frequency_power_fraction(estimate, low_hz=above)


def test_an_axis_that_publishes_no_nyquist_refuses_without_a_bound_to_assert() -> None:
    """With no rate there is no Nyquist, so there is no edge a request can exceed.

    The refusal is the answer for every positive finite edge; the strict bound above applies only
    where a bound exists. A non-positive or non-finite edge is still the caller error it always is.
    """
    b = _require_backend()
    estimate = _estimate(_one_profile_view())
    assert estimate.verdict is SpectralVerdict.REFUSED_AXIS
    assert estimate.nyquist_hz is None
    for edge in (LOW_HZ, 1e9):
        fraction = b.low_frequency_power_fraction(estimate, low_hz=edge)
        assert fraction.state is b.BandFractionState.REFUSED_AXIS
        assert fraction.low_hz == edge
        assert fraction.fraction is None
        assert fraction.band_power is None
        assert fraction.total_power is None
    with pytest.raises(b.BandFractionError):
        b.low_frequency_power_fraction(estimate, low_hz=0.0)


@pytest.mark.parametrize("build", [_one_profile_view, _zero_span_view])
def test_a_refused_cell_on_an_undefined_axis_keeps_gate_identity_rows(build) -> None:
    """A degenerate axis is a refusal, not a construction failure: the cell still exists.

    With one profile, or a zero span, the axis honestly publishes no rate and no bin spacing - and
    a cell must still carry one identity row per supported gate with the refusal typed on it,
    exactly as a duplicate-stamp axis does. Requiring a *positive* ``delta_f_hz`` of an axis that
    has none makes the cell unbuildable and loses the rows the report needs: what a refused axis
    cannot define is absent, never fabricated.
    """
    b = _require_backend()
    view = build()
    estimate = _estimate(view)
    assert estimate.verdict is SpectralVerdict.REFUSED_AXIS
    assert estimate.delta_f_hz is None, (
        "the degenerate axis has no bin spacing to record"
    )
    record = b.characterization_of_view(view, low_hz=LOW_HZ)
    assert record.admission.admitted is False
    assert record.admission.characterization.frequency_resolution_hz is None
    assert record.low_hz == LOW_HZ
    supported = [int(column) for column in view.supported_columns]
    assert [gate.gate_index for gate in record.gates] == supported
    assert len(record.gates) == view_provenance(view).supported_gates >= 1
    for gate in record.gates:
        assert gate.verdict is SpectralVerdict.REFUSED_AXIS
        assert gate.band_fraction.state is b.BandFractionState.REFUSED_AXIS
        assert gate.band_fraction.fraction is None
        assert gate.band_fraction.band_power is None
        assert gate.band_fraction.total_power is None
        assert gate.band_fraction.reason == record.admission.reason


def test_the_probe_set_is_fixed_and_cannot_disagree_with_the_cell_validator() -> None:
    """The cell and its validator state one probe set, so neither can override the other.

    The validator requires a row per design probe (``PROBE_TARGETS``). A ``targets`` parameter on
    the sweep would let a caller build a cell the validator rejects - a knob whose value the model
    then refuses - so the probe set is the design's fixed set and not a parameter at all. Both
    halves are asserted: the signature offers no override, and a cell missing a design probe row is
    refused rather than quietly accepted.
    """
    b = _require_backend()
    parameters = inspect.signature(b.characterization_of_view).parameters
    assert "targets" not in parameters, (
        "a targets override would let a caller build a cell whose rows the validator pins, which "
        f"is the conflict the fix removes; got {sorted(parameters)}"
    )
    record = b.characterization_of_view(_two_gate_view(), low_hz=LOW_HZ)
    assert [target.target_label for target in record.targets] == [
        label for label, _frequency in PROBE_TARGETS
    ]
    assert sorted(target.target_hz for target in record.targets) == sorted(
        frequency for _label, frequency in PROBE_TARGETS
    )
    # A missing design-probe row is refused. The live admission object is re-injected so the row
    # is refused for the missing *label*, which is the check under test, and not because a
    # re-validated payload cannot share an object identity the validator would demand.
    payload = record.model_dump()
    payload["admission"] = record.admission
    for target in payload["targets"]:
        target["admission"] = record.admission
    dropped, _frequency = PROBE_TARGETS[0]
    payload["targets"] = [
        target for target in payload["targets"] if target["target_label"] != dropped
    ]
    message = _validation_message(b.CellSpectralCharacterization, payload)
    assert dropped in message


def test_a_cell_round_trips_through_its_own_serialization() -> None:
    """A cell is a value object: it must survive ``model_dump`` -> ``model_validate`` unchanged.

    Every ``ValueModel`` promises a ``model_dump(mode="json")`` round trip, and a cell is what a
    report quotes, so a cell that cannot be rebuilt from its own serialization is not a value. This
    is the control the tampered-payload rows need: if the honest payload were refused too, a
    "foreign admission" refusal would prove nothing about consistency.
    """
    b = _require_backend()
    record = b.characterization_of_view(_two_gate_view(), low_hz=LOW_HZ)
    rebuilt = b.CellSpectralCharacterization.model_validate(
        record.model_dump(mode="json")
    )
    assert rebuilt == record
    assert rebuilt.admission == record.admission
    assert [target.target_label for target in rebuilt.targets] == [
        target.target_label for target in record.targets
    ]
    assert [gate.gate_index for gate in rebuilt.gates] == [
        gate.gate_index for gate in record.gates
    ]


def test_a_defined_band_fraction_refuses_a_non_finite_power() -> None:
    """NaN is not a power: ``NaN < 0`` and ``NaN > total`` are both false, so it slips the guards.

    Every comparison the state validator makes against a power has to *pass* a NaN to let it
    through, which is precisely why a non-finite power must be refused by name rather than by the
    ordering it defeats. The honest row is the control.
    """
    b = _require_backend()
    model = b.LowFrequencyBandFraction
    good = {
        "low_hz": LOW_HZ,
        "state": "defined",
        "fraction": 0.5,
        "band_power": 1.0,
        "total_power": 2.0,
    }
    assert model.model_validate(good).fraction == 0.5
    _refused_for(
        _validation_message(model, {**good, "band_power": math.nan}),
        "band_power",
        "band power",
        "band ",
    )
    _refused_for(
        _validation_message(model, {**good, "total_power": math.nan}),
        "total_power",
        "total power",
        "total ",
    )
    _refused_for(
        _validation_message(model, {**good, "band_power": math.inf}),
        "band_power",
        "band power",
        "band ",
    )
    _refused_for(
        _validation_message(model, {**good, "total_power": math.inf}),
        "total_power",
        "total power",
        "total ",
    )
    _refused_for(
        _validation_message(model, {**good, "fraction": math.nan}),
        "fraction",
    )


def test_a_cell_refuses_a_gate_row_whose_band_edge_disagrees_with_the_cell() -> None:
    """One cell, one band edge: every gate row's fraction is the cell's own ``low_hz``."""
    b = _require_backend()
    record = b.characterization_of_view(_two_gate_view(), low_hz=LOW_HZ)
    payload = record.model_dump()
    payload["gates"][0]["band_fraction"]["low_hz"] = LOW_HZ + 0.5
    _refused_for(
        _validation_message(b.CellSpectralCharacterization, payload),
        "low_hz",
        "band edge",
    )


def test_a_cell_refuses_a_target_row_asked_of_a_foreign_admission() -> None:
    """Every target row is asked of this cell's own admission, not a rebuilt or borrowed one."""
    b = _require_backend()
    record = b.characterization_of_view(_two_gate_view(), low_hz=LOW_HZ)
    foreign = _estimate(_window(_tone(_stamps(N_ODD), 0.6), _stamps(N_ODD))).admission
    assert foreign is not record.admission
    payload = record.model_dump()
    payload["targets"][0]["admission"] = foreign.model_dump()
    _refused_for(
        _validation_message(b.CellSpectralCharacterization, payload), "admission"
    )


def test_a_cell_refuses_a_refused_gate_row_on_an_admitted_cell() -> None:
    """One axis, one admission: a row cannot be refused while the cell that owns it is admitted."""
    b = _require_backend()
    record = b.characterization_of_view(_two_gate_view(), low_hz=LOW_HZ)
    assert record.admission.admitted is True
    payload = record.model_dump()
    row = payload["gates"][0]
    row["verdict"] = "refused-irregular-axis"
    row["parseval_relative_error"] = None
    row["band_fraction"] = {
        "low_hz": LOW_HZ,
        "state": "refused-axis",
        "fraction": None,
        "band_power": None,
        "total_power": None,
        "reason": "synthetic refusal",
    }
    _refused_for(
        _validation_message(b.CellSpectralCharacterization, payload),
        "admission",
        "verdict",
    )


def test_a_defined_fraction_is_held_to_its_own_band_over_total_ratio() -> None:
    """A ``defined`` row's fraction *is* ``band_power / total_power`` - it is not a free float.

    The row carries three numbers: two powers and their ratio. Each of the invariants already
    tested reads only one or two of them - ``band <= total``, ``0 <= fraction <= 1`` - so a row can
    satisfy every one of those and still be self-contradictory: ``fraction = 0.9`` beside a band of
    ``1.0`` and a total of ``2.0`` is inside the unit interval and is not more power than the
    total, yet it is not the ratio of the two numbers printed next to it. A report quoting it would
    publish two quantities that cannot both be right. The validator holds the third field to the
    first two, so the inconsistent rows are refusals and the honest ratio is the control.

    Both directions are tampered with, and the inconsistency is shown to be refused when it arrives
    nested in a cell as well as on the bare row.
    """
    b = _require_backend()
    model = b.LowFrequencyBandFraction
    good = {
        "low_hz": LOW_HZ,
        "state": "defined",
        "fraction": 0.5,
        "band_power": 1.0,
        "total_power": 2.0,
    }
    assert model.model_validate(good).fraction == 0.5, "the honest row is the control"
    # above and below the ratio its own powers produce: both are the same inconsistency
    for wrong in (0.9, 0.75, 0.1, 0.25):
        _refused_for(
            _validation_message(model, {**good, "fraction": wrong}),
            "fraction",
            "ratio",
            "band",
        )
    # a band power above the total is not a part of it, whatever fraction is quoted beside it
    _refused_for(
        _validation_message(model, {**good, "band_power": 3.0, "fraction": 1.0}),
        "band_power",
        "band power",
        "band ",
        "exceeds",
    )
    # the boundary ratio of exactly one, from equal powers, is honest
    assert (
        model.model_validate({**good, "band_power": 2.0, "fraction": 1.0}).fraction
        == 1.0
    )
    # the same inconsistent ratio is refused when it arrives nested inside a cell
    record = b.characterization_of_view(_two_gate_view(), low_hz=LOW_HZ)
    payload = record.model_dump()
    row = payload["gates"][0]["band_fraction"]
    assert row["state"] == "defined" and row["total_power"] > 0.0
    row["fraction"] = row["band_power"] / row["total_power"] + 0.5
    _refused_for(
        _validation_message(b.CellSpectralCharacterization, payload),
        "fraction",
        "ratio",
        "band",
    )


def test_a_defined_fraction_refuses_a_negative_ratio_or_a_negative_power() -> None:
    """Power is an integral of a density and the fraction is a ratio of two of them: no negative.

    ``0.0`` is a measurement - the ``defined-zero-power`` state carries it - and a ``NaN`` power is
    refused by name in a sibling row above; what was untested is the sign. A negative band power, a
    negative total or a negative fraction is not a measurement at all, and unlike a ``NaN`` it does
    not defeat the ordering guards by comparing false: it passes ``< 0`` and would be published
    unless the sign is refused. The two ``*_power`` rows are made self-consistent with their own
    powers so the sign is the *only* thing wrong with them, and the honest row is the control.
    """
    b = _require_backend()
    model = b.LowFrequencyBandFraction
    good = {
        "low_hz": LOW_HZ,
        "state": "defined",
        "fraction": 0.5,
        "band_power": 1.0,
        "total_power": 2.0,
    }
    assert model.model_validate(good).fraction == 0.5, "the honest row is the control"
    # a negative band power whose fraction is exactly that band's ratio of the total
    _refused_for(
        _validation_message(model, {**good, "band_power": -1.0, "fraction": -0.5}),
        "band_power",
        "band power",
        "band ",
        "negative",
    )
    # a negative total, likewise the only thing wrong with the row
    _refused_for(
        _validation_message(model, {**good, "total_power": -2.0, "fraction": -0.5}),
        "total_power",
        "total power",
        "total ",
        "negative",
    )
    # a negative fraction beside nonnegative powers: still a refusal, never a printed number
    _refused_for(
        _validation_message(model, {**good, "fraction": -0.1}),
        "fraction",
        "negative",
        "ratio",
    )


#: The estimator-owned definitions a cell must repeat: the taper's convention, the density
#: normalization and the one-sided folding rule. They are the estimator's own fields, so a cell
#: *reads* them from the estimate it reduces rather than restating them - and a report quotes them
#: beside the number they describe, which is only possible if they are carried.
ESTIMATOR_OWNED_DEFINITIONS = (
    "taper_convention",
    "normalization_rule",
    "one_sided_rule",
)


def test_the_cell_carries_the_estimators_own_definitions_and_they_survive_serialization() -> (
    None
):
    """The conventions the fraction was computed under are the estimator's, read, and durable.

    A band fraction is only interpretable beside the taper's convention, the density normalization
    and the one-sided folding that produced the density it reduces - and those are the estimator's
    own fields, not a comparison this module may restate. The cell therefore carries each one
    *verbatim* from the estimate: this asserts the field exists, is non-empty, and equals the
    estimate's own value (so a cell that re-worded it would fail), and then that all three survive
    the ``model_dump(mode="json")`` -> ``model_validate`` round trip a report relies on.
    """
    b = _require_backend()
    view = _two_gate_view()
    record = b.characterization_of_view(view, low_hz=LOW_HZ)
    column = int(view.supported_columns[0])
    depth = float(np.asarray(view.depths_mm, dtype=float)[column])
    estimate = periodogram_of_view(view, depth_mm=depth)
    fields = b.CellSpectralCharacterization.model_fields
    for name in ESTIMATOR_OWNED_DEFINITIONS:
        assert name in fields, (
            f"a cell quotes the estimator's own {name} beside the numbers it describes; the "
            "field is absent, so a report cannot state the convention its fraction was computed "
            f"under. Fields present: {sorted(fields)}"
        )
        value = getattr(record, name)
        assert isinstance(value, str) and value, (name, value)
        assert value == getattr(estimate, name), (
            f"the cell's {name} is the estimate's own, read rather than restated"
        )
    rebuilt = b.CellSpectralCharacterization.model_validate(
        record.model_dump(mode="json")
    )
    for name in ESTIMATOR_OWNED_DEFINITIONS:
        assert getattr(rebuilt, name) == getattr(record, name), (
            f"the cell's {name} did not survive serialization"
        )
    assert rebuilt == record
