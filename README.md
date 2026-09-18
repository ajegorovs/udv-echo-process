# UDV Echo Process

Multi-sensor Ultrasonic Doppler Velocimetry (UDV) processing for rotating machinery analysis. Supports **echo** (amplitude) and **velocity** measurements from single-sensor continuous recordings and multi-sensor rolling (round-robin) arrays, in both raw time-series and statistical-summary formats.

## Capabilities

- **Parse** any `.ADD` file — auto-detect single/multi-sensor, echo/velocity, raw/stat
- **Inspect** recording setup — channel count, gate depths, blocks, profiles, timing
- **Visualize** per-channel heatmaps with synchronized time axis + gate profile statistics
- **Analyze RPM** from single-sensor echo data via FFT (0.28% mean / 1.5% max
  error against the filename setpoint across the 19 committed echo recordings)
  — on the `.ADD` path (`rpm_from_echo`) and on the artifact model
  (`rpm_from_channel` → `EchoRpmEstimate`, plus a batch sweep)

### Supported Data

| Directory | Sensors | Type | Gates | Format |
|-----------|---------|------|-------|--------|
| `data/echo/` | Single (ch4) | Echo | 26 | Raw + Stat |
| `data/echo-4-sensors-2x2/` | 4 (ch6–9) | Echo | 35 | Stat |
| `data/4-sensor-velocity/` | 4 (ch6–9) | Velocity | 55 | Raw + Stat |

## Usage

```bash
uv run --extra dev pytest                   # run the test suite
uv run udv-inspect <file.ADD-or-BDD>        # inspect by recording content
uv run udv-viz <file.ADD>                   # heatmaps for one file
uv run udv-viz                              # heatmaps for all data/* experiments
uv run udv-run-all                          # batch echo RPM analysis + viz
uv run python examples/filter_echo_minimal.py  # echo → filter, 3 statements
```

Output goes to `outputs/<experiment>/<stem>/`:
- `heatmap.png` — per-channel time×gate heatmaps
- `profiles.png` — mean ± std signal across time per gate

The artifact-model echo RPM sweep is a Python entry point (no CLI yet), because
`udv-run-all` also writes the legacy heatmaps/profiles above:

```bash
uv run python -c "
from udv_echo_process.run_all import run_artifact_rpm_sweep
rows = run_artifact_rpm_sweep('data/echo', 'outputs/summary-artifact-rpm.png')
print(len(rows), rows[0].setpoint_rpm, round(rows[0].measured_rpm, 2))"
```

It loads each single-channel `.BDD` recording into an `ArtifactBundle`, estimates
one echo channel's RPM with the FFT peak /2 method, derives the commanded RPM
from the filename and plots setpoint vs recovered RPM. See
[`docs/architecture.md`](docs/architecture.md#echo-rpm-two-entry-points-one-kernel)
for the estimator's contract (full-span frequency calibration, the
quasi-uniformity guard, and why `/2` is rig-specific).

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

The package deliberately keeps two *analysis* pipelines separate, and carries a third path
that produces the recordings they read:

```text
.ADD: parser.extract() → ExtractedData → viz / RPM / CLI
.BDD: io.load() → ArtifactBundle → process transforms → provenance / storage
                        └→ select_channel(...) → analysis terminal results
                                                 (states, profiles, echo RPM)
acquire: plan/definition → (Windows-only driver) → stored .BDD + JSONL job log
                        └→ verify the point from its own decoded words
```

- The `.ADD` path is the established ASCII parser, visualization, and
  single-channel echo-RPM workflow.
- The `.BDD` path uses immutable domain models, owned read-only arrays,
  bundle-closed transforms, normalized provenance, and NPY + manifest storage.
- Both RPM entry points share one private FFT kernel, so the estimator cannot
  drift between the pipelines. There is still no `.ADD` → bundle adapter: the
  legacy `rpm_from_echo`/`udv-run-all` path and the artifact-model
  `rpm_from_channel`/`run_artifact_rpm_sweep` path are separate by design.
- The artifact-model implementation landed through Phase 9 but has two active
  provenance-identity acceptance fixes; see the rework plan §15 before treating
  it as complete.
- The acquisition path (`acquire/`, `uvd-acquire`, `tools/live/`) is the only
  platform-bound one: it drives the DOP3010's Windows application over Win32
  messages, so a gesture, a geometry or a painted caption can only be *verified*
  on a machine that runs that application. Everything else about it — planning,
  the cycle, verification, the log — runs and is tested anywhere.

For the package map, boundaries, public entry points, and testing workflow, see
[`docs/architecture.md`](docs/architecture.md). The precise artifact contracts
live in [`docs/signal-model-rework-plan.md`](docs/signal-model-rework-plan.md).
Working from a machine that cannot reach the instrument (a refactor on Linux,
say): start at [`docs/dev-handoff.md`](docs/dev-handoff.md).

## Project Structure

| File / Dir | Purpose |
|------------|---------|
| `src/udv_echo_process/` | Python package (parser, viz, analysis, acquire, CLI) |
| `examples/` | Runnable scripts on the public API (`filter_echo_minimal.py`, `campaign-single-channel.json`) |
| `tests/` | Pytest suite; `tests/data/` holds measured control-tree fixtures |
| `data/<experiment>/` | Raw UDV data per experiment (`.ADD`, `.BDD`, notes) |
| `references/wolfram/` | Original Wolfram notebooks + porting map |
| `tools/live/` | The interactive-session route for instrument probes (Windows-only) |
| `tools/ui/` | The committed UI crops, their index checker, and the magnify/glyph tool |
| `outputs/` | Generated plots, dispatch logs, captures (git-ignored) |
| `pyproject.toml` | Project config (Python ≥3.14, uv, Pydantic, console scripts) |

## Agent skills

Repo-local agent skills live in `.agents/skills/` — one Markdown `SKILL.md` per
skill. `udop-acquisition` is the one for the instrument: the Win32 driving craft,
the record/store cycle, the crops/vision route and the bring-up for a second
machine.

Hermes Agent does not auto-load skills from a cloned repo: a `SKILL.md` is a set
of instructions the agent follows, so it requires explicit opt-in. Once per repo,
per machine, from the repository root:

```bash
hermes skills trust "$(git rev-parse --show-toplevel)"
```

Pass the root explicitly: the no-argument form resolves the caller's cwd itself and
reports *"Not inside a git checkout"* even when it is run from inside this repository.
It takes effect in your **next** session; `hermes skills list` shows the loaded skills.

A project-local skill **wins** over a profile-global skill of the same name, so keep the
local names distinct (`udop-acquisition`, not `windows-gui-automation`) — a local copy that
falls behind the global one silently hides it.
