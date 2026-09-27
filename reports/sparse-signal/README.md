# SA2.4 - committed-data spectral characterization (scalar report)

The scalar characterization of the committed sparse recordings, per `recording x view x supported gate`. It publishes named scalar reductions of an already-published density and the scalar metadata needed to interpret them; no density array, no whole estimate and no field that follows a bin is published here.

## Files

- `sa2-4-spectral-characterization.csv` - one row per `cell x supported gate` (plan §5): identity, the settings, the axis numbers, the gate's band-fraction numbers and the QA field. This table is the **sole per-gate record**; the document beside it does not repeat these rows.
- `sa2-4-spectral-characterization.json` - the gate (`ok`, `checks`), the plan fingerprints and the analysis revision, the prespecified constants, one record per cell with its two probe target rows stated once, the estimator's and taper's definitions, the admission's reason, the descriptive plan §4 repeat-spread row set (its rule, groups, rows and counts), and a summary of counts. The document carries **no per-gate rows**: those are the table's, published once in the CSV, so the same 5720 rows are never serialized twice.
- `README.md` - this file.

## The published quantity, defined

- **`band_fraction`** - the low-frequency band power fraction `Phi = B / T` at a closed `[0, 1] Hz` band, where `B = sum_k w_k * psd[k] * delta_f` and `w_k = clip(length(cell_k intersect [0, low_band_hz]) / length(cell_k), 0, 1)` is the overlap *fraction of the bin's own cell*, on the repository's one one-sided frequency grid and its one cell rule. `T` is the estimate's own `integrated_psd_power`, which equals the window-normalized mean-square power: the denominator is **read**, never recomputed. `Phi` is dimensionless in `[0, 1]`; a percentage is display only. The reduction is read on the repository's one **discrete** one-sided grid as this cell-overlap weighted sum - a step-function power on the fixed grid - and is **never a continuous-band integral** (plan §6).
- The band edge `low_band_hz = 1 Hz` is the design's declared recurrence scale and probe target, not a located spectral feature. A different band is a different prespecified band in a new labelled table. A cell edge exactly on the band edge adds zero length, so the closed/open question changes no value.
- **`band_state`** - the three states never conflated: `defined` carries `B / T`; `defined-zero-power` is a measured zero total (a constant gate) whose ratio is `0/0` and therefore undefined, carried as `band_power == 0.0`; `refused-axis` was **not measured** and carries no fraction, no band power and no total.
- **`band_power`**, **`total_power`** - in `(mm/s)^2`; `band_power <= total_power` and the fraction is the ratio of the two numbers printed beside it.
- **`parseval_relative_error`** - a QA field: the relative difference between the integrated density and the window-normalized power, an implementation invariant of the one-sided fold at floating-point accuracy. It is not a measure of timestamp irregularity, and it is not compared across jobs.
- **the axis fields** - `profiles`, `span_s`, `dt_eff_s`, `effective_sample_rate_hz`, `nyquist_hz`, `delta_f_hz`, `duration_resolution_scale_hz`, `max_relative_timing_error`, `max_timing_error_s`, `max_relative_interval_deviation`, `largest_gap_ratio`, `spectral_uniformity_tol` and `admitted` are read from the estimate's own admission and its characterization; `delta_f_hz` is the bin spacing `fs_eff / N` and is **not** `1 / span`, which is `duration_resolution_scale_hz`. The admission's own reason is stated once per cell in the document, not repeated on every gate row.
- **the probe target rows** (JSON only, once per cell) - the 1 Hz recurrence scale and the 8.333 Hz rotor reference, each with `band_supported` (the Nyquist and cell answer) and `analysis_supported` (the estimator answer) stated separately, their reasons, the nearest bin, the bin offset and the evaluated cell edges.
- **`repeat_spread`** (JSON only, plan §4) - the within-sitting repeat spread, published as its own row set. A group is every recording of one pass acquired under one whole condition on one window, keyed by `(pass, kind, condition, resolution_mm, window_gates)` with the condition the job's run-wide `(burst_length, emissions_per_profile, prf_us)` triple; the four acquisition fields are forwarded by the capability sweep (`committed_window_views`), so a group is one condition rather than an average over several. Per group, view and native gate the row states every member cell's own `band_fraction` (`null` where it is undefined - a refused axis or a `0/0` ratio, never a measured zero), the count `n` of members whose fraction is defined there, and the descriptive `min`, `max` and `range` of those values. A recording whose condition was acquired once has no repeat and is excluded (the `cc1/cc2/cc3/cc4` contrasts); `repeat_spread_summary` states 12 group(s) over 44 recording(s) / 88 cell(s) and 8 singleton recording(s) / 16 cell(s) excluded. **Descriptive only**: this is not a screening floor, not a resolvability threshold, no condition or sitting is ranked, and no effect is labelled.

