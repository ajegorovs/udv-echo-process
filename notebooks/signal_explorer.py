import marimo

__generated_with = "0.24.0"
app = marimo.App(width="columns")


@app.cell
def imports():
    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from udv_echo_process.acquire.run_plan import RunPlanError
    from udv_echo_process.analysis._sparse_pass import (
        decode_pass,
        point_qc,
        retains_designed_window,
    )
    from udv_echo_process.analysis.sparse_gate_stats import (
        VIEW_EXPLORATION,
        VIEW_FULL_RECORD,
        VIEW_LABELS,
        VIEW_PRIMARY,
        VIEW_RULES,
        SparseGateStatsError,
        SparseViewError,
        exploration_view,
        full_record_view,
        gate_statistics,
        primary_view,
        reduce_equal_weight,
        reduce_native_slab,
        statistic_units,
    )
    from udv_echo_process.analysis.sparse_inventory import SparseIngestError
    from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES, pass_by_name
    from udv_echo_process.analysis.sparse_recurrence import (
        Detrending,
        RecurrenceError,
        RecurrenceVerdict,
        recurrence_of_view,
    )
    # SA2.3's surface, and only its surface: the SA2.2 estimator (which carries its own
    # admission), the two probe targets SA2 names once, and the target-support question asked
    # of that carried admission. No SA2 module exposes a second window selector or an
    # admission builder, so the notebook cannot assemble its own.
    from udv_echo_process.analysis.sparse_periodogram import (
        SpectralPeriodogramError,
        SpectralVerdict,
        periodogram_of_view,
    )
    from udv_echo_process.analysis.sparse_spectral_capability import PROBE_TARGETS
    from udv_echo_process.analysis.sparse_target_support import (
        SpectralSupportError,
        target_frequency_support,
    )

    return (
        COMMITTED_PASSES,
        Detrending,
        PROBE_TARGETS,
        RecurrenceError,
        RecurrenceVerdict,
        RunPlanError,
        SparseIngestError,
        SparseViewError,
        SpectralPeriodogramError,
        SpectralSupportError,
        SpectralVerdict,
        VIEW_EXPLORATION,
        VIEW_FULL_RECORD,
        VIEW_LABELS,
        VIEW_PRIMARY,
        VIEW_RULES,
        decode_pass,
        exploration_view,
        full_record_view,
        gate_statistics,
        go,
        make_subplots,
        mo,
        np,
        pass_by_name,
        periodogram_of_view,
        point_qc,
        primary_view,
        recurrence_of_view,
        retains_designed_window,
        statistic_units,
        target_frequency_support,
    )


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Sparse signal explorer — SA0 checkpoint + SA1 preview + SA2.3 spectral preview

    The **first usable checkpoint** of the sparse signal analysis: dataset → job →
    recording → channel selection over the **committed** sparse passes, the selected
    recording's provenance/QC, its **native time–depth heatmap**, below it
    **SA1's preview** — per-gate mean and variability profiles, representative gate
    traces and time slices, the reported per-gate distributions, and the normalized
    trace autocorrelation with its raw trace — and below that **SA2.3's spectral
    preview**, one gate's periodogram with the timebase/admission it rests on, its
    target-frequency rows and its provenance. The default selection is the second
    mixer-enabled sitting, `sparse-mixer-live-2`.

    This notebook is a **thin wrapper**: every number comes from tested functions in
    `src/udv_echo_process/`. Six backend modules do the work and the notebook owns
    none of it:

    - `analysis.sparse_passes` — the **committed-pass catalogue**: each pass's root,
      plan path, name, role (*sitting* or *campaign*) and one-line note. The notebook
      keeps no pass list of its own; only the default selection is its own choice.
    - `analysis._sparse_pass` — the shared loader (`decode_pass`, which binds and
      decodes the pass once), the shared cut (`primary_window`) and the two accessors
      that own the record's own QC (`point_qc`) and its window-retention question
      (`retains_designed_window`).
    - `analysis._sparse_view`, re-exported by `analysis.sparse_gate_stats` — the one
      view vocabulary (`SparseView`), the one rule per label (`VIEW_RULES`) and the
      three labelled views (`primary_view`, `full_record_view`, `exploration_view`).
    - `analysis.sparse_gate_stats` and `analysis.sparse_recurrence` — every SA1
      number and curve: the per-gate statistics with their provenance and estimator
      conventions, the depth reductions with their declared weighting, and the
      normalized autocorrelation with its timebase and unsupported-claim verdicts.
    - `analysis.sparse_periodogram` — SA2.2's one estimator: `periodogram_of_view`
      cuts one gate's trace out of the **same** view, characterizes its stamps, asks
      its own `SpectralAdmission` whether the uniform-grid transform may be applied,
      and returns a `SpectralEstimate` that carries that admission, its taper and
      normalization conventions, the density and the view provenance — or an explicit
      `refused-irregular-axis` verdict with empty arrays.
    - `analysis.sparse_spectral_capability` and `analysis.sparse_target_support` —
      the two probe targets SA2 names once (`PROBE_TARGETS`: the ~1 Hz recurrence
      probe and the 25/3 Hz nominal rotor reference) and the question of whether a
      target is supported by the axis an admission was issued for. The notebook
      builds neither a frequency grid nor an admission of its own.

    Here the notebook only *selects* (pass, job, recording, channel, view, gate,
    detrending, exploration bounds) and *displays*; it computes no mean, percentile,
    standard deviation, correlation, reduction, window, FFT, taper or PSD
    normalization of its own, and it holds no pass table, no view translation map and
    no reference row of its own. A view reads the same way in this notebook as inside
    the modules that produce the numbers — one label, one rule, no second spelling.

    **Units and views.** Velocity is the instrument's own signed axial component in
    `mm/s`; depth is the instrument's **native gate coordinate** in `mm`. Every view
    carries one of the view module's own three labels — `primary-comparison` (the
    designed 12 s window: the pass's fixed comparison interval, a **nominal-duration
    equivalence** of the 100 revolutions the design asked for at the 500 RPM the design
    assumes and the recording does not establish), `full-record` (every stored profile,
    which retains the acquisition's own stopping overshoot), and `exploration`
    (explicitly selected time/depth bounds) — and each label travels with the rule that
    fixes its meaning. This notebook restates none of them and holds no translation
    between them: the label chosen in the sidebar is the label every result below
    carries, and an exploration selection never stands in for the primary comparison.

    **What this checkpoint does not measure.** It measures no scientific effect and
    compares no conditions. The profiles, traces, slices, distributions and
    autocorrelation below are SA1's views, and the periodogram at the foot of the
    notebook is SA2.2's, each appearing only beside the tested estimator that produced
    it; no spectrogram, no spatial correlation and no POD (SA3) are shown. SA2.3 adds
    **no new spectral estimator and no scientific interpretation** — it exposes and
    inspects an already-reviewed backend result. These `.BDD` velocity files carry
    **no tachometer, echo or energy channel**, so measured mixer speed, SNR and
    receiver saturation cannot be read from this notebook at all — that absence is a
    property of the data, not a pending feature.
    """)
    return


@app.cell(hide_code=True)
def pass_catalogue():
    # The committed passes are the backend catalogue's: `analysis.sparse_passes` is the
    # one place their roots, plan paths, names, roles and notes are stated, and it derives
    # the WP0 period-law table from itself. This notebook keeps no list, no root and no
    # "sitting" label of its own - a pass that is a campaign is shown as a campaign,
    # because the catalogue's own role says so.
    #
    # The *only* thing stated here is the default selection, which is a presentation
    # choice: the SA0 sitting.
    DEFAULT_PASS = "sparse-mixer-live-2"
    return (DEFAULT_PASS,)


@app.cell(hide_code=True)
def dataset_picker(COMMITTED_PASSES, DEFAULT_PASS, mo):
    # LEVEL 1 of the sidebar cascade. The option label carries the catalogue's own role,
    # so a pass that is a campaign is shown as a campaign - the notebook restates neither
    # the membership of the catalogue nor its roles.
    #
    # The catalogue's own one-line description of the selection follows in `dataset_note`:
    # a widget's value cannot be read in the cell that created it.
    _options = {f"{ref.name} · {ref.role.value}": ref.name for ref in COMMITTED_PASSES}
    _default_label = next(
        label for label, name in _options.items() if name == DEFAULT_PASS
    )
    dataset_picker = mo.ui.dropdown(
        options=_options,
        value=_default_label,
        label="Sparse pass (committed)",
        full_width=True,
    )
    mo.sidebar([mo.md("### Dataset"), dataset_picker])
    return (dataset_picker,)


@app.cell(hide_code=True)
def dataset_note(dataset_picker, mo, pass_by_name):
    # The selected dataset in the catalogue's own words, under the control, so the reader
    # never has to remember which realization — or which campaign, which is a separate
    # design — they are looking at.
    mo.sidebar([mo.md(f"_{pass_by_name(dataset_picker.value).note}_")])
    return


@app.cell(hide_code=True)
def pass_decoding(
    RunPlanError,
    SparseIngestError,
    dataset_picker,
    decode_pass,
    pass_by_name,
):
    # The ONE expensive cell: `decode_pass` binds and decodes every committed recording
    # of the pass the catalogue names (the pass itself decides how many - a nine-job
    # sitting binds 26, the Stage-2 campaign's eight run-level jobs bind 8). It depends on
    # the dataset control alone, so changing job / recording / channel below re-runs only
    # the selection and the views - no file is ever re-decoded by a widget change beyond
    # the pass itself.
    #
    # A refusal is data too, and the two loader modules raise their own named errors for
    # one: the frozen ingest refuses a pass record, plan, binding, declared word or
    # retired target it cannot answer to, and the plan loader refuses a plan it cannot
    # read. Either is shown rather than swallowed (rendered by `pass_status`), so a
    # checkout without the committed dataset - or a committed recording that failed its
    # own verification - degrades to a stated absence, not a crash.
    decoding = None
    decoding_error = ""
    if dataset_picker.value:
        _ref = pass_by_name(dataset_picker.value)
        try:
            decoding = decode_pass(
                _ref.root, plan_path=_ref.plan_path, plan_name=_ref.name
            )
        except (SparseIngestError, RunPlanError, OSError) as exc:
            decoding_error = f"{type(exc).__name__}: {exc}"
    else:
        decoding_error = "no dataset selected"
    return decoding, decoding_error


@app.cell(hide_code=True)
def pass_status(dataset_picker, decoding, decoding_error, mo, pass_by_name):
    # The pass-level banner: what the catalogue says this dataset is, how many recordings
    # bound, the pass's own shared views, and the plan fingerprint the rows answer to.
    # Never a fabricated number - every value below is read off the decoded pass or off
    # the catalogue's own note.
    if decoding_error:
        _out = mo.md(
            f"**No pass loaded for `{dataset_picker.value}`.**\n\n"
            f"`{decoding_error}`\n\n"
            "_If this is a missing dataset, the committed recordings are not present "
            "in this checkout; nothing is plotted and no number is invented._"
        )
    elif decoding is not None:
        _ref = pass_by_name(dataset_picker.value)
        _lo, _hi = decoding.support_mm
        _out = mo.md(
            f"**{_ref.name}** · `{_ref.role.value}` · {len(decoding.points)} recordings "
            f"bound · plan `{decoding.plan.plan}` "
            f"sha256:{decoding.plan_fingerprint[:12]}…\n"
            f"- primary window: **{decoding.window_s:g} s** "
            f"(a nominal-duration equivalence: {decoding.window_revolutions} revolutions "
            "at the nominal 500 RPM, not a measured speed), the pass's "
            "designed exposure\n"
            f"- common physical support: **{_lo:.3f}–{_hi:.3f} mm** "
            f"(native gate grids, no interpolation)\n"
            f"- channel fixed by the plan: **ch{decoding.plan.channel}**\n"
            f"- _{_ref.note}_"
        )
    else:
        _out = mo.md("_No dataset selected._")
    _out
    return


@app.cell(hide_code=True)
def job_picker(decoding, mo):
    # LEVEL 2. Jobs are listed in the plan's own step order (the order the pass ran
    # them in), so the acquisition sequence is visible in the control. The default is
    # the job recording the plan's own reference condition — a view default, not an
    # analysis decision.
    if decoding is not None:
        _jobs = [record.job for record in decoding.records]
        _reference = decoding.plan.reference_condition.as_triple
        _default = next(
            (record.job for record in decoding.records if record.condition == _reference),
            _jobs[0],
        )
        job_picker = mo.ui.dropdown(
            options=_jobs,
            value=_default,
            label="Job (plan step order)",
            full_width=True,
        )
    else:
        job_picker = mo.ui.dropdown(
            options=[], value=None, label="Job", full_width=True
        )
    mo.sidebar([mo.md("### Job"), job_picker])
    return (job_picker,)


@app.cell(hide_code=True)
def recording_picker(decoding, job_picker, mo):
    # LEVEL 3. One recording of the selected job, keyed by the pass's own identity so
    # the value the widget holds is the binding key, not a filename. The label carries
    # the point's label (its condition within the job) and the stored file name.
    if decoding is not None and job_picker.value:
        _points = decoding.of_job(job_picker.value)
        _options = {
            f"{point.binding.point.label} · {point.binding.relative_path}": (
                point.binding.identity
            )
            for point in _points
        }
        recording_picker = mo.ui.dropdown(
            options=_options,
            value=next(iter(_options)),
            label="Recording",
            full_width=True,
        )
    else:
        recording_picker = mo.ui.dropdown(
            options=[], value=None, label="Recording", full_width=True
        )
    mo.sidebar([mo.md("### Recording"), recording_picker])
    return (recording_picker,)


@app.cell(hide_code=True)
def channel_note(decoding, mo):
    # LEVEL 4, and deliberately NOT a control. The sparse pass stores exactly ONE channel
    # stream per recording — the shared loader refuses a file that carries any other
    # number — so a channel dropdown here would offer a single option that nothing reads:
    # a control that controls nothing, implying a choice the data does not have. The note
    # carries the fact instead, including the channel the pass's own plan fixed. A pass
    # that carried several channels would list them and this would become a selector.
    mo.sidebar(
        [
            mo.md("### Channel"),
            mo.md(
                f"the pass's plan fixes channel {int(decoding.plan.channel)}; every "
                "recording of this pass carries a single channel stream (the loader "
                "refuses a multi-channel file), so there is nothing to select"
                if decoding is not None
                else "_No channel: no pass is decoded._"
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def point_select(decoding, recording_picker):
    # Resolve the selected identity to the one bound point. No decoding happens here:
    # the points were decoded once in `pass_decoding`, and the widget value is matched
    # against the binding's own identity.
    point = None
    if decoding is not None and recording_picker.value is not None:
        _matches = [
            candidate
            for candidate in decoding.points
            if candidate.binding.identity == recording_picker.value
        ]
        point = _matches[0] if len(_matches) == 1 else None
    return (point,)


@app.cell(hide_code=True)
def point_metadata(decoding, mo, point, point_qc, retains_designed_window):
    # The selected recording's metadata, decoded settings and QC. Every measured number
    # here is handed to this cell by the loader: `point_qc` owns the record's own shape,
    # timing and whole-record counters (span, median Δt, achieved period, monotonicity,
    # finite/zero counts) and `retains_designed_window` owns the retention question. This
    # cell formats them; it recomputes none of them, so it cannot disagree with a frozen
    # table rendered beside it.
    _out = mo.md("_No recording selected — no metadata to show._")
    if point is not None and decoding is not None:
        _b = point.binding
        _job = _b.job
        _params = _b.point.parameters
        _cfg = point.config
        _qc = point_qc(point)
        _lo, _hi = decoding.support_mm
        _lines = [
            f"**{_b.identity}** · `{_b.relative_path}` · "
            f"**{_job.job}** (step {_job.step}, {_job.kind}) · "
            f"acquisition order {_b.order} of {len(decoding.points)}",
            "",
            f"- **condition (run-wide, plan)**: burst {_job.burst_length}, "
            f"emissions/profile {_job.emissions_per_profile}, PRF {_job.prf_us:g} µs "
            f"= {1e6 / _job.prf_us:.1f} Hz",
            f"- **point `{_b.point.label}`** (key {_b.point.key}) · requested pitch "
            f"{_params.resolution_mm:g} mm → **stored rung {_cfg.resolution_mm:g} mm** · "
            f"{_params.gates} gates · first gate {_params.first_gate_mm:g} mm · "
            f"planned depth {_params.depth_mm:.2f} mm · c {_params.sound_speed_ms:g} m/s",
            f"- **decoded**: `{point.quantity}` in `{point.unit}` · "
            f"{_qc.profiles} profiles × {_qc.gates} native gates · "
            f"gate {_qc.first_gate_mm:.3f} → {_qc.last_gate_mm:.3f} mm",
            f"- **stored instrument words**: burst {_cfg.burst_length}, emissions/profile "
            f"{_cfg.emissions_per_profile}, PRF {_cfg.pulse_repetition_freq_hz:g} Hz, "
            f"pitch {_cfg.resolution_mm:g} mm, SV index {_cfg.sampling_volume_index}, "
            f"emit power {_cfg.emit_power}, sensitivity {_cfg.sensitivity}, "
            f"v_max {_cfg.velo_max_ms} m/s, doppler {_cfg.doppler_angle_deg}°, "
            f"TGC {_cfg.tgc_mode} {_cfg.tgc_start_db}→{_cfg.tgc_end_db} dB, "
            f"skipped {_cfg.skipped_profiles}",
            f"- **timing, measured from the stored stamps** (`_sparse_pass.point_qc`): "
            f"span {_qc.span_s:.4f} s · median Δt {_qc.median_interval_s * 1e3:.3f} ms · "
            f"achieved period {_qc.achieved_interval_s:.6f} s · monotone {_qc.monotone}",
            f"- **signal QC of the full record** (`point_qc`): finite "
            f"{_qc.finite_samples}/{_qc.total_samples} ({_qc.finite_fraction:.4f}) · "
            f"exact zeros {_qc.exact_zeros} ({_qc.zero_fraction:.4f})",
            f"- **shared pass views**: primary window {decoding.window_s:g} s "
            f"({decoding.window_revolutions} revolutions at the nominal 500 RPM) · common "
            f"support {_lo:.3f}–{_hi:.3f} mm · this record retains the designed window: "
            f"**{retains_designed_window(point, window_s=decoding.window_s)}** "
            "(its own stamps, not the log's target)",
            f"- **provenance**: sha256:{point.source_sha256} · "
            f"{point.file_size_bytes} bytes · recording stamp "
            f"`{_b.recording_stamp}` · plan `{decoding.plan.plan}` "
            f"sha256:{decoding.plan_fingerprint}",
        ]
        _out = mo.md("\n".join(_lines))
    _out
    return


@app.cell(hide_code=True)
def heatmap(
    decoding,
    gate_stats,
    go,
    mo,
    np,
    point,
    position,
    profile_position,
    sparse_view,
    sparse_view_error,
):
    # The native time–depth heatmap of the one shared view. The selected stored time
    # and supported gate are drawn as crosshairs, locating the selected time slice and
    # gate trace below on the same data without adding a derived quantity.
    _out = mo.md("_No view selected — nothing to plot._")
    if sparse_view is None:
        if sparse_view_error:
            _out = mo.md(
                "**No heatmap: the view module refused the current selection.** Its own "
                f"statement, unchanged:\n\n`{sparse_view_error}`"
            )
    else:
        _time = np.asarray(sparse_view.time_s, dtype=float)
        _depths = np.asarray(sparse_view.depths_mm, dtype=float)
        _values = np.asarray(sparse_view.values, dtype=float)
        _stride = max(1, _time.size // 800)
        _z = _values[::_stride].T
        if point.quantity == "axial_velocity":
            _scale = float(np.nanmax(np.abs(_z))) or 1.0
            _kw = dict(zmin=-_scale, zmax=_scale, colorscale="RdBu_r")
            _crosshair = "#43A047"
        else:
            _kw = dict(colorscale="Viridis")
            _crosshair = "#FF1744"
        _fig = go.Figure(
            go.Heatmap(
                x=_time[::_stride],
                y=_depths,
                z=_z,
                colorbar={"title": f"{point.quantity} [{point.unit}]"},
                **_kw,
            )
        )
        _cursor_suffix = ""
        if (
            gate_stats is not None
            and position is not None
            and profile_position is not None
        ):
            _selected_time = float(_time[profile_position])
            _selected_column = sparse_view.column_of_depth(
                float(gate_stats.depths_mm[position])
            )
            _selected_depth = float(_depths[_selected_column])
            _fig.add_vline(
                x=_selected_time,
                line=dict(color=_crosshair, width=2.5, dash="dot"),
            )
            _fig.add_hline(
                y=_selected_depth,
                line=dict(color=_crosshair, width=2.5, dash="dash"),
            )
            _cursor_suffix = (
                f" · cursors: t = {_selected_time:.4f} s, depth = "
                f"{_selected_depth:.3f} mm"
            )
        _fig.update_layout(
            title=(
                f"{point.binding.identity} — ch{decoding.plan.channel} · "
                f"{point.quantity} [{point.unit}] · view `{sparse_view.view.value}` · "
                f"{sparse_view.supported_columns.size} supported of "
                f"{sparse_view.native_gates} native gates · "
                f"{'every profile' if _stride == 1 else f'every {_stride}th profile'} shown"
                f"{_cursor_suffix}"
            ),
            xaxis_title="time from the record's first stored profile [s]",
            yaxis_title="native gate depth [mm] (instrument gate coordinate)",
            height=520,
        )
        _out = mo.ui.plotly(_fig)
    _out

    return


@app.cell(hide_code=True)
def heatmap_notes(mo):
    mo.md("""
    **Reading the heatmap.** Both axes and the colour are the recording's own stored
    coordinates and units: `x` = seconds from that record's first stored profile, `y` =
    the instrument's **native gate coordinate** in `mm`, colour = the signed axial
    velocity component in `mm/s`. The instrument's own gate numbers are preserved and
    **not** relabelled to a physical depth along the beam: the entry wall, beam sign,
    physical mapping of gate zero and any CFD sampling line are conventions this
    notebook does not assume. The heatmap draws **the view selected in the sidebar, and
    only that block** — the gates and profiles the statistics and the autocorrelation
    below are computed from. Choosing the full-record view widens it to every stored
    profile, the acquisition's retained stopping overshoot included; that overshoot is a
    property of the recording's own record, and it belongs to no comparison.

    **Not shown here, on purpose.** Spectrograms, spatial correlation and POD
    (SA3) are absent: each is added only alongside the tested estimator and sampling
    guard that produce it. Gate traces, per-gate profiles, per-gate distributions and
    the normalized autocorrelation are in **SA1's section below**, and one gate's
    periodogram with its timebase/admission and target-support rows is in **SA2.3's
    section at the foot of the notebook**, where the tested estimator that returns
    each of them is named beside every display. The primary/exploratory label on every
    view is the same rule the later slices inherit.
    """)
    return


@app.cell(hide_code=True)
def time_slice_figure(
    go,
    mo,
    np,
    profile_position,
    profile_position_note,
    sparse_view,
):
    # The one selected stored profile read across the view's native supported gates. The
    # heatmap's vertical cursor marks this exact timestamp; no interpolation or new grid
    # is introduced.
    _out = mo.md("_No selected time slice: no view to read._")
    if sparse_view is not None and profile_position is not None:
        _values = np.asarray(sparse_view.values, dtype=float)
        _depths = np.asarray(sparse_view.depths_mm, dtype=float)
        _columns = np.asarray(sparse_view.supported_columns)
        _time = float(sparse_view.time_s[profile_position])
        _fig = go.Figure(
            go.Scatter(
                x=_depths[_columns],
                y=_values[profile_position, _columns],
                mode="lines+markers",
                name="selected stored profile",
                hovertemplate="depth %{x:.3f} mm<br>velocity %{y:.6f} mm/s<extra></extra>",
            )
        )
        _fig.update_layout(
            title=(
                f"{sparse_view.point_label} · selected stored profile "
                f"{profile_position} at t = {_time:.4f} s · view "
                f"`{sparse_view.view.value}` · supported gates only "
                f"({_columns.size} of {_depths.size})"
            ),
            xaxis_title="native gate depth [mm]",
            yaxis_title="signed axial velocity [mm/s]",
            showlegend=False,
            height=460,
        )
        _plot = mo.ui.plotly(_fig)
        _out = (
            mo.vstack([mo.callout(mo.md(profile_position_note), kind="warn"), _plot])
            if profile_position_note
            else _plot
        )
    _out

    return


@app.cell(hide_code=True)
def sa1_intro(mo):
    mo.md("""
    ## SA1 preview — per-gate profiles, traces, slices, distributions, recurrence

    Every number and curve below is returned by two tested modules over the **same**
    decoded pass SA0 selected above, and both of them read their samples from the **one**
    view object this notebook asks for:

    - `analysis.sparse_gate_stats` — the labelled views (re-exported from
      `analysis._sparse_view`, which owns the vocabulary and the cut), the per-gate
      statistics (the five frozen names plus SA1's `std`, `mad_scaled`, `min`, `max`,
      `q05/q25/q50/q75/q95`, `skewness`, `excess_kurtosis`) with their estimator
      conventions on the result, and the declared depth reductions;
    - `analysis.sparse_recurrence` — the normalized trace autocorrelation of one gate of
      that same view, with its raw and analysed traces, the lag/frequency resolution, the
      timebase verdict and every unsupported-claim verdict.

    This notebook chooses **which view, which gate and which detrending** to ask for
    and prints what comes back. It cuts no window (the view constructors do that with
    the recording's own stored stamps), computes no percentile, standard deviation,
    correlation or reduction, smooths, resamples and interpolates nothing, and holds no
    second spelling of a view: the label selected here is the label the results carry.
    Where a quantity is undefined or unsupported, the module's own statement is printed
    — no number is invented here to fill the gap.
    """)
    return


@app.cell(hide_code=True)
def sa1_view_controls(
    Detrending,
    VIEW_LABELS,
    VIEW_PRIMARY,
    VIEW_RULES,
    decoding,
    mo,
):
    # The SA1 view control. Its options ARE the view module's own vocabulary
    # (`VIEW_LABELS`) and every option label carries that module's own rule text
    # (`VIEW_RULES`), so the reader sees the rule the result will carry and this notebook
    # restates neither the membership nor the wording. The primary comparison is the
    # default: an exploration window is never allowed to replace it silently — it is a
    # separate, explicitly labelled choice.
    _view_options = {
        f"{view.value} — {VIEW_RULES[view]}": view for view in VIEW_LABELS
    }
    _default_view = next(
        label for label, view in _view_options.items() if view == VIEW_PRIMARY
    )
    gate_view = mo.ui.dropdown(
        options=_view_options,
        value=_default_view,
        label="SA1 view (the view module's own label and rule travel with every result)",
        full_width=True,
    )
    # The detrending is passed THROUGH to the recurrence module; the notebook removes
    # nothing itself and shows what was removed by plotting the raw trace beside it.
    _detrending_options = {
        "mean — the plan's default (subtract the trace mean)": Detrending.MEAN,
        "mean+linear — also remove a least-squares line; its slope is reported": (
            Detrending.MEAN_AND_LINEAR
        ),
        "none — correlate the stored trace as it stands": Detrending.NONE,
    }
    _default_detrending = next(
        label for label, kind in _detrending_options.items() if kind == Detrending.MEAN
    )
    detrending_picker = mo.ui.dropdown(
        options=_detrending_options,
        value=_default_detrending,
        label="Detrending (sparse_recurrence.Detrending)",
        full_width=True,
    )
    # Exploration bounds, in the record's own stored stamps and native gate
    # coordinates. They are handed to `exploration_view` unchanged; that function
    # refuses bounds reaching outside the record, and its refusal is displayed.
    _lo, _hi = decoding.support_mm if decoding is not None else (0.0, 1.0)
    explore_time_start = mo.ui.number(
        value=0.0, start=-1.0, stop=600.0, step=0.01,
        label="exploration time start [s]", full_width=True,
    )
    explore_time_end = mo.ui.number(
        value=float(decoding.window_s) if decoding is not None else 12.0,
        start=0.0, stop=600.0, step=0.01,
        label="exploration time end [s]", full_width=True,
    )
    explore_depth_low = mo.ui.number(
        value=float(_lo), start=-1000.0, stop=1000.0, step=0.01,
        label="exploration depth low [mm]", full_width=True,
    )
    explore_depth_high = mo.ui.number(
        value=float(_hi), start=-1000.0, stop=1000.0, step=0.01,
        label="exploration depth high [mm]", full_width=True,
    )
    # Keep the widgets alive regardless of the selected view, but keep this
    # exploration-only configuration out of the normal sidebar scan path.
    _exploration_bounds = mo.accordion(
        {
            "Exploration bounds — used only by the exploration view": mo.vstack(
                [
                    explore_time_start,
                    explore_time_end,
                    explore_depth_low,
                    explore_depth_high,
                ]
            )
        }
    )
    mo.sidebar(
        [
            mo.md("### SA1 view"),
            gate_view,
            detrending_picker,
            _exploration_bounds,
        ]
    )

    return (
        detrending_picker,
        explore_depth_high,
        explore_depth_low,
        explore_time_end,
        explore_time_start,
        gate_view,
    )


@app.cell(hide_code=True)
def sparse_view_checkpoint(
    SparseViewError,
    VIEW_EXPLORATION,
    VIEW_FULL_RECORD,
    decoding,
    exploration_view,
    explore_depth_high,
    explore_depth_low,
    explore_time_end,
    explore_time_start,
    full_record_view,
    gate_view,
    point,
    primary_view,
):
    # The ONE place this notebook decides *which block of samples to ask for*. It calls
    # the view module's own three constructors and nothing else: the primary view's cut
    # is `_sparse_pass.primary_window`, so the designed leading window here is the
    # interval the WP floor uses, never the retained overshoot.
    #
    # A refusal is the module's own and is shown as it stands: `SparseViewError` is the
    # whole sparse-view refusal (the statistics module's error subclasses it), so one
    # except here catches an exploratory selection that reaches outside the record, a
    # recording whose stamps cover no profile of the designed window, and a selection
    # that lands on no supported gate alike - and none of them is widened here into
    # something that would render.
    sparse_view = None
    sparse_view_error = ""
    if point is not None and decoding is not None:
        try:
            if gate_view.value == VIEW_EXPLORATION:
                sparse_view = exploration_view(
                    point,
                    time_bounds_s=(
                        float(explore_time_start.value),
                        float(explore_time_end.value),
                    ),
                    depth_bounds_mm=(
                        float(explore_depth_low.value),
                        float(explore_depth_high.value),
                    ),
                    support_mm=decoding.support_mm,
                )
            elif gate_view.value == VIEW_FULL_RECORD:
                sparse_view = full_record_view(point, support_mm=decoding.support_mm)
            else:
                sparse_view = primary_view(
                    point, window_s=decoding.window_s, support_mm=decoding.support_mm
                )
        except SparseViewError as exc:
            sparse_view_error = f"{type(exc).__name__}: {exc}"
    return sparse_view, sparse_view_error


@app.cell(hide_code=True)
def sa1_view_label(mo, sparse_view, sparse_view_error):
    # The visible view label, in the view module's own words, printed above the SA1
    # displays: which view, what its rule is, the declared window beside the span the
    # stored stamps actually achieve, and the three depth extents the module keeps apart
    # (the pass's declared support, the recording's own native grid, and this
    # selection's participating extent). A reader never has to infer the view from a
    # colour or a title.
    if sparse_view is None:
        _out = mo.md(
            "_No SA1 view: no recording and view combination is selected._"
            + (f"\n\n`{sparse_view_error}`" if sparse_view_error else "")
        )
    else:
        _declared = (
            f"{sparse_view.declared_window_s:g} s declared"
            if sparse_view.declared_window_s is not None
            else "no declared interval (a bounds-selected or full-record view)"
        )
        _bounds = (
            f" · selected bounds {sparse_view.time_bounds_s} s, "
            f"{sparse_view.depth_bounds_mm} mm"
            if sparse_view.time_bounds_s is not None
            else ""
        )
        _participating = sparse_view.participating_depth_extent_mm
        _out = mo.md(
            f"**SA1 view: `{sparse_view.view.value}`** — {sparse_view.view_rule}\n\n"
            f"- window: **{sparse_view.window_start_s:.4f}–"
            f"{sparse_view.window_end_s:.4f} s** (span {sparse_view.window_s:.4f} s; "
            f"{_declared}){_bounds}\n"
            f"- stored profiles in the view: **{sparse_view.values.shape[0]}** "
            f"(indices [{sparse_view.start_index}, {sparse_view.stop_index}) of the "
            "recording's own profile axis)\n"
            f"- native gates in the view: {sparse_view.depths_mm.size} of the recording's "
            f"{sparse_view.native_gates} · inside the pass's common support "
            f"[{sparse_view.pass_support_mm[0]:.3f}, "
            f"{sparse_view.pass_support_mm[1]:.3f}] mm: "
            f"**{sparse_view.supported_columns.size}** · the participating depth extent "
            f"**{_participating[0]:.3f}–{_participating[1]:.3f} mm**\n"
            f"- source: `{sparse_view.relative_path}` · job `{sparse_view.job}` · point "
            f"`{sparse_view.point_label}` · "
            f"sha256:{sparse_view.source_sha256[:12]}…"
        )
    _out
    return


@app.cell(hide_code=True)
def gate_stats_result(SparseViewError, gate_statistics, sparse_view):
    # `gate_statistics` calls the frozen `gate_metrics` and SA1's extension on the
    # view's supported block, so the five frozen names and SA1's eleven cannot drift
    # apart. Nothing is reduced here: the result keeps one value per gate.
    gate_stats = None
    gate_stats_error = ""
    if sparse_view is not None:
        try:
            gate_stats = gate_statistics(sparse_view)
        except SparseViewError as exc:
            gate_stats_error = f"{type(exc).__name__}: {exc}"
    return gate_stats, gate_stats_error


@app.cell(hide_code=True)
def sa1_stats_readout(gate_stats, gate_stats_error, mo):
    # What the statistics result itself declares: the view it was computed on with the
    # three depth extents kept apart, the estimator conventions that made the numbers
    # (they describe *how*, which is the estimator's property, and they travel on the
    # result rather than on the view), and — never silently — which statistics it could
    # not measure at any gate.
    if gate_stats is None:
        _out = mo.md(
            "_No per-gate statistics: no view is available._"
            + (f"\n\n`{gate_stats_error}`" if gate_stats_error else "")
        )
    else:
        _prov = gate_stats.provenance
        _unmeasured = gate_stats.unmeasured()
        _native = _prov.native_depth_extent_mm
        _support = _prov.pass_support_mm
        _participating = _prov.participating_depth_extent_mm
        if _unmeasured:
            _unmeasured_lines = "\n".join(
                f"  - `{name}`: undefined (non-finite) at {len(positions)} of "
                f"{gate_stats.depths_mm.size} supported gate-columns "
                f"({list(positions)[:8]}{'…' if len(positions) > 8 else ''})"
                for name, positions in _unmeasured.items()
            )
        else:
            _unmeasured_lines = (
                "  - none: every reported statistic is finite at every supported gate "
                "of this view"
            )
        _declared = (
            f"{_prov.declared_window_s:g} s declared"
            if _prov.declared_window_s is not None
            else "no declared interval"
        )
        _out = mo.md(
            f"**Per-gate statistics of the `{_prov.view.value}` view** "
            f"({len(gate_stats.statistic_names)} statistics × "
            f"{gate_stats.depths_mm.size} supported gates)\n\n"
            f"- the three depth extents, kept apart: the selection **participates** in "
            f"**{_participating[0]:.3f}–{_participating[1]:.3f} mm** (what these numbers "
            f"cover) · the pass's declared **common support** it was restricted to "
            f"{_support[0]:.3f}–{_support[1]:.3f} mm · the recording's own **native "
            f"grid** {_native[0]:.3f}–{_native[1]:.3f} mm "
            f"({_prov.supported_gates} of {_prov.native_gates} native gates supported)\n"
            f"- window: {_prov.window_start_s:.4f}–{_prov.window_end_s:.4f} s "
            f"(span {_prov.window_s:.4f} s; {_declared}) · profiles {_prov.profiles} "
            f"(indices [{_prov.start_index}, {_prov.stop_index})) · source "
            f"`{_prov.relative_path}` sha256:{_prov.source_sha256[:12]}…\n"
            f"- method: {gate_stats.method}\n"
            f"- percentile method: `{gate_stats.percentile_method}` · std ddof "
            f"{gate_stats.std_ddof}\n"
            f"- MAD scaling: **{gate_stats.mad_scale:g}** ({gate_stats.mad_scaling})\n"
            f"- kurtosis convention: {gate_stats.excess_kurtosis_convention}\n"
            f"- constant-trace rule: {gate_stats.constant_trace_rule}\n"
            f"- statistics the result reports as **unmeasured** (an undefined value is "
            f"named, never drawn as a zero curve):\n{_unmeasured_lines}"
        )
    _out
    return


@app.cell(hide_code=True)
def gate_profile_figure(
    gate_stats,
    go,
    make_subplots,
    mo,
    np,
    statistic_units,
):
    # Per-gate mean and variability profiles over the instrument's native depth. Every
    # y value is a row the statistics result returned (`mean`, `q25`, `q75`, `std`,
    # `mad_scaled`) and every unit is the module's own (`statistic_units`); this cell
    # selects rows and draws them, it computes nothing. The interquartile envelope is
    # filled between invisible q75 and q25 boundary traces: they stay out of the legend
    # but remain in the shared depth hover alongside the mean.
    _out = mo.md("_No per-gate profiles: no statistics to plot._")
    if gate_stats is not None:
        _depths = np.asarray(gate_stats.depths_mm, dtype=float)
        _q25 = gate_stats.of("q25")
        _q75 = gate_stats.of("q75")
        _prov = gate_stats.provenance
        _fig = make_subplots(
            rows=1, cols=2, horizontal_spacing=0.09,
            subplot_titles=(
                f"per-gate mean with the reported q25–q75 band "
                f"[{statistic_units('mean')}]",
                f"per-gate variability [{statistic_units('std')}]",
            ),
        )
        _fig.add_trace(
            go.Scatter(
                x=_depths, y=_q75, mode="lines",
                name="q75 (upper quartile)",
                line=dict(width=0),
                showlegend=False,
                hovertemplate="q75 (upper quartile): %{y:.3f} mm/s<extra></extra>",
            ),
            row=1, col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=_depths, y=_q25, mode="lines",
                name="q25 (lower quartile)",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(144,202,249,0.35)",
                showlegend=False,
                hovertemplate="q25 (lower quartile): %{y:.3f} mm/s<extra></extra>",
            ),
            row=1, col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=_depths, y=gate_stats.of("mean"), mode="lines",
                name="mean (signed axial velocity)",
                line=dict(color="#1E88E5", width=2.4),
                hovertemplate="mean: %{y:.3f} mm/s<extra></extra>",
            ),
            row=1, col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=_depths, y=gate_stats.of("std"), mode="lines",
                name=f"std (population, ddof={gate_stats.std_ddof})",
                line=dict(color="#E53935", width=1.9),
            ),
            row=1, col=2,
        )
        _fig.add_trace(
            go.Scatter(
                x=_depths, y=gate_stats.of("mad_scaled"), mode="lines",
                name=f"mad_scaled (MAD × {gate_stats.mad_scale:g})",
                line=dict(color="#FB8C00", width=1.9, dash="dash"),
            ),
            row=1, col=2,
        )
        _fig.update_layout(
            title=(
                f"{_prov.point_label} · view "
                f"`{_prov.view.value}` · window {_prov.window_start_s:.4f}–"
                f"{_prov.window_end_s:.4f} s · per-gate profiles vs native gate depth"
            ),
            hovermode="x",
            height=560,
        )
        _fig.update_xaxes(title_text="native gate depth [mm]", row=1, col=1)
        _fig.update_xaxes(title_text="native gate depth [mm]", row=1, col=2)
        _fig.update_yaxes(
            title_text="signed axial velocity [mm/s]", row=1, col=1
        )
        _fig.update_yaxes(title_text="variability [mm/s]", row=1, col=2)
        _out = mo.ui.plotly(_fig)
    _out
    return


@app.cell(hide_code=True)
def gate_selection_memory(mo):
    # PRESENTATION state only: the depth and timestamp the reader last chose. These
    # controls re-run whenever the view or recording changes, so their widgets would
    # otherwise return to declared middle defaults and silently move the crosshair.
    # No result value comes from this state; it holds reader selections only.
    #
    # `allow_self_loops=True` is required because each widget's `on_change` writes the
    # state from the cell that reads it. The loop settles on the newly declared default.
    get_reader_gate_mm, set_reader_gate_mm = mo.state(None, allow_self_loops=True)
    get_reader_time_s, set_reader_time_s = mo.state(None, allow_self_loops=True)

    return (
        get_reader_gate_mm,
        get_reader_time_s,
        set_reader_gate_mm,
        set_reader_time_s,
    )


@app.cell(hide_code=True)
def gate_picker_cell(
    gate_stats,
    get_reader_gate_mm,
    get_reader_time_s,
    mo,
    np,
    set_reader_gate_mm,
    set_reader_time_s,
    sparse_view,
):
    # The two SA1 cursors address the same view used by the heatmap and selected-gate
    # displays. Both widgets use stored row positions; their remembered physical
    # coordinates prevent a view rebuild from silently returning the reader to middle
    # defaults.
    if gate_stats is not None and sparse_view is not None:
        _depths = np.asarray(gate_stats.depths_mm, dtype=float)
        _gate_count = int(_depths.size)
        _gate_default = _gate_count // 2
        _wanted_gate = get_reader_gate_mm()
        if _wanted_gate is not None:
            _matches = np.flatnonzero(np.isclose(_depths, float(_wanted_gate)))
            if _matches.size:
                _gate_default = int(_matches[0])

        def _remember_gate(_picked, _depths=_depths):
            """Record the chosen gate depth; the slider value is its row position."""
            _index = int(_picked)
            if 0 <= _index < _depths.size:
                set_reader_gate_mm(float(_depths[_index]))

        _time = np.asarray(sparse_view.time_s, dtype=float)
        _profiles = int(_time.size)
        _time_default = _profiles // 2
        _wanted_time = get_reader_time_s()
        if _wanted_time is not None:
            _matches = np.flatnonzero(np.isclose(_time, float(_wanted_time)))
            if _matches.size:
                _time_default = int(_matches[0])

        def _remember_time(_picked, _time=_time):
            """Record the selected stored timestamp; the slider value is its index."""
            _index = int(_picked)
            if 0 <= _index < _time.size:
                set_reader_time_s(float(_time[_index]))

        profile_picker = mo.ui.slider(
            start=0,
            stop=max(1, _profiles - 1),
            value=_time_default,
            step=1,
            label=(
                f"Time (SA1) — stored profile index · t {_time[0]:.4f}–"
                f"{_time[-1]:.4f} s"
            ),
            full_width=True,
            show_value=True,
            on_change=_remember_time,
        )
        gate_picker = mo.ui.slider(
            start=0,
            stop=max(1, _gate_count - 1),
            value=_gate_default,
            step=1,
            label=(
                f"Gate (SA1) — supported-gate index · depth {_depths[0]:.3f}–"
                f"{_depths[-1]:.3f} mm ({_gate_count} gates)"
            ),
            full_width=True,
            show_value=True,
            on_change=_remember_gate,
        )
    else:
        profile_picker = mo.ui.slider(
            start=0, stop=1, value=0, step=1, label="Time (SA1)", full_width=True
        )
        gate_picker = mo.ui.slider(
            start=0, stop=1, value=0, step=1, label="Gate (SA1)", full_width=True
        )
    mo.sidebar(
        [
            mo.md("### Time (SA1)"),
            profile_picker,
            mo.md("### Gate (SA1)"),
            gate_picker,
        ]
    )

    return gate_picker, profile_picker


@app.cell(hide_code=True)
def gate_position(
    gate_picker,
    gate_stats,
    get_reader_gate_mm,
    get_reader_time_s,
    np,
    profile_picker,
    sparse_view,
):
    # Resolve both cursor positions once against the current result and view. A view or
    # recording may not carry the reader's previous coordinate; in that case each cursor
    # falls back to its middle entry and states the move rather than silently changing it.
    position = None
    position_note = ""
    profile_position = None
    profile_position_note = ""

    if sparse_view is not None and profile_picker.value is not None:
        _time = np.asarray(sparse_view.time_s, dtype=float)
        _picked_time = int(profile_picker.value)
        _profile_count = int(_time.size)
        _wanted_time = get_reader_time_s()
        if 0 <= _picked_time < _profile_count:
            profile_position = _picked_time
        elif _profile_count > 0:
            profile_position = _profile_count // 2
            profile_position_note = (
                f"the profile position selected before this view change ({_picked_time}) is "
                f"not in this view, which has {_profile_count} stored profile(s): the "
                "middle one is shown"
            )
        if profile_position is not None and _wanted_time is not None:
            _shown_time = float(_time[profile_position])
            if not np.isclose(_shown_time, float(_wanted_time)) and not profile_position_note:
                profile_position_note = (
                    f"the time you last selected ({float(_wanted_time):.4f} s) is not a "
                    f"stored profile of this view: the middle stored profile at "
                    f"{_shown_time:.4f} s is shown"
                )

    if gate_stats is not None and gate_picker.value is not None:
        _depths = np.asarray(gate_stats.depths_mm, dtype=float)
        _picked_gate = int(gate_picker.value)
        _gate_count = int(_depths.size)
        _wanted_gate = get_reader_gate_mm()
        if 0 <= _picked_gate < _gate_count:
            position = _picked_gate
        elif _gate_count > 0:
            position = _gate_count // 2
            position_note = (
                f"the gate position selected before this view change ({_picked_gate}) is not "
                f"in this view, which has {_gate_count} supported gate(s): the middle one "
                "is shown"
            )
        if position is not None and _wanted_gate is not None:
            _shown_depth = float(_depths[position])
            if _shown_depth != _wanted_gate and not position_note:
                position_note = (
                    f"the gate you last selected (depth {_wanted_gate:.3f} mm) is not a "
                    f"supported gate of this view, which has {_gate_count} supported gate(s) "
                    f"from {float(_depths[0]):.3f} to {float(_depths[-1]):.3f} mm: the "
                    f"middle supported gate (depth {_shown_depth:.3f} mm) is shown"
                )

    return position, position_note, profile_position, profile_position_note


@app.cell(hide_code=True)
def gate_trace_figure(
    gate_stats,
    go,
    make_subplots,
    mo,
    np,
    position,
    position_note,
    sparse_view,
):
    # The selected gate shown as its stored temporal trace and its distribution. Both
    # panels share velocity as the y-axis: the right panel is a horizontal histogram,
    # with the same reported quantile/range landmarks previously drawn separately.
    # Nothing is averaged, smoothed or decimated.
    _out = mo.md("_No selected-gate trace: no view to read._")
    if sparse_view is not None and gate_stats is not None and position is not None:
        _values = np.asarray(sparse_view.values, dtype=float)
        _depths = np.asarray(sparse_view.depths_mm, dtype=float)
        _selected = sparse_view.column_of_depth(float(gate_stats.depths_mm[position]))
        _trace = _values[:, _selected]
        _depth = float(_depths[_selected])
        _minimum = float(gate_stats.of("min")[position])
        _maximum = float(gate_stats.of("max")[position])
        _q05 = float(gate_stats.of("q05")[position])
        _q25 = float(gate_stats.of("q25")[position])
        _q50 = float(gate_stats.of("q50")[position])
        _q75 = float(gate_stats.of("q75")[position])
        _q95 = float(gate_stats.of("q95")[position])
        _hist_counts, _ = np.histogram(_trace, bins=30)
        _landmark_x = -max(1.0, float(_hist_counts.max()) * 0.12)
        _fig = make_subplots(
            rows=1,
            cols=2,
            shared_yaxes=True,
            column_widths=[0.68, 0.32],
            horizontal_spacing=0.12,
            subplot_titles=(
                "stored velocity over time",
                "histogram + reported distribution landmarks",
            ),
        )
        _fig.add_trace(
            go.Scatter(
                x=sparse_view.time_s,
                y=_trace,
                mode="lines",
                name="selected gate trace",
                line=dict(width=1.8, color="#111111"),
                hovertemplate="time %{x:.6f} s<br>velocity %{y:.6f} mm/s<extra></extra>",
            ),
            row=1,
            col=1,
        )
        _fig.add_trace(
            go.Histogram(
                y=_trace,
                orientation="h",
                nbinsy=30,
                name="velocity histogram",
                marker=dict(color="#90CAF9"),
                hovertemplate="profiles %{x}<br>velocity bin %{y}<extra></extra>",
            ),
            row=1,
            col=2,
        )
        _fig.add_trace(
            go.Scatter(
                x=[_landmark_x, _landmark_x],
                y=[_minimum, _maximum],
                mode="lines",
                name="min to max",
                line=dict(color="#90A4AE", width=1.6),
                hovertemplate="observed extreme: %{y:.6f} mm/s<extra></extra>",
            ),
            row=1,
            col=2,
        )
        _fig.add_trace(
            go.Scatter(
                x=[_landmark_x, _landmark_x],
                y=[_q25, _q75],
                mode="lines",
                name="q25 to q75 (IQR)",
                line=dict(color="#1E88E5", width=10),
                hovertemplate="interquartile landmark: %{y:.6f} mm/s<extra></extra>",
            ),
            row=1,
            col=2,
        )
        _fig.add_trace(
            go.Scatter(
                x=[_landmark_x],
                y=[_q50],
                mode="markers",
                name="q50 (median)",
                marker=dict(size=13, color="#0D47A1"),
                hovertemplate="q50 (median): %{y:.6f} mm/s<extra></extra>",
            ),
            row=1,
            col=2,
        )
        _fig.add_trace(
            go.Scatter(
                x=[_landmark_x, _landmark_x],
                y=[_q05, _q95],
                mode="markers",
                name="q05 and q95",
                marker=dict(size=9, color="#FB8C00"),
                hovertemplate="q05/q95 landmark: %{y:.6f} mm/s<extra></extra>",
            ),
            row=1,
            col=2,
        )
        _fig.update_xaxes(
            title_text="time from the record's first stored profile [s]", row=1, col=1
        )
        _fig.update_xaxes(title_text="profiles per bin", row=1, col=2)
        _fig.update_yaxes(title_text="signed axial velocity [mm/s]", row=1, col=1)
        _fig.update_layout(
            title=(
                f"{sparse_view.point_label} · selected gate at depth {_depth:.3f} mm · "
                f"view `{sparse_view.view.value}` · window "
                f"{sparse_view.window_start_s:.4f}–{sparse_view.window_end_s:.4f} s "
                f"(span {sparse_view.window_s:.4f} s)"
            ),
            legend=dict(
                orientation="v", yanchor="top", y=1, xanchor="left", x=1.02
            ),
            margin=dict(r=190),
            height=460,
        )
        _plot = mo.ui.plotly(_fig)
        _out = (
            mo.vstack([mo.callout(mo.md(position_note), kind="warn"), _plot])
            if position_note
            else _plot
        )
    _out

    return


@app.cell(hide_code=True)
def gate_statistics_table(gate_stats, mo, np, position):
    # Exact selected-gate statistics. The trace-and-histogram figure immediately above
    # draws its min/max, q05/q25/q50/q75/q95 landmarks; this table remains the full,
    # auditable readout returned by `sparse_gate_stats`.
    _out = mo.md("_No selected-gate statistics: no result to show._")
    if gate_stats is not None and position is not None:
        _depth = float(gate_stats.depths_mm[position])
        _rows = []
        for _index, _name in enumerate(gate_stats.statistic_names):
            _value = float(gate_stats.statistics[_index][position])
            _rows.append(
                f"| `{_name}` | "
                + (f"{_value:.6f}" if np.isfinite(_value) else "**undefined (NaN)**")
                + f" | {gate_stats.units[_index]} |"
            )
        _table = "\n".join(
            [
                f"### Exact statistics — gate depth {_depth:.3f} mm "
                f"(supported gate {position + 1} of {gate_stats.depths_mm.size})",
                "| statistic | value | unit |",
                "| --- | --- | --- |",
            ]
            + _rows
        )
        _out = mo.md(
            _table
            + "\n\nAn entry marked **undefined (NaN)** is the module's own "
            "constant-trace rule: a gate with no variance has no shape to describe; it "
            "is not a measured zero. "
            f"mad_scaled is scaled by {gate_stats.mad_scale:g} "
            f"({gate_stats.mad_scaling}), and every percentile uses NumPy's "
            f"`{gate_stats.percentile_method}` interpolation, as the result declares."
        )
    _out

    return


@app.cell(hide_code=True)
def recurrence_result(
    RecurrenceError,
    SparseViewError,
    detrending_picker,
    gate_stats,
    point,
    position,
    recurrence_of_view,
    sparse_view,
):
    # The recurrence call: one view, one gate depth, one detrending. `recurrence_of_view`
    # is the module's single entry point and it takes NO arrays — the trace is the
    # selected view's own column at that depth, over the view's own stored stamps, so the
    # ACF reads exactly the block the statistics above were computed on, and the label,
    # job, path, window, gate index, depth, quantity and unit all come from that one
    # view's provenance.
    #
    # There is deliberately no view translation here: the statistics module and the
    # recurrence module share the one view vocabulary, so the label the reader selected
    # above is the label this result carries, and no cell has to reconcile two spellings.
    recurrence = None
    recurrence_error = ""
    if (
        sparse_view is not None
        and gate_stats is not None
        and position is not None
        and point is not None
    ):
        _depth = float(gate_stats.depths_mm[position])
        try:
            recurrence = recurrence_of_view(
                sparse_view,
                depth_mm=_depth,
                quantity=str(point.quantity),
                unit=str(point.unit),
                detrending=detrending_picker.value,
            )
        except (RecurrenceError, SparseViewError) as exc:
            recurrence_error = f"{type(exc).__name__}: {exc}"
    return recurrence, recurrence_error


@app.cell(hide_code=True)
def recurrence_figure(
    RecurrenceVerdict,
    go,
    make_subplots,
    mo,
    np,
    recurrence,
    recurrence_error,
    sparse_view,
):
    # The selected gate's raw trace, the analysed trace, and its normalized autocorrelation.
    # The method note makes the finite-window overlap explicit: it is an intentional feature
    # of the estimator, not an unlabelled visual decay.
    _out = mo.md(
        "_No recurrence: no gate trace is available for the selected view._"
        + (f"\n\n`{recurrence_error}`" if recurrence_error else "")
    )
    if recurrence is not None:
        _raw = np.asarray(recurrence.raw_trace, dtype=float)
        _analysed = np.asarray(recurrence.detrended_trace, dtype=float)
        _times = (
            np.asarray(sparse_view.time_s, dtype=float)[: _raw.size]
            if sparse_view is not None
            else np.arange(_raw.size, dtype=float)
        )
        _defined = recurrence.verdict is RecurrenceVerdict.DEFINED
        _method = mo.md(
            r"""
    **Method — normalized autocorrelation.** For the analysed continuous trace
    \(x(t)\) over a finite window \([t_0, t_1]\), the corresponding quantity is

    \[
    R(\tau) =
    \frac{\int_{t_0}^{t_1-\tau} x(t)\,x(t+\tau)\,dt}
         {\int_{t_0}^{t_1} x(t)^2\,dt}.
    \]

    The notebook evaluates the stored-sample version of this expression: the numerator
    uses only pairs that overlap after a lag, while the denominator stays fixed at the
    full zero-lag energy. Consequently, fewer pairs contribute at longer lags and the
    curve has an intentional finite-window taper. Read local peaks, especially early
    ones, as candidate recurrence lags; do not read a later curve height alone as an
    untapered recurrence strength. Diamonds mark every local maximum currently reported
    by the backend, so a split or noisy peak is visible rather than hidden. The analysed
    trace uses the selected detrending rule.
    """
        )
        if _defined:
            _fig = make_subplots(
                rows=2,
                cols=1,
                vertical_spacing=0.16,
                subplot_titles=(
                    "the trace: raw as stored, and what the module correlated",
                    "normalized autocorrelation of the analysed trace",
                ),
            )
        else:
            _fig = make_subplots(
                rows=1,
                cols=1,
                subplot_titles=("the trace: raw as stored (no curve was returned)",),
            )
        _fig.add_trace(
            go.Scatter(
                x=_times,
                y=_raw,
                mode="lines",
                name="raw trace (as stored)",
                line=dict(color="#546E7A", width=1.4),
            ),
            row=1,
            col=1,
        )
        if _defined:
            _fig.add_trace(
                go.Scatter(
                    x=_times,
                    y=_analysed,
                    mode="lines",
                    name=f"analysed trace (detrending `{recurrence.detrending.value}`)",
                    line=dict(color="#1E88E5", width=1.6),
                ),
                row=1,
                col=1,
            )
            _fig.add_trace(
                go.Scatter(
                    x=recurrence.lag_s,
                    y=recurrence.acf,
                    mode="lines",
                    name="normalized ACF",
                    line=dict(color="#6D4C41", width=1.9),
                ),
                row=2,
                col=1,
            )
            _peaks = tuple(recurrence.recurrence_peaks)
            if _peaks:
                _fig.add_trace(
                    go.Scatter(
                        x=[_peak.lag_s for _peak in _peaks],
                        y=[_peak.correlation for _peak in _peaks],
                        mode="markers",
                        name="detected local maxima",
                        marker=dict(color="#FB8C00", size=8, symbol="diamond"),
                        customdata=[[_peak.weak, _peak.reason] for _peak in _peaks],
                        hovertemplate=(
                            "lag %{x:.4f} s<br>normalized ACF %{y:.3f}"
                            "<br>weak %{customdata[0]}<br>%{customdata[1]}<extra></extra>"
                        ),
                    ),
                    row=2,
                    col=1,
                )
            _fig.add_hline(y=0.0, line=dict(color="#B0BEC5", width=1.0), row=2, col=1)
            if bool(recurrence.period_claim.supported):
                _fig.add_vline(
                    x=float(recurrence.period_claim.period_s),
                    line=dict(color="#43A047", width=2.0, dash="dot"),
                    row=2,
                    col=1,
                    annotation_text="claimed period",
                )
        _fig.update_layout(
            title=(
                f"{recurrence.label} · gate depth {recurrence.depth_mm:.3f} mm · view "
                f"`{recurrence.view.value}` · {recurrence.profile_count} profiles over "
                f"{recurrence.window_duration_s:.4f} s · timebase "
                f"`{recurrence.timebase.value}` · verdict "
                f"`{recurrence.verdict.value}`"
            ),
            height=640 if _defined else 380,
        )
        _fig.update_xaxes(
            title_text="time from the record's first stored profile [s]",
            row=1,
            col=1,
        )
        _fig.update_yaxes(title_text=f"velocity [{recurrence.unit}]", row=1, col=1)
        if _defined:
            _fig.update_xaxes(title_text="lag [s]", row=2, col=1)
            _fig.update_yaxes(title_text="normalized autocorrelation", row=2, col=1)
        _out = mo.vstack([_method, mo.ui.plotly(_fig)])
    _out
    return


@app.cell(hide_code=True)
def recurrence_readout(mo, recurrence, recurrence_error):
    # A compact recurrence readout: the method note above explains the estimator; this cell
    # keeps only the evidence a reader needs to assess candidate recurrence peaks and whether
    # the backend permits a period claim.
    if recurrence is None:
        _out = mo.md(
            "_No recurrence result._"
            + (f"\n\n`{recurrence_error}`" if recurrence_error else "")
        )
    else:
        _claim = recurrence.period_claim
        _early_peaks = [
            _peak for _peak in recurrence.recurrence_peaks if _peak.lag_s <= 1.0
        ]
        _lines = [
            f"**Candidate recurrence peaks — gate depth {recurrence.depth_mm:.3f} mm, "
            f"view `{recurrence.view.value}`**",
            "",
            f"- analysed with `{recurrence.detrending.value}` detrending over "
            f"{recurrence.profile_count} profiles and {recurrence.window_duration_s:.3f} s "
            f"(lag step {recurrence.lag_resolution_s:.4f} s; timebase "
            f"`{recurrence.timebase.value}`).",
            f"- **period claim: `{_claim.supported}`** — {_claim.reason}",
            "",
            "The table lists local ACF maxima in the first second, where the finite-window "
            "overlap taper is least severe. They are descriptive candidate lags, not periods "
            "unless the period claim above is supported.",
            "",
            "| candidate lag [s] | normalized ACF | status |",
            "| ---: | ---: | :--- |",
        ]
        if _early_peaks:
            _lines.extend(
                f"| {_peak.lag_s:.4f} | {_peak.correlation:.3f} | "
                f"{'weak candidate' if _peak.weak else 'candidate'} |"
                for _peak in _early_peaks
            )
        else:
            _lines.append("| — | — | no local maximum in the first second |")
        _out = mo.md("\n".join(_lines))
    _out
    return


@app.cell(hide_code=True)
def acf_baseline_residual(
    RecurrenceVerdict,
    go,
    make_subplots,
    mo,
    np,
    recurrence,
    recurrence_error,
):
    # Exploratory only: separate a slowly varying ACF baseline from faster residual structure.
    # This does not alter `recurrence`, its backend peak list, or its period claim.
    _out = mo.md(
        "_No ACF residual: no recurrence result is available for the selected view._"
        + (f"\n\n`{recurrence_error}`" if recurrence_error else "")
    )
    if recurrence is not None and recurrence.verdict is RecurrenceVerdict.DEFINED:
        _lag_s = np.asarray(recurrence.lag_s, dtype=float)
        _acf = np.asarray(recurrence.acf, dtype=float)
        _sigma_s = 0.10
        _radius = max(1, int(np.ceil(4.0 * _sigma_s / recurrence.lag_resolution_s)))
        _offset_s = np.arange(-_radius, _radius + 1, dtype=float) * recurrence.lag_resolution_s
        _kernel = np.exp(-0.5 * (_offset_s / _sigma_s) ** 2)
        _kernel /= np.sum(_kernel)
        _baseline = np.convolve(
            np.pad(_acf, (_radius, _radius), mode="reflect"), _kernel, mode="valid"
        )
        _residual = _acf - _baseline
        _method = mo.md(
            rf"""
    ### Exploratory ACF residual

    This cell does **not** re-estimate the trace autocorrelation or change the backend
    period decision. It only decomposes the displayed ACF \(R(\tau)\) into a local smooth
    baseline and a residual:

    \[
    B(\tau) = (G_{{\sigma}} * R)(\tau), \qquad
    R_{{\mathrm{{residual}}}}(\tau) = R(\tau) - B(\tau),
    \]

    where \(G_{{\sigma}}\) is a unit-area Gaussian kernel with
    \(\sigma = {_sigma_s:.2f}\,\mathrm{{s}}\), evaluated on the existing lag grid and
    reflect-padded at the two ends. It is a visual high-pass separation: broad ACF
    structure remains in \(B\), while faster departures appear in the residual. It is
    not a fitted 2 s oscillation, a new recurrence estimator, or a period claim.
    """
        )
        _fig = make_subplots(
            rows=2,
            cols=1,
            vertical_spacing=0.15,
            subplot_titles=(
                "reported ACF and exploratory smooth baseline",
                "ACF residual after subtracting the smooth baseline",
            ),
        )
        _fig.add_trace(
            go.Scatter(
                x=_lag_s,
                y=_acf,
                mode="lines",
                name="reported normalized ACF",
                line=dict(color="#6D4C41", width=1.8),
            ),
            row=1,
            col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=_lag_s,
                y=_baseline,
                mode="lines",
                name=f"Gaussian baseline (σ={_sigma_s:.2f} s)",
                line=dict(color="#1E88E5", width=2.0),
            ),
            row=1,
            col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=_lag_s,
                y=_residual,
                mode="lines",
                name="ACF residual",
                line=dict(color="#FB8C00", width=1.8),
            ),
            row=2,
            col=1,
        )
        _fig.add_hline(y=0.0, line=dict(color="#B0BEC5", width=1.0), row=2, col=1)
        _fig.update_layout(
            title=(
                f"Exploratory ACF baseline separation · gate depth "
                f"{recurrence.depth_mm:.3f} mm · detrending "
                f"`{recurrence.detrending.value}`"
            ),
            height=620,
        )
        _fig.update_xaxes(title_text="lag [s]", row=2, col=1)
        _fig.update_yaxes(title_text="normalized ACF", row=1, col=1)
        _fig.update_yaxes(title_text="ACF residual", row=2, col=1)
        _out = mo.vstack([_method, mo.ui.plotly(_fig)])
    _out
    return


@app.cell(hide_code=True)
def acf_residual_spectrum(
    RecurrenceVerdict,
    go,
    mo,
    np,
    recurrence,
    recurrence_error,
):
    # Exploratory spectrum of the ACF residual. This is intentionally distinct from SA2.3's
    # trace periodogram: it is a compact way to inspect scales remaining after the ACF baseline
    # separation, not a second spectral estimator for the recorded velocity trace.
    _out = mo.md(
        "_No residual spectrum: no defined recurrence result is available for the selected view._"
        + (f"\n\n`{recurrence_error}`" if recurrence_error else "")
    )
    if recurrence is not None and recurrence.verdict is RecurrenceVerdict.DEFINED:
        _lag_s = np.asarray(recurrence.lag_s, dtype=float)
        _acf = np.asarray(recurrence.acf, dtype=float)
        _sigma_s = 0.10
        _radius = max(1, int(np.ceil(4.0 * _sigma_s / recurrence.lag_resolution_s)))
        _offset_s = np.arange(-_radius, _radius + 1, dtype=float) * recurrence.lag_resolution_s
        _kernel = np.exp(-0.5 * (_offset_s / _sigma_s) ** 2)
        _kernel /= np.sum(_kernel)
        _baseline = np.convolve(
            np.pad(_acf, (_radius, _radius), mode="reflect"), _kernel, mode="valid"
        )
        _residual = _acf - _baseline
        _window = np.hanning(_residual.size)
        _frequencies_hz = np.fft.rfftfreq(_residual.size, d=recurrence.lag_resolution_s)
        _magnitude = np.abs(np.fft.rfft((_residual - np.mean(_residual)) * _window))
        _nonzero_scale = float(np.max(_magnitude[1:]))
        _relative_magnitude = (
            _magnitude / _nonzero_scale
            if _nonzero_scale > 0.0
            else np.zeros_like(_magnitude)
        )
        _peak_indices = np.array(
            [
                _index
                for _index in range(1, _relative_magnitude.size - 1)
                if _relative_magnitude[_index] > _relative_magnitude[_index - 1]
                and _relative_magnitude[_index] >= _relative_magnitude[_index + 1]
            ],
            dtype=int,
        )
        _ranked_peak_indices = _peak_indices[
            np.argsort(_relative_magnitude[_peak_indices])[::-1]
        ]
        _method = mo.md(
            rf"""
    ### Exploratory residual-spectrum peaks

    This is the one-sided FFT magnitude of the **Gaussian-baseline residual** in the
    cell above. Before the transform, the residual mean is removed and a symmetric Hann
    window is applied to reduce the finite-lag endpoint discontinuity. The vertical scale
    is normalized to its largest non-zero-frequency bin, so it is for relative comparison
    only. Orange diamonds mark every strict adjacent-bin local maximum; the compact table
    lists the five strongest.

    It is **not** SA2.3's velocity PSD and it does not make a recurrence-period claim.
    It is an exploratory frequency view of the displayed finite ACF residual. Its bin
    spacing is \({_frequencies_hz[1]:.4f}\,\mathrm{{Hz}}\), so a bin's reciprocal period is
    only resolved to that finite-window grid.
    """
        )
        _figure = go.Figure()
        _figure.add_trace(
            go.Scatter(
                x=_frequencies_hz[1:],
                y=_relative_magnitude[1:],
                mode="lines",
                name="residual FFT magnitude",
                line=dict(color="#6D4C41", width=1.9),
                customdata=np.column_stack((1.0 / _frequencies_hz[1:],)),
                hovertemplate=(
                    "frequency %{x:.4f} Hz<br>period %{customdata[0]:.4f} s"
                    "<br>relative magnitude %{y:.3f}<extra></extra>"
                ),
            )
        )
        if _peak_indices.size:
            _figure.add_trace(
                go.Scatter(
                    x=_frequencies_hz[_peak_indices],
                    y=_relative_magnitude[_peak_indices],
                    mode="markers",
                    name="detected spectral peaks",
                    marker=dict(color="#FB8C00", size=9, symbol="diamond"),
                    customdata=np.column_stack((1.0 / _frequencies_hz[_peak_indices],)),
                    hovertemplate=(
                        "frequency %{x:.4f} Hz<br>period %{customdata[0]:.4f} s"
                        "<br>relative magnitude %{y:.3f}<extra></extra>"
                    ),
                )
            )
        _figure.update_layout(
            title=(
                f"Exploratory FFT of ACF residual · gate depth {recurrence.depth_mm:.3f} mm "
                f"· detrending `{recurrence.detrending.value}`"
            ),
            height=460,
            xaxis=dict(title="frequency [Hz]", range=[0.0, min(10.0, _frequencies_hz[-1])]),
            yaxis=dict(title="relative FFT magnitude [max = 1]"),
        )
        _lines = [
            "**Five strongest detected residual-spectrum peaks**",
            "",
            "| frequency [Hz] | reciprocal period [s] | relative magnitude |",
            "| ---: | ---: | ---: |",
        ]
        if _ranked_peak_indices.size:
            _lines.extend(
                f"| {_frequencies_hz[_index]:.4f} | "
                f"{1.0 / _frequencies_hz[_index]:.4f} | "
                f"{_relative_magnitude[_index]:.3f} |"
                for _index in _ranked_peak_indices[:5]
            )
        else:
            _lines.append("| — | — | no strict local maximum |")
        _out = mo.vstack([_method, mo.ui.plotly(_figure), mo.md("\n".join(_lines))])
    _out
    return


@app.cell(hide_code=True)
def sa1_notes(mo):
    mo.md("""
    **Reading SA1's preview.** Every view carries the view module's own label
    (`primary-comparison`, `full-record`, `exploration`) and its rule; the
    primary-comparison view is the pass's designed leading window cut by the
    recording's own stored stamps, and selecting the exploration view **adds** a
    labelled selection rather than replacing it. Depth is always the instrument's
    native gate coordinate in `mm` and colour/axis values are the signed axial
    velocity component in `mm/s`; both are never relabelled or interpolated. The
    statistics result keeps three depth extents apart — the pass's declared common
    support, the recording's own native grid, and the extent the selection actually
    participates in — and prints all three, so a number's depth range is never a
    guess.

    **What is deliberately not here.** No confidence interval appears anywhere: the
    profiles and gates of one recording are correlated samples, not independent
    replicates, so `sparse_gate_stats` computes no interval and `sparse_recurrence`
    computes none either. No spectrogram or sampling-support guard beyond SA2.3's own
    periodogram section (SA2), and no spatial correlation or POD (SA3). No period is
    claimed from a weak recurrence peak: the claim above states the threshold that
    refused it, and if the stored timestamps do not support a lag in seconds at all,
    the timebase verdict says so. The hypothesized ~1 s vortex timescale is *sought*,
    never assumed — nothing in this notebook names it, and SA2.3's spectrum is not
    offered as proof of it.
    """)
    return


@app.cell(hide_code=True)
def sa2_intro(mo):
    mo.md("""
    ## SA2.3 preview — one view's spectrum, its timebase/admission and its target support

    **SA2.3 adds no new spectral estimator and no scientific interpretation.** Everything
    below *displays* one already-merged backend result:
    `analysis.sparse_periodogram.periodogram_of_view` (SA2.2), asked of the **same**
    `WindowView` the heatmap, the gate statistics and the recurrence above were computed
    from, at the **same** gate the gate picker names and the **same** detrending the picker
    holds. There is no second time-window selector: the one window decision is
    `sparse_view`, and the admission the target rows are asked of is the one carried
    *inside* the returned `SpectralEstimate` — never a second admission derived here.

    The shape stays `selection → backend call → display`. No FFT call, no taper
    construction, no PSD normalization, no frequency-grid construction and no admission
    arithmetic live in a cell; every number stated is a field of a backend result
    (`SpectralEstimate`, its `TimebaseCharacterization`, its `SpectralAdmission`, its
    `ViewProvenance`, or a `TargetFrequencySupport`).

    **The detrending control is deliberately shared, and that coupling is stated.** SA1's
    recurrence and this spectrum read the *same* `detrending_picker`; the notebook does not
    silently re-point SA1's control, and each result names the detrending *it* used beside
    its own display (`SpectralEstimate.detrending` for the spectrum,
    `RecurrenceResult.detrending` for the trace above). It is an intentional coupling, not
    an accident — and because both then analyse the same gate trace, the two displays are
    comparable without the notebook fusing them. They are **two descriptive estimators of
    the same trace**, and this notebook never says one "confirms" the other.

    What is deliberately **not** here (SA2.4 / SA3): peak finding, automated frequency
    bands, low-frequency integrated-power metrics, condition-comparison tables,
    depth–frequency maps, cross-gate or cross-sitting spectra, Welch, coherence, modal/SVD
    analysis and serialization. The low-frequency view below is inspection only: no
    dominant frequency is named, no peak is picked, and no band power is compared.
    """)
    return


@app.cell(hide_code=True)
def sa2_controls(mo):
    # A DISPLAY-ONLY control. It changes the PSD plot's x-limits and nothing else: the
    # estimator already ran on the full view inside the backend, and the zoom neither
    # truncates, resamples nor re-estimates the array it is drawn from. `0` means the full
    # supported range, which is the default extent the plan asks for.
    psd_zoom_max_hz = mo.ui.number(
        value=0.0,
        start=0.0,
        stop=1000.0,
        step=0.1,
        label=(
            "PSD display zoom: upper x-limit [Hz] (display only — 0 shows the full "
            "supported range)"
        ),
        full_width=True,
    )
    mo.sidebar([mo.md("### SA2.3 spectral preview"), psd_zoom_max_hz])
    return (psd_zoom_max_hz,)


@app.cell(hide_code=True)
def sa2_spectral_estimate(
    SparseViewError,
    SpectralPeriodogramError,
    detrending_picker,
    gate_stats,
    periodogram_of_view,
    point,
    position,
    sparse_view,
):
    # SA2.3's **backend call**: one view, one gate depth, one detrending. `periodogram_of_view`
    # is SA2.2's single entry point and it takes NO arrays — the trace is the selected view's
    # own column at that depth, over the view's own stored stamps — and the quantity/unit are
    # passed explicitly exactly as SA1's recurrence call already does, so the spectrum names
    # its own measured quantity instead of relying on the signature defaults.
    #
    # The notebook computes no FFT, builds no taper, derives no frequency grid and applies no
    # normalization: the spectrum *is* the returned `SpectralEstimate`.
    #
    # A **refused axis is not an exception**: the estimator returns a `SpectralEstimate`
    # whose verdict is `refused-irregular-axis`, whose arrays are empty and whose carried
    # admission names the failed conditions. The `except` below is only for a request that
    # cannot produce a result at all — a depth that is not a native gate, a depth outside
    # the pass's common support, an unknown detrending, stamps a characterization cannot be
    # built from — never for a scientific refusal.
    spectral_estimate = None
    spectral_error = ""
    if (
        sparse_view is not None
        and gate_stats is not None
        and position is not None
        and point is not None
    ):
        _depth = float(gate_stats.depths_mm[position])
        try:
            spectral_estimate = periodogram_of_view(
                sparse_view,
                depth_mm=_depth,
                quantity=str(point.quantity),
                unit=str(point.unit),
                detrending=detrending_picker.value,
            )
        except (SpectralPeriodogramError, SparseViewError) as exc:
            spectral_error = f"{type(exc).__name__}: {exc}"
    return spectral_error, spectral_estimate


@app.cell(hide_code=True)
def sa2_target_support(
    PROBE_TARGETS,
    SpectralSupportError,
    spectral_estimate,
    target_frequency_support,
):
    # The two probe targets SA2 names once (`sparse_spectral_capability.PROBE_TARGETS`): the
    # ~1 Hz recurrence-scale probe and the 25/3 Hz nominal rotor reference. Each row is asked
    # of the admission carried INSIDE the returned estimate — never a second admission built
    # here — so the row and the spectrum cannot disagree about the axis.
    #
    # A `REFUSED_AXIS` estimate carries no admission-granted spectrum, so its rows are asked
    # on the characterized stamps for the *band* question and report the estimator refusal
    # through `analysis_supported` / `reason`. Keeping `band_supported` and `supported` apart
    # is what stops a bandwidth refusal being read as an estimator inability, or the reverse.
    target_support_rows = ()
    target_support_error = ""
    if spectral_estimate is not None:
        try:
            target_support_rows = tuple(
                target_frequency_support(
                    spectral_estimate.admission, frequency_hz, label=label
                )
                for label, frequency_hz in PROBE_TARGETS
            )
        except SpectralSupportError as exc:
            target_support_error = f"{type(exc).__name__}: {exc}"
    return target_support_error, target_support_rows


@app.cell(hide_code=True)
def sa2_spectrum_readout(
    dataset_picker,
    gate_stats,
    mo,
    position,
    position_note,
    sparse_view,
    sparse_view_error,
    spectral_error,
    spectral_estimate,
):
    # What this spectrum is, and what allowed it. Every value is read off the returned
    # `SpectralEstimate` or off the characterization / admission / provenance it carries;
    # nothing is recomputed and no admission arithmetic is repeated here.
    #
    # The unavailable and refused states are kept apart on purpose (plan §K). "No view", "no
    # resolved gate" and "the request could not produce a result" are **not** spectral
    # verdicts, and a refused axis is a verdict that carries no density at all. A missing
    # view is never rendered as a spectral refusal, and a refusal is never rendered as a zero
    # spectrum — the two are distinguishable because the branch is on the *verdict*, not on
    # the values.

    def _shown(value, unit="", none_text="undefined"):
        """A backend field for display: `None` reads as undefined, never as a zero."""
        return none_text if value is None else f"{value:.6g}{unit}"

    if sparse_view is None:
        _out = mo.md(
            "**SA2.3 — no spectrum: the view module refused this selection.** This is not a "
            "spectral verdict; no estimator ran, so there is no PSD, no zero line and no "
            "axis to show.\n\n"
            + (f"`{sparse_view_error}`" if sparse_view_error else "")
        )
    elif gate_stats is None or position is None:
        _out = mo.md(
            "**SA2.3 — no spectrum: no gate is resolved for this view.** "
            + (
                "`gate_statistics` returned nothing"
                if gate_stats is None
                else "the per-gate statistics are present"
            )
            + " and the picked gate position is "
            + ("absent" if position is None else "present")
            + ", so there is no depth to ask `periodogram_of_view` at. This is the "
            "notebook's own stated absence, deliberately kept distinct from a spectral "
            "refusal."
        )
    elif spectral_estimate is None:
        _out = mo.md(
            "**SA2.3 — no spectrum: the request itself could not produce a result.** A "
            "depth that is not one of this view's native gates, a depth outside the pass's "
            "common support, an unknown detrending or stamps a characterization cannot be "
            "built from is a malformed request, not a scientific refusal.\n\n"
            f"`{spectral_error}`"
        )
    else:
        _est = spectral_estimate
        _prov = _est.provenance
        _axis = _est.characterization
        _adm = _est.admission
        _conditions = "\n".join(
            f"  - `{item.condition.value}`: "
            + ("satisfied" if item.satisfied else "**failed**")
            + f" — observed {_shown(item.observed)}, threshold {_shown(item.threshold)}"
            for item in _adm.conditions
        )
        _declared = (
            f"declared {_prov.declared_window_s:g} s"
            if _prov.declared_window_s is not None
            else "no declared interval (a bounds-selected or full-record view)"
        )
        _trend = (
            f"{_est.linear_trend_per_s!r} {_est.unit}/s removed by the estimator"
            if _est.linear_trend_per_s is not None
            else "no linear trend was removed (the `mean` and `none` detrendings remove none)"
        )
        _lines = [
            f"**SA2.3 spectrum — `{_prov.point_label}` · gate depth {_est.depth_mm:.3f} mm · "
            f"view `{_prov.view.value}`** · {_prov.view_rule}",
            "",
            "**Provenance** — every field read from the object that already owns it:",
            f"- **pass**: `{dataset_picker.value}` — the notebook's own selection from "
            "`analysis.sparse_passes`. The pass is **not** a `ViewProvenance` field and is "
            "not presented as one; the spectrum's own recording identity is the fields "
            "below.",
            f"- job `{_prov.job}` · point label `{_prov.point_label}` · order {_prov.order}",
            f"- source `{_prov.relative_path}` · sha256:{_prov.source_sha256}",
            f"- view `{_prov.view.value}` · window {_prov.window_start_s:.4f}–"
            f"{_prov.window_end_s:.4f} s (span {_prov.window_s:.4f} s; {_declared})",
            f"- gate/depth: view column {_est.gate_index} · depth {_est.depth_mm:.3f} mm "
            "(the instrument's native gate coordinate)",
            f"- quantity `{_est.quantity}` [{_est.unit}] · PSD unit `{_est.psd_unit}`",
            f"- detrending `{_est.detrending.value}` — {_trend}",
            f"- estimator: {_est.estimator_name}",
            f"- taper `{_est.taper_name}` — {_est.taper_convention}",
            f"- normalization: {_est.normalization_rule}",
            f"- one-sided folding: {_est.one_sided_rule}",
            "",
            "**Timebase of this actual view's own stamps** (the axis quantities, read off "
            "the characterization the result carries):",
            f"- N **{_est.profiles}** profiles · actual span "
            f"{_shown(_est.span_s, ' s')} · dt_eff {_shown(_est.dt_eff_s, ' s')} · "
            f"fs_eff {_shown(_est.effective_sample_rate_hz, ' Hz')}",
            f"- Nyquist **{_shown(_est.nyquist_hz, ' Hz')}** (a bin sits exactly at Nyquist: "
            f"{_est.nyquist_is_represented}) · bin spacing delta_f "
            f"{_shown(_est.delta_f_hz, ' Hz')} = fs_eff / N, which is **not** `1 / span` · "
            f"1/span duration scale {_shown(_axis.duration_resolution_scale_hz, ' Hz')}",
            f"- first/last stored stamp: {_shown(_axis.start_s, ' s')} … "
            f"{_shown(_axis.end_s, ' s')} · median adjacent interval "
            f"{_shown(_axis.median_interval_s, ' s')} (a timestamp diagnostic — never the "
            "sample rate)",
            "",
            f"**Admission — `{'admitted' if _adm.admitted else 'refused'}`** · "
            f"verdict `{_est.verdict.value}`",
            f"- {_adm.reason}",
            f"- the operand admission rests on: **max relative timing error "
            f"{_shown(_adm.max_relative_timing_error)} effective interval(s)** "
            f"({_shown(_adm.max_timing_error_s, ' s')}) against the calibrated tolerance "
            f"**{_adm.spectral_uniformity_tol:g}** ({_adm.timing_error_admission})",
            f"- sample floor: {_adm.min_samples} · condition verdicts, in policy order:",
            _conditions,
            f"- secondary diagnostics (the design's own, not the threshold): max relative "
            f"interval deviation {_shown(_adm.max_relative_interval_deviation)} · largest "
            f"gap ratio {_shown(_adm.largest_gap_ratio)} · {_adm.interval_deviation_role}",
        ]
        if _est.psd.size == 0:
            _lines += [
                "",
                "**No density is published for this axis** — a refused axis carries empty "
                "`frequency_hz` / `psd` arrays, and the fields below are `None` rather than "
                "`0.0`, so nothing here can be read as a measurement that was not made.",
            ]
        else:
            _lines += [
                "",
                "**Descriptive quantities of the defined spectrum** (secondary — available, "
                "not headline):",
                f"- integrated PSD power `sum(Pxx) * delta_f` "
                f"{_shown(_est.integrated_psd_power, ' (' + _est.unit + ')^2')} · "
                f"window-normalized mean-square power "
                f"{_shown(_est.window_normalized_mean_square_power, ' (' + _est.unit + ')^2')}",
                f"- taper ENBW: {_shown(_est.enbw_bins, ' bins')} = "
                f"{_shown(_est.enbw_hz, ' Hz')}",
                f"- Parseval residual (relative) {_shown(_est.parseval_relative_error)} — "
                "this is a **numerical QA field, not a scientific observable**: it checks "
                "the fold and the normalization against each other, it is not plotted as a "
                "headline and it is not compared across jobs.",
                f"- window-normalized power relation: {_est.parseval_rule}",
            ]
        _block = mo.md("\n".join(_lines))
        _out = (
            mo.vstack([mo.callout(mo.md(position_note), kind="warn"), _block])
            if position_note
            else _block
        )
    _out
    return


@app.cell(hide_code=True)
def sa2_spectrum_figure(
    SpectralVerdict,
    go,
    make_subplots,
    mo,
    np,
    position_note,
    psd_zoom_max_hz,
    sparse_view,
    spectral_estimate,
    target_support_rows,
):
    # The stored trace beside the one-sided PSD, drawn straight from the backend's own
    # arrays. The trace is the view's own stored column the estimator cut its samples from,
    # drawn raw; the estimator's detrending runs *inside* `periodogram_of_view` and is
    # reported (and plotted on the SA1 recurrence figure above as the module's own analysed
    # series) rather than re-applied here, because re-deriving it would be notebook-side
    # spectral arithmetic.
    #
    # A refused axis is rendered as its refusal and **never as an empty or zero plot**: a
    # zero spectrum is a measurement, and a refused axis was not measured.
    #
    # Target markers are drawn **only where the backend says the target is supported** —
    # i.e. only inside the measurable band — so a target above this axis's Nyquist frequency
    # is not drawn inside the PSD axes as though it were part of the measured range.
    _out = mo.md(
        "**No PSD is drawn.** No view, no resolved gate or no estimator result for this "
        "selection — the SA2.3 readout above carries the module's own statement."
    )
    if spectral_estimate is not None and sparse_view is not None:
        _est = spectral_estimate
        if _est.verdict is not SpectralVerdict.DEFINED:
            _failed = "\n".join(
                f"  - `{item.condition.value}`: {item.rule}"
                for item in _est.admission.conditions
                if not item.satisfied
            )
            _out = mo.md(
                f"**Spectrum refused — verdict `{_est.verdict.value}`.** The estimator "
                "declined this axis and returned **no density and no frequency axis** (both "
                "arrays are empty). This is deliberately *not* drawn as a zero or empty "
                "line: a zero spectrum is a measurement, and this axis was not measured.\n\n"
                f"- estimator: {_est.estimator_name}\n"
                f"- why: **{_est.admission.reason}**\n"
                f"- failed condition(s):\n{_failed}"
            )
        else:
            _time = np.asarray(sparse_view.time_s, dtype=float)
            _values = np.asarray(sparse_view.values, dtype=float)
            _fig = make_subplots(
                rows=2, cols=1, vertical_spacing=0.15,
                subplot_titles=(
                    "the stored trace the spectrum was cut from (raw as stored; view column "
                    f"{_est.gate_index} · depth {_est.depth_mm:.3f} mm)",
                    f"one-sided PSD [{_est.psd_unit}]",
                ),
            )
            _fig.add_trace(
                go.Scatter(
                    x=_time, y=_values[:, _est.gate_index], mode="lines",
                    name="stored trace (raw, not re-detrended here)",
                    line=dict(color="#546E7A", width=1.4),
                ),
                row=1, col=1,
            )
            _fig.add_trace(
                go.Scatter(
                    x=_est.frequency_hz, y=_est.psd, mode="lines",
                    name="PSD (as returned by periodogram_of_view)",
                    line=dict(color="#1E88E5", width=1.8),
                ),
                row=2, col=1,
            )
            _marked = []
            for _target in target_support_rows:
                if _target.supported:
                    _fig.add_vline(
                        x=float(_target.target_hz),
                        line=dict(color="#43A047", width=1.6, dash="dot"),
                        row=2, col=1,
                        annotation_text=f"{_target.target_label} · {_target.target_hz:g} Hz",
                    )
                    _marked.append(f"`{_target.target_label}` at {_target.target_hz:g} Hz")
            _zoom = float(psd_zoom_max_hz.value or 0.0)
            if _zoom > 0.0:
                _fig.update_xaxes(range=[0.0, _zoom], row=2, col=1)
            _fig.update_layout(
                title=(
                    f"{_est.provenance.point_label} · view "
                    f"`{_est.provenance.view.value}` · N {_est.profiles} · span "
                    f"{_est.span_s:.4f} s · Nyquist {_est.nyquist_hz:.4f} Hz · detrending "
                    f"`{_est.detrending.value}` · verdict `{_est.verdict.value}`"
                ),
                height=720,
            )
            _fig.update_xaxes(
                title_text="time from the record's first stored profile [s]", row=1, col=1
            )
            _fig.update_yaxes(title_text=f"velocity [{_est.unit}]", row=1, col=1)
            _fig.update_xaxes(title_text="frequency [Hz]", row=2, col=1)
            _fig.update_yaxes(title_text=f"PSD [{_est.psd_unit}]", row=2, col=1)
            _caption = (
                "The PSD is drawn directly from the backend's own `frequency_hz` / `psd` "
                f"arrays over the full supported range 0–{float(_est.frequency_hz[-1]):.4f} Hz. "
                + (
                    f"**Zoomed to 0–{_zoom:g} Hz by a display-only control**: the plot limits "
                    "changed, the estimator input did not, and the underlying density is not "
                    "truncated or re-estimated. "
                    if _zoom > 0.0
                    else ""
                )
                + "Target markers added (only where the backend's own "
                "`TargetFrequencySupport.supported` is true): "
                + (", ".join(_marked) if _marked else "none")
                + ". Refused targets are surfaced in the target-support panel below and are "
                "deliberately **not** drawn inside the axis; the full axis ending below them "
                "reinforces that. A spectrum whose density were identically zero would still "
                "be drawn as a measured zero — `defined` and `refused` are distinguished by "
                "the verdict, never by the values."
            )
            _out = mo.vstack(
                [
                    mo.callout(mo.md(position_note), kind="warn"),
                    mo.ui.plotly(_fig),
                    mo.md(_caption),
                ]
                if position_note
                else [mo.ui.plotly(_fig), mo.md(_caption)]
            )
    _out
    return


@app.cell(hide_code=True)
def sa2_target_readout(
    mo,
    spectral_estimate,
    target_support_error,
    target_support_rows,
):
    # The target-frequency rows. Each row shows overall supported/refused, band support,
    # analysis (admission) support, the target, the axis Nyquist, the nearest prospective
    # bin, the bin offset, the frequency resolution, `cycles_in_view` for *this* actual view
    # and the reason — all of them fields of the `TargetFrequencySupport` the backend
    # returned, plus the two reasons quoted verbatim rather than paraphrased.
    def _shown(value, unit=""):
        """A backend field for display: `None` (no grid to locate the target on) reads
        as an em dash, never as a zero."""
        return "—" if value is None else f"{value:.6g}{unit}"

    if spectral_estimate is None:
        _out = mo.md(
            "_No target rows: no spectrum was produced for this selection._"
        )
    elif target_support_error:
        _out = mo.md(f"**No target rows:** `{target_support_error}`")
    else:
        _rows = []
        _details = []
        for _target in target_support_rows:
            _rows.append(
                f"| `{_target.target_label}` | {_target.target_hz:g} | "
                f"**{'supported' if _target.supported else 'unsupported'}** | "
                f"{_target.band_supported} | {_target.analysis_supported} | "
                f"{_shown(_target.nyquist_hz, ' Hz')} | "
                f"{_shown(_target.prospective_bin)} | "
                f"{_shown(_target.prospective_bin_hz, ' Hz')} | "
                f"{_shown(_target.bin_offset_hz, ' Hz')} | "
                f"{_shown(_target.bin_offset_bins, ' bins')} | "
                f"{_shown(_target.frequency_resolution_hz, ' Hz')} | "
                f"{_shown(_target.cycles_in_view, ' cycles')} |"
            )
            _details.append(
                f"- **`{_target.target_label}` — {_target.target_hz:g} Hz**: "
                f"{'supported' if _target.supported else 'unsupported'} on this axis. "
                f"Reason (the backend's own): {_target.reason}\n"
                f"  - band support: {_target.band_supported} · analysis (admission) "
                f"support: {_target.analysis_supported}\n"
                f"  - band reason, quoted verbatim: \"{_target.band_reason}\"\n"
                f"  - analysis reason, quoted verbatim: \"{_target.analysis_reason}\""
            )
        _detail_lines = "\n\n".join(_details)
        _table = "\n".join(
            [
                "| target | target [Hz] | overall | band-supported | analysis-supported | "
                "Nyquist [Hz] | nearest bin | bin frequency | bin offset | bin offset "
                "[bins] | Δf [Hz] | cycles in this view |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            + _rows
        )
        _refused_note = (
            ""
            if any(_t.analysis_supported for _t in target_support_rows)
            else "\n\nThe estimator **refused this axis**, so its rows report the estimator "
            "refusal through analysis support and the reason above — while the band "
            "question is still answered from the characterized stamps, because it needs no "
            "estimator."
        )
        _out = mo.md(
            f"**Target-frequency rows — asked of the admission carried inside this "
            f"`SpectralEstimate`** (never a second admission derived in the notebook). Rows "
            f"are `sparse_spectral_capability.PROBE_TARGETS`, in the order SA2 names them. "
            f"`cycles_in_view` is `target_hz * span_s` on *this* view's own span — an "
            f"interpretation-quality diagnostic that refuses nothing.\n\n"
            f"{_table}\n\n{_detail_lines}{_refused_note}\n\n"
            "**Wording rule (binding):** `unsupported at 8.333 Hz` ⇏ `no 8.333-Hz signal`. "
            "The first is a statement about this axis and this window; the second would be a "
            "claim about the flow, which this stage does not make. Where a target is refused "
            "for being **at or above this axis's Nyquist frequency**, those are the backend's "
            "own words (quoted above, not paraphrased), and the Nyquist value quoted is the "
            "adopted-rate Nyquist this view's own characterization published — never a value "
            "the notebook derived.\n\n"
            "**Sampling-support caveat (binding).** A supported verdict is a "
            "*sampling-support statement for the stored profile sequence*: it means the "
            "sequence can represent that frequency without the basic Nyquist impossibility. "
            "It does **not** mean the amplitude is unbiased, that higher-frequency content "
            "cannot alias into it, or that the emissions/profile sequence carries no "
            "temporal averaging at that frequency. No temporal transfer function and no "
            "instrument anti-alias response is resolved anywhere in SA2, so a target inside "
            "the band is never worded as a measured, calibrated or anti-aliased amplitude. "
            "This matters most for the fastest-emissions configuration here whose target "
            "sits closest to its band edge."
        )
    _out
    return


@app.cell(hide_code=True)
def sa2_notes(mo):
    mo.md("""
    **Reading SA2.3's preview.** The spectrum belongs to **one** view — the label selected
    in the sidebar, cut by the view module's own constructors — and the admission summary,
    the density, the target rows and the provenance all come from that one
    `SpectralEstimate` and the `ViewProvenance` it carries. Switching the view control
    visibly updates N, span, `delta_f`, the cycle counts, the PSD and every target-support
    field; a full-record spectrum is never presented under the primary-comparison label,
    and the two views' spans here are numerically close, which is exactly why they are
    labelled rather than assumed. Switching the gate or the detrending re-calls the
    backend, and the result names the gate depth and the detrending it used.

    **The four display states, kept distinct.** An *admitted* spectrum shows its PSD. A
    *spectrally refused* axis shows the admission's failed conditions and **no empty or
    zero plot**. A target *above Nyquist* still shows the PSD where the estimator is
    admitted, with the target marked unsupported in the panel below and **not** drawn
    inside the axes. A *constant signal* would be a valid zero spectrum shown as zero, not
    as a refusal — the branch is on the verdict, never on the values. Before any estimate
    can exist, a missing view or an unresolved gate is shown as the notebook's own stated
    absence, with no PSD, no zero line and no fabricated axis.

    **The stale-gate guard reaches this display too.** If a view change leaves the
    previously picked gate outside the new view, `position_note` resolves the position to
    the middle supported gate and **says so**; the spectrum is then computed at that
    fallback gate with the note shown beside it, rather than silently drawing a spectrum
    for a gate other than the one named.

    **Low-frequency inspection only.** The zoom above exists so a reader can look at the
    first few Hz. No peak is picked, no "dominant" frequency is named, no band power is
    integrated or compared, and no recurrence label is inferred from the spectrum. The
    autocorrelation and the PSD are two descriptive estimators of the same trace and are
    not numerically fused in this stage.
    """)
    return


if __name__ == "__main__":
    app.run()
