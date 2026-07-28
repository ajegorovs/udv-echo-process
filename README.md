# UDV Echo Process

Multi-sensor Ultrasonic Doppler Velocimetry (UDV) processing for rotating machinery analysis. Supports **echo** (amplitude) and **velocity** measurements from single-sensor continuous recordings and multi-sensor rolling (round-robin) arrays, in both raw time-series and statistical-summary formats.

## Capabilities

- **Parse** any `.ADD` file — auto-detect single/multi-sensor, echo/velocity, raw/stat
- **Inspect** recording setup — channel count, gate depths, blocks, profiles, timing
- **Visualize** per-channel heatmaps with synchronized time axis + gate profile statistics
- **Analyze RPM** from single-sensor echo data via FFT (mean error 0.6%)

### Supported Data

| Directory | Sensors | Type | Gates | Format |
|-----------|---------|------|-------|--------|
| `data-echo/` | Single (ch4) | Echo | 26 | Raw + Stat |
| `data-echo-4-sensors-2x2/` | 4 (ch6–9) | Echo | 35 | Stat |
| `data-4-sensor-velocity/` | 4 (ch6–9) | Velocity | 55 | Raw + Stat |

## Usage

```bash
uv run viz_layer.py                          # process all data-* dirs
uv run viz_layer.py <file.ADD>               # single file
uv run run_all.py                             # batch echo RPM analysis + viz
uv run parse_udv.py <file.ADD>               # inspect recording setup
```

Output goes to `viz_output/<data_dir>/<stem>/`:
- `heatmap.png` — per-channel time×gate heatmaps
- `profiles.png` — mean ± std signal across time per gate

## Architecture

```
parse_udv.py       Unified parser (Pydantic). extract() → ExtractedData
                   .by_channel(), .by_block(), .describe()

viz_layer.py       plot_recording() — synchronized heatmaps
                   plot_channel_stats() — gate profiles
                   plot_all() — both in one call

run_all.py         Batch RPM from echo data + viz_layer per file
inspect_udv.py     Wrapper around extract().describe()
```

## Project Structure

| File / Dir | Purpose |
|------------|---------|
| `parse_udv.py` | Unified parser: `extract()`, `ExtractedData`, `ChannelFrame` |
| `viz_layer.py` | Visualization: heatmaps, gate profiles |
| `viz_udv.py` | Backward-compat wrapper |
| `inspect_udv.py` | Recording setup inspector |
| `run_all.py` | Batch RPM analysis + visualizations |
| `data-echo/` | Single-sensor echo (200–650 RPM) |
| `data-echo-4-sensors-2x2/` | 4-sensor echo array |
| `data-4-sensor-velocity/` | 4-sensor velocity profiles |
| `viz_output/` | Generated plots |
| `pyproject.toml` | Project config (Python ≥3.14, uv, Pydantic) |
