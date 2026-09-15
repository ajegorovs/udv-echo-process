"""Generate visualizations and a summary for all UDV measurement files.

Two RPM sweeps coexist, mirroring the two pipelines:

- the legacy ``.ADD`` path (:func:`collect_results` / :func:`main`) parses
  ``ExtractedData`` and also emits the per-file heatmaps/profiles;
- the artifact-model ``.BDD`` path (:func:`collect_artifact_results` /
  :func:`run_artifact_rpm_sweep`) loads each recording into an
  ``ArtifactBundle``, estimates one channel's echo RPM through
  ``rpm_from_channel`` and writes the same setpoint-vs-recovered summary plot.

There is still no adapter between the pipelines: ``udv-run-all`` stays on the
``.ADD`` path because it also generates legacy visualizations that have no
artifact-model counterpart yet.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from udv_echo_process.analysis import (
    RpmResult,
    rpm_from_channel,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)
from udv_echo_process.io import load, sniff
from udv_echo_process.parser import ExtractedData, extract, list_add_files
from udv_echo_process.provenance import select_channel
from udv_echo_process.viz import plot_all


def plot_summary(results: list[RpmResult], output_path: Path) -> None:
    """Combined scatter plot: measured vs setpoint RPM with error panel."""
    setpoints = np.array([r.setpoint_rpm for r in results])
    measured = np.array([r.measured_rpm for r in results])
    errors = np.array([r.rel_error_pct for r in results])

    fig, (ax1, ax2) = plt.subplots(
        2,
        1,
        figsize=(10, 8),
        gridspec_kw={"height_ratios": [3, 1]},
        constrained_layout=True,
    )

    ax1.plot(setpoints, setpoints, "k--", lw=1, alpha=0.5, label="Ideal")
    ax1.scatter(setpoints, measured, c="C0", s=40, zorder=3)
    for sp, m in zip(setpoints, measured):
        ax1.plot([sp, sp], [sp, m], "C0", lw=0.5, alpha=0.4)

    ax1.set_xlabel("Setpoint RPM")
    ax1.set_ylabel("Measured RPM")
    ax1.set_title("UDV RPM Measurement \u2014 FFT Peak /2 Method")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.bar(range(len(errors)), errors, color="C1", width=0.6)
    ax2.set_xticks(range(len(errors)))
    ax2.set_xticklabels([str(r.setpoint_rpm) for r in results], fontsize=8)
    ax2.set_xlabel("Setpoint RPM")
    ax2.set_ylabel("Error [%]")
    ax2.set_title(f"Relative Error (mean: {errors.mean():.1f}%)")
    ax2.grid(True, alpha=0.3, axis="y")

    fig.savefig(output_path, dpi=150)
    print(f"Saved: {output_path}")
    plt.close(fig)


def collect_results(
    datasets: dict[str, ExtractedData],
    dt_s: float | None = None,
) -> list[RpmResult]:
    """Estimate RPM for each parsed dataset keyed by file stem.

    ``dt_s`` is the sampling interval in seconds; when omitted it is derived
    per dataset from the parsed TBD column (see
    :func:`udv_echo_process.analysis.rpm.mean_sample_interval_s`).
    """
    results: list[RpmResult] = []
    for stem, d in datasets.items():
        rpm, f_peak, n = rpm_from_echo(d, dt_s)
        setpoint = setpoint_rpm_from_stem(stem)
        err = abs(rpm - setpoint) / setpoint * 100
        results.append(
            RpmResult(
                setpoint_rpm=setpoint,
                measured_rpm=rpm,
                peak_freq_hz=f_peak,
                rel_error_pct=err,
                n_samples=n,
            )
        )
    results.sort(key=lambda r: r.setpoint_rpm)
    return results


def collect_artifact_results(paths: Iterable[str | Path]) -> list[RpmResult]:
    """Estimate RPM for each artifact-model recording path, sorted by setpoint.

    Loads every path through ``io.load()`` (content-sniffed, not
    extension-trusted), requires **exactly one recording stream**, selects that
    stream by its real :class:`~udv_echo_process.models.identity.ChannelKey`,
    runs :func:`~udv_echo_process.analysis.rpm.rpm_from_channel` and converts
    the terminal estimate into the scalar ``RpmResult`` rows the legacy summary
    plot already consumes. The setpoint is derived from the path stem via
    :func:`~udv_echo_process.analysis.rpm.setpoint_rpm_from_stem`.

    A multi-stream recording raises ``ValueError`` naming the path: silently
    reducing it to stream 0 would report one channel's spectrum as the whole
    recording's RPM.

    Args:
        paths: recording paths (``.BDD`` content) to estimate.

    Returns:
        ``RpmResult`` rows sorted by setpoint RPM.

    Raises:
        ValueError: a path carries more than one recording stream.
        EchoRpmInputError: a single-stream recording cannot enter the estimator
            (non-echo channel, invalid support, non-uniform axis).
    """
    results: list[RpmResult] = []
    for raw_path in paths:
        path = Path(raw_path)
        bundle = load(path)
        streams = bundle.recording.streams
        if len(streams) != 1:
            channels = [s.acquisition.channel.device_channel for s in streams]
            raise ValueError(
                f"{path.name} carries {len(streams)} recording streams "
                f"(channels {channels}); echo RPM is a single-channel estimate — "
                "select a channel with select_channel() and call "
                "rpm_from_channel() per channel instead"
            )
        channel = select_channel(bundle, streams[0].acquisition.channel)
        estimate = rpm_from_channel(channel)
        setpoint = setpoint_rpm_from_stem(path.stem)
        results.append(
            RpmResult(
                setpoint_rpm=setpoint,
                measured_rpm=estimate.rpm,
                peak_freq_hz=estimate.peak_freq_hz,
                rel_error_pct=abs(estimate.rpm - setpoint) / setpoint * 100,
                n_samples=estimate.profile_count,
            )
        )
    results.sort(key=lambda r: r.setpoint_rpm)
    return results


def run_artifact_rpm_sweep(
    data_dir: str | Path = "data/echo",
    output_path: str | Path = "outputs/summary-artifact-rpm.png",
) -> list[RpmResult]:
    """Reproduce the single-channel echo RPM sweep on the artifact model.

    Scans **only the immediate files** of ``data_dir`` (no recursion) and keeps
    the paths whose leading bytes ``io.sniff()`` recognizes as an artifact-model
    recording, so a misnamed image, an ``.ADD`` text export or a statistical
    export is skipped by content rather than by extension. The recognized paths
    go through :func:`collect_artifact_results`, and the collected rows are
    written with the existing :func:`plot_summary` (setpoint vs recovered RPM
    plus the relative-error panel).

    Args:
        data_dir: directory holding the single-channel echo recordings.
        output_path: destination for the summary PNG; its parent is created.

    Returns:
        The collected ``RpmResult`` rows (sorted by setpoint).

    Raises:
        ValueError: ``data_dir`` is not a directory, it holds no artifact-model
            recording, or a recognized recording's filename carries no RPM
            setpoint (``setpoint_rpm_from_stem`` names the stem instead of
            silently dropping the recording).
    """
    directory = Path(data_dir)
    if not directory.is_dir():
        raise ValueError(f"not a directory: {directory}")
    paths: list[Path] = []
    for path in sorted(entry for entry in directory.iterdir() if entry.is_file()):
        try:
            head = path.read_bytes()[:128]
        except OSError:
            continue
        if sniff(head) is not None:
            paths.append(path)
    if not paths:
        raise ValueError(
            f"no artifact-model recordings found in {directory} (immediate files "
            "only; discovery is content-sniffed, so an unrecognized or "
            "subdirectory entry is skipped)"
        )

    results = collect_artifact_results(paths)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    plot_summary(results, output)
    return results


def main(
    data_dir: str | Path = "data/echo",
    output_dir: str | Path = "outputs",
) -> None:
    output = Path(output_dir)
    output.mkdir(exist_ok=True)

    # Parse each file once and reuse for both analysis and visualization.
    files = list_add_files(data_dir)
    datasets = {fp.stem: extract(fp) for fp in files}

    results = collect_results(datasets)

    print(f"{'Setpt':>5s}  {'Meas':>6s}  {'Freq':>7s}  {'Err%':>5s}  {'Samps':>6s}")
    print("-" * 33)
    for r in results:
        print(
            f"{r.setpoint_rpm:5d}  {r.measured_rpm:6.0f}  "
            f"{r.peak_freq_hz:7.2f}  {r.rel_error_pct:4.1f}%  {r.n_samples:6d}"
        )
    print("-" * 33)
    print(f"Mean error: {np.mean([r.rel_error_pct for r in results]):.1f}%")

    plot_summary(results, output / "summary.png")

    for d in datasets.values():
        plot_all(d, output_dir=output)

    print("\nDone \u2014 all visualizations in outputs/")
