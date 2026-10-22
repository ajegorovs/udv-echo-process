# SA2.3 — executed-notebook export evidence

**Generated — do not edit by hand.** Plan [`sa2-3-notebook-preview-plan.md`](sa2-3-notebook-preview-plan.md) §N and merge-gate item 4 require the executed notebook pass to be committed at a reviewable path outside the frozen `reports/` tree. This document is that captured execution report: every value in it was read out of a real `marimo export html --no-include-code` run of the committed notebook. No value is transcribed, paraphrased or invented.

- **Notebook under test:** `notebooks/signal_explorer.py` · sha256 `0ac62b690a239da9b5120c5c4097095b42a3cdf6444e51307f1db335c98c2fa5`
- **Generator:** `tools/notebook_evidence/sa23_export_evidence.py`
- **Write:** `.venv/Scripts/python.exe tools/notebook_evidence/sa23_export_evidence.py`
- **Verify:** `.venv/Scripts/python.exe tools/notebook_evidence/sa23_export_evidence.py --check` (exit 1 the moment this file and a fresh run disagree)
- **Generated with:** CPython `3.14.3` · marimo `0.24.0` · numpy `2.5.0`

## How the six exports are driven

A marimo widget's default cannot be set from outside the notebook, so each variant is the committed notebook text with a small set of **exact** string substitutions applied to the widget-default expressions. Every substitution's occurrence count is asserted before it is applied — a notebook that has moved fails loudly instead of silently rendering the default selection — and the variant is written to a throwaway directory. Each variant is then actually executed by

```text
python -m marimo export html --no-include-code <scratch>/variant_<slug>.py -o <scratch>/variant_<slug>.html -f
```

runs with the repository root as the working directory, so the committed recordings resolve exactly as they do for a normal export. Each export must carry **zero** `marimo-error` markers and **zero** `Traceback`; each rendered value below is asserted against the value the export actually carried. The exported HTML itself is never committed and never quoted here — only the values read out of it.

## Variants, and the export outcome

| variant | selection | substitutions applied | `marimo-error` | `Traceback` |
| --- | --- | --- | --- | --- |
| `default` | the notebook's own defaults — `sparse-mixer-live-2`, the plan's reference-condition job, the `primary-comparison` view, the middle supported gate, `mean` detrending | 0 | 0 | 0 |
| `full-record` | the same selection with the view control moved to `full-record` (plan §M) | 1 | 0 | 0 |
| `e128-primary` | the committed E128 real-data case — job `emissions-128`, point `e128`, `primary-comparison` view (plan §F/§K) | 2 | 0 | 0 |
| `e128-full-record` | the same E128 recording with the view control moved to `full-record` | 3 | 0 | 0 |
| `changed-gate` | the default selection with the gate control moved to the shallowest supported gate (§C/plan §K); the spectrum must name the gate it used | 1 | 0 | 0 |
| `changed-detrending` | the default selection with the detrending control moved to `mean+linear` (§C); the spectrum must name the detrending it used and report the removed trend | 1 | 0 | 0 |

## Rendered spectrum and axis values

Every cell is a value the export rendered: the header the readout states (point label, gate depth, view) and the axis quantities the PSD figure title states. The two `primary-comparison` / `full-record` pairs show N, span and Nyquist moving with the cut (plan §M); the E128 axes show the view's own Nyquist, below the 8.333 Hz rotor reference.

| variant | point | view | gate depth [mm] | N | span [s] | Nyquist [Hz] | detrending | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `default` | `cr1` | `primary-comparison` | `54.538` | `536` | `11.9804` | `22.3281` | `mean` | `defined` |
| `full-record` | `cr1` | `full-record` | `54.538` | `560` | `12.5179` | `22.3280` | `mean` | `defined` |
| `e128-primary` | `e128` | `primary-comparison` | `54.538` | `138` | `11.9455` | `5.7344` | `mean` | `defined` |
| `e128-full-record` | `e128` | `full-record` | `54.538` | `145` | `12.5559` | `5.7344` | `mean` | `defined` |
| `changed-gate` | `cr1` | `primary-comparison` | `10.138` | `536` | `11.9804` | `22.3281` | `mean` | `defined` |
| `changed-detrending` | `cr1` | `primary-comparison` | `54.538` | `536` | `11.9804` | `22.3281` | `mean+linear` | `defined` |

## Target support, and the markers actually drawn

The overall verdict of each probe row, and the caption's own list of the target markers the export drew inside the PSD axes (plan §G: a marker is drawn only where the backend's `TargetFrequencySupport.supported` is true). For E128 the 8.333 Hz reference is refused and its marker is absent; the export carries no vertical line for it.

