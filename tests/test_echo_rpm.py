"""Terminal artifact-model echo RPM estimation (FFT peak /2).

Coverage:

- ``EchoRpmSettings`` (frozen, JSON-round-trippable, strict, validated
  ``uniform_rtol``) and ``EchoRpmEstimate`` model invariants — a result whose
  frequency axis, spectrum, peak index, peak frequency or RPM disagree cannot
  be constructed;
- owned, C-contiguous, read-only result arrays;
- the private shared FFT kernel (mean ``|rfft|`` across gates with DC excluded)
  and the ``rpm_from_echo`` tuple it now feeds, which must stay numerically
  identical;
- the input contract: a ``ChannelBundle`` of echo amplitude, fewer than two
  profiles / one gate, an invalid ``SampleSupport`` cell and a structurally
  non-uniform time axis are refused with a typed error;
- the full-span FFT calibration on a quasi-uniform (3.1/3.2 ms) axis, which
  must not use the timestamp-increment median;
- a real single-channel echo fixture pair (``data/echo/650.ADD`` / ``.BDD``)
  whose legacy and artifact estimates agree.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from udv_echo_process import extract, rpm_from_echo
from udv_echo_process.analysis import RpmResult
from udv_echo_process.analysis.rpm import (
    EchoRpmInputError,
    _echo_rpm_spectrum,
    rpm_from_channel,
)
from udv_echo_process.models import (
    AcquisitionRef,
    ChannelConfig,
    ChannelKey,
    EchoRpmEstimate,
    EchoRpmSettings,
    QualityFlag,
    SampleSupport,
    SignalData,
    SignalDescriptor,
    SignalQuantity,
    observed_signal,
    source_artifact,
)
from udv_echo_process.models.identity import recording_id_for
from udv_echo_process.provenance import ChannelBundle, source_bundle
from udv_echo_process.run_all import collect_artifact_results, run_artifact_rpm_sweep

ROOT = Path(__file__).resolve().parents[1]
SINGLE_ADD = ROOT / "data" / "echo" / "650.ADD"
SINGLE_BDD = ROOT / "data" / "echo" / "650.BDD"

_HEX = "1" * 64
_ASSET_ID = "sha256:" + _HEX
_ECHO = SignalDescriptor(quantity=SignalQuantity.ECHO_AMPLITUDE, unit="module")
_VELOCITY = SignalDescriptor(quantity=SignalQuantity.AXIAL_VELOCITY, unit="mm/s")


# ── builders ─────────────────────────────────────────────────────────────


def _bundle(
    field: object,
    *,
    time_s: object = None,
    gate_depths: object = None,
    channel: int = 4,
    descriptor: SignalDescriptor = _ECHO,
    quality: object = None,
    data: SignalData | None = None,
) -> ChannelBundle:
    """Build a SOURCE ``ChannelBundle`` for one echo payload."""
    if data is None:
        arr = np.asarray(field, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr[:, None]
        n, g = arr.shape
        if time_s is None:
            time_s = np.arange(n, dtype=np.float64) * 0.0032
        if gate_depths is None:
            gate_depths = np.linspace(40.0, 50.0, g)
        data = observed_signal(time_s, gate_depths, arr, quality=quality)
    ref = AcquisitionRef(
        recording_id=recording_id_for(_ASSET_ID),
        source_asset_id=_ASSET_ID,
        channel=ChannelKey(device_channel=channel),
    )
    return source_bundle(source_artifact(ref, descriptor, ChannelConfig(), data))


def _exact_bin_field(n: int = 64, bin_index: int = 4, gates: int = 3) -> np.ndarray:
    """Return a ``(N, G)`` echo field whose rFFT peak sits exactly on a bin.

    Every gate carries the same modulation frequency with its own amplitude, so
    the gate-averaged magnitude spectrum still peaks at ``bin_index``.
    """
    samples = np.arange(n, dtype=np.float64)
    wave = np.cos(2.0 * np.pi * bin_index * samples / n)
    amplitudes = 1.0 + 0.25 * np.arange(gates, dtype=np.float64)
    return amplitudes[None, :] * wave[:, None]


def _estimate(**over: object) -> EchoRpmEstimate:
    """Build a valid estimate, with field overrides for negative tests."""
    n = 64
    time_step_s = 0.002
    frequencies = np.fft.rfftfreq(n, d=time_step_s)
    spectrum = np.zeros_like(frequencies)
    spectrum[4] = 10.0
    base: dict[str, object] = {
        "settings": EchoRpmSettings(),
        "artifact_id": _ASSET_ID,
        "descriptor": _ECHO,
        "profile_count": n,
        "gate_count": 2,
        "time_step_s": time_step_s,
        "max_relative_interval_deviation": 0.0,
        "peak_index": 4,
        "peak_freq_hz": float(frequencies[4]),
        "rpm": float(frequencies[4]) / 2 * 60,
        "frequencies_hz": frequencies,
        "spectrum": spectrum,
    }
    base.update(over)
    return EchoRpmEstimate(**base)  # type: ignore[arg-type]


def _quantized_axis(n: int = 101) -> np.ndarray:
    """Return a real-data-like axis: 3.2 ms cadence with every 10th step short.

    Mirrors the committed echo fixtures, whose adjacent intervals alternate
    between 3.1 and 3.2 ms: the median increment is 3.2 ms while the full-span
    effective interval is smaller, and the worst relative deviation from the
    median is 3.125%.
    """
    steps = np.full(n - 1, 0.0032, dtype=np.float64)
    steps[::10] = 0.0031
    return np.concatenate(([0.0], np.cumsum(steps)))


# ── settings ─────────────────────────────────────────────────────────────


def test_settings_default_and_json_round_trip() -> None:
    settings = EchoRpmSettings()
    assert settings.uniform_rtol == 0.05
    dumped = settings.model_dump(mode="json")
    assert dumped == {"uniform_rtol": 0.05}
    assert json.loads(json.dumps(dumped)) == dumped
    assert EchoRpmSettings(**dumped) == settings


def test_settings_are_frozen_and_forbid_extras() -> None:
    settings = EchoRpmSettings()
    with pytest.raises(ValidationError):
        settings.uniform_rtol = 0.01  # type: ignore[misc]
    with pytest.raises(ValidationError):
        EchoRpmSettings(uniform_rtol=0.01, lowest_bin_index=1)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "value",
    [-0.01, 0.0500001, float("nan"), float("inf"), float("-inf")],
)
def test_settings_reject_invalid_uniform_rtol(value: float) -> None:
    with pytest.raises(ValidationError, match="uniform_rtol"):
        EchoRpmSettings(uniform_rtol=value)


@pytest.mark.parametrize("value", [0.0, 0.03125, 0.05])
def test_settings_accept_the_declared_rtol_range(value: float) -> None:
    assert EchoRpmSettings(uniform_rtol=value).uniform_rtol == value


# ── estimate invariants ──────────────────────────────────────────────────


def test_estimate_arrays_are_owned_contiguous_and_read_only() -> None:
    frequencies = np.fft.rfftfreq(64, d=0.002)
    estimate = _estimate(frequencies_hz=frequencies)
    for name in ("frequencies_hz", "spectrum"):
        array = getattr(estimate, name)
        assert array.flags.owndata
        assert array.flags.c_contiguous
        assert not array.flags.writeable
    assert not np.shares_memory(estimate.frequencies_hz, frequencies)
    with pytest.raises(ValueError, match="read-only"):
        estimate.spectrum[0] = 1.0


def test_estimate_rejects_wrong_frequency_axis_shape() -> None:
    with pytest.raises(ValidationError, match="frequencies_hz"):
        _estimate(frequencies_hz=np.zeros(32, dtype=np.float64))
    with pytest.raises(ValidationError, match="spectrum"):
        _estimate(spectrum=np.zeros(10, dtype=np.float64))


def test_estimate_rejects_non_right_frequency_axis() -> None:
    assert _estimate().frequencies_hz.shape == (33,)
    with pytest.raises(ValidationError, match="rfftfreq|frequency axis"):
        _estimate(
            frequencies_hz=np.linspace(0.0, 100.0, 33),
            peak_index=4,
            peak_freq_hz=float(np.linspace(0.0, 100.0, 33)[4]),
            rpm=float(np.linspace(0.0, 100.0, 33)[4]) / 2 * 60,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("spectrum", "negative", "non-negative"),
        ("spectrum", "nan", "finite"),
        ("peak_index", 0, "peak_index"),
        ("peak_index", 33, "peak_index"),
        ("peak_index", -1, "peak_index"),
        ("peak_index", 5, "maximum"),
    ],
)
def test_estimate_rejects_bad_spectrum_or_peak(
    field: str, value: object, match: str
) -> None:
    spectrum = np.zeros(33, dtype=np.float64)
    spectrum[4] = 10.0
    if field == "spectrum" and value == "negative":
        spectrum[4] = -10.0
    if field == "spectrum" and value == "nan":
        spectrum[4] = np.nan
    over: dict[str, object] = {field: value} if field != "spectrum" else {}
    if field == "spectrum":
        over["spectrum"] = spectrum
    with pytest.raises(ValidationError, match=match):
        _estimate(**over)


def test_estimate_rejects_inconsistent_peak_frequency_and_rpm() -> None:
    with pytest.raises(ValidationError, match="peak_freq_hz"):
        _estimate(peak_freq_hz=123.0)
    with pytest.raises(ValidationError, match="rpm"):
        _estimate(rpm=123.0)


def test_estimate_rejects_non_echo_descriptor() -> None:
    with pytest.raises(ValidationError, match="echo"):
        _estimate(descriptor=_VELOCITY)


def test_estimate_rejects_deviation_above_the_settings_tolerance() -> None:
    with pytest.raises(ValidationError, match="uniform_rtol|deviation"):
        _estimate(max_relative_interval_deviation=0.2)
    tolerated = _estimate(
        settings=EchoRpmSettings(uniform_rtol=0.03125),
        max_relative_interval_deviation=0.03125,
    )
    assert tolerated.max_relative_interval_deviation == 0.03125


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("profile_count", 1, "profile_count"),
        ("gate_count", 0, "gate_count"),
        ("time_step_s", 0.0, "time_step_s"),
        ("max_relative_interval_deviation", -0.1, "deviation"),
        ("artifact_id", "not-an-id", "artifact_id"),
    ],
)
def test_estimate_rejects_degenerate_scalars(
    field: str, value: object, match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        _estimate(**{field: value})


# ── shared private kernel ────────────────────────────────────────────────


def test_kernel_is_the_mean_gate_magnitude_spectrum() -> None:
    rng = np.random.default_rng(20260915)
    samples = np.arange(128, dtype=np.float64)
    values = np.stack(
        [
            12.0 * np.cos(2 * np.pi * 7 * samples / 128) + 3.0,
            8.0 * np.cos(2 * np.pi * 7 * samples / 128 + 0.4) + 30.0,
            5.0 * np.cos(2 * np.pi * 11 * samples / 128) + 60.0,
        ],
        axis=1,
    )
    values = values + rng.normal(scale=0.1, size=values.shape)
    frequencies, spectrum, peak_index = _echo_rpm_spectrum(values, 0.02)
    np.testing.assert_array_equal(frequencies, np.fft.rfftfreq(values.shape[0], 0.02))
    np.testing.assert_array_equal(
        spectrum, np.abs(np.fft.rfft(values, axis=0)).mean(axis=1)
    )
    assert spectrum.shape == (values.shape[0] // 2 + 1,)
    assert peak_index == int(np.argmax(spectrum[1:])) + 1


def test_kernel_excludes_the_dc_bin() -> None:
    """A dominant DC offset must not become the reported peak."""
    n = 128
    samples = np.arange(n, dtype=np.float64)
    wave = 5.0 * np.cos(2 * np.pi * 8 * samples / n)
    values = np.stack([1000.0 + wave, 2000.0 + 2.0 * wave], axis=1)
    _, spectrum, peak_index = _echo_rpm_spectrum(values, 0.01)
    assert int(np.argmax(spectrum)) == 0  # DC is by far the largest bin
    assert peak_index == 8  # ...and the kernel still selects the modulation


# ── legacy entry point stays numerically identical ───────────────────────


def test_rpm_from_echo_tuple_matches_independent_recomputation() -> None:
    parsed = extract(SINGLE_ADD)
    tbds = np.array([f.tbd_ms for f in parsed.frames], dtype=np.float64)
    dt_s = float(np.mean(np.diff(tbds))) / 1000.0
    matrix = np.array([f.values for f in parsed.frames], dtype=np.float64)
    n_samples = matrix.shape[0]
    frequencies = np.fft.rfftfreq(n_samples, d=dt_s)
    spectrum = np.abs(np.fft.rfft(matrix, axis=0)).mean(axis=1)
    peak_index = int(np.argmax(spectrum[1:])) + 1
    expected = (float(frequencies[peak_index]) / 2 * 60, float(frequencies[peak_index]))
    rpm, peak_freq_hz, n = rpm_from_echo(parsed)
    assert n == n_samples == 4630
    assert (rpm, peak_freq_hz) == pytest.approx(expected, rel=1e-12, abs=1e-12)
    assert rpm == pytest.approx(649.576228, abs=1e-6)


def test_rpm_from_echo_still_accepts_an_explicit_dt() -> None:
    rpm, peak_freq_hz, n = rpm_from_echo(extract(SINGLE_ADD), dt_s=0.0032)
    assert n == 4630
    assert 0.0 < rpm < 2000.0
    assert peak_freq_hz > 0.0


# ── channel estimator: exact-bin synthetic case ──────────────────────────


def test_rpm_from_channel_recovers_an_exact_bin_modulation() -> None:
    n, bin_index, time_step_s = 64, 4, 0.002
    bundle = _bundle(
        _exact_bin_field(n=n, bin_index=bin_index),
        time_s=np.arange(n, dtype=np.float64) * time_step_s,
    )
    estimate = rpm_from_channel(bundle)
    expected_frequency = bin_index / (n * time_step_s)
    assert estimate.peak_index == bin_index
    assert estimate.peak_freq_hz == pytest.approx(expected_frequency, rel=1e-12)
    assert estimate.rpm == pytest.approx(expected_frequency / 2 * 60, rel=1e-12)
    assert estimate.rpm == pytest.approx(937.5, rel=1e-12)
    assert (estimate.profile_count, estimate.gate_count) == (n, 3)
    assert estimate.time_step_s == pytest.approx(time_step_s, rel=1e-12)
    assert estimate.max_relative_interval_deviation == pytest.approx(0.0, abs=1e-12)
    assert estimate.artifact_id == bundle.artifact.artifact_id
    assert estimate.descriptor == bundle.artifact.descriptor
    assert estimate.settings == EchoRpmSettings()
    assert estimate.frequencies_hz.shape == estimate.spectrum.shape == (n // 2 + 1,)


def test_rpm_from_channel_leaves_the_source_bundle_untouched() -> None:
    bundle = _bundle(_exact_bin_field())
    artifact_id = bundle.artifact.artifact_id
    values = bundle.artifact.data.values.copy()
    valid = bundle.artifact.data.support.valid.copy()
    graph = bundle.graph
    estimate = rpm_from_channel(bundle)
    assert bundle.artifact.artifact_id == artifact_id
    assert np.array_equal(bundle.artifact.data.values, values)
    assert np.array_equal(bundle.artifact.data.support.valid, valid)
    assert bundle.graph is graph
    assert bundle.graph.operations == ()
    assert bundle.graph.derivations == ()
    assert not np.shares_memory(estimate.spectrum, bundle.artifact.data.values)


# ── channel estimator: input guard ───────────────────────────────────────


def test_rpm_from_channel_rejects_wrong_types() -> None:
    with pytest.raises(TypeError, match="ChannelBundle"):
        rpm_from_channel(np.zeros((10, 2)))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="EchoRpmSettings"):
        rpm_from_channel(_bundle(_exact_bin_field()), settings={"uniform_rtol": 0.01})  # type: ignore[arg-type]


def test_rpm_from_channel_rejects_a_velocity_channel() -> None:
    bundle = _bundle(_exact_bin_field(), descriptor=_VELOCITY)
    with pytest.raises(EchoRpmInputError, match="echo"):
        rpm_from_channel(bundle)


def test_rpm_from_channel_rejects_too_few_profiles_and_gates() -> None:
    single_profile = _bundle(np.ones((1, 2), dtype=np.float64))
    with pytest.raises(EchoRpmInputError, match="at least 2 profiles"):
        rpm_from_channel(single_profile)
    two_profiles = _bundle(np.ones((2, 2), dtype=np.float64))
    assert rpm_from_channel(two_profiles).profile_count == 2


def test_rpm_from_channel_rejects_an_invalid_support_cell() -> None:
    field = _exact_bin_field(n=16, bin_index=2, gates=2)
    field[3, 1] = np.nan
    bundle = _bundle(
        field, quality=np.full(field.shape, int(QualityFlag.OUTLIER), dtype=np.uint32)
    )
    with pytest.raises(EchoRpmInputError) as excinfo:
        rpm_from_channel(bundle)
    message = str(excinfo.value)
    assert "1 invalid cell" in message
    assert "time=3" in message and "gate=1" in message


def test_rpm_from_channel_allows_valid_interpolated_samples() -> None:
    """A resampled (derived) bundle is a legitimate input; only invalid is not."""
    n, gates = 32, 2
    field = _exact_bin_field(n=n, bin_index=2, gates=gates)
    time_s = np.arange(n, dtype=np.float64) * 0.0032
    depths = np.linspace(40.0, 50.0, gates)
    data = SignalData(
        time_s=time_s,
        gate_depths_mm=depths,
        values=field,
        support=SampleSupport(
            kind=np.full(field.shape, 2, dtype=np.uint8),  # INTERPOLATED
            valid=np.ones(field.shape, dtype=bool),
            quality=np.zeros(field.shape, dtype=np.uint32),
        ),
    )
    bundle = _bundle(field, data=data)
    estimate = rpm_from_channel(bundle)
    assert estimate.peak_index == 2


# ── time-axis regularity ─────────────────────────────────────────────────


def test_rpm_from_channel_calibrates_by_the_full_span_not_the_median() -> None:
    axis = _quantized_axis()
    intervals = np.diff(axis)
    median_interval = float(np.median(intervals))
    span_interval = float((axis[-1] - axis[0]) / (axis.size - 1))
    assert median_interval == pytest.approx(0.0032)
    assert span_interval == pytest.approx(0.00319)
    n, bin_index = axis.size, 4
    wave = np.cos(2.0 * np.pi * bin_index * np.arange(n) / n)
    bundle = _bundle(np.stack([wave, 2.0 * wave], axis=1), time_s=axis)
    estimate = rpm_from_channel(bundle)
    assert estimate.time_step_s == pytest.approx(span_interval, rel=1e-15)
    assert estimate.time_step_s == pytest.approx(float(np.mean(intervals)), rel=1e-12)
    # the short steps drag the full-span mean BELOW the dominant quantum, so a
    # median-calibrated FFT would overstate every recovered frequency
    assert estimate.time_step_s < median_interval
    assert estimate.max_relative_interval_deviation == pytest.approx(0.03125, abs=1e-6)
    frequency_step = span_interval
    assert estimate.frequencies_hz[bin_index] == pytest.approx(
        bin_index / (n * frequency_step), rel=1e-12
    )
    assert estimate.rpm == pytest.approx(estimate.peak_freq_hz / 2 * 60, rel=1e-15)


def test_rpm_from_channel_rejects_a_structural_gap() -> None:
    axis = _quantized_axis()
    axis[1:] = axis[1:] + 0.3  # a burst/visit boundary after profile 0
    bundle = _bundle(_exact_bin_field(n=axis.size), time_s=axis)
    with pytest.raises(EchoRpmInputError, match="uniform"):
        rpm_from_channel(bundle)


def test_rpm_from_channel_honours_a_tighter_uniform_rtol() -> None:
    axis = _quantized_axis()
    bundle = _bundle(_exact_bin_field(n=axis.size), time_s=axis)
    assert rpm_from_channel(bundle).max_relative_interval_deviation == pytest.approx(
        0.03125, abs=1e-6
    )
    with pytest.raises(EchoRpmInputError, match="uniform"):
        rpm_from_channel(bundle, EchoRpmSettings(uniform_rtol=0.01))
    # the committed fixtures clear the default 5% with a 5/3 margin, and a
    # caller who wants less tolerance than that gets a typed refusal
    tolerated = rpm_from_channel(bundle, EchoRpmSettings(uniform_rtol=0.04))
    assert tolerated.settings.uniform_rtol == 0.04
    assert tolerated.max_relative_interval_deviation == pytest.approx(0.03125, abs=1e-6)


# ── real fixture pair ────────────────────────────────────────────────────


def test_rpm_from_channel_matches_the_add_estimate_on_650() -> None:
    from udv_echo_process.io import load
    from udv_echo_process.provenance import select_channel

    bundle = load(SINGLE_BDD)
    channel = select_channel(bundle, bundle.recording.streams[0].acquisition.channel)
    estimate = rpm_from_channel(channel)
    parsed = extract(SINGLE_ADD)
    legacy_rpm, legacy_freq, legacy_n = rpm_from_echo(parsed)
    assert (estimate.profile_count, estimate.gate_count) == (4630, 26)
    assert estimate.time_step_s == pytest.approx(0.003182, abs=1e-6)
    assert estimate.max_relative_interval_deviation == pytest.approx(0.03125)
    assert estimate.rpm == pytest.approx(649.576228, abs=1e-6)
    assert estimate.rpm == pytest.approx(legacy_rpm, rel=1e-12, abs=1e-12)
    assert estimate.peak_freq_hz == pytest.approx(legacy_freq, rel=1e-12, abs=1e-12)
    assert estimate.profile_count == legacy_n
    assert estimate.rpm == pytest.approx(estimate.peak_freq_hz / 2 * 60, rel=1e-15)


# ── public surface ───────────────────────────────────────────────────────


def test_new_public_names_resolve_from_every_documented_surface() -> None:
    import udv_echo_process
    import udv_echo_process.analysis as analysis_module
    import udv_echo_process.models as models_module

    terminal = ("EchoRpmEstimate", "EchoRpmSettings")
    estimator = ("EchoRpmInputError", "rpm_from_channel")
    for name in terminal:
        assert hasattr(models_module, name)
        assert name in models_module.__all__
        assert name in analysis_module.__all__
        assert name in udv_echo_process.__all__
    for name in estimator:
        assert name in analysis_module.__all__
        assert name in udv_echo_process.__all__
    assert "artifact" in ChannelBundle.model_fields  # the documented input type


def test_channel_estimator_requires_a_bundle_not_a_bare_artifact() -> None:
    bundle = _bundle(_exact_bin_field())
    with pytest.raises(TypeError, match="ChannelBundle"):
        rpm_from_channel(bundle.artifact)  # type: ignore[arg-type]


# ── artifact batch sweep ─────────────────────────────────────────────────
#
# Acceptance table pinned from the committed fixture set: the shared legacy
# kernel plus the full-span effective interval. Each value equals its paired
# ``.ADD`` result to floating-point precision (asserted separately below), and
# the filename-derived setpoint is an experiment label, not independent
# tachometer ground truth — so the 2% check is a campaign sanity limit rather
# than an uncertainty claim.

PINNED_ECHO_RPM: dict[int, tuple[int, float]] = {
    200: (4180, 202.995583),
    230: (4287, 230.918406),
    250: (4193, 251.832871),
    280: (4307, 280.192124),
    300: (4517, 300.561842),
    330: (4211, 331.358566),
    350: (4284, 349.920135),
    380: (4266, 380.125002),
    400: (4813, 399.608697),
    430: (4267, 430.857276),
    450: (4927, 449.683825),
    480: (4289, 477.007576),
    500: (4465, 498.325472),
    530: (4239, 529.340515),
    550: (4675, 550.555590),
    580: (4342, 579.750760),
    600: (4553, 598.443550),
    630: (4253, 629.572995),
    650: (4630, 649.576228),
}

DATA_ECHO = ROOT / "data" / "echo"
FOUR_CHANNEL_ECHO = ROOT / "data" / "echo-4-sensors-2x2" / "20260723_143754.jpg"
FOUR_CHANNEL_VELOCITY = ROOT / "data" / "4-sensor-velocity" / "200RPM.BDD"


@pytest.fixture(scope="module")
def echo_sweep(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[list[RpmResult], Path]:
    """Run the real 19-recording artifact sweep once and keep its PNG path."""
    output = tmp_path_factory.mktemp("artifact-rpm") / "figures" / "summary.png"
    rows = run_artifact_rpm_sweep(DATA_ECHO, output)
    return rows, output


def test_sweep_discovers_the_19_single_channel_echo_recordings(
    echo_sweep: tuple[list[RpmResult], Path],
) -> None:
    rows, _ = echo_sweep
    assert [r.setpoint_rpm for r in rows] == sorted(PINNED_ECHO_RPM)
    assert len(rows) == 19


def test_sweep_matches_the_pinned_acceptance_table(
    echo_sweep: tuple[list[RpmResult], Path],
) -> None:
    rows, _ = echo_sweep
    for row in rows:
        profiles, expected_rpm = PINNED_ECHO_RPM[row.setpoint_rpm]
        assert row.n_samples == profiles, row.setpoint_rpm
        assert row.measured_rpm == pytest.approx(expected_rpm, abs=0.01)
        assert row.rel_error_pct <= 2.0
        expected_error = (
            abs(row.measured_rpm - row.setpoint_rpm) / row.setpoint_rpm * 100
        )
        assert row.rel_error_pct == pytest.approx(expected_error, rel=1e-12)


def test_sweep_writes_a_real_summary_figure(
    echo_sweep: tuple[list[RpmResult], Path],
) -> None:
    _, output = echo_sweep
    assert output.is_file()
    assert output.stat().st_size > 0
    assert output.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_sweep_rows_match_the_paired_add_estimates(
    echo_sweep: tuple[list[RpmResult], Path],
) -> None:
    rows, _ = echo_sweep
    for row in rows:
        parsed = extract(DATA_ECHO / f"{row.setpoint_rpm}.ADD")
        legacy_rpm, legacy_freq_hz, legacy_n = rpm_from_echo(parsed)
        assert row.measured_rpm == pytest.approx(legacy_rpm, rel=1e-12, abs=1e-12)
        assert row.peak_freq_hz == pytest.approx(legacy_freq_hz, rel=1e-12, abs=1e-12)
        assert row.n_samples == legacy_n


def test_collect_artifact_results_sorts_by_setpoint() -> None:
    paths = [
        DATA_ECHO / "650.BDD",
        DATA_ECHO / "200.BDD",
        DATA_ECHO / "300.BDD",
    ]
    rows = collect_artifact_results(paths)
    assert [r.setpoint_rpm for r in rows] == [200, 300, 650]


def test_collect_artifact_results_rows_match_the_estimates() -> None:
    from udv_echo_process.io import load
    from udv_echo_process.provenance import select_channel

    path = DATA_ECHO / "650.BDD"
    bundle = load(path)
    channel = select_channel(bundle, bundle.recording.streams[0].acquisition.channel)
    estimate = rpm_from_channel(channel)
    (row,) = collect_artifact_results([path])
    assert row.setpoint_rpm == 650
    assert row.measured_rpm == estimate.rpm
    assert row.peak_freq_hz == estimate.peak_freq_hz
    assert row.n_samples == estimate.profile_count
    assert row.rel_error_pct == pytest.approx(
        abs(estimate.rpm - 650) / 650 * 100, rel=1e-12
    )


def test_collect_artifact_results_rejects_a_multi_stream_recording() -> None:
    """Never silently reduce a four-channel recording to stream 0."""
    with pytest.raises(ValueError) as excinfo:
        collect_artifact_results([FOUR_CHANNEL_VELOCITY])
    message = str(excinfo.value)
    assert FOUR_CHANNEL_VELOCITY.name in message
    assert "4 recording streams" in message
    assert "rpm_from_channel() per channel" in message


def test_estimator_rejects_one_channel_of_a_multi_stream_recording() -> None:
    from udv_echo_process.io import load
    from udv_echo_process.provenance import select_channel

    bundle = load(FOUR_CHANNEL_VELOCITY)
    channel = select_channel(bundle, bundle.recording.streams[0].acquisition.channel)
    with pytest.raises(EchoRpmInputError, match="echo"):
        rpm_from_channel(channel)


def test_burst_sampled_echo_fixture_is_refused() -> None:
    """The four-channel burst fixture is a refusal case, not an accuracy claim.

    Its ``(1000, 35)`` echo payload is burst/visit sampled: the adjacent
    intervals deviate from their median by ~46x, so *every* selected channel is
    refused instead of being compacted onto a uniform cadence — the compacted
    ~450 RPM figure is deliberately not pinned or documented.
    """
    from udv_echo_process.io import load
    from udv_echo_process.provenance import select_channel

    bundle = load(FOUR_CHANNEL_ECHO)
    channels = [s.acquisition.channel for s in bundle.recording.streams]
    assert len(channels) == 4
    for key in channels:
        channel = select_channel(bundle, key)
        with pytest.raises(EchoRpmInputError, match="uniform"):
            rpm_from_channel(channel)


def test_sweep_skips_unrecognized_and_nested_entries(tmp_path: Path) -> None:
    """Discovery is content-sniffed, non-recursive and extension-independent."""
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "650.BDD").symlink_to(DATA_ECHO / "650.BDD")  # real bytes
    # real BDD bytes under a wrong extension: sniffing must keep it
    (experiment / "200.jpg").symlink_to(DATA_ECHO / "200.BDD")
    # .BDD extension over text bytes: sniffing must drop it
    (experiment / "text.BDD").write_text("not a recording\n")
    (experiment / "300_Stat.ADD").write_text("Gate Depth [mm]\n")
    nested = experiment / "nested"
    nested.mkdir()
    (nested / "300.BDD").symlink_to(DATA_ECHO / "300.BDD")  # must not be scanned

    output = tmp_path / "figures" / "summary.png"
    rows = run_artifact_rpm_sweep(experiment, output)
    assert [r.setpoint_rpm for r in rows] == [200, 650]
    assert output.stat().st_size > 0


def test_sweep_reports_a_recognized_recording_without_a_setpoint_stem(
    tmp_path: Path,
) -> None:
    """A recognized recording with no filename setpoint fails loudly.

    It is not silently dropped: ``setpoint_rpm_from_stem`` names the stem, so a
    mis-named recording is visible instead of quietly missing from the sweep.
    """
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    (experiment / "run-a.BDD").symlink_to(DATA_ECHO / "650.BDD")
    with pytest.raises(ValueError, match="cannot parse RPM setpoint from stem"):
        run_artifact_rpm_sweep(experiment, tmp_path / "summary.png")


def test_sweep_raises_when_no_recording_is_recognized(tmp_path: Path) -> None:
    (tmp_path / "text.BDD").write_text("not a recording\n")
    (tmp_path / "200.ADD").write_text("Gate Depth [mm]\n")
    with pytest.raises(ValueError, match="no artifact-model recordings"):
        run_artifact_rpm_sweep(tmp_path, tmp_path / "summary.png")


def test_sweep_rejects_a_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a directory"):
        run_artifact_rpm_sweep(tmp_path / "absent", tmp_path / "summary.png")
