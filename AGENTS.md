# Agents

## Commands

```bash
uv run parse_udv.py <data-echo/*.ADD>    # parse & print data
uv run viz_udv.py <data-echo/*.ADD>      # single-file viz (3-panel)
uv run run_all.py                        # batch process all files
```

Python ≥3.14, managed by [uv](https://docs.astral.sh/uv/). No test runner configured yet.

## Conventions

- **Naming**: snake_case for modules, functions, variables. PascalCase for classes/ NamedTuples.
- **Typing**: use `from __future__ import annotations`, type hints on all public functions.
- **Format**: no formatter configured; match existing style (4-space indent, ~88 char lines).
- **Data**: `.ADD` files use TSV with comma as decimal separator (`parse_comma_decimal()`).

## Planned Architecture

- `parse_udv.py` — will be extended with multi-sensor `.ADD`/`.BDD` parser
- `viz_udv.py` — will get multi-sensor visualization functions
- New modules expected: `process_rolling.py`, `sensor_fusion.py`, `velocity.py`
- `data-echo-4-sensors-2x2/` — multi-sensor data (4 sensors, channels 6–9, rolling sequential recording)
