"""Generate visualizations and summary for all UDV measurement files."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from numpy.fft import rfft, rfftfreq

from parse_udv import list_add_files, extract
from viz_layer import plot_recording

DT_S = 0.0032
OUTPUT = Path("viz_output")
OUTPUT.mkdir(exist_ok=True)


def plot_summary(results, output_path):
    """Combined scatter plot: measured vs setpoint RPM with error panel."""
    setpoints = np.array([r[0] for r in results])
    measured = np.array([r[1] for r in results])
    errors = np.array([r[3] for r in results])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8),
                                    gridspec_kw={"height_ratios": [3, 1]},
                                    constrained_layout=True)

    ax1.plot(setpoints, setpoints, "k--", lw=1, alpha=0.5, label="Ideal")
    ax1.scatter(setpoints, measured, c="C0", s=40, zorder=3)
    for sp, m in zip(setpoints, measured):
        ax1.plot([sp, sp], [sp, m], "C0", lw=0.5, alpha=0.4)

    ax1.set_xlabel("Setpoint RPM")
    ax1.set_ylabel("Measured RPM")
    ax1.set_title("UDV RPM Measurement — FFT Peak /2 Method")
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    ax2.bar(range(len(errors)), errors, color="C1", width=0.6)
    ax2.set_xticks(range(len(errors)))
    ax2.set_xticklabels([str(r[0]) for r in results], fontsize=8)
    ax2.set_xlabel("Setpoint RPM")
    ax2.set_ylabel("Error [%]")
    ax2.set_title(f"Relative Error (mean: {errors.mean():.1f}%)")
    ax2.grid(True, alpha=0.3, axis="y")

    fig.savefig(output_path, dpi=150)
    print(f"Saved: {output_path}")
    plt.close(fig)


results = []
for fp in list_add_files():
    d = extract(fp)
    arr = np.array([f.values for f in d.frames])  # (T, G)
    T = arr.shape[0]
    freqs = rfftfreq(T, d=DT_S)
    # FFT per gate, average magnitude spectra across gates
    spec = np.abs(rfft(arr, axis=0)).mean(axis=1)
    peak_idx = np.argmax(spec[1:]) + 1
    f_peak = freqs[peak_idx]
    rpm = f_peak / 2 * 60
    setpoint = int(fp.stem)
    err = abs(rpm - setpoint) / setpoint * 100
    results.append((setpoint, rpm, f_peak, err, len(arr)))

results.sort()

print(f"{'Setpt':>5s}  {'Meas':>6s}  {'Freq':>7s}  {'Err%':>5s}  {'Samps':>6s}")
print("-" * 33)
for sp, rpm, f, err, n in results:
    print(f"{sp:5d}  {rpm:6.0f}  {f:7.2f}  {err:4.1f}%  {n:6d}")
print("-" * 33)
print(f"Mean error: {np.mean([r[3] for r in results]):.1f}%")

plot_summary(results, OUTPUT / "summary.png")

for fp in list_add_files():
    d = extract(fp)
    plot_recording(d, output_dir=OUTPUT)

print("\nDone — all visualizations in viz_output/")
