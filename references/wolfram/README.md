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
| `UDV_Data_Analysis_Echo.txt` / `.nb` | `analysis/rpm.py` (FFT peak /2 RPM: legacy `rpm_from_echo` + artifact-model `rpm_from_channel` on one shared private kernel) | Ported; artifact-model entry point 2026-09-15 |
| `UDV_Data_Analysis_Echo.txt` / `.nb` | Total-variation filtering (`TotalVariationFilter`) → `process/filter.py` (`FilterSpec` + `filter`/`filter_sequence` — MEDIAN/MEAN/SAVGOL on scipy + TV via scikit-image `denoise_tv_chambolle`, not a line-port) | TV: Ported 2026-09-09 |
| `UDV_Data_Analysis_Echo.txt` / `.nb` | Peak detection (`PeakDetect`) and image/histogram transforms | Not yet ported |
| Absent Windows-local `QuantileRegression.m` import in `UDV_Data_Analysis_Echo` (same-campaign relative; not the direct predecessor) | `analysis/profiles.py` robust quantile-envelope profiles + private `analysis/_tv_l1.py` preprocessing | Absorbed from `udv-analysis`; immediate Python predecessor and dependency unrecoverable |

## Workflow for porting a new notebook

1. Drop the notebook into this directory (both `.nb` and a `.txt` export if
   available).
2. Add a row to the porting-map table noting the date and owning analyst.
3. Create the corresponding module under `src/udv_echo_process/analysis/`
   (e.g. `analysis/tv_filter.py`, `analysis/peak_detect.py`) and re-export any
   public API from `analysis/__init__.py`.
4. Add tests under `tests/` and update this table's Status column to `Ported`.

**Note on the echo-RPM entry:** the section labelled `Fourier` does not run an
FFT. Its cell total-variation filters the profile trace, peak-detects it and
computes (source spelling, verbatim)

```text
measuredRPM=(Total@signalRPMpeakMask/2)/(timeStepMiliseconds*(Length@signalRPMpeakMask-1)/1000/60)
```

— a whole-recording peak *count* divided by the duration, with the step passed as
the literal constant `3.2` ms. The ported estimator is instead the FFT peak /2
method the later Python workflow uses (gate-averaged unnormalised magnitude
spectrum, DC excluded), which also settles the timebase question in the other
direction: on a quantized 3.1/3.2 ms axis the effective interval is 3.182 ms, not
the 3.2 ms median quantum. The peak-count method remains unported (see the
`PeakDetect` row above).
