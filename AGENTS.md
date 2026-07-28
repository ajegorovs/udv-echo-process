# Agents

## Commands

```bash
uv run parse_udv.py <file.ADD>              # parse & describe
uv run viz_layer.py <file.ADD>              # time-synced per-channel heatmaps
uv run run_all.py                            # batch process all files
```

Python ≥3.14, managed by [uv](https://docs.astral.sh/uv/). No test runner configured yet.

## Conventions

- **Naming**: snake_case for modules, functions, variables. PascalCase for classes/ Pydantic models.
- **Typing**: use `from __future__ import annotations`, type hints on all public functions.
- **Format**: no formatter configured; match existing style (4-space indent, ~88 char lines).
- **Data**: `.ADD` files use TSV with comma as decimal separator (`parse_comma_decimal()`).
- **Models**: use Pydantic `BaseModel` for all data structures. Enum for fixed sets (`MeasType`).

## Architecture

```
parse_udv.py                        — unified parser (Pydantic models + auto-detect)
│
├── MeasType (enum)                 — ECHO | VELOCITY
├── ChannelFrame (Pydantic)         — one measurement: channel, block, tbd_ms,
│                                     meas_type, gate_depths_mm, values,
│                                     n_profiles, std_dev, min_val, max_val
├── ExtractedData (Pydantic)        — file_path, header, comment, frames[]
│                                    .by_channel() / .by_block() / .describe()
│
├── extract(filepath)               — auto-detect: single-sensor vs multi-sensor,
│                                     echo vs velocity, raw vs stat
│
└── list_add_files(), load_all_data() — backward-compat helpers
│
viz_layer.py                        — visualization layer
│
├── plot_recording(d)               — per-channel heatmaps, synced time axis
│   ├── raw files: TBD/1000 → seconds
│   ├── stat files: block index → time
│   └── y-axis: gate depth, inverted (shallow at top)
│
└── _channel_time_axis()            — returns (time_values, axis_label)

viz_udv.py                          — backward-compat wrapper (aliases plot_recording)
run_all.py                          — batch RPM extraction + viz_layer per file
```

Detection logic:
- **Column header**: `Amp` → echo, `mm/s` → velocity
- **Gate Depth count**: 1 → single-sensor, >1 → multi-sensor
- **Post-header line**: starts with "Statistical" → stat format, otherwise raw
