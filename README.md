# UDV Echo Process

Multi-sensor Ultrasonic Doppler Velocimetry (UDV) processing for rotating machinery analysis. Currently supports single-sensor echo-based RPM measurement, with planned support for multi-sensor rolling echo and velocity processing.

---

## Single-Sensor Echo RPM Analysis

Rotational speed measurement from UDV echo data using FFT-based frequency analysis. A rotating shaft with two ends produces two UDV echoes per revolution, so the dominant FFT peak is at **2× the shaft frequency**:

**RPM = (FFT peak frequency / 2) × 60**

### Data

`.ADD` files in `data-echo/` contain UDV measurements at various RPM setpoints (200–650 RPM). Each file is a tab-separated table with comma as decimal separator:

### Method

1. **Parse** the `.ADD` file — extract 26 gate amplitudes across all timesteps
2. **FFT per gate** — compute the magnitude spectrum for each gate along the time axis (sampling interval 3.2 ms → 312.5 Hz)
3. **Average spectra** — average magnitude spectra across all gates (time shift per gate = phase shift only, magnitude is unchanged)
4. **Peak detection** — find the dominant frequency in the averaged spectrum
5. **Divide by 2** — each shaft rotation produces two echoes, so FFT peak is at 2× shaft frequency
6. **Convert to RPM** — multiply by 60

### Results

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

**Mean error: 0.6%** (vs ~43% for the original Mathematica peak-detection approach).

### Usage

```bash
uv run run_all.py                              # batch process all files
uv run viz_udv.py data-echo/650.ADD            # single file viz
uv run parse_udv.py data-echo/650.ADD          # print parsed data
```

Outputs go to `viz_output/`:
- `summary.png` — scatter + error bar chart
- `{RPM}_viz.png` — 3-panel view (time heatmap, FFT heatmap, mean FFT profile)

---

## Multi-Sensor Rolling Processing (In Development)

Extension to process data from a **4-sensor 2×2 array** with sequentially (rolling) recorded channels.

### Hardware Configuration

- 4 UDV sensors arranged in a 2×2 grid, 20 mm center-to-center
- Sensors connected to instrument channels 6, 7, 8, 9
- Sensor bottom 3 mm from vessel bottom, sensor diameter 8 mm
- Pointed at mixer pillar

### Recording Scheme

The instrument records channels **sequentially** (round-robin, not simultaneously):
- Each channel records **P = 10 profiles** per acquisition burst
- Profiles are reduced to one gate signal + per-gate statistics (mean, std dev, min, max)
- The cycle repeats over **B blocks** → produces a rolling time series across all sensor channels

### Data Format (Multi-Sensor `.ADD`)

Files in `data-echo-4-sensors-2x2/` have a different structure from single-sensor files:
- **35 gates** per channel (vs 26 for single-sensor)
- Repeated per-(Block, Channel) sections, each containing:
  - Gate depth definition
  - Statistical summary: mean, std deviation, min, max (over P=10 profiles)
- Raw time-series may be in companion `.BDD` files (TBD)

### Planned Processing Pipeline

1. **Parse multi-sensor `.ADD`/`.BDD`** — extract per-channel, per-block statistical profiles
2. **Reconstruct rolling time series** — interleave channel data in recording order
3. **Per-channel FFT** — compute echo-based RPM for each sensor independently
4. **Multi-sensor fusion** — combine estimates across sensors for improved accuracy/reliability
5. **Velocity processing** — extend from echo-based RPM to full velocity profile analysis per sensor

---

## Project Structure

| File / Dir | Purpose |
|------------|---------|
| `parse_udv.py` | Data import and parsing (single-sensor `.ADD`) |
| `viz_udv.py` | Visualization (heatmaps, FFT, RPM annotation) |
| `run_all.py` | Batch processing and summary generation |
| `data-echo/` | Single-sensor measurement files (200–650 RPM) |
| `data-echo-4-sensors-2x2/` | Multi-sensor 2×2 array recordings |
| `viz_output/` | Generated visualizations |
| `UDV_Data_Analysis_Echo.nb` | Original Mathematica notebook |
| `pyproject.toml` | Project config (Python ≥3.14, uv) |
