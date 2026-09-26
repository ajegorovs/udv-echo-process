import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


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

    return (
        COMMITTED_PASSES,
        Detrending,
        RecurrenceError,
        RecurrenceVerdict,
        RunPlanError,
        SparseGateStatsError,
        SparseIngestError,
        SparseViewError,
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
        point_qc,
        primary_view,
        recurrence_of_view,
        reduce_equal_weight,
        reduce_native_slab,
        retains_designed_window,
        statistic_units,
    )


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Sparse signal explorer — SA0 checkpoint + SA1 preview

    The **first usable checkpoint** of the sparse signal analysis: dataset → job →
    recording → channel selection over the **committed** sparse passes, the selected
    recording's provenance/QC, its **native time–depth heatmap**, and below it
    **SA1's preview** — per-gate mean and variability profiles, representative gate
    traces and time slices, the reported per-gate distributions, and the normalized
    trace autocorrelation with its raw trace. The default selection is the second
    mixer-enabled sitting, `sparse-mixer-live-2`.

    This notebook is a **thin wrapper**: every number comes from tested functions in
    `src/udv_echo_process/`. Four backend modules do the work and the notebook owns
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

    Here the notebook only *selects* (pass, job, recording, channel, view, gate,
    detrending, exploration bounds) and *displays*; it computes no mean, percentile,
    standard deviation, correlation, reduction or window of its own, and it holds no
    pass table, no view translation map and no reference row of its own. A view reads
    the same way in this notebook as inside the two modules that produce the numbers —
    one label, one rule, no second spelling.

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
    autocorrelation below are SA1's views and appear only beside the tested
    estimators that produce them; spectra and spectrograms (SA2), spatial
    correlation and POD (SA3) are still absent. These `.BDD` velocity files carry
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
def heatmap(decoding, go, mo, np, point, sparse_view, sparse_view_error):
    # The native time–depth heatmap of **the one shared view**: the same `WindowView`
    # object the SA1 statistics and the autocorrelation below are computed from, so the
    # block on screen and every number under it come from one cut. There is no second
    # "full record" control here any more — the view dropdown in the sidebar is the only
    # place a cut is chosen, and `sa1_view_label` prints that module's own label and rule.
    #
    # The view's own columns are plotted: the supported gates the statistics reduce over,
    # not the recording's whole native grid, because drawing gates that are in no
    # statistic would invite reading a row that no number below uses. The transposition is
    # x = time, y = the instrument's own gate coordinate. No derived quantity is plotted
    # and no physics is overlaid; the stride and the symmetric colour axis are drawing
    # choices, not measurements.
    _out = mo.md("_No view selected — nothing to plot._")
    if sparse_view is None:
        if sparse_view_error:
            _out = mo.md(
                "**No heatmap: the view module refused the current selection.** Its own "
                f"statement, unchanged:\n\n`{sparse_view_error}`"
            )
    else:
        _time = np.asarray(sparse_view.time_s, dtype=float)
        _values = np.asarray(sparse_view.values, dtype=float)
        _stride = max(1, _time.size // 800)
        _z = _values[::_stride].T
        if point.quantity == "axial_velocity":
            # Signed velocity is symmetric about zero, so the colour axis is forced
            # symmetric: an autoscaled range would put white somewhere other than zero.
            _scale = float(np.nanmax(np.abs(_z))) or 1.0
            _kw = dict(zmin=-_scale, zmax=_scale, colorscale="RdBu_r")
        else:
            _kw = dict(colorscale="Viridis")
        _fig = go.Figure(
            go.Heatmap(
                x=_time[::_stride],
                y=np.asarray(sparse_view.depths_mm, dtype=float),
                z=_z,
                colorbar={"title": f"{point.quantity} [{point.unit}]"},
                **_kw,
            )
        )
        _fig.update_layout(
            title=(
                f"{point.binding.identity} — ch{decoding.plan.channel} · "
                f"{point.quantity} [{point.unit}] · view `{sparse_view.view.value}` · "
                f"{sparse_view.supported_columns.size} supported of "
                f"{sparse_view.native_gates} native gates · "
                f"{'every profile' if _stride == 1 else f'every {_stride}th profile'} shown"
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

    **Not shown here, on purpose.** Spectra/spectrograms and sampling support (SA2)
    and spatial correlation/POD (SA3) are absent: each is added only alongside the
    tested estimator and sampling guard that produce it. Gate traces, per-gate
    profiles, per-gate distributions and the normalized autocorrelation are now in
    **SA1's section below**, where the tested estimators that return them are named
    beside every display. The primary/exploratory label on every view is the same rule
    the later slices inherit.
    """)
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
def sa1_view_controls(Detrending, VIEW_LABELS, VIEW_PRIMARY, VIEW_RULES, decoding, mo):
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
    mo.sidebar(
        [
            mo.md("### SA1 view"),
            gate_view,
            detrending_picker,
            mo.md("### SA1 exploration bounds (used only by the exploration view)"),
            explore_time_start,
            explore_time_end,
            explore_depth_low,
            explore_depth_high,
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
    explore_depth_high,
    explore_depth_low,
    explore_time_end,
    explore_time_start,
    exploration_view,
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
def gate_stats_result(SparseGateStatsError, gate_statistics, sparse_view):
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
def gate_profile_figure(gate_stats, go, make_subplots, mo, np, statistic_units):
    # Per-gate mean and variability profiles over the instrument's native depth. Every
    # x value is a row the statistics result returned (`mean`, `q25`, `q75`, `std`,
    # `mad_scaled`) and every unit is the module's own (`statistic_units`); this cell
    # selects rows and draws them, it computes nothing. The quantile band is the frozen
    # `q25`/`q75` pair — the same numbers as `median ± iqr/2` — so it cannot disagree
    # with the frozen table.
    _out = mo.md("_No per-gate profiles: no statistics to plot._")
    if gate_stats is not None:
        _depths = np.asarray(gate_stats.depths_mm, dtype=float)
        _prov = gate_stats.provenance
        _fig = make_subplots(
            rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.09,
            subplot_titles=(
                f"per-gate mean with the reported q25–q75 band "
                f"[{statistic_units('mean')}]",
                f"per-gate variability [{statistic_units('std')}]",
            ),
        )
        _fig.add_trace(
            go.Scatter(
                x=gate_stats.of("q25"), y=_depths, mode="lines", name="q25",
                line=dict(color="#90CAF9", width=1.0),
            ),
            row=1, col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=gate_stats.of("q75"), y=_depths, mode="lines",
                name="q75 (band = the reported interquartile range)",
                line=dict(color="#90CAF9", width=1.0), fill="tonexty",
                fillcolor="rgba(144,202,249,0.35)",
            ),
            row=1, col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=gate_stats.of("mean"), y=_depths, mode="lines",
                name="mean (signed axial velocity)",
                line=dict(color="#1E88E5", width=2.4),
            ),
            row=1, col=1,
        )
        _fig.add_trace(
            go.Scatter(
                x=gate_stats.of("std"), y=_depths, mode="lines",
                name=f"std (population, ddof={gate_stats.std_ddof})",
                line=dict(color="#E53935", width=1.9),
            ),
            row=1, col=2,
        )
        _fig.add_trace(
            go.Scatter(
                x=gate_stats.of("mad_scaled"), y=_depths, mode="lines",
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
            height=560,
        )
        _fig.update_yaxes(title_text="native gate depth [mm]", row=1, col=1)
        _fig.update_xaxes(
            title_text="signed axial velocity [mm/s]", row=1, col=1
        )
        _fig.update_xaxes(title_text="variability [mm/s]", row=1, col=2)
        _out = mo.ui.plotly(_fig)
    _out
    return


@app.cell(hide_code=True)
def depth_reduction_table(
    SparseGateStatsError, gate_stats, mo, reduce_equal_weight, reduce_native_slab
):
    # The depth reductions are `sparse_gate_stats` calls, so the scalar arrives with its
    # weighting, its weights and the two extents it declares (the gates it actually
    # reduced, and the support the native-slab cells were clipped to). The per-gate rows
    # above stay on screen: the reduction is one scalar beside the profile, never a
    # replacement for it. A statistic the module reports as undefined is refused by the
    # reduction, and its refusal is printed as it comes back.
    _out = mo.md("_No depth reduction: no per-gate statistics._")
    if gate_stats is not None:
        _depths = gate_stats.depths_mm
        _support = gate_stats.provenance.pass_support_mm
        _rows: list[str] = []
        _rules: dict[str, str] = {}
        for _name in ("mean", "std"):
            _values = gate_stats.of(_name)
            _weightings = (
                (
                    "equal",
                    lambda values=_values, name=_name: reduce_equal_weight(
                        values, statistic=name, depths_mm=_depths
                    ),
                ),
                (
                    "native-slab",
                    lambda values=_values, name=_name: reduce_native_slab(
                        values, depths_mm=_depths, statistic=name, support_mm=_support
                    ),
                ),
            )
            for _label, _call in _weightings:
                try:
                    _reduction = _call()
                except SparseViewError as exc:
                    _rows.append(
                        f"| `{_name}` | *(refused)* | **refused**: {exc} | "
                        "— | — | — | — | — |"
                    )
                    continue
                _slab = (
                    f"{_reduction.slab_support_mm[0]:.3f}–"
                    f"{_reduction.slab_support_mm[1]:.3f} mm"
                    if _reduction.slab_support_mm is not None
                    else "— (equal weighting clips nothing)"
                )
                _rows.append(
                    f"| `{_reduction.statistic}` | {_reduction.weighting} | "
                    f"{_reduction.value:.6f} | {_reduction.units} | "
                    f"{_reduction.gates} | {_reduction.weight_sum:.6f} | "
                    f"{_reduction.gate_extent_mm[0]:.3f}–"
                    f"{_reduction.gate_extent_mm[1]:.3f} mm | {_slab} |"
                )
                _rules.setdefault(_reduction.weighting, _reduction.weighting_rule)
        _table = "\n".join(
            [
                "| statistic | weighting | value | unit | gates | weight sum | "
                "reduced gate extent | slab support clipped to |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            + _rows
        )
        _rule_lines = "\n".join(
            f"- **{_weighting}** — {_text}" for _weighting, _text in _rules.items()
        )
        _out = mo.md(
            f"**Declared depth reductions of the `{gate_stats.provenance.view.value}` "
            f"view** (over the {_depths.size} supported gates, "
            f"{_depths[0]:.3f}–{_depths[-1]:.3f} mm)\n\n{_table}\n\n{_rule_lines}"
        )
    _out
    return


@app.cell(hide_code=True)
def gate_picker_cell(gate_stats, mo):
    # The gate selector for the trace, distribution and recurrence displays. Its options
    # are the statistics result's own supported gates — the depth the result reports,
    # with the gate's position among those columns — and its value is that position, so
    # every consumer reads a row of the result it was shown rather than recomputing a
    # gate index of its own. It is selection, not a statistic.
    if gate_stats is not None:
        _depths = [float(depth) for depth in gate_stats.depths_mm]
        _options = {
            f"depth {depth:.3f} mm · supported gate {position + 1} of {len(_depths)}": (
                position
            )
            for position, depth in enumerate(_depths)
        }
        gate_picker = mo.ui.dropdown(
            options=_options,
            value=list(_options)[len(_options) // 2],
            label="Gate (SA1)",
            full_width=True,
        )
    else:
        gate_picker = mo.ui.dropdown(
            options=[], value=None, label="Gate (SA1)", full_width=True
        )
    mo.sidebar([mo.md("### Gate (SA1)"), gate_picker])
    return (gate_picker,)


@app.cell(hide_code=True)
def gate_position(gate_picker, gate_stats, np):
    # The picked position, resolved once against the result it currently addresses.
    #
    # This cell exists because a marimo widget keeps its value when its options change:
    # moving to a narrower view — an exploration window, or one whose support drops gates —
    # rebuilds the picker with fewer entries while the stored value stays where it was, so
    # a consumer indexing with `gate_picker.value` directly would read past the end of the
    # result and raise inside a figure. The guard falls back to the middle supported gate
    # and *says so*, rather than silently showing a different gate than the one named.
    position = None
    position_note = ""
    if gate_stats is not None and gate_picker.value is not None:
        _picked = int(gate_picker.value)
        _count = int(np.asarray(gate_stats.depths_mm).size)
        if 0 <= _picked < _count:
            position = _picked
        elif _count > 0:
            position = _count // 2
            position_note = (
                f"the gate position selected before this view change ({_picked}) is not in "
                f"this view, which has {_count} supported gate(s): the middle one is shown"
            )
    return position, position_note


@app.cell(hide_code=True)
def gate_trace_figure(gate_stats, go, mo, np, position, position_note, sparse_view):
    # Representative gate traces: the view's own sampled columns, drawn against the
    # view's own stored timestamps. The three representatives are index picks
    # (shallowest, median-depth, deepest supported gate) over the view's own
    # `supported_columns`, and the selected gate is drawn on top — its column resolved
    # from the depth the statistics result reported, by the view's own `column_of_depth`.
    # No trace is averaged, smoothed or decimated.
    _out = mo.md("_No gate traces: no view to read._")
    if sparse_view is not None and gate_stats is not None and position is not None:
        _values = np.asarray(sparse_view.values, dtype=float)
        _depths = np.asarray(sparse_view.depths_mm, dtype=float)
        _columns = np.asarray(sparse_view.supported_columns)
        _representatives = [_columns[0], _columns[len(_columns) // 2], _columns[-1]]
        _selected = sparse_view.column_of_depth(float(gate_stats.depths_mm[position]))
        _fig = go.Figure()
        for _column in _representatives:
            _fig.add_trace(
                go.Scatter(
                    x=sparse_view.time_s, y=_values[:, _column], mode="lines",
                    name=f"view column {_column} · depth {_depths[_column]:.3f} mm",
                    line=dict(width=1.3),
                )
            )
        _fig.add_trace(
            go.Scatter(
                x=sparse_view.time_s, y=_values[:, _selected], mode="lines",
                name=f"SELECTED · view column {_selected} · depth "
                f"{_depths[_selected]:.3f} mm",
                line=dict(width=2.6, color="#111111"),
            )
        )
        _fig.update_layout(
            title=(
                f"{sparse_view.point_label} · gate traces of the view "
                f"`{sparse_view.view.value}` · window {sparse_view.window_start_s:.4f}–"
                f"{sparse_view.window_end_s:.4f} s (span {sparse_view.window_s:.4f} s)"
            ),
            xaxis_title="time from the record's first stored profile [s]",
            yaxis_title="signed axial velocity [mm/s]",
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
def time_slice_figure(go, mo, np, sparse_view):
    # Representative time slices: one stored profile read across the view's native
    # gates at its own timestamp. The three slices are index picks (first, middle, last
    # stored profile of the view) and the depth axis is the instrument's own gate
    # coordinate; nothing is interpolated onto a new grid. Only the view's own
    # supported columns are drawn, and they are the view's own list of them.
    _out = mo.md("_No time slices: no view to read._")
    if sparse_view is not None:
        _values = np.asarray(sparse_view.values, dtype=float)
        _depths = np.asarray(sparse_view.depths_mm, dtype=float)
        _columns = np.asarray(sparse_view.supported_columns)
        _profiles = _values.shape[0]
        _indices = [0, _profiles // 2, _profiles - 1]
        _fig = go.Figure()
        for _index in _indices:
            _fig.add_trace(
                go.Scatter(
                    x=_values[_index, _columns], y=_depths[_columns],
                    mode="lines+markers",
                    name=f"stored profile {_index} · t = "
                    f"{float(sparse_view.time_s[_index]):.4f} s",
                )
            )
        _fig.update_layout(
            title=(
                f"{sparse_view.point_label} · time slices of the view "
                f"`{sparse_view.view.value}` · supported gates only "
                f"({_columns.size} of {_depths.size})"
            ),
            xaxis_title="signed axial velocity [mm/s]",
            yaxis_title="native gate depth [mm]",
            height=460,
        )
        _out = mo.ui.plotly(_fig)
    _out
    return


@app.cell(hide_code=True)
def gate_distribution_figure(gate_stats, go, mo, np, position, statistic_units):
    # The per-gate distribution as the statistics module reports it: min, q05, q25,
    # q50, q75, q95 and max are read straight out of the result and drawn as they are
    # — no box plot is re-derived here and no whisker is chosen by this notebook. The
    # table below carries every statistic of the selected gate, and a value the module
    # reports as NaN is printed as undefined rather than as a zero.
    _out = mo.md("_No per-gate distribution: no statistics to show._")
    if gate_stats is not None and position is not None:
        _position = position
        _depth = float(gate_stats.depths_mm[_position])
        _names = gate_stats.statistic_names
        _minimum = float(gate_stats.of("min")[_position])
        _maximum = float(gate_stats.of("max")[_position])
        _q05 = float(gate_stats.of("q05")[_position])
        _q25 = float(gate_stats.of("q25")[_position])
        _q50 = float(gate_stats.of("q50")[_position])
        _q75 = float(gate_stats.of("q75")[_position])
        _q95 = float(gate_stats.of("q95")[_position])
        _fig = go.Figure()
        _fig.add_trace(
            go.Scatter(
                x=[_minimum, _maximum], y=[0, 0], mode="lines",
                name="min → max (the reported extremes)",
                line=dict(color="#90A4AE", width=1.6),
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=[_q25, _q75], y=[0, 0], mode="lines",
                name="q25 → q75 (the reported interquartile range)",
                line=dict(color="#1E88E5", width=10),
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=[_q50], y=[0], mode="markers", name="q50 (equals the frozen median)",
                marker=dict(size=13, color="#0D47A1"),
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=[_q05, _q95], y=[0, 0], mode="markers+text",
                name="q05 and q95",
                text=[f"{_q05:.4f}", f"{_q95:.4f}"], textposition="bottom center",
                marker=dict(size=9, color="#FB8C00"),
            )
        )
        _fig.update_layout(
            title=(
                f"gate depth {_depth:.3f} mm · view "
                f"`{gate_stats.provenance.view.value}` · distribution as "
                "`sparse_gate_stats` reports it "
                f"({gate_stats.provenance.profiles} profiles)"
            ),
            xaxis_title=f"velocity [{statistic_units('mean')}]",
            yaxis=dict(showticklabels=False, range=[-1.0, 1.0]),
            height=330,
        )
        _rows = []
        for _index, _name in enumerate(_names):
            _value = float(gate_stats.statistics[_index][_position])
            _rows.append(
                f"| `{_name}` | "
                + (f"{_value:.6f}" if np.isfinite(_value) else "**undefined (NaN)**")
                + f" | {gate_stats.units[_index]} |"
            )
        _table = "\n".join(
            [
                f"| statistic of gate depth {_depth:.3f} mm "
                f"(supported gate {_position + 1} of {gate_stats.depths_mm.size}) "
                "| value | unit |",
                "| --- | --- | --- |",
            ]
            + _rows
        )
        _out = mo.vstack(
            [
                mo.ui.plotly(_fig),
                mo.md(
                    _table
                    + "\n\nAn entry marked **undefined (NaN)** is the module's own "
                    "constant-trace rule reporting that a gate with no variance has no "
                    "shape to describe; it is not a measured zero. "
                    f"mad_scaled is scaled by {gate_stats.mad_scale:g} "
                    f"({gate_stats.mad_scaling}) and every percentile uses "
                    f"numpy's `{gate_stats.percentile_method}` interpolation, "
                    "as the result declares."
                ),
            ]
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
    RecurrenceVerdict, go, make_subplots, mo, np, recurrence, recurrence_error, sparse_view
):
    # The raw trace beside the trace the module actually correlated, and the normalized
    # autocorrelation the module returned. The curve is drawn as returned — no curve is
    # drawn when the verdict is anything but `defined`, because the module returns none;
    # instead its own message is printed under the raw trace, which is still shown.
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
        if _defined:
            _fig = make_subplots(
                rows=2, cols=1, vertical_spacing=0.16,
                subplot_titles=(
                    "the trace: raw as stored, and what the module correlated",
                    "normalized autocorrelation of the analysed trace",
                ),
            )
        else:
            _fig = make_subplots(
                rows=1, cols=1,
                subplot_titles=("the trace: raw as stored (no curve was returned)",),
            )
        _fig.add_trace(
            go.Scatter(
                x=_times, y=_raw, mode="lines", name="raw trace (as stored)",
                line=dict(color="#546E7A", width=1.4),
            ),
            row=1, col=1,
        )
        if _defined:
            _fig.add_trace(
                go.Scatter(
                    x=_times, y=_analysed, mode="lines",
                    name=f"analysed trace (detrending `{recurrence.detrending.value}`)",
                    line=dict(color="#1E88E5", width=1.6),
                ),
                row=1, col=1,
            )
            _fig.add_trace(
                go.Scatter(
                    x=recurrence.lag_s, y=recurrence.acf, mode="lines",
                    name="normalized ACF",
                    line=dict(color="#6D4C41", width=1.9),
                ),
                row=2, col=1,
            )
            _fig.add_hline(y=0.0, line=dict(color="#B0BEC5", width=1.0), row=2, col=1)
            for _quantity, _colour, _dash in (
                (recurrence.first_zero_crossing, "#E53935", "dot"),
                (recurrence.decay_1e_lag, "#FB8C00", "dash"),
            ):
                if bool(_quantity.supported):
                    _fig.add_vline(
                        x=float(_quantity.value),
                        line=dict(color=_colour, width=1.4, dash=_dash),
                        row=2, col=1,
                        annotation_text=(
                            "first zero crossing"
                            if _colour == "#E53935"
                            else "1/e decay lag"
                        ),
                    )
            if bool(recurrence.period_claim.supported):
                _fig.add_vline(
                    x=float(recurrence.period_claim.period_s),
                    line=dict(color="#43A047", width=2.0, dash="dot"),
                    row=2, col=1, annotation_text="claimed period",
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
        _fig.update_xaxes(title_text="time from the record's first stored profile [s]",
                          row=1, col=1)
        _fig.update_yaxes(title_text=f"velocity [{recurrence.unit}]", row=1, col=1)
        if _defined:
            _fig.update_xaxes(title_text="lag [s]", row=2, col=1)
            _fig.update_yaxes(title_text="normalized autocorrelation", row=2, col=1)
        _out = mo.ui.plotly(_fig)
    _out
    return


@app.cell(hide_code=True)
def recurrence_readout(mo, recurrence, recurrence_error):
    # Everything the recurrence result says about itself: the verdict and its message,
    # the timebase verdict that decides whether a lag in seconds may be claimed at all
    # and why, what the stored stamps resolve (lag and frequency resolution), the
    # descriptive quantities with their own support verdicts and reasons, the peaks, and
    # the period claim with its thresholds. An unsupported quantity is printed as the
    # module's own statement — never as a zero and never as a number this notebook
    # supplied — and a summary the module could not compute is printed as `None`.
    if recurrence is None:
        _out = mo.md(
            "_No recurrence result._"
            + (f"\n\n`{recurrence_error}`" if recurrence_error else "")
        )
    else:
        def _quantity_line(name, quantity):
            if bool(quantity.supported):
                return (
                    f"- **{name}**: **{quantity.value!r} {quantity.unit}** — "
                    f"{quantity.reason}"
                )
            return f"- **{name}**: **not reported** — {quantity.reason}"

        _lines = [
            f"**Recurrence — gate depth {recurrence.depth_mm:.3f} mm, view "
            f"`{recurrence.view.value}`** · `{recurrence.relative_path}` (gate column "
            f"{recurrence.gate_index} of the view, point `{recurrence.label}`)",
            "",
            f"- trace: `{recurrence.quantity}` [{recurrence.unit}] · "
            f"{recurrence.profile_count} profiles · window "
            f"{recurrence.window_start_s:.4f}–{recurrence.window_end_s:.4f} s "
            f"(duration {recurrence.window_duration_s!r} s)",
            f"- estimator: {recurrence.acf_estimator} · detrending "
            f"`{recurrence.detrending.value}`",
            f"- **timebase `{recurrence.timebase.value}`**: {recurrence.timebase_reason} "
            f"· this timebase supports claims in seconds, regardless of what this "
            f"particular trace resolves: **{recurrence.lag_claims_supported}**",
            f"- **verdict `{recurrence.verdict.value}`**: {recurrence.message}",
            "",
            f"- **resolution**: sample interval {recurrence.sample_interval_s!r} s · "
            f"lag resolution {recurrence.lag_resolution_s!r} s (one stored profile "
            "period — the only lag step the timestamps define) · frequency resolution "
            f"1/window = {recurrence.frequency_resolution_hz!r} Hz · lag grid: "
            f"{recurrence.lag_grid_rule}",
            f"- reported lag range 0 … {recurrence.max_lag_s!r} s (requested "
            f"{recurrence.requested_max_lag_s!r} s) · largest relative interval "
            f"deviation {recurrence.max_relative_interval_deviation!r}",
            f"- trace summaries: mean of the trace as stored "
            f"{recurrence.trace_mean_mm_s!r} mm/s · std of the analysed series "
            f"{recurrence.trace_std_mm_s!r} mm/s · stored exact zeros "
            f"{recurrence.trace_zero_fraction!r}",
        ]
        if recurrence.linear_trend_mm_s_per_s is not None:
            _lines.append(
                f"- linear trend removed by the module: "
                f"{recurrence.linear_trend_mm_s_per_s!r} mm/s per s"
            )
        _lines += [
            f"- thresholds this result carries: weak-peak correlation "
            f"{recurrence.weak_peak_correlation!r} · min candidate cycles "
            f"{recurrence.min_candidate_cycles!r} · min peak lag steps "
            f"{recurrence.min_peak_lag_steps} · constant-trace threshold "
            f"{recurrence.constant_trace_threshold_mm_s!r} mm/s",
            "",
            _quantity_line("first zero crossing", recurrence.first_zero_crossing),
            _quantity_line("1/e decay lag", recurrence.decay_1e_lag),
            _quantity_line("integral time", recurrence.integral_time),
            "",
            f"- **peaks**: {recurrence.peaks_reason}",
        ]
        for _peak in recurrence.recurrence_peaks:
            _lines.append(
                f"  - lag {_peak.lag_s!r} s · correlation {_peak.correlation!r} · "
                f"weak {_peak.weak} · preceded by a dip below the weak threshold "
                f"{_peak.preceded_by_dip_below_weak_threshold} — {_peak.reason}"
            )
        _claim = recurrence.period_claim
        _lines += [
            "",
            f"- **period claim**: supported `{_claim.supported}` — {_claim.reason}",
        ]
        if _claim.peak_lag_s is not None:
            _lines.append(
                f"  - peak evidence: lag {_claim.peak_lag_s!r} s · correlation "
                f"{_claim.peak_correlation!r} · candidate cycles in the window "
                f"{_claim.candidate_cycles_in_window!r}"
            )
        if _claim.supported:
            _lines.append(
                f"  - period {_claim.period_s!r} s, resolved to one lag step "
                f"{_claim.period_resolution_s!r} s"
            )
        _out = mo.md("\n".join(_lines))
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
    computes none either. No spectrum, PSD, spectrogram or sampling-support guard is
    shown (SA2), and no spatial correlation or POD (SA3). No period is claimed from a
    weak recurrence peak: the claim above states the threshold that refused it, and
    if the stored timestamps do not support a lag in seconds at all, the timebase
    verdict says so. The hypothesized ~1 s vortex timescale is *sought*, never
    assumed — nothing in this notebook names it.
    """)
    return


if __name__ == "__main__":
    app.run()