## Field glossary (the closed schema)

Every field the CSV and the JSON publish is named below: the field set is **closed**, so a new field is a schema change rather than a new value (plan §6). Every entry is a scalar of the observation unit - a column of the table or a named scalar in the document - and none follows a bin, a sample or an element. In the document `cells[*]` is one `recording x view`; its per-gate band-fraction rows are the table's, keyed by `pass`/`relative_path`/`view`/`gate_index`, and are **not** duplicated in the document.

- **per gate (one CSV row - the sole per-gate record)** - `gate_index`, `depth_mm`, `verdict`, `band_state`, `band_fraction`, `band_power`, `total_power`, `parseval_relative_error`, `enbw_bins`, `enbw_hz`.
- **cell provenance and settings (`cells[*]`)** - `pass`, `plan_fingerprint`, `job`, `point_label`, `order`, `relative_path`, `source_sha256`, `view`, `view_rule`, `quantity`, `unit`, `psd_unit`, `detrending`, `low_band_hz`, `estimator_name`, `taper_name`, `taper_convention`, `normalization_rule`, `one_sided_rule`.
- **cell window extent and acquisition condition (`cells[*]`)** - `profiles`, `native_gates`, `supported_gates`, `native_depth_extent_mm`, `pass_support_mm`, `participating_depth_extent_mm`, `window_s`, `declared_window_s`, and the condition the §4 grouping reads: `kind`, `condition.burst_length`, `condition.emissions_per_profile`, `condition.prf_us`, `resolution_mm` and `window_gates`. `window_gates` is the planned native gate count of the window - the window's own dimension - and is deliberately not the cell's `gates` row count.
- **axis (`cells[*].axis`, JSON only)** - `profiles`, `span_s`, `dt_eff_s`, `effective_sample_rate_hz`, `nyquist_hz`, `delta_f_hz`, `duration_resolution_scale_hz`, `max_relative_timing_error`, `max_timing_error_s`, `max_relative_interval_deviation`, `largest_gap_ratio`, `spectral_uniformity_tol`, `min_samples`, `admitted`, `admission_reason`, `estimator`. `min_samples` is the admission's own sample floor - the minimum profile count the axis is admitted at - quoted as metadata and read, never recomputed.
- **probe target (`cells[*].targets[*]`, JSON only)** - `target_label`, `target_hz`, `band_supported`, `analysis_supported`, `supported`, `reason`, `band_reason`, `analysis_reason`, `nyquist_hz`, `frequency_resolution_hz`, `duration_resolution_scale_hz`, `cycles_in_view`, `nyquist_represented`, `prospective_bin`, `prospective_bin_hz`, `bin_offset_hz`, `bin_offset_bins`, `cell_low_hz`, `cell_high_hz`, `resolution_bins_to_target`, `actual_span_s`.
- **plan §4 repeat row set (JSON only)** - `repeat_spread_rule`, `repeat_condition_key`, `repeat_groups`, `repeat_spread`, `repeat_spread_summary`; each group and row is keyed by `(pass, kind, condition, resolution_mm, window_gates)` and its remaining fields are the ones named above (`members`, `n_recordings`, `n_cells`; `view`, `gate_index`, `depth_mm`, `members`, `n`, `min`, `max`, `range`).

