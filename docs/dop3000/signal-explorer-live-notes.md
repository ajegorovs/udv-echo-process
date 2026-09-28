# `signal_explorer.py` — live iteration notes

The running note for the single-measurement explorer. It records what the notebook exposes,
which tested backend each number comes from, what was actually driven **in a live session**,
what the reader asked for, and what the next proposed section is. The notebook is the
deliverable; this file is its change log and its live-test record.

It exists because the committed executed-export evidence
([`sa2-3-notebook-preview-evidence.md`](sa2-3-notebook-preview-evidence.md)) proves *static*
behaviour only: an export runs every cell once from a fixed widget default, so it can never
show whether a control change propagates to its consumers, and it cannot show stale state.
§SA4 of [`sparse-signal-analysis-plan.md`](sparse-signal-analysis-plan.md) recorded live
widget read-back as the remaining acceptance gap; §2 below discharges it.

## 1. Launching it

```bash
uv sync --extra marimo --extra dev
.venv/Scripts/marimo edit --no-token notebooks/signal_explorer.py   # POSIX: .venv/bin/marimo
```

The server keeps marimo's default host binding (`127.0.0.1`), so the notebook is reachable
from this machine only — `--no-token` is safe at that binding and is what makes the URL
directly openable. Nothing here needs the `--headless` server, a browser-automation harness
or the MCP provider.

## 2. Live-session record — 2026-09-28

**Method.** A `marimo edit --headless` server on `127.0.0.1`; a browser attached to that page
over its own DevTools protocol; the notebook allowed to finish running (every cell run,
`needs-run` count 0, error count 0). Each control was then driven by dispatching a native
`change` event on the widget's own `<select>`/`<input>` inside its shadow root, and after each
change the *dependent* displays were read back as text: the heatmap caption, the per-gate
distribution caption, the recurrence caption, the spectrum caption, the target-support table,
the stale-gate callout — plus the notebook's error and stale-cell counts.

Widgets are read and driven through the marimo UI surface, not through `marimo-inspect`:
the configured MCP entry currently cannot start in this checkout, so the provider was not
available for this session (recorded as an open item in [`../agenda.md`](../agenda.md)
§ Marimo consumer follow-ups).

**Baseline selected state.** Pass `sparse-mixer-live-2` / job `common-reference-1` /
recording `cr1` (`sparse3-common-reference-1-cr1-20260924T172037`) / channel `ch1`, view
`primary-comparison`, detrending `mean`, gate depth `54.538 mm` (supported gate 25 of 49).

### 2.1 Transitions that were driven, and what moved

| # | control changed | before → after | dependent read-back |
|---|---|---|---|
| 1 | Sparse pass | `sparse-mixer-live-2` → `stage2-e20-e64` | recording/heatmap/spectrum all switch to `stage2-e20-a-ref`; N 536, span 11.9803 s, Nyquist 22.3283 Hz, **50** supported of 50 native gates, gate re-read `56.388 mm` |
| 2 | Sparse pass | back to `sparse-mixer-live-2` | every value returns to the baseline row above (536 / 11.9804 s / 22.3281 Hz / 49 of 50) |
| 3 | Job | `common-reference-1` → `emissions-128` | recording list narrows to `e128`; N 536 → 138, span 11.9804 s → 11.9455 s, **Nyquist 22.3281 → 5.7344 Hz** |
| 4 | Recording | `cr1` → `e128` within a pass | heatmap caption, gate statistics, recurrence and spectrum all re-key to the new stem |
| 5 | SA1 view | `primary-comparison` → `full-record` | N 536 → 560, span 11.9804 → 12.5179 s, Δf 0.0833 → 0.0797 Hz, rotor marker bin 100 → 105 (8.33139 → 8.37301 Hz, offset +0.0233 → −0.4976 bins) |
| 6 | SA1 view | back to `primary-comparison` | all five read-backs return to the baseline row exactly (stale-state check) |
| 7 | Gate (SA1) | gate 25 → gate 40 (`54.538` → `82.288 mm`) | distribution, recurrence, raw trace, spectrum and the target table all re-key to `82.288 mm` (spectrum notes "view column 39"); 1 Hz marker moves to bin 12 |
| 8 | Detrending | `mean` → `mean+linear` → `mean` | the spectrum caption's `detrending` field follows; the PSD redraws; returning to `mean` restores the baseline curve |
| 9 | SA1 exploration bounds | depth low `60`, high `70` (while the view is `exploration`) | the supported-gate list narrows and the resolved gate becomes the middle of the *narrowed* list: bounds `60+` → `80.438 mm`, then `60–70` → `65.638 mm` |
| 10 | SA1 view | `primary-comparison` → `exploration` with a gate remembered outside the narrowed band | the gate falls back to that view's middle (`65.638 mm`) **and the callout says so**: *"the gate you last selected (depth 82.288 mm) is not a supported gate of this view, which has 6 supported gate(s) from 60.088 to 69.338 mm: the middle supported gate (depth 65.638 mm) is shown"* |
| 11 | SA1 view | back to `primary-comparison` | the remembered `82.288 mm` is restored and the callout clears |
| 12 | SA2.3 PSD display zoom | `1` → `2` | the spectrum's x-range halves; the estimate, its verdict and the target table are unchanged (a display control, not an estimator input) |
| 13 | Target support under low Nyquist | see below | the `rotor-8.333hz` target is **refused** whenever the selected view's Nyquist is below it |