| variant | 1 Hz row | 8.333 Hz row | markers drawn in the axes |
| --- | --- | --- | --- |
| `default` | `supported` | `supported` | `recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz` |
| `full-record` | `supported` | `supported` | `recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz` |
| `e128-primary` | `supported` | `unsupported` | `recurrence-1hz at 1 Hz` |
| `e128-full-record` | `supported` | `unsupported` | `recurrence-1hz at 1 Hz` |
| `changed-gate` | `supported` | `supported` | `recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz` |
| `changed-detrending` | `supported` | `supported` | `recurrence-1hz at 1 Hz, rotor-8.333hz at 8.33333 Hz` |

## Target reasons, quoted verbatim from the rendered export

The binding wording rule is that an unsupported target is a statement about the axis and the window, not about the flow (plan §F/§G). The reasons below are the export's own text, asserted character for character rather than paraphrased; the 8.333 Hz reason for E128 is the backend's `TargetFrequencySupport.band_reason`, and its Nyquist value is the view's own characterized value.

- **`default`**
  - `1 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 12's cell [0.95811, 1.04142] Hz`
  - `8.33333 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 100's cell [8.28974, 8.37305] Hz`
- **`full-record`**
  - `1 Hz is below this axis's Nyquist frequency 22.328 Hz and inside bin 13's cell [0.996787, 1.07653] Hz`
  - `8.33333 Hz is below this axis's Nyquist frequency 22.328 Hz and inside bin 105's cell [8.33314, 8.41288] Hz`
- **`e128-primary`**
  - `1 Hz is below this axis's Nyquist frequency 5.73438 Hz and inside bin 12's cell [0.955729, 1.03884] Hz`
  - `8.33333 Hz is at or above this axis's Nyquist frequency 5.73438 Hz: band-supported requires strictly below it`
- **`e128-full-record`**
  - `1 Hz is below this axis's Nyquist frequency 5.73436 Hz and inside bin 13's cell [0.988682, 1.06778] Hz`
  - `8.33333 Hz is at or above this axis's Nyquist frequency 5.73436 Hz: band-supported requires strictly below it`
- **`changed-gate`**
  - `1 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 12's cell [0.95811, 1.04142] Hz`
  - `8.33333 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 100's cell [8.28974, 8.37305] Hz`
- **`changed-detrending`**
  - `1 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 12's cell [0.95811, 1.04142] Hz`
  - `8.33333 Hz is below this axis's Nyquist frequency 22.3281 Hz and inside bin 100's cell [8.28974, 8.37305] Hz`

## Exact substitutions, per variant

The substitutions the generator asserts before applying them. A variant with no row list is the notebook's own unmodified default.

- **`default`** — no substitution (the committed default).
- **`full-record`**
  - ×1 `if view == VIEW_PRIMARY` → `if view == VIEW_FULL_RECORD`
- **`e128-primary`**
  - ×1 `record.condition == _reference` → `record.job == "emissions-128"`
  - ×1 `value=next(iter(_options)),` → `value=next(label for label in _options if label.startswith("e128")),`
- **`e128-full-record`**
  - ×1 `record.condition == _reference` → `record.job == "emissions-128"`
  - ×1 `value=next(iter(_options)),` → `value=next(label for label in _options if label.startswith("e128")),`
  - ×1 `if view == VIEW_PRIMARY` → `if view == VIEW_FULL_RECORD`
- **`changed-gate`**
  - ×1 `_default = len(_labels) // 2` → `_default = 0`
- **`changed-detrending`**
  - ×1 `if kind == Detrending.MEAN` → `if kind == Detrending.MEAN_AND_LINEAR`

## What the generator asserts

- Each variant's substitutions apply exactly the counted number of times, and change the text — a moved notebook is a failure, not a silent fall back to the default selection.
- `marimo export html --no-include-code` exits zero for every variant, and its exported HTML carries zero `marimo-error` markers and zero `Traceback`.
- Every rendered value in the tables above equals the value the export carried — point, view, gate depth, N, span, Nyquist, detrending, verdict, both target verdicts and the marker caption.
- Every target reason quoted above appears in the export verbatim.
- The 1 Hz marker is drawn in every variant; the 8.333 Hz marker is drawn only where the backend admits the target, and is **absent** from both E128 exports.
- `--check` re-runs all six exports and compares this file; any drift exits non-zero.

SA2.3 adds no new spectral estimator or scientific interpretation. This capture exposes already-reviewed backend results: `analysis.sparse_periodogram.periodogram_of_view` and `analysis.sparse_target_support.target_frequency_support`, both merged before this stage.
