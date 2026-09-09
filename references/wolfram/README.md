# Wolfram Reference Notebooks

Original Mathematica/Wolfram notebooks used as algorithm references for the
**UDV signal-processing** scope. Each notebook may have a binary `.nb` and/or a
portable `.txt` export of the same content. Functionality ported to Python
lives in `src/udv_echo_process/analysis/` — one module per feature.

> The optical/camera Wolfram sources (`Mixer_velocimetry.nb`,
> `TemporalProjections_v1.1.0.wl`) were moved to the sibling
> `python-image-processing-notebooks` repo alongside their ports — see that
> repo's `references/wolfram/`.

## Porting map

| Notebook | Python module | Status |
|----------|---------------|--------|
| `UDV_Data_Analysis_Echo.txt` / `.nb` | `analysis/rpm.py` (FFT peak /2 RPM) | Ported |
| `UDV_Data_Analysis_Echo.txt` / `.nb` | Total-variation filtering (`TotalVariationFilter`) → `process/filter.py` (`FilterSpec` + `filter`/`filter_sequence` — MEDIAN/MEAN/SAVGOL on scipy + TV via scikit-image `denoise_tv_chambolle`, not a line-port) | TV: Ported 2026-09-09 |
| `UDV_Data_Analysis_Echo.txt` / `.nb` | Peak detection (`PeakDetect`), image/histogram transforms, quantile regression (`QuantileRegression.m`) | Not yet ported |

## Workflow for porting a new notebook

1. Drop the notebook into this directory (both `.nb` and a `.txt` export if
   available).
2. Add a row to the porting-map table noting the date and owning analyst.
3. Create the corresponding module under `src/udv_echo_process/analysis/`
   (e.g. `analysis/tv_filter.py`, `analysis/peak_detect.py`) and re-export any
   public API from `analysis/__init__.py`.
4. Add tests under `tests/` and update this table's Status column to `Ported`.
