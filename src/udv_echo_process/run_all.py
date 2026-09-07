"""Generate visualizations and a summary for all UDV measurement files."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from udv_echo_process.analysis import (
    RpmResult,
    rpm_from_echo,
    setpoint_rpm_from_stem,
)
from udv_echo_process.parser import ExtractedData, extract, list_add_files
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
