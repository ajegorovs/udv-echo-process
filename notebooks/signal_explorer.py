import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def imports():
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from udv_echo_process.acquire.run_plan import RunPlanError
    from udv_echo_process.analysis._sparse_pass import decode_pass, primary_window
    from udv_echo_process.analysis.sparse_gate_stats import (
        VIEW_EXPLORATION,
        VIEW_FULL_RECORD,
        VIEW_PRIMARY,
        SparseGateStatsError,
        exploration_view,
        full_record_view,
        gate_statistics,
        primary_view,
        reduce_equal_weight,
        reduce_native_slab,
    )
    from udv_echo_process.analysis.sparse_inventory import SparseIngestError
    from udv_echo_process.analysis.sparse_recurrence import (
        Detrending,
        RecurrenceError,
        RecurrenceView,
        trace_recurrence,
    )

    return (
        Detrending,
        Path,
        RecurrenceError,
        RecurrenceView,
        RunPlanError,
        SparseGateStatsError,
        SparseIngestError,
        VIEW_EXPLORATION,
        VIEW_FULL_RECORD,
        VIEW_PRIMARY,
        decode_pass,
        exploration_view,
        full_record_view,
        gate_statistics,
        go,
        make_subplots,
        mo,
        np,
        primary_view,
        primary_window,
        reduce_equal_weight,
        reduce_native_slab,
        trace_recurrence,
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
    `src/udv_echo_process/` — the pass is bound and decoded once by the shared loader
    `analysis._sparse_pass.decode_pass`, the primary window is cut by the same
    shared helper WP1/WP2 use (`primary_window`), and every SA1 number or curve is
    returned by `analysis.sparse_gate_stats` or `analysis.sparse_recurrence`. Here
    the notebook only *selects* (dataset, job, recording, channel, gate, view,
    detrending) and *displays*; it computes no mean, percentile, standard deviation,
    correlation or window of its own.

    **Units and views.** Velocity is the instrument's own signed axial component in
    `mm/s`; depth is the instrument's **native gate coordinate** in `mm`. Every view
    is labelled either the *primary* designed 12 s window — the pass's fixed comparison
    interval, a **nominal-duration equivalence** (the 100 revolutions the design asked
    for, at the 500 RPM the design assumes and the recording does not establish) — or
    the *exploratory* full stored record, which retains the acquisition's own stopping
    overshoot.

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
def passes(Path):
    # The committed passes SA0 selects from, and the one it opens on. A pass is named
    # by its dataset root + its plan file + the name of its own run record inside the
    # root; `decode_pass` takes all three, and its live-1 defaults are never touched.
    PASSES = {
        "sparse-mixer-live-2": {
            "root": Path("data/sparse-mixer-live-2"),
            "plan": Path("examples/sparse-mixer-live-2/run-plan.json"),
            "plan_name": "sparse-mixer-live-2",
            "sitting": "second mixer-enabled sitting — SA0 default",
        },
        "sparse-mixer-live-1": {
            "root": Path("data/sparse-mixer-live-1"),
            "plan": Path("examples/sparse-mixer-live-1/run-plan.json"),
            "plan_name": "sparse-mixer-live-1",
            "sitting": (
                "first mixer-enabled sitting — its WP0–WP5 artefacts are frozen; "
                "opening it here displays stored recordings and regenerates nothing"
            ),
        },
    }
    DEFAULT_PASS = "sparse-mixer-live-2"
    return DEFAULT_PASS, PASSES


@app.cell(hide_code=True)
def dataset_picker(DEFAULT_PASS, PASSES, mo):
    # LEVEL 1 of the sidebar cascade. The immediate sitting note sits under the control
    # so the reader never has to remember which realization they are looking at.
    dataset_picker = mo.ui.dropdown(
        options=list(PASSES),
        value=DEFAULT_PASS,
        label="Sparse pass (committed)",
        full_width=True,
    )
    mo.sidebar([mo.md("### Dataset"), dataset_picker])
    return (dataset_picker,)


@app.cell(hide_code=True)
def pass_decoding(
    PASSES,
    RunPlanError,
    SparseIngestError,
    dataset_picker,
    decode_pass,
):
    # The ONE expensive cell: `decode_pass` binds and decodes every committed recording
    # of the pass (26 files, ~6 MB, ~2 s). It depends on the dataset control alone, so
    # changing job / recording / channel below re-runs only the selection and the views
    # — no file is ever re-decoded by a widget change.
    #
    # A refusal is data too, and the two loader modules raise their own named errors for
    # one: the frozen ingest refuses a pass record, plan, binding, declared word or
    # retired target it cannot answer to, and the plan loader refuses a plan it cannot
    # read. Either is shown rather than swallowed (rendered by `pass_status`), so a
    # checkout without the committed dataset degrades to a stated absence, not a crash.
    decoding = None
    decoding_error = ""
    if dataset_picker.value:
        _spec = PASSES[dataset_picker.value]
        try:
            decoding = decode_pass(
                _spec["root"], plan_path=_spec["plan"], plan_name=_spec["plan_name"]
            )
        except (SparseIngestError, RunPlanError, OSError) as exc:
            decoding_error = f"{type(exc).__name__}: {exc}"
    else:
        decoding_error = "no dataset selected"
    return decoding, decoding_error


@app.cell(hide_code=True)
def pass_status(PASSES, dataset_picker, decoding, decoding_error, mo):
    # The pass-level banner: how many recordings bound, the pass's own shared views,
    # and the plan fingerprint the rows answer to. Never a fabricated number — every
    # value below is read off the decoded pass.
    if decoding_error:
        _out = mo.md(
            f"**No pass loaded for `{dataset_picker.value}`.**\n\n"
            f"`{decoding_error}`\n\n"
            "_If this is a missing dataset, the committed recordings are not present "
            "in this checkout; nothing is plotted and no number is invented._"
        )
    elif decoding is not None:
        _lo, _hi = decoding.support_mm
        _out = mo.md(
            f"**{dataset_picker.value}** · {len(decoding.points)} recordings bound · "
            f"plan `{decoding.plan.plan}` "
            f"sha256:{decoding.plan_fingerprint[:12]}…\n"
            f"- primary window: **{decoding.window_s:g} s** "
            f"(a nominal-duration equivalence: {decoding.window_revolutions} revolutions "
            "at the nominal 500 RPM, not a measured speed), the pass's "
            "designed exposure\n"
            f"- common physical support: **{_lo:.3f}–{_hi:.3f} mm** "
            f"(native gate grids, no interpolation)\n"
            f"- channel fixed by the plan: **ch{decoding.plan.channel}**\n"
            f"- _{PASSES[dataset_picker.value]['sitting']}_"
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
def channel_picker(decoding, mo):
    # LEVEL 4. The sparse pass stores exactly ONE channel stream per recording — the
    # shared loader refuses a file that carries any other number — so the channel
    # cascade has a single option here. It is a real selector (the plan fixes the
    # channel; a multi-channel pass would list its own), not a decorative label, and
    # the note states why there is one entry.
    if decoding is not None:
        _ids = [int(decoding.plan.channel)]
    else:
        _ids = []
    channel_picker = mo.ui.dropdown(
        options=_ids,
        value=_ids[0] if _ids else None,
        label="Channel",
        full_width=True,
    )
    _note = mo.md(
        f"the pass's plan fixes channel {_ids[0]}; each recording of this pass carries "
        "a single channel stream (the loader refuses a multi-channel file)"
        if _ids
        else "_No channel available._"
    )
    mo.sidebar([mo.md("### Channel"), channel_picker, _note])
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
def point_metadata(decoding, mo, np, point):
    # The selected recording's metadata, decoded settings and QC — all read off the
    # decode (no estimator, no derived physics). `finite`/`zero` counts are QC, and the
    # timing cells are measured from the record's own stored timestamps.
    _out = mo.md("_No recording selected — no metadata to show._")
    if point is not None and decoding is not None:
        _b = point.binding
        _job = _b.job
        _params = _b.point.parameters
        _cfg = point.config
        _values = point.values
        _time = point.time_s
        _depths = point.depths
        _span = float(_time[-1] - _time[0])
        _intervals = np.diff(_time)
        _median_dt = float(np.median(_intervals)) if _intervals.size else float("nan")
        _achieved = _span / (_time.size - 1) if _time.size > 1 else float("nan")
        _finite = int(np.count_nonzero(np.isfinite(_values)))
        _zeros = int(np.count_nonzero(_values == 0.0))
        _covers = _span + 1e-9 >= decoding.window_s
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
            f"{_values.shape[0]} profiles × {_values.shape[1]} native gates · "
            f"gate {_depths[0]:.3f} → {_depths[-1]:.3f} mm",
            f"- **stored instrument words**: burst {_cfg.burst_length}, emissions/profile "
            f"{_cfg.emissions_per_profile}, PRF {_cfg.pulse_repetition_freq_hz:g} Hz, "
            f"pitch {_cfg.resolution_mm:g} mm, SV index {_cfg.sampling_volume_index}, "
            f"emit power {_cfg.emit_power}, sensitivity {_cfg.sensitivity}, "
            f"v_max {_cfg.velo_max_ms} m/s, doppler {_cfg.doppler_angle_deg}°, "
            f"TGC {_cfg.tgc_mode} {_cfg.tgc_start_db}→{_cfg.tgc_end_db} dB, "
            f"skipped {_cfg.skipped_profiles}",
            f"- **timing, measured from the stored stamps**: span {_span:.4f} s · "
            f"median Δt {_median_dt * 1e3:.3f} ms · achieved period {_achieved:.6f} s · "
            f"monotone {bool(np.all(_intervals > 0.0)) if _intervals.size else 'n/a'}",
            f"- **signal QC of the full record**: finite {_finite}/{_values.size} · "
            f"exact zeros {_zeros} ({_zeros / _values.size:.4f})",
            f"- **shared pass views**: primary window {decoding.window_s:g} s "
            f"({decoding.window_revolutions} revolutions at the nominal 500 RPM) · common "
            f"support {_lo:.3f}–{_hi:.3f} mm · this record retains the designed window: "
            f"**{_covers}** (its own stamps, not the log's target)",
            f"- **provenance**: sha256:{point.source_sha256} · "
            f"{point.file_size_bytes} bytes · recording stamp "
            f"`{_b.recording_stamp}` · plan `{decoding.plan.plan}` "
            f"sha256:{decoding.plan_fingerprint}",
        ]
        _out = mo.md("\n".join(_lines))
    _out
    return


@app.cell(hide_code=True)
def view_controls(mo):
    # The one view control. The primary designed 12 s window is the default because it
    # is the pass's fixed comparison interval; widening to the full stored record is
    # explicitly labelled exploratory — the surplus span is the acquisition's stopping
    # latency, not a longer experiment.
    show_full_record = mo.ui.checkbox(
        value=False,
        label=(
            "Exploratory: plot the full stored record (retained overshoot included), "
            "not only the designed 12 s primary window"
        ),
    )
    show_full_record
    return (show_full_record,)


@app.cell(hide_code=True)
def heatmap(decoding, go, mo, np, point, primary_window, show_full_record):
    # The native time–depth heatmap: the stored (profiles × gates) block, transposed so
    # x = time and y = the instrument's own gate depth. No derived quantity is plotted
    # and no physics is overlaid. The long time axis is strided for drawing only; every
    # gate is kept as a row.
    _out = mo.md("_No recording selected — nothing to plot._")
    if point is not None and decoding is not None:
        if bool(show_full_record.value):
            _values = point.values
            _view = "EXPLORATORY · full stored record"
        else:
            _values = primary_window(point, decoding.window_s)
            _view = f"PRIMARY · designed {decoding.window_s:g} s window"
        _time = point.time_s[: _values.shape[0]]
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
                y=point.depths,
                z=_z,
                colorbar={"title": f"{point.quantity} [{point.unit}]"},
                **_kw,
            )
        )
        _fig.update_layout(
            title=(
                f"{point.binding.identity} — ch{decoding.plan.channel} · "
                f"{point.quantity} [{point.unit}] · {_view} · "
                f"every {_stride}th profile shown"
            ),
            xaxis_title="time from the record's first stored profile [s]",
            yaxis_title="native gate depth [mm] (instrument gate coordinate)",
            height=520,
        )
        if bool(show_full_record.value):
            _fig.add_vline(
                x=float(_time[0]) + decoding.window_s,
                line=dict(color="#43A047", width=2.0, dash="dot"),
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
    notebook does not assume. With the exploratory view on, the dotted green line marks
    the end of the designed 12 s primary window — everything to its right is retained
    overshoot (`12.47–12.59 s` per record), which belongs to the full-record view.

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
    decoded pass SA0 selected above:

    - `analysis.sparse_gate_stats` — the labelled views (`primary-comparison`,
      `full-record`, `exploration`), the per-gate statistics (the five frozen names
      plus SA1's `std`, `mad_scaled`, `min`, `max`, `q05/q25/q50/q75/q95`, `skewness`,
      `excess_kurtosis`) and the declared depth reductions;
    - `analysis.sparse_recurrence` — the normalized trace autocorrelation, its raw and
      analysed traces, the lag/frequency resolution and every unsupported-claim
      verdict.

    This notebook chooses **which view, which gate and which detrending** to ask for
    and prints what comes back. It cuts no window (the view constructors do that with
    the recording's own stored stamps), computes no percentile, standard deviation,
    correlation or reduction, and smooths, resamples and interpolates nothing. Where a
    quantity is undefined or unsupported, the module's own statement is printed — no
    number is invented here to fill the gap.
    """)
    return


@app.cell(hide_code=True)
def sa1_view_controls(
    Detrending,
    VIEW_EXPLORATION,
    VIEW_FULL_RECORD,
    VIEW_PRIMARY,
    decoding,
    mo,
):
    # The SA1 view control. Its options ARE the statistics module's own view
    # constants, so the label the reader sees below is the label the module put on the
    # result. The primary comparison is the default: an exploration window is never
    # allowed to replace it silently — it is a separate, explicitly labelled choice.
    _view_options = {
        "primary-comparison — the pass's designed leading window, cut by the "
        "recording's own stamps": VIEW_PRIMARY,
        "full-record — every stored profile (duration varies between recordings)": (
            VIEW_FULL_RECORD
        ),
        "exploration — explicit time and depth bounds selected below": (
            VIEW_EXPLORATION
        ),
    }
    gate_view = mo.ui.dropdown(
        options=_view_options,
        value=next(iter(_view_options)),
        label="SA1 view (the module's own label travels with every result)",
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
    detrending_picker = mo.ui.dropdown(
        options=_detrending_options,
        value=next(iter(_detrending_options)),
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
    SparseGateStatsError,
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
    # the statistics module's own three view constructors, and nothing else: the
    # primary view's cut is `_sparse_pass.primary_window`, so the designed leading
    # window here is the interval the WP floor uses, never the retained overshoot.
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
        except SparseGateStatsError as exc:
            # The module's refusal is shown as it stands: an exploratory selection that
            # reaches outside the record, or a window no stored profile covers, is not
            # widened here into something that would render.
            sparse_view_error = f"{type(exc).__name__}: {exc}"
    return sparse_view, sparse_view_error


@app.cell(hide_code=True)
def sa1_view_label(gate_view, mo, sparse_view, sparse_view_error):
    # The visible view label, in the module's own words, printed above the SA1
    # displays: which view, what its rule is, and the declared window beside the span
    # the stored stamps actually achieve. A reader never has to infer the view from a
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
        _out = mo.md(
            f"**SA1 view: `{sparse_view.view}`** — {sparse_view.view_rule}\n\n"
            f"- window: **{sparse_view.window_start_s:.4f}–"
            f"{sparse_view.window_end_s:.4f} s** (span {sparse_view.window_s:.4f} s; "
            f"{_declared}){_bounds}\n"
            f"- stored profiles in the view: **{sparse_view.values.shape[0]}** "
            f"(indices [{sparse_view.start_index}, {sparse_view.stop_index}) of the "
            "recording's own profile axis)\n"
            f"- native gates in the view: {sparse_view.values.shape[1]} · inside the "
            f"common support "
            f"[{sparse_view.support_mm[0]:.3f}, {sparse_view.support_mm[1]:.3f}] mm: "
            f"**{int(sparse_view.support_mask.sum())}**\n"
            f"- source: `{sparse_view.relative_path}` · job `{sparse_view.job}` · point "
            f"`{sparse_view.point_label}` · "
            f"sha256:{sparse_view.source_sha256[:12]}…"
        )
    _out
    return


@app.cell(hide_code=True)
def gate_stats_result(gate_statistics, sparse_view):
    # `gate_statistics` calls the frozen `gate_metrics` and SA1's extension on the
    # view's supported block, so the five frozen names and SA1's eleven cannot drift
    # apart. Nothing is reduced here: the result keeps one value per gate.
    gate_stats = None
    gate_stats_error = ""
    if sparse_view is not None:
        try:
            gate_stats = gate_statistics(sparse_view)
        except (SparseGateStatsError, ValueError) as exc:
            gate_stats_error = f"{type(exc).__name__}: {exc}"
    return gate_stats, gate_stats_error


@app.cell(hide_code=True)
def sa1_stats_readout(gate_stats, gate_stats_error, mo):
    # What the statistics result itself declares: its provenance (view, support,
    # method settings, MAD scaling and the constant-trace rule) and — never silently —
    # which statistics it could not measure at any gate.
    if gate_stats is None:
        _out = mo.md(
            "_No per-gate statistics: no view is available._"
            + (f"\n\n`{gate_stats_error}`" if gate_stats_error else "")
        )
    else:
        _prov = gate_stats.provenance
        _unmeasured = gate_stats.unmeasured()
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
        _out = mo.md(
            f"**Per-gate statistics of the `{_prov.view}` view** "
            f"({gate_stats.statistic_names.__len__()} statistics × "
            f"{gate_stats.depths_mm.size} supported gates)\n\n"
            f"- depth support the numbers cover: "
            f"**{_prov.depth_support_mm[0]:.3f}–{_prov.depth_support_mm[1]:.3f} mm** "
            f"({_prov.supported_gates} of {_prov.native_gates} native gates)\n"
            f"- profiles: {_prov.profiles} · method: {_prov.method}\n"
            f"- MAD scaling: {_prov.mad_scaling}\n"
            f"- kurtosis convention: {_prov.excess_kurtosis_convention}\n"
            f"- constant-trace rule: {_prov.constant_trace_rule}\n"
            f"- statistics the result reports as **unmeasured** (an undefined value is "
            f"named, never drawn as a zero curve):\n{_unmeasured_lines}"
        )
    _out
    return


@app.cell(hide_code=True)
def gate_profile_figure(gate_stats, go, make_subplots, mo, np):
    # Per-gate mean and variability profiles over the instrument's native depth. Every
    # x value is a row the statistics result returned (`mean`, `q25`, `q75`, `std`,
    # `mad_scaled`); this cell selects rows and draws them, it computes nothing. The
    # quantile band is the frozen `q25`/`q75` pair — the same numbers as `median ±
    # iqr/2` — so it cannot disagree with the frozen table.
    _out = mo.md("_No per-gate profiles: no statistics to plot._")
    if gate_stats is not None:
        _names = gate_stats.statistic_names
        _unit = lambda name: gate_stats.units[_names.index(name)]  # noqa: E731
        _depths = np.asarray(gate_stats.depths_mm, dtype=float)
        _prov = gate_stats.provenance
        _fig = make_subplots(
            rows=1, cols=2, shared_yaxes=True, horizontal_spacing=0.09,
            subplot_titles=(
                f"per-gate mean with the reported q25–q75 band "
                f"[{_unit('mean')}]",
                f"per-gate variability [{_unit('std')}]",
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
                name="std (population, ddof=0)",
                line=dict(color="#E53935", width=1.9),
            ),
            row=1, col=2,
        )
        _fig.add_trace(
            go.Scatter(
                x=gate_stats.of("mad_scaled"), y=_depths, mode="lines",
                name="mad_scaled (MAD × 1.4826)",
                line=dict(color="#FB8C00", width=1.9, dash="dash"),
            ),
            row=1, col=2,
        )
        _fig.update_layout(
            title=(
                f"{gate_stats.provenance.point_label} · view "
                f"`{_prov.view}` · window {_prov.window_start_s:.4f}–"
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
    # The depth reductions are `sparse_gate_stats` calls, so the scalar comes with its
    # weighting declared. The per-gate rows above stay on screen: the reduction is one
    # scalar beside the profile, never a replacement for it. A statistic the module
    # reports as undefined is refused by the reduction, and its refusal is printed.
    _out = mo.md("_No depth reduction: no per-gate statistics._")
    if gate_stats is not None:
        _depths = gate_stats.depths_mm
        _rows = []
        _rules: list[tuple[str, str]] = []
        for _name in ("mean", "std"):
            _values = gate_stats.of(_name)
            _weightings = (
                ("unweighted", lambda: reduce_equal_weight(
                    _values, statistic=_name, depths_mm=_depths)),
                ("native-slab", lambda: reduce_native_slab(
                    _values, _depths, statistic=_name,
                    support_mm=gate_stats.provenance.support_mm)),
            )
            for _label, _call in _weightings:
                try:
                    _reduction = _call()
                except (SparseGateStatsError, ValueError) as exc:
                    _rows.append(
                        f"| `{_name}` | {_label} | **refused**: {exc} | — | — | — |"
                    )
                    continue
                _rows.append(
                    f"| `{_reduction.statistic}` | {_reduction.weighting} | "
                    f"{_reduction.value:.6f} | {_reduction.units} | "
                    f"{_reduction.gates} | {_reduction.weight_sum:.6f} · end gates "
                    f"{_reduction.weights[0]:.6f} / {_reduction.weights[-1]:.6f} |"
                )
                if _reduction.weighting not in [_weighting for _weighting, _ in _rules]:
                    _rules.append((_reduction.weighting, _reduction.weighting_rule))
        _table = "\n".join(
            [
                "| statistic | weighting | value | unit | gates | weight sum · "
                "end-gate weights |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            + _rows
        )
        _rule_lines = "\n".join(
            f"- **{_weighting}** — {_text}" for _weighting, _text in _rules
        )
        _out = mo.md(
            f"**Declared depth reductions of the `{gate_stats.provenance.view}` view** "
            f"(over the {_depths.size} supported gates, "
            f"{_depths[0]:.3f}–{_depths[-1]:.3f} mm)\n\n{_table}\n\n{_rule_lines}"
        )
    _out
    return


@app.cell(hide_code=True)
def gate_picker_cell(gate_stats, mo, np):
    # The gate selector for the trace, distribution and recurrence displays. Its value
    # is the gate's position among the result's supported columns — exactly the column
    # the statistics result reports that gate in — and the label carries the depth the
    # view preserved. It is selection, not a statistic.
    if gate_stats is not None:
        _depths = np.asarray(gate_stats.depths_mm, dtype=float)
        _columns = [int(column) for column in np.flatnonzero(np.asarray(gate_stats.support_mask))]
        _options = {
            f"depth {float(_depths[position]):.3f} mm · view column {column}": position
            for position, column in enumerate(_columns)
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
def gate_trace_figure(gate_picker, go, mo, np, sparse_view):
    # Representative gate traces: the sampled trace columns themselves, drawn against
    # the view's own stored timestamps. The three representatives are index picks
    # (shallowest, median-depth, deepest supported gate) and the selected gate is drawn
    # on top; no trace is averaged, smoothed or decimated.
    _out = mo.md("_No gate traces: no view to read._")
    if sparse_view is not None and gate_picker.value is not None:
        _values = np.asarray(sparse_view.values, dtype=float)
        _depths = np.asarray(sparse_view.depths_mm, dtype=float)
        _columns = [int(column) for column in np.flatnonzero(np.asarray(sparse_view.support_mask))]
        _representatives = [_columns[0], _columns[len(_columns) // 2], _columns[-1]]
        _selected = _columns[int(gate_picker.value)]
        _fig = go.Figure()
        for _column in _representatives:
            _fig.add_trace(
                go.Scatter(
                    x=sparse_view.time_s, y=_values[:, _column], mode="lines",
                    name=f"gate column {_column} · depth {_depths[_column]:.3f} mm",
                    line=dict(width=1.3),
                )
            )
        _fig.add_trace(
            go.Scatter(
                x=sparse_view.time_s, y=_values[:, _selected], mode="lines",
                name=f"SELECTED · gate column {_selected} · depth "
                f"{_depths[_selected]:.3f} mm",
                line=dict(width=2.6, color="#111111"),
            )
        )
        _fig.update_layout(
            title=(
                f"{sparse_view.point_label} · gate traces of the view "
                f"`{sparse_view.view}` · window {sparse_view.window_start_s:.4f}–"
                f"{sparse_view.window_end_s:.4f} s (span {sparse_view.window_s:.4f} s)"
            ),
            xaxis_title="time from the record's first stored profile [s]",
            yaxis_title="signed axial velocity [mm/s]",
            height=460,
        )
        _out = mo.ui.plotly(_fig)
    _out
    return


@app.cell(hide_code=True)
def time_slice_figure(go, mo, np, sparse_view):
    # Representative time slices: one stored profile read across the view's native
    # gates at its own timestamp. The three slices are index picks (first, middle, last
    # stored profile of the view) and the depth axis is the instrument's own gate
    # coordinate; nothing is interpolated onto a new grid.
    _out = mo.md("_No time slices: no view to read._")
    if sparse_view is not None:
        _values = np.asarray(sparse_view.values, dtype=float)
        _depths = np.asarray(sparse_view.depths_mm, dtype=float)
        _mask = np.asarray(sparse_view.support_mask)
        _profiles = _values.shape[0]
        _indices = [0, _profiles // 2, _profiles - 1]
        _fig = go.Figure()
        for _index in _indices:
            _fig.add_trace(
                go.Scatter(
                    x=_values[_index, _mask], y=_depths[_mask], mode="lines+markers",
                    name=f"stored profile {_index} · t = "
                    f"{float(sparse_view.time_s[_index]):.4f} s",
                )
            )
        _fig.update_layout(
            title=(
                f"{sparse_view.point_label} · time slices of the view "
                f"`{sparse_view.view}` · supported gates only "
                f"({int(_mask.sum())} of {_depths.size})"
            ),
            xaxis_title="signed axial velocity [mm/s]",
            yaxis_title="native gate depth [mm]",
            height=460,
        )
        _out = mo.ui.plotly(_fig)
    _out
    return


@app.cell(hide_code=True)
def gate_distribution_figure(gate_picker, gate_stats, go, mo, np):
    # The per-gate distribution as the statistics module reports it: min, q05, q25,
    # q50, q75, q95 and max are read straight out of the result and drawn as they are
    # — no box plot is re-derived here and no whisker is chosen by this notebook. The
    # table below carries every statistic of the selected gate, and a value the module
    # reports as NaN is printed as undefined rather than as a zero.
    _out = mo.md("_No per-gate distribution: no statistics to show._")
    if gate_stats is not None and gate_picker.value is not None:
        _position = int(gate_picker.value)
        _depth = float(gate_stats.depths_mm[_position])
        _names = gate_stats.statistic_names
        _unit_of = lambda name: gate_stats.units[_names.index(name)]  # noqa: E731
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
                f"gate depth {_depth:.3f} mm · view `{gate_stats.provenance.view}` · "
                f"distribution as `sparse_gate_stats` reports it "
                f"({gate_stats.provenance.profiles} profiles)"
            ),
            xaxis_title=f"velocity [{_unit_of('mean')}]",
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
                f"(view column {_position} of the supported columns) | value | unit |",
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
                    f"mad_scaled is scaled by {gate_stats.provenance.mad_scale} "
                    f"({gate_stats.provenance.mad_scaling}) and every percentile uses "
                    f"numpy's {gate_stats.provenance.percentile_method} interpolation, "
                    f"as the result declares."
                ),
            ]
        )
    _out
    return


@app.cell(hide_code=True)
def recurrence_result(
    RecurrenceError,
    RecurrenceView,
    VIEW_EXPLORATION,
    VIEW_FULL_RECORD,
    VIEW_PRIMARY,
    detrending_picker,
    gate_picker,
    gate_view,
    np,
    point,
    sparse_view,
    trace_recurrence,
):
    # The recurrence call. One gate, one view, one window: the trace and its stored
    # timestamps are the SELECTED view's own columns (so the ACF reads exactly the
    # block the statistics above were computed on), and the view constant, gate depth
    # and detrending are passed through. The window is the view's — this cell cuts
    # nothing, and the module returns its own raw trace beside the analysed one.
    #
    # The block's own stamps are used rather than `gate_recurrence`'s recording-level
    # window because that entry point expresses a *leading* window for the exploration
    # label, while `exploration_view` selects an arbitrary contiguous block; feeding
    # both displays from one view object is what keeps the statistics and the ACF on
    # the same samples.
    _RECURRENCE_VIEWS = {
        VIEW_PRIMARY: RecurrenceView.PRIMARY,
        VIEW_FULL_RECORD: RecurrenceView.FULL_RECORD,
        VIEW_EXPLORATION: RecurrenceView.EXPLORATION,
    }
    recurrence = None
    recurrence_error = ""
    if sparse_view is not None and gate_picker.value is not None and point is not None:
        _columns = [int(column) for column in np.flatnonzero(np.asarray(sparse_view.support_mask))]
        _column = _columns[int(gate_picker.value)]
        try:
            recurrence = trace_recurrence(
                np.asarray(sparse_view.values, dtype=float)[:, _column],
                time_s=np.asarray(sparse_view.time_s, dtype=float),
                view=_RECURRENCE_VIEWS[gate_view.value],
                label=f"{point.binding.identity} · {sparse_view.view}",
                relative_path=str(point.relative_path),
                gate_index=int(_column),
                depth_mm=float(sparse_view.depths_mm[_column]),
                quantity=str(point.quantity),
                unit=str(point.unit),
                detrending=detrending_picker.value,
            )
        except RecurrenceError as exc:
            recurrence_error = f"{type(exc).__name__}: {exc}"
    return recurrence, recurrence_error


@app.cell(hide_code=True)
def recurrence_figure(go, make_subplots, mo, np, recurrence, recurrence_error, sparse_view):
    # The raw trace beside the trace the module actually correlated, and the normalized
    # autocorrelation the module returned. The curve is drawn as returned — no curve is
    # drawn when the verdict is undefined, because the module returns none; instead its
    # own message is printed under the raw trace, which is still shown.
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
        _defined = str(recurrence.verdict.value) == "defined"
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
                f"{recurrence.window_duration_s:.4f} s · verdict "
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
    # what the stored stamps resolve (lag and frequency resolution), the descriptive
    # quantities with their own support verdicts and reasons, the peaks, and the period
    # claim with its thresholds. An unsupported quantity is printed as the module's own
    # statement — never as a zero and never as a number this notebook supplied.
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
            return (
                f"- **{name}**: **not reported** — {quantity.reason}"
            )

        _lines = [
            f"**Recurrence — gate depth {recurrence.depth_mm:.3f} mm, view "
            f"`{recurrence.view.value}`** · `{recurrence.relative_path}` (gate column "
            f"{recurrence.gate_index})",
            "",
            f"- trace: `{recurrence.quantity}` [{recurrence.unit}] · "
            f"{recurrence.profile_count} profiles · window "
            f"{recurrence.window_start_s:.4f}–{recurrence.window_end_s:.4f} s "
            f"(duration {recurrence.window_duration_s!r} s)",
            f"- estimator: {recurrence.acf_estimator} · detrending "
            f"`{recurrence.detrending.value}`",
            f"- **verdict `{recurrence.verdict.value}`**: {recurrence.message}",
            "",
            f"- **resolution**: sample interval {recurrence.sample_interval_s!r} s · "
            f"lag resolution {recurrence.lag_resolution_s!r} s (one stored profile "
            f"period — the only lag step the timestamps define) · frequency resolution "
            f"1/window = {recurrence.frequency_resolution_hz!r} Hz · reported lag range "
            f"0 … {recurrence.max_lag_s!r} s · largest relative interval deviation "
            f"{recurrence.max_relative_interval_deviation!r}",
            f"- trace summaries: mean {recurrence.trace_mean_mm_s!r} mm/s · "
            f"std of the analysed series {recurrence.trace_std_mm_s!r} mm/s · stored "
            f"exact zeros {recurrence.trace_zero_fraction!r}",
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
    **Reading SA1's preview.** Every view carries the statistics module's own label
    (`primary-comparison`, `full-record`, `exploration`) and its rule; the
    primary-comparison view is the pass's designed leading window cut by the
    recording's own stored stamps, and selecting the exploration view **adds** a
    labelled selection rather than replacing it. Depth is always the instrument's
    native gate coordinate in `mm` and colour/axis values are the signed axial
    velocity component in `mm/s`; both are never relabelled or interpolated.

    **What is deliberately not here.** No confidence interval appears anywhere: the
    profiles and gates of one recording are correlated samples, not independent
    replicates, so `sparse_gate_stats` computes no interval and `sparse_recurrence`
    computes none either. No spectrum, PSD, spectrogram or sampling-support guard is
    shown (SA2), and no spatial correlation or POD (SA3). No period is claimed from a
    weak recurrence peak: the claim above states the threshold that refused it. The
    hypothesized ~1 s vortex timescale is *sought*, never assumed — nothing in this
    notebook names it.
    """)
    return


if __name__ == "__main__":
    app.run()
