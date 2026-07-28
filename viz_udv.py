"""Visualize UDV data: gate-depth-over-time heatmap and FFT frequency analysis."""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from matplotlib.ticker import MultipleLocator

from parse_udv import extract, list_add_files

# Interval between successive measurements in milliseconds
DT_MS = 3.2
DT_S = DT_MS / 1000  # 0.0032 s


def plot_data_heatmap(data, gate_depths, tbd_ms, title="UDV Amplitude", ax=None):
    """Plot gate depth vs time as a 2D heatmap."""
    if ax is None:
        ax = plt.gca()

    arr = np.array(data, dtype=float)  # shape (T, G)
    T, G = arr.shape

    # TBD column is cumulative time in ms; or use uniform grid
    if len(tbd_ms) == T:
        time_s = np.array(tbd_ms) / 1000
    else:
        time_s = np.arange(T) * DT_S

    extent = [time_s[0], time_s[-1], gate_depths[-1], gate_depths[0]]

    im = ax.imshow(
        arr.T,
        aspect="auto",
        extent=extent,
        interpolation="none",
        cmap="viridis",
        norm=Normalize(vmin=0, vmax=np.percentile(arr, 99)),
    )
    ax.set_xlabel("Time [s]")
    ax.set_ylabel("Gate Depth [mm]")
    ax.set_title(title)
    return im


def plot_fft_heatmap(data, gate_depths, title="UDV Frequency Spectrum", ax=None):
    """FFT along time axis and plot frequency vs gate depth heatmap."""
    if ax is None:
        ax = plt.gca()

    arr = np.array(data, dtype=float)  # (T, G)
    T, G = arr.shape

    freqs = np.fft.rfftfreq(T, d=DT_S)  # positive frequencies only
    spectrum = np.fft.rfft(arr, axis=0)  # (n_freqs, G)
    magnitude = np.abs(spectrum)

    extent = [freqs[0], freqs[-1], gate_depths[-1], gate_depths[0]]

    im = ax.imshow(
        magnitude,
        aspect="auto",
        extent=extent,
        interpolation="none",
        cmap="inferno",
        norm=Normalize(vmin=0, vmax=np.percentile(magnitude, 99)),
    )
    ax.set_xlabel("Frequency [Hz]")
    ax.set_ylabel("Gate Depth [mm]")
    ax.set_title(title)
    return im, freqs, magnitude


def compute_rpm_from_fft(data, dt_s=DT_S):
    """Compute RPM from FFT averaged across all gate spectra (/2 for two echoes/rev).

    Each gate sees the same periodic signal with a time shift (echo travels
    across depth axis). Time shift → phase shift in FFT, leaving magnitude
    unchanged. Averaging magnitude spectra across gates reinforces the
    common frequency content while suppressing gate-specific noise.
    """
    arr = np.array(data, dtype=float)  # (T, G)
    T = arr.shape[0]
    freqs = np.fft.rfftfreq(T, d=dt_s)
    # FFT per gate, average magnitude spectra
    spectra = np.abs(np.fft.rfft(arr, axis=0))  # (n_freqs, G)
    spec_mean = spectra.mean(axis=1)
    spec_std = spectra.std(axis=1)
    peak_idx = np.argmax(spec_mean[1:]) + 1
    f_peak = freqs[peak_idx]
    rpm = f_peak / 2 * 60
    return rpm, f_peak, freqs, spec_mean, spec_std


def plot_all_views(data_path: str | Path, output_dir: str | Path | None = None):
    """Generate heatmap, FFT heatmap, and sample gate profiles."""
    path = Path(data_path)
    d = extract(path)

    setpoint_rpm = int(path.stem)
    gate_depths = np.array(d.frames[0].gate_depths_mm)
    data = [f.values for f in d.frames]
    arr = np.array(data, dtype=float)
    T, G = arr.shape

    rpm_measured, f_peak, _, spec_mean, spec_std = compute_rpm_from_fft(data)
    error_pct = abs(rpm_measured - setpoint_rpm) / setpoint_rpm * 100

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), constrained_layout=True)

    summary = f"Setpoint: {setpoint_rpm} RPM  |  FFT: {f_peak:.2f} Hz  |  Measured: {rpm_measured:.0f} RPM  |  Error: {error_pct:.1f}%"

    tbd_ms = [f.tbd_ms for f in d.frames]

    # --- 1. Time-domain heatmap ---
    im1 = plot_data_heatmap(
        data, gate_depths, tbd_ms,
        title=summary,
        ax=axes[0],
    )
    fig.colorbar(im1, ax=axes[0], label="Amplitude")

    # --- 2. Frequency-domain heatmap ---
    im2, freqs, magnitude = plot_fft_heatmap(
        data, gate_depths,
        title=f"FFT Magnitude - {path.name}",
        ax=axes[1],
    )
    fig.colorbar(im2, ax=axes[1], label="|FFT|")
    secax1 = axes[1].secondary_xaxis("top", functions=(lambda hz: hz / 2 * 60, lambda rpm: rpm / 60 * 2))
    secax1.set_xlabel("Shaft RPM", fontsize=9)
    secax1.xaxis.set_minor_locator(MultipleLocator(100))
    axes[1].axvline(f_peak, color="cyan", ls="--", lw=1, alpha=0.6,
                    label=f"Peak: {f_peak:.2f} Hz ({rpm_measured:.0f} RPM)")
    axes[1].axvline(f_peak / 2, color="white", ls=":", lw=1, alpha=0.4,
                    label=f"Shaft: {f_peak/2:.2f} Hz ({setpoint_rpm} RPM setpoint)")
    axes[1].legend(fontsize=8, loc="upper right")

    # --- 3. FFT profile averaged across gates ---
    _, _, freqs_full, spec_mean, spec_std = compute_rpm_from_fft(data)
    axes[2].fill_between(freqs_full, spec_mean - spec_std, spec_mean + spec_std,
                         alpha=0.25, color="C0", label="\u00b11 std")
    axes[2].plot(freqs_full, spec_mean, color="black", lw=1, label="Mean")
    secax2 = axes[2].secondary_xaxis("top", functions=(lambda hz: hz / 2 * 60, lambda rpm: rpm / 60 * 2))
    secax2.set_xlabel("Shaft RPM", fontsize=9)
    secax2.xaxis.set_minor_locator(MultipleLocator(100))
    axes[2].axvline(f_peak, color="red", ls="--", lw=1, alpha=0.6,
                    label=f"Peak: {f_peak:.2f} Hz ({rpm_measured:.0f} RPM)")
    axes[2].axvline(f_peak / 2, color="gray", ls=":", lw=1, alpha=0.5,
                    label=f"Shaft freq: {f_peak/2:.2f} Hz")
    axes[2].set_xlabel("Frequency [Hz]")
    axes[2].set_ylabel("|FFT|")
    axes[2].set_title("Mean FFT Spectrum \u00b1 1 std across gates")
    axes[2].legend(fontsize=8)
    axes[2].set_xlim(0, 50)

    if output_dir:
        out_path = Path(output_dir) / f"{path.stem}_viz.png"
        fig.savefig(out_path, dpi=150)
        print(f"Saved: {out_path}  |  {summary}")

    return fig, (freqs, magnitude, gate_depths, rpm_measured)


if __name__ == "__main__":
    output_dir = "viz_output"
    Path(output_dir).mkdir(exist_ok=True)

    targets = sys.argv[1:] if len(sys.argv) > 1 else ["data-echo/650.ADD"]

    for t in targets:
        print(f"\n--- Processing {t} ---")
        plot_all_views(t, output_dir=output_dir)

    if not output_dir:
        plt.show()