Every transition above kept the notebook at `needs-run 0` / `errors 0`, and each change was
driven back to its previous value to catch stale reactive state.

### 2.2 The Nyquist refusal, live

With the `emissions-128` pass selected the view's Nyquist is `5.7344 Hz`. The spectral cell
keeps its `rotor-8.333hz` row in the target table with `analysis-supported False` and renders
**no marker** at 8.333 Hz; the refusal is stated rather than drawn as a zero or a flat line.
Switching back to `sparse-mixer-live-2` (Nyquist 22.3281 Hz) restores the supported row and
the marker. This is the case the exported variant "E128 primary" pinned statically, confirmed
here as a live transition rather than a single default render.

### 2.3 Defect found and fixed (the one live-only defect)

**Symptom.** Changing the SA1 view silently reset the gate picker to the *middle* supported
gate of the new view. Reproduced live: gate 40 (`82.288 mm`) selected, view switched
`primary-comparison` → `full-record`, and the distribution, recurrence, spectrum and marker
set all silently moved to `54.538 mm`. The notebook's own stale-gate guard — the callout that
exists to say "your gate is not in this view" — never fired, because the picker had already
been overwritten by the new view's declared default before the guard could see a difference.

**Cause.** The gate control's declared value was recomputed from the current view's option
list on every view change, so the view change itself overwrote the reader's choice. The
documented guard was unreachable.

**Fix (presentation-only, no estimator touched).** The picker cell was split into a
presentation-only memory of the reader's chosen depth (`gate_selection_memory`) and the picker
itself, whose declared value is now the reader's remembered depth when the new view still
carries it and the middle supported gate only otherwise. The guard cell now receives the
remembered depth and fires the callout when the new view drops it.

**Verified live after the fix, in a freshly started session.**

- Gate 40 (`82.288 mm`) → view `full-record`: the gate stays `82.288 mm` (previously it
  became `54.538 mm`) across the heatmap, distribution, recurrence, spectrum and markers;
  back to `primary-comparison`: still `82.288 mm`, no callout, every value coherent (§2.1
  rows 5–6).
- A gate chosen in one view survives into a *different* view that still carries that depth:
  exploration gate 6 (`69.338 mm`) → `primary-comparison` resolves to `69.338 mm` (supported
  gate 33 of 49), not that view's middle.
- When a view change *drops* the remembered depth the fallback is stated, not silent: with
  `82.288 mm` remembered and the exploration view narrowed to 60.088–69.338 mm, the resolved
  gate is that view's middle (`65.638 mm`) and the callout reads *"the gate you last selected
  (depth 82.288 mm) is not a supported gate of this view, which has 6 supported gate(s) from
  60.088 to 69.338 mm: the middle supported gate (depth 65.638 mm) is shown"*; returning to
  `primary-comparison` restores `82.288 mm` and clears the callout (round-tripped twice,
  §2.1 rows 10–11).

One correction is worth recording, because it decided how this notebook gets verified from
now on. An earlier pass over the same transitions read the callout as *absent* in a session
that had been live-edited mid-run (the notebook file was patched under the running session),
while the identical transitions render it in a session started against the final file.
Read-backs for this notebook are therefore taken from a session started fresh against the
file being reviewed, never from one that has had the file reloaded underneath it.