## Settings every number was computed under

- views: `primary-comparison, full-record` (the primary comparison and the full record)
- detrending: `mean` on both views
- estimator: `admitted uniform-grid periodogram: the real one-sided rFFT of the tapered, detrended trace, whose sampling coordinates are the adopted uniform grid (dt_eff = span / (N - 1)) that the admission admitted the stored stamps under, evaluated at the SA2.1 grid's own bin frequencies f_k = k * fs_eff / N`, taper `hann`, convention: periodic: w[n] = 0.5 - 0.5 * cos(2 * pi * n / N) for n = 0 .. N - 1, the endpoint not repeated; the symmetric convention w[n] = 0.5 - 0.5 * cos(2 * pi * n / (N - 1)) instead has ENBW 1.5 * N / (N - 1) bins, which is why the value is measured from these coefficients rather than quoted as 1.5
- normalization: Pxx[k] = |rfft(w * x)[k]|^2 / (fs_eff * sum_n w[n]^2) with f_k = k * fs_eff / N: a power spectral *density* in (unit)^2 / Hz, so a bin's power is Pxx[k] * delta_f and the integral over the one-sided grid is the window-normalized mean square of the analysed trace
- one-sided fold: one-sided with DC never doubled and every interior bin doubled; for even N the last bin sits exactly at Nyquist (fs_eff / 2) and is therefore not doubled; for odd N the last bin sits delta_f / 2 below Nyquist, is not Nyquist, and follows the interior rule - it is doubled, because the one-sided grid of an odd-length transform folds the upper half onto it
- quantity and unit: `axial_velocity` in `mm/s`; density `(mm/s)^2/Hz`
- gate rule: one row per cell x supported gate: the gates of a cell are exactly WindowView.supported_columns - the accessor that owns the question - enumerated in native depth order, never a re-derived mask and never a hand-picked subset. The report records the count per cell and asserts it against ViewProvenance.supported_gates.

## Provenance and digests

