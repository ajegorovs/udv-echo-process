# UDV Echo Process

Rotational speed measurement from Ultrasonic Doppler Velocimetry (UDV) data using FFT-based frequency analysis.

## Data

`.ADD` files in `data-echo/` contain UDV measurements at various RPM setpoints (200–650 RPM). Each file is a tab-separated table with comma as decimal separator:

| Row | Content |
|-----|---------|
| 1 | Instrument header |
| 2 | Comment |
| 4 | `Gate Depth [mm]` |
| 5 | 26 gate depths (tab-separated, comma-decimal) |
| 6 | 26×`Amp` + `TBD [ms]` + `No block` + `Channel` |
| 7+ | Data rows (26 amplitude values + 3 aux columns) |

## Physical Principle

A rotating shaft with two shaft ends produces two UDV echoes per revolution. The time-domain signal at each gate depth shows two peaks per shaft rotation. The FFT of this signal therefore has its dominant peak at **2× the shaft frequency**.

**RPM = (FFT peak frequency / 2) × 60**

## Method

1. **Parse** the .ADD file — extract 26 gate amplitudes across all timesteps
2. **FFT per gate** — compute the magnitude spectrum for each of the 26 gates along the time axis (sampling interval 3.2 ms → 312.5 Hz)
3. **Average spectra** — average the magnitude spectra across all gates. The echo from each shaft end arrives at different gates at different times, but this time shift only affects FFT phase, not magnitude. Averaging across gates reinforces the common frequency while suppressing noise.
4. **Peak detection** — find the dominant frequency in the averaged spectrum
5. **Divide by 2** — each shaft rotation produces two echoes (two shaft ends), so the dominant FFT peak is at 2× the shaft frequency
6. **Convert to RPM**: multiply by 60

## Results

| Setpoint | Measured | Error |
|----------|----------|-------|
| 200 RPM | 202 RPM | 0.9% |
| 230 RPM | 230 RPM | 0.2% |
| 250 RPM | 250 RPM | 0.2% |
| 280 RPM | 279 RPM | 0.5% |
| 300 RPM | 299 RPM | 0.4% |
| 330 RPM | 329 RPM | 0.2% |
| 350 RPM | 348 RPM | 0.6% |
| 380 RPM | 378 RPM | 0.5% |
| 400 RPM | 397 RPM | 0.7% |
| 430 RPM | 428 RPM | 0.4% |
| 450 RPM | 447 RPM | 0.6% |
| 480 RPM | 474 RPM | 1.2% |
| 500 RPM | 496 RPM | 0.9% |
| 530 RPM | 526 RPM | 0.7% |
| 550 RPM | 547 RPM | 0.5% |
| 580 RPM | 576 RPM | 0.6% |
| 600 RPM | 595 RPM | 0.8% |
| 630 RPM | 626 RPM | 0.6% |
| 650 RPM | 646 RPM | 0.6% |

**Mean error across all 19 setpoints: 0.6%**, compared to the original Mathematica peak-detection approach which yielded ~43% error at 650 RPM.

## Usage

```bash
uv run run_all.py              # generate all visualizations
uv run viz_udv.py data-echo/650.ADD  # single file viz
uv run parse_udv.py data-echo/650.ADD  # print parsed data
```

Outputs are saved to `viz_output/`:

- `summary.png` — measured vs setpoint RPM scatter + error bar chart
- `{RPM}_viz.png` — per-file 3-panel view (time heatmap, FFT heatmap, mean FFT profile)

## Files

| File | Purpose |
|------|---------|
| `parse_udv.py` | Data import and parsing |
| `viz_udv.py` | Visualization (heatmaps, FFT, RPM annotation) |
| `run_all.py` | Batch processing and summary |
| `pyproject.toml` | Project config (Python ≥3.14, numpy, matplotlib) |
