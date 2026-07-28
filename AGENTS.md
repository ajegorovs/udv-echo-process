# Agents

## Commands

```bash
uv run parse_udv.py <file.ADD>              # parse & print (old parser)
uv run viz_udv.py <data-echo/*.ADD>         # single-file 3-panel viz
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
parse_udv.py
├── parse_comma_decimal()           — low-level: convert "42,97" → 42.97
├── parse_add_file()                — old single-sensor parser (backward compat)
├── parse_stat_add_file()           — old stat-file parser
├── list_add_files(), load_all_data()
│
├── MeasType (enum)                 — ECHO | VELOCITY
├── ChannelFrame (Pydantic)         — one measurement at one time point for one channel
├── ExtractedData (Pydantic)        — unified result with .by_channel() / .by_block()
│
└── extract(filepath)               — unified entry point: auto-detects format
      ├── single-sensor continuous  — one "Gate Depth" section, continuous rows
      └── multi-sensor block-channel — repeating "Gate Depth" sections
            ├── raw format          — P data rows per (block, channel)
            └── stat format         — mean/stddev/min/max per (block, channel)
```

Detection logic:
- **Column header**: `Amp` → echo, `mm/s` → velocity
- **Gate Depth count**: 1 → single-sensor, >1 → multi-sensor
- **Post-header line**: starts with "Statistical" → stat format, otherwise raw

## Data Structure

```python
d = extract("path/to/file.ADD")
d.by_channel()  # {channel: [ChannelFrame, ...]}
d.by_block()    # {block: [ChannelFrame, ...]}

# Per frame:
f.channel, f.block, f.tbd_ms
f.gate_depths_mm  # list[float]
f.values           # list[float] — one per gate
# Stat-only:
f.n_profiles, f.std_dev, f.min_val, f.max_val
```

## Planned Modules

- `process_rolling.py` — rolling echo/velocity processing
- `sensor_fusion.py` — multi-sensor RPM fusion
- `velocity.py` — velocity profile analysis
