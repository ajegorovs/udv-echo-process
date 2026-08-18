# Agents

## Commands

```bash
uv run udv-inspect <file.ADD>               # inspect recording setup
uv run udv-viz [<file.ADD> ...]             # time-synced per-channel heatmaps
uv run udv-run-all                          # batch process echo data
uv run --extra dev pytest                    # run the test suite
uv run udv-inspect data/echo/650.ADD         # default when no file given
uv run python -c "from udv_echo_process import extract, plot_all; plot_all(extract('data/echo/650.ADD'))"
```

Python ≥3.14, managed by [uv](https://docs.astral.sh/uv/). Tests: pytest (dev extra, `uv run --extra dev pytest`).

## Conventions

- **Naming**: snake_case for modules, functions, variables. PascalCase for classes/ Pydantic models.
- **Typing**: use `from __future__ import annotations`, type hints on all public functions.
- **Format**: no formatter configured; match existing style (4-space indent, ~88 char lines).
- **Data**: `.ADD` files use TSV with comma as decimal separator (`parse_comma_decimal()`).
- **Models**: use Pydantic `BaseModel` for all data structures. Enum for fixed sets (`MeasType`).
- **Ported features**: one module per ported Wolfram feature under `udv_echo_process/analysis/`; map in `references/wolfram/README.md`.

## Architecture

```
src/udv_echo_process/
├── parser.py                        — unified parser (Pydantic models + auto-detect)
│   ├── MeasType (enum)              — ECHO | VELOCITY
│   ├── ChannelFrame (Pydantic)      — one measurement: channel, block, tbd_ms,
│   │                                  meas_type, gate_depths_mm, values,
│   │                                  n_profiles, std_dev, min_val, max_val
│   ├── ExtractedData (Pydantic)     — file_path, header, comment, frames[]
│   │                                  .by_channel() / .by_block() / .describe()
│   ├── extract(filepath)            — auto-detect: single-sensor vs multi-sensor,
│   │                                  echo vs velocity, raw vs stat
│   └── list_add_files(), load_all_data() — backward-compat helpers
│
├── viz.py                           — visualization layer
│   ├── plot_recording(d)            — per-channel heatmaps, synced time axis
│   │   ├── raw files: TBD/1000 → seconds
│   │   ├── stat files: block index → time
│   │   └── y-axis: gate depth, inverted (shallow at top)
│   ├── plot_channel_stats(d)        — gate depth vs mean±std across time
│   ├── plot_all(d)                  — heatmap + profiles in one call
│   ├── _channel_time_axis()         — returns (time_values, axis_label)
│   ├── _subplot_layout()            — figure grid layout helper
│   ├── _figure_for_channels()       — shared subplot-grid setup
│   ├── _output_path()               — outputs/<experiment>/<stem>/<name>
│   └── _discover_data_files()       — find valid .ADD files in data/* dirs
│
├── analysis/                        — one module per ported Wolfram feature
│   ├── rpm.py                       — RPM analysis
│   │   ├── RpmResult (dataclass)    — setpoint, measured rpm, freq, error, n
│   │   ├── rpm_from_echo(d, dt_s)   — FFT peak /2 estimate → (rpm, f_peak, n)
│   │   └── setpoint_rpm_from_stem() — parse setpoint RPM from filename stem
│   ├── temporal_projection.py       — chunked Min/Max/Mean/StdDev over frames
│   │   └── temporal_projections()   — Welford M2, streaming (get_chunk, n)
│   ├── image_projection.py          — run projections over an image sequence
│   │   ├── frame_paths() / select_frames() / project_images() / save_projections()
│   ├── mixer.py                     — optical mixer particle pipeline
│   │   ├── normalize()/tone_map()   — ImageAdjust / ColorToneMapping
│   │   ├── top_hat_enhanced()/particle_mask() — particle isolation
│   │   ├── largest_component_box()/scale_box()/crop_to_box()
│   │   └── deflicker()              — histogram-match to reference frame
│   └── feature_track.py             — Lucas-Kanade coarse motion
│       ├── track_grid_flow()        — grid seed points, drop untracked
│       └── plot_flow()              — quiver of displacement vectors
│
├── run_all.py                       — batch RPM extraction + viz per file
└── cli.py                           — udv-inspect / udv-viz / udv-run-all
                                      / udv-project / udv-mixvel

tests/                               — pytest suite (parser + analysis)
references/wolfram/                  — original Wolfram notebooks + porting map
data/<experiment>/                   — per-experiment .ADD/.BDD/notes (raw+stat mixed)
```

Detection logic:
- **Column header**: `Amp` → echo, `mm/s` → velocity
- **Gate Depth count**: 1 → single-sensor, >1 → multi-sensor
- **Post-header line**: starts with "Statistical" → stat format, otherwise raw

Output structure:
```
outputs/
  summary.png                         — cross-file RPM summary (udv-run-all)
  <experiment>/<stem>/
    heatmap.png                       — per-channel heatmaps
    profiles.png                      — mean ± std gate profiles
```