**Consequence for the committed evidence.** The executed-export capture
(`tools/notebook_evidence/sa23_export_evidence.py`) anchors its "changed gate" variant on the
exact expression that changed, so its anchor and the regenerated
[`sa2-3-notebook-preview-evidence.md`](sa2-3-notebook-preview-evidence.md) moved with the
notebook — as that tool is designed to force.

### 2.4 What was *not* automated

- **The plots' pixels.** Read-back is text (captions, table rows, verdicts), not a pixel
  comparison: it proves the right number reached the right figure title/label chain, not that
  a curve is visually correct. The exported variants remain the visual record.
- **The widget's own displayed text is not a read-back.** After a re-instantiation the
  `<select>` can show an option the backend is not using — observed displaying the *first*
  option while the resolved gate was the sixth — so every claim above is taken from what the
  backend produced (captions, table rows, figure trace names) and the control's text is used
  only to confirm that the option list itself changed.
- **Hover/brush interactions** (`TraceScrubber`, marimo's own plot toolbar, the heatmap
  tooltip) — not driven; they are marimo's, not this notebook's.
- **The sidebar twin** (`channel_preview_sidebar.py`) — a different notebook, untouched.

## 3. What the notebook exposes today

One measurement at a time; every number comes from a tested module under
`src/udv_echo_process/`, and no cell computes an estimator of its own.

| Section | Backend it displays | Controls |
|---|---|---|
| Measurement / provenance | `analysis.sparse_passes` (committed-pass catalogue), `analysis.sparse_pass` | dataset (pass), job, recording, channel |
| Decoded acquisition + QC | decoded `AcquisitionMode`, support/quality fields of the pass | — |
| Native time–depth heatmap | the selected `WindowView` (columns = gates, rows = profiles) | SA1 view, exploration depth bounds |
| Gate selection | `analysis.sparse_gate_stats` (supported-gate list) | gate picker + remembered depth, stale-gate callout |
| Per-gate statistics / profiles | `analysis.sparse_gate_stats` | view, gate |
| Representative traces and time slices | `analysis.sparse_gate_stats`, the view's own samples | view, gate |
| Distribution | `analysis.sparse_gate_stats` | view, gate |
| Recurrence / autocorrelation | `analysis.sparse_recurrence` | view, gate, detrending |
| Periodogram / PSD | `analysis.sparse_periodogram.periodogram_of_view` (+ SA2.2 admission/verdict) | view, gate, detrending, display zoom |
| Target support / refusal | `analysis.sparse_spectral_capability`, `analysis.sparse_target_support` | follows the view's Nyquist |

## 4. Iteration checklist

One row per review cycle. Only the last column is a proposal — nothing below it is built
until the reader asks for it.

| # | Section | Backend | Controls | Live test performed | Reader feedback | Adjustment | Next proposed |
|---|---|---|---|---|---|---|---|
| 0 | live baseline (as committed) | — | all six dropdowns + five numbers | §2: 13 transitions, driven and read back both ways; one live-only defect found and fixed (the gate reverted to the view's middle, and its own guard never fired) | *pending — baseline handed over for review* | gate memory + reachable callout (§2.3) | *pending reader steer* |

## 5. Candidates for the next sections

Classified by what actually exists, because a new estimator is a separate backend decision
with its own tests — not a notebook cell:

1. **Implemented and tested, already displayed** — `sparse_gate_stats`,
   `sparse_recurrence`, `sparse_periodogram`, `sparse_spectral_capability`,
   `sparse_target_support`. Nothing to add; only presentation can change.
2. **Implemented and tested, not yet exposed interactively** — `rpm_from_channel` /
   `rpm_from_echo` (an echo-RPM estimate per recording/gate, currently batch-only) and the
   deterministic scalar report in `analysis.sparse_signal_report`, whose
   `low_frequency_power_fraction` is the SA2 fixed-band metric the explorer does not yet
   show.
3. **Not implemented (a backend decision, not a notebook change)** — spectrogram/STFT,
   spatial/depth correlation, POD/SVD, filtering/TV denoising. Each needs its own design and
   tests before any cell may call it.
