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
| `data/echo/` | Single (ch4) | Echo | 26 | Raw + Stat |
| `data/echo-4-sensors-2x2/` | 4 (ch6–9) | Echo | 35 | Stat |
| `data/4-sensor-velocity/` | 4 (ch6–9) | Velocity | 55 | Raw + Stat |

## Usage

```bash
uv run --extra dev pytest                   # run the test suite
uv run udv-inspect <file.ADD>               # inspect recording setup
uv run udv-viz <file.ADD>                   # heatmaps for one file
uv run udv-viz                              # heatmaps for all data/* experiments
uv run udv-run-all                          # batch echo RPM analysis + viz
```

Output goes to `outputs/<experiment>/<stem>/`:
- `heatmap.png` — per-channel time×gate heatmaps
- `profiles.png` — mean ± std signal across time per gate

## Optional live marimo co-work

The command-line UDV tools do not require marimo or MCP. To use the live
notebooks with the `marimo-inspect` MCP, opt in to the project's `marimo` extra:

```bash
uv sync --extra marimo --extra dev
```

This installs the pinned `marimo-inspect` release into this project's `.venv`.
Configure the chosen MCP harness to run that installed console script—not
`uv run` and not a sibling checkout:

```text
<project-root>/.venv/bin/marimo-inspect --transport stdio
```

Start a notebook with `--no-token`, open it in a browser to materialize a
session, then use `list_active_notebooks`. Before editing a live notebook, read
the server's packaged MCP resources; they are the workflow and safety authority.
The provider's [installation and harness guide](https://github.com/ajegorovs/marimo-mcp-cowork#install-and-connect-an-mcp-client)
covers bootstrap and harness-specific setup. A local editable provider override
is only for testing unreleased provider changes; ordinary users and consumer
contributors do not need it.

## Architecture

```
src/udv_echo_process/
├── parser.py        Unified parser (Pydantic). extract() → ExtractedData
│                    .by_channel(), .by_block(), .describe()
├── viz.py           plot_recording() — synchronized heatmaps
│                    plot_channel_stats() — gate profiles
│                    plot_all() — both in one call
├── analysis/        One module per ported Wolfram feature
│   └── rpm.py       rpm_from_echo() — FFT peak /2 RPM estimation
│                    RpmResult, setpoint_rpm_from_stem()
├── run_all.py       Batch RPM from echo data + viz per file
└── cli.py           Console entry points (udv-inspect / udv-viz / udv-run-all)

tests/               Pytest suite locking in parser / analysis behavior
references/wolfram/  Original Wolfram notebooks + porting map
```

## Project Structure

| File / Dir | Purpose |
|------------|---------|
| `src/udv_echo_process/` | Python package (parser, viz, analysis, CLI) |
| `tests/` | Pytest suite |
| `data/<experiment>/` | Raw UDV data per experiment (`.ADD`, `.BDD`, notes) |
| `references/wolfram/` | Original Wolfram notebooks + porting map |
| `outputs/` | Generated plots |
| `pyproject.toml` | Project config (Python ≥3.14, uv, Pydantic, console scripts) |
