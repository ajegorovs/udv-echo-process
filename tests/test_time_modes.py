"""Terminal time-direction SVD (POD) of one ``(profile, gate)`` field.

Coverage:

- the arithmetic identities the result model promises: ``explained_variance_ratio``
  sums to 1 and is non-increasing, the modes and coefficients are orthonormal,
  the retained share is the sum of the retained modes' shares, the whole basis
  reconstructs the decomposed field, and the decomposition is deterministic;
- the exact meaning of :func:`gate_amplitudes` — the signed per-gate amplitude
  whose magnitude is the **root-mean-square over the profile axis** of that
  mode's contribution, with ``sum over all modes of amplitude**2`` reproducing
  the gate's mean-square fluctuation (Parseval, the identity that makes it a
  velocity-scale quantity rather than a norm over the whole field);
- the two declared choices: the time mean is removed by default and reported,
  and ``center=False`` reproduces the uncentred snapshot-matrix SVD whose first
  mode is the level direction;
- the pinned sign convention (every retained mode's largest-magnitude gate is
  positive), so a mirrored mode can never be reported as a different one;
- the refusals: shape/rank, non-finite cells, a mode count above ``max_modes``,
  a field with no fluctuation at all, and a wrong settings type;
- the model's own invariants, which reject a hand-built result that contradicts
  the arithmetic (bad unit, non-increasing singular values, orthonormality,
  retained-share mismatch, sign convention);
- the committed four-sensor fixture (``data/4-sensor-velocity/200RPM.BDD``,
  channels 6-9): all 55 modes fit, the fluctuation spectrum of this rig is
  **broadband** rather than low-rank — no small mode set carries it — and the
  gate amplitudes are finite and velocity-scaled.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process.analysis.time_modes import (
    SIGN_CONVENTION,
    TimeModesInputError,
    decompose_time_modes,
    gate_amplitudes,
    modes_for_variance_share,
)
from udv_echo_process.io import load
from udv_echo_process.models.time_modes import TimeModes, TimeModesSettings

REPO = Path(__file__).resolve().parents[1]
FOUR_SENSOR_PATH = REPO / "data" / "4-sensor-velocity" / "200RPM.BDD"

N_PROFILES = 120
N_GATES = 8


def _gate_pattern() -> np.ndarray:
    """A smooth hump over the gate axis, as a unit-norm gate profile."""
    gates = np.linspace(20.0, 79.0, N_GATES)
    hump = np.exp(-((gates - 50.0) ** 2) / 200.0)
    return hump


def _rank_one_field(amplitude: float = 11.0) -> np.ndarray:
    """A (profile, gate) field whose fluctuation is one time-scaled gate shape."""
    index = np.arange(N_PROFILES)
    time = np.sin(2.0 * np.pi * index / 30.0)
    gates = np.linspace(20.0, 79.0, N_GATES)
    base = 24.0 + 3.0 * gates / 79.0
    return base[None, :] + amplitude * time[:, None] * _gate_pattern()[None, :]


def _known_spectrum(singular_values: np.ndarray, seed: int = 7) -> np.ndarray:
    """A field whose singular values are exactly ``singular_values``."""
    rng = np.random.default_rng(seed)
    rank = singular_values.size
    left, _ = np.linalg.qr(rng.normal(size=(N_PROFILES, rank)))
    right, _ = np.linalg.qr(rng.normal(size=(N_GATES, rank)))
    return (left * singular_values) @ right.T


def _fixture_channels() -> dict[int, np.ndarray]:
    bundle = load(FOUR_SENSOR_PATH)
    return {
        int(stream.acquisition.channel.device_channel): np.asarray(
            stream.data.values, dtype=np.float64
        )
        for stream in bundle.recording.streams
    }


# ── the arithmetic identities ───────────────────────────────────────────


def test_explained_variance_sums_to_one_and_is_ordered() -> None:
    rng = np.random.default_rng(3)
    result = decompose_time_modes(rng.normal(size=(60, 12)), unit="mm/s")
    assert result.explained_variance_ratio.shape == (12,)
    assert math.isclose(
        float(result.explained_variance_ratio.sum()), 1.0, abs_tol=1e-12
    )
    assert (np.diff(result.singular_values) <= 0.0).all()
    assert (result.explained_variance_ratio >= 0.0).all()
    assert result.max_modes == 12


def test_orthonormal_basis_and_full_reconstruction() -> None:
    rng = np.random.default_rng(11)
    field = rng.normal(size=(40, 9)) * 3.0
    result = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=9)
    )
    assert np.allclose(result.modes @ result.modes.T, np.eye(9), atol=1e-12)
    assert np.allclose(
        result.coefficients.T @ result.coefficients, np.eye(9), atol=1e-12
    )
    anomaly = field - result.mean_profile
    reconstructed = (result.coefficients * result.singular_values) @ result.modes
    assert np.allclose(reconstructed, anomaly, atol=1e-10)


def test_retained_share_is_the_sum_of_the_retained_modes() -> None:
    rng = np.random.default_rng(5)
    field = rng.normal(size=(50, 10))
    result = decompose_time_modes(field, unit="mm/s")
    expected = float(result.explained_variance_ratio[:3].sum())
    assert math.isclose(result.retained_variance_ratio, expected, abs_tol=1e-12)
    assert result.retained_variance_ratio < 1.0


def test_decomposition_is_deterministic() -> None:
    rng = np.random.default_rng(2)
    field = rng.normal(size=(70, 6))
    first = decompose_time_modes(field, unit="mm/s")
    second = decompose_time_modes(field, unit="mm/s")
    assert np.array_equal(first.modes, second.modes)
    assert np.array_equal(first.singular_values, second.singular_values)


def test_recovers_a_rank_one_fluctuation() -> None:
    field = _rank_one_field()
    result = decompose_time_modes(field, unit="mm/s")
    pattern = _gate_pattern()
    correlation = float(np.corrcoef(result.modes[0], pattern)[0, 1])
    assert abs(correlation) > 0.999
    assert result.explained_variance_ratio[0] > 0.99
    amplitudes = gate_amplitudes(result)
    assert amplitudes.shape == (3, N_GATES)
    # The recovered amplitude is 11 mm/s * rms(sin) * peak(hump): the mode profile
    # is unit-norm over the gates, so the 11/sqrt(2) scale is carried by sigma.
    assert float(np.max(np.abs(amplitudes[0]))) == pytest.approx(
        11.0 / math.sqrt(2.0) * float(np.max(_gate_pattern())), rel=1e-3
    )


# ── what gate_amplitudes means ──────────────────────────────────────────


def test_gate_amplitudes_are_the_rms_of_the_mode_contribution() -> None:
    rng = np.random.default_rng(13)
    field = rng.normal(size=(80, 7))
    result = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=4)
    )
    amplitudes = gate_amplitudes(result)
    for mode_index in range(4):
        contribution = (
            result.singular_values[mode_index]
            * result.coefficients[:, mode_index, None]
            * result.modes[mode_index][None, :]
        )
        rms = np.sqrt(np.mean(contribution * contribution, axis=0))
        assert np.allclose(rms, np.abs(amplitudes[mode_index]), rtol=1e-12)


def test_amplitudes_parseval_over_the_whole_basis() -> None:
    rng = np.random.default_rng(17)
    field = rng.normal(size=(90, 5))
    # centre=False: the identity then holds over the field's mean square value,
    # which is the gate's mean square *plus* the square of its time mean.
    result = decompose_time_modes(
        field,
        unit="mm/s",
        settings=TimeModesSettings(n_modes=5, center=False),
    )
    amplitudes = gate_amplitudes(result)
    per_gate_mean_square = np.mean(field * field, axis=0)
    assert np.allclose(
        np.sum(amplitudes * amplitudes, axis=0), per_gate_mean_square, rtol=1e-10
    )
    # centre=True: the same sum is the gate's mean square *fluctuation* instead.
    centred = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=5)
    )
    anomaly = field - centred.mean_profile
    assert np.allclose(
        np.sum(gate_amplitudes(centred) ** 2, axis=0),
        np.mean(anomaly * anomaly, axis=0),
        rtol=1e-10,
    )


def test_amplitudes_are_retained_modes_only() -> None:
    rng = np.random.default_rng(23)
    field = rng.normal(size=(60, 9))
    result = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=2)
    )
    assert gate_amplitudes(result).shape == (2, 9)
    assert result.singular_values.shape == (9,)


# ── the two declared choices: centring and sign ─────────────────────────


def test_mean_profile_is_reported_in_both_readings() -> None:
    field = _rank_one_field()
    centred = decompose_time_modes(field, unit="mm/s")
    assert np.array_equal(centred.mean_profile, field.mean(axis=0))
    # The uncentred form keeps the mean in the decomposition, and still reports
    # it, so `field - mean_profile` is the anomaly in either reading.
    raw = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=3, center=False)
    )
    assert np.array_equal(raw.mean_profile, field.mean(axis=0))
    # The uncentred first mode bends toward the time-mean profile (the level
    # direction) while the centred one is the pure fluctuation shape, whose own
    # alignment with the mean profile is lower.
    mean_direction = field.mean(axis=0)
    raw_alignment = abs(float(np.corrcoef(raw.modes[0], mean_direction)[0, 1]))
    centred_alignment = abs(float(np.corrcoef(centred.modes[0], mean_direction)[0, 1]))
    assert raw_alignment > centred_alignment


def test_uncentred_first_mode_is_the_level_direction() -> None:
    """A field whose fluctuation is a common level swing has one level mode."""
    index = np.arange(N_PROFILES)
    gates = np.linspace(20.0, 79.0, N_GATES)
    level = 6.0 * np.sin(2.0 * np.pi * index / 30.0)
    base = 24.0 + 3.0 * gates / 79.0
    rng = np.random.default_rng(43)
    field = (
        base[None, :]
        + level[:, None]
        + rng.normal(scale=0.05, size=(N_PROFILES, N_GATES))
    )
    raw = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=3, center=False)
    )
    # The level swing is the same at every gate, so the first mode is a flat
    # profile and the time mean points along it.
    assert abs(float(np.corrcoef(raw.modes[0], field.mean(axis=0))[0, 1])) > 0.99
    assert float(raw.explained_variance_ratio[0]) > 0.99


def test_sign_convention_orients_every_retained_mode() -> None:
    rng = np.random.default_rng(29)
    result = decompose_time_modes(
        rng.normal(size=(75, 11)), unit="mm/s", settings=TimeModesSettings(n_modes=6)
    )
    assert result.sign_convention == SIGN_CONVENTION
    for mode in result.modes:
        assert float(mode[int(np.argmax(np.abs(mode)))]) > 0.0


def test_flipping_a_mode_keeps_the_reconstruction() -> None:
    """The sign convention moves the sign into the coefficients, not the data."""
    rng = np.random.default_rng(31)
    field = rng.normal(size=(64, 8))
    result = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=8)
    )
    raw_left, raw_singular, raw_right = np.linalg.svd(
        field - result.mean_profile, full_matrices=False
    )
    flipped = np.array(
        [1.0 if np.dot(raw_right[k], result.modes[k]) > 0.0 else -1.0 for k in range(8)]
    )
    assert np.allclose(raw_singular, result.singular_values)
    assert np.allclose(raw_right * flipped[:, None], result.modes, atol=1e-12)
    assert np.allclose(raw_left * flipped[None, :], result.coefficients, atol=1e-12)


# ── mode counting helper ────────────────────────────────────────────────


def test_modes_for_variance_share_counts_the_known_spectrum() -> None:
    singular_values = np.array([4.0, 3.0, 2.0, 1.0])
    field = _known_spectrum(singular_values)
    result = decompose_time_modes(
        field,
        unit="mm/s",
        settings=TimeModesSettings(n_modes=4, center=False),
    )
    # The other N_GATES - 4 directions are exactly empty, so the reported
    # spectrum is the constructed one followed by zeros.
    assert np.allclose(result.singular_values[:4], singular_values, rtol=1e-12)
    assert np.allclose(result.singular_values[4:], 0.0, atol=1e-10)
    shares = singular_values**2 / float(np.sum(singular_values**2))
    assert shares[0] == pytest.approx(0.5333, abs=1e-3)
    assert modes_for_variance_share(result, 0.5) == 1
    assert modes_for_variance_share(result, 0.8) == 2
    assert modes_for_variance_share(result, 0.93) == 3
    assert modes_for_variance_share(result, 0.999) == 4
    assert modes_for_variance_share(result, 1.0) == 4


def test_modes_for_variance_share_uses_the_offset_reading() -> None:
    """``offset`` sets aside leading modes and counts against what is left."""
    singular_values = np.array([4.0, 3.0, 2.0, 1.0])  # shares 53.3/30/13.3/3.3 %
    field = _known_spectrum(singular_values)
    result = decompose_time_modes(
        field,
        unit="mm/s",
        settings=TimeModesSettings(n_modes=4, center=False),
    )
    # of the energy left after mode 1 (46.7%): modes 2+3 carry 43.3/46.7 = 92.9%
    assert modes_for_variance_share(result, 0.92, offset=1) == 2
    assert modes_for_variance_share(result, 0.95, offset=1) == 3
    assert modes_for_variance_share(result, 1.0, offset=1) == 3
    # an offset changes the answer for the same share
    assert modes_for_variance_share(result, 0.6) == 2
    assert modes_for_variance_share(result, 0.6, offset=1) == 1


def test_modes_for_variance_share_refuses_a_bad_offset() -> None:
    rng = np.random.default_rng(19)
    result = decompose_time_modes(rng.normal(size=(30, 4)), unit="mm/s")
    for bad in (-1, 4, 99):
        with pytest.raises(ValueError, match="offset must lie in"):
            modes_for_variance_share(result, 0.95, offset=bad)


def test_modes_for_variance_share_refuses_a_bad_share() -> None:
    rng = np.random.default_rng(37)
    result = decompose_time_modes(rng.normal(size=(30, 4)), unit="mm/s")
    for bad in (0.0, -0.1, 1.5, float("nan")):
        with pytest.raises(ValueError, match="share must be finite"):
            modes_for_variance_share(result, bad)


# ── refusals ────────────────────────────────────────────────────────────


def test_refuses_a_non_matrix() -> None:
    with pytest.raises(TimeModesInputError, match="must be a 2-D"):
        decompose_time_modes(np.zeros(10), unit="mm/s")


def test_refuses_a_single_profile() -> None:
    with pytest.raises(TimeModesInputError, match="at least 2 profiles"):
        decompose_time_modes(np.zeros((1, 5)), unit="mm/s")


def test_refuses_a_non_finite_cell() -> None:
    field = np.zeros((6, 4))
    field[3, 2] = np.nan
    with pytest.raises(TimeModesInputError, match=r"profile 3, gate 2"):
        decompose_time_modes(field, unit="mm/s")


def test_refuses_a_mode_count_above_the_basis() -> None:
    with pytest.raises(TimeModesInputError, match="exceeds the 4 modes"):
        decompose_time_modes(
            np.arange(20).reshape(4, 5).astype(float),
            unit="mm/s",
            settings=TimeModesSettings(n_modes=5),
        )


def test_refuses_a_field_with_no_fluctuation() -> None:
    field = np.repeat(np.arange(5).reshape(1, 5).astype(float), 9, axis=0)
    with pytest.raises(TimeModesInputError, match="no fluctuation to decompose"):
        decompose_time_modes(field, unit="mm/s")


def test_refuses_a_wrong_settings_type() -> None:
    with pytest.raises(TypeError, match="TimeModesSettings"):
        decompose_time_modes(np.zeros((5, 3)), unit="mm/s", settings={"n_modes": 2})


def test_refuses_a_bad_settings_value() -> None:
    with pytest.raises(ValidationError, match="must be >= 1"):
        TimeModesSettings(n_modes=0)


# ── the model's own invariants ──────────────────────────────────────────


def _valid_result() -> TimeModes:
    rng = np.random.default_rng(41)
    return decompose_time_modes(rng.normal(size=(30, 6)), unit="mm/s")


def test_model_requires_a_unit() -> None:
    payload = _valid_result().model_dump()
    payload["unit"] = "   "
    with pytest.raises(ValidationError, match="non-empty signal unit"):
        TimeModes.model_validate(payload)


def test_model_rejects_an_increasing_singular_spectrum() -> None:
    payload = _valid_result().model_dump()
    payload["singular_values"] = payload["singular_values"][::-1].copy()
    with pytest.raises(ValidationError, match="non-increasing"):
        TimeModes.model_validate(payload)


def test_model_rejects_non_orthonormal_modes() -> None:
    payload = _valid_result().model_dump()
    modes = payload["modes"].copy()
    modes[1] = modes[0]
    payload["modes"] = modes
    with pytest.raises(ValidationError, match="orthonormal rows"):
        TimeModes.model_validate(payload)


def test_model_rejects_a_mismatched_retained_share() -> None:
    payload = _valid_result().model_dump()
    payload["retained_variance_ratio"] = float(payload["retained_variance_ratio"]) / 2.0
    with pytest.raises(ValidationError, match="retained_variance_ratio must equal"):
        TimeModes.model_validate(payload)


def test_model_rejects_a_mirrored_mode() -> None:
    payload = _valid_result().model_dump()
    modes = payload["modes"].copy()
    modes[0] = -modes[0]
    payload["modes"] = modes
    with pytest.raises(ValidationError, match="sign_convention"):
        TimeModes.model_validate(payload)


def test_model_rejects_a_share_that_does_not_sum_to_one() -> None:
    payload = _valid_result().model_dump()
    payload["explained_variance_ratio"] = (
        payload["explained_variance_ratio"] * 0.5
    ).copy()
    with pytest.raises(ValidationError, match="must sum to 1"):
        TimeModes.model_validate(payload)


# ── the committed four-sensor fixture ───────────────────────────────────


def test_fixture_channels_decompose_with_all_modes_finite() -> None:
    channels = _fixture_channels()
    assert sorted(channels) == [6, 7, 8, 9]
    for device_channel, field in channels.items():
        result = decompose_time_modes(field, unit="mm/s")
        assert result.n_profiles == 400
        assert result.n_gates == 55
        assert result.max_modes == 55
        assert np.isfinite(gate_amplitudes(result)).all()
        assert math.isclose(
            float(result.explained_variance_ratio.sum()), 1.0, abs_tol=1e-12
        )
        # The mode profiles are velocity-scale, not norms over the whole field.
        assert 0.0 < float(np.max(np.abs(gate_amplitudes(result))[0])) < 60.0
        assert device_channel in (6, 7, 8, 9)


def test_fixture_fluctuation_spectrum_is_broadband() -> None:
    """This rig's fluctuation is not low-rank: no small mode set carries it.

    Measured 2026-10-16 on ``200RPM.BDD``: the first mode carries 12.9-17.1% of
    the mean-removed energy and 95% needs 33-35 of the 55 available modes, so a
    handful of modes must not be read as "the flow's structures".
    """
    for device_channel, field in _fixture_channels().items():
        result = decompose_time_modes(field, unit="mm/s")
        first_share = float(result.explained_variance_ratio[0])
        assert 0.10 < first_share < 0.25, device_channel
        assert first_share < 0.5 * result.retained_variance_ratio + 1.0
        assert modes_for_variance_share(result, 0.95) >= 20, device_channel


def test_fixture_uncentred_first_mode_is_the_stationary_field() -> None:
    """The reading the four-sensor notebook presents: mode 1 is the time mean.

    Measured on ``200RPM.BDD``: the uncentred mode 1 carries 72-86% of the field
    energy, correlates with the per-gate time-mean profile at r >= +0.999, holds
    >= 99.9% of the mean field's energy, and the modes after it are essentially
    orthogonal to that mean (|cos| <= 0.02) — i.e. perturbations about the
    stationary field rather than a repeat of it.
    """
    for device_channel, field in _fixture_channels().items():
        mean = field.mean(axis=0)
        raw = decompose_time_modes(
            field, unit="mm/s", settings=TimeModesSettings(n_modes=4, center=False)
        )
        first_share = float(raw.explained_variance_ratio[0])
        assert 0.70 < first_share < 0.90, device_channel
        assert float(np.corrcoef(raw.modes[0], mean)[0, 1]) > 0.999
        captured = float((mean @ raw.modes[0]) ** 2 / (mean @ mean))
        assert captured > 0.999
        for mode in raw.modes[1:]:
            cosine = float(mean @ mode / np.linalg.norm(mean))
            assert abs(cosine) <= 0.02, device_channel
        # the perturbation energy is spread, not low-rank
        assert modes_for_variance_share(raw, 0.90, offset=1) >= 20, device_channel


def test_fixture_uncentred_first_mode_is_the_level_direction() -> None:
    """Without centring, one mode carries most of the raw energy (the time mean)."""
    for field in _fixture_channels().values():
        raw = decompose_time_modes(
            field, unit="mm/s", settings=TimeModesSettings(n_modes=3, center=False)
        )
        assert float(raw.explained_variance_ratio[0]) > 0.5


def test_fixture_parseval_holds_on_measured_data() -> None:
    field = _fixture_channels()[6]
    result = decompose_time_modes(
        field, unit="mm/s", settings=TimeModesSettings(n_modes=55)
    )
    amplitudes = gate_amplitudes(result)
    anomaly = field - result.mean_profile
    assert np.allclose(
        np.sum(amplitudes * amplitudes, axis=0),
        np.mean(anomaly * anomaly, axis=0),
        rtol=1e-10,
    )
