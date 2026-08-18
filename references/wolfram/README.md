# Wolfram Reference Notebooks

Original Mathematica/Wolfram notebooks used as algorithm references. Each
notebook may have a binary `.nb` and/or a portable `.txt` export of the same
content. Functionality ported to Python lives in `src/udv_echo_process/analysis/`
— one module per feature.

## Porting map

| Notebook | Python module | Status |
|----------|---------------|--------|
| `UDV_Data_Analysis_Echo.txt` / `.nb` | `analysis/rpm.py` (FFT peak /2 RPM) | Ported |
| `UDV_Data_Analysis_Echo.txt` / `.nb` | Total-variation filtering (`TotalVariationFilter`), peak detection (`PeakDetect`), image/histogram transforms, quantile regression (`QuantileRegression.m`) | Not yet ported |
| `TemporalProjections_v1.1.0.wl` | `analysis/temporal_projection.py` (chunk-wise Min/Max/Mean/StdDev) | Ported |
| `Mixer_velocimetry.nb` | `analysis/mixer.py` (ROI crop, particle segmentation/enhancement, histogram-match de-flicker), `analysis/feature_track.py` (Lucas-Kanade coarse motion + flow plot), `analysis/image_projection.py` (temporal projection over the sequence) | Ported |

## Workflow for porting a new notebook

1. Drop the notebook into this directory (both `.nb` and a `.txt` export if
   available).
2. Add a row to the porting-map table noting the date and owning analyst.
3. Create the corresponding module under `src/udv_echo_process/analysis/`
   (e.g. `analysis/tv_filter.py`, `analysis/peak_detect.py`) and re-export any
   public API from `analysis/__init__.py`.
4. Add tests under `tests/` and update this table's Status column to `Ported`.