- analysis revision: `f0eb5e4d67903302c55bf54686579e1b5275a415`
- plan fingerprint (aggregate over the row set): `sha256:2c0cdc9013b41d2bd772cbd49532f14fff85b5ca29a13f98470258d31b952f89`
- plan fingerprint of `sparse-mixer-live-1`: `655298032dab02efe516e2e9d0294fc28330243f4aeb5f1e733fc5a50fd5ce86`
- plan fingerprint of `sparse-mixer-live-2`: `f9de5b803921b62e788572ef5209a779d05638f1f7da4933384a743c02b6b7ef`
- plan fingerprint rule: plan_fingerprints maps each selected pass's own name to that pass's plan fingerprint, as the pass's own plan file hashes (RunPlan.plan_fingerprint). plan_fingerprint is the aggregate binding the whole row set: 'sha256:' + SHA-256 over the canonical JSON (sort_keys=True, separators=(',', ':'), ASCII) of that {pass_name: fingerprint} map, the same canonical-JSON form the repository hashes a run plan with. A single fingerprint cannot stand for two plans, and a bare one would bind the report to one sitting while reading as if it bound both.
- `sa2-4-spectral-characterization.csv` sha256: `sha256:97edf94a4cd45771a044f646d8700a6f372d9e903d6762bccc1e20151fe4d159`
- the digest is the SHA-256 of the table's canonical LF bytes, so a Windows checkout with CRLF materialised on disk hashes to the same value git stores. It is populated from the bytes this run staged, not from a tree regenerated beside it.
- Two precisions, stated separately. The CSV is the fixed-precision table and the one per-gate record: it rounds band_fraction to fraction_decimals decimals and every other float to number_significant_digits significant digits, and a positive fraction that would round to a published zero is refused. The JSON does not duplicate the table's per-gate numbers; it carries the §4 repeat-spread members' band_fraction and every other float it publishes at their full double-precision value (Python's shortest round-tripping repr), never rounded to the CSV's precision. The JSON is strict: a non-finite value is refused (allow_nan=False) and fails the run before any file is written, never serialized as NaN or Infinity.
- every file is UTF-8 with LF endings and exactly one trailing newline; the numbers are formatted by one fixed rule per artefact (above), so a regeneration at this revision can be compared byte for byte - that comparison is the report's own regeneration test, not a claim this file makes about bytes it did not read.
- publication is staged, and honestly so: the three files are written beside the destination under unique, fsynced temporary names and moved onto their final names one `os.replace` at a time. Each rename is atomic on its own, but the three-file set is **not** a transaction - a failure after some renames have landed can leave a mixed set, and that is left for a reader to detect rather than rolled back. What detects it is this document's `table_sha256`: recompute the `sa2-4-spectral-characterization.csv` digest and compare it with the value above. The ordinary failures (a build, a refusal, a serialization or staging fault) leave the destination as it was. A publication lock beside these files makes two runs into one directory serialize rather than interleave, and an existing file this writer did not produce - or a stage file or lock an interrupted run left behind - is refused rather than overwritten.

## Reproduce

```bash
uv run python -m udv_echo_process.cli sparse-signal-report --analysis-commit f0eb5e4d67903302c55bf54686579e1b5275a415
```

## What this report does not claim

- A refusal is not an absence. 'unsupported at 8.333 Hz' describes the instrument and the window; it never means that no 8.333-Hz component exists.
- No feature is labelled from the spectrum: the report locates no spectral maximum, singles out no frequency as the feature, and infers no recurrence label from a spectral shape.
- No physical mechanism is attributed. From a band-power fraction alone, genuine flow dynamics, slow drift, finite-record structure and the detrending choice are indistinguishable, so no mechanism is named and no configuration is ranked.
- No amplitude is read from a raw density maximum: the fraction is a band-integrated power ratio, not an amplitude.
- No anti-alias or transfer-function claim. Nyquist support is a sampling-support statement for the stored profile sequence only, and it matters most where a target sits closest to a band edge.
- No cross-sitting inference and no condition contrast. The report is per sitting, descriptive, and compares no sitting with another and no condition with another.
- No borrowed floor and no independence claim: the profiles and gates within a recording are not treated as independent, and no spread is read as a screening floor or a resolvability threshold.
- No floor and no effect label from the repeat spread. The §4 within-sitting spread is descriptive only: it repeats one whole condition (pass, kind, condition, resolution_mm, window_gates), states its members' own fractions with their min, max, range and count, and derives no screening floor, no resolvability threshold, no condition or sitting ranking and no labelled effect from them.
- parseval_relative_error is a QA field, not a scientific observable.
- No new estimator, admission rule, threshold or tolerance is introduced by this report.
- No exploratory datum enters the report, its checks or its wording: an expected fraction, a per-sitting mean and any assumed spread are uncommitted and are not quoted, asserted as an expectation, or checked against.

## The gate

- `one_hundred_and_four_cells` - ok
- `both_reproducibility_sittings_are_present` - ok
- `both_views_are_present` - ok
- `every_cell_publishes_one_table_row_per_supported_gate` - ok
- `the_table_schema_is_the_closed_one` - ok
- `one_axis_per_cell` - ok
- `the_band_edge_is_the_prespecified_one` - ok
- `detrending_is_mean_on_both_views` - ok
- `published_fractions_lie_in_the_unit_interval` - ok
- `a_published_band_power_is_a_part_of_its_total` - ok
- `a_published_fraction_is_the_ratio_of_its_published_powers` - ok
- `a_refused_axis_publishes_no_numeric_fraction` - ok
- `a_defined_zero_power_publishes_two_zeros_and_no_fraction` - ok
- `plan_fingerprints_are_per_pass_and_the_aggregate_is_their_hash` - ok
- `the_destination_is_the_designated_root_or_outside_the_repository` - ok
- `the_repeat_groups_are_the_conditions_the_sweep_repeats` - ok
- `a_repeat_group_is_one_whole_condition` - ok
- `the_repeat_spread_covers_each_group_view_and_gate_once` - ok
- `the_repeat_spread_is_its_members_own_descriptive_arithmetic` - ok
