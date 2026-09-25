import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def imports():
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go

    from udv_echo_process.acquire.run_plan import RunPlanError
    from udv_echo_process.analysis._sparse_pass import decode_pass, primary_window
    from udv_echo_process.analysis.sparse_inventory import SparseIngestError

    return (
        Path,
        RunPlanError,
        SparseIngestError,
        decode_pass,
        go,
        mo,
        np,
        primary_window,
    )


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Sparse signal explorer — SA0 checkpoint

    The **first usable checkpoint** of the sparse signal analysis: dataset → job →
    recording → channel selection over the **committed** sparse passes, the selected
    recording's provenance/QC, and its **native time–depth heatmap**. The default
    selection is the second mixer-enabled sitting, `sparse-mixer-live-2`.

    This notebook is a **thin wrapper**: every number comes from tested functions in
    `src/udv_echo_process/` — the pass is bound and decoded once by the shared loader
    `analysis._sparse_pass.decode_pass`, and the primary window is cut by the same
    shared helper WP1/WP2 use (`primary_window`), so the views here cannot disagree
    with the ingest table about what a recording is or what its window is.

    **Units and views.** Velocity is the instrument's own signed axial component in
    `mm/s`; depth is the instrument's **native gate coordinate** in `mm`. Every view
    is labelled either the *primary* designed 12 s window (100 nominal 500-RPM
    revolutions — the pass's fixed comparison interval) or the *exploratory* full
    stored record, which retains the acquisition's own stopping overshoot.

    **What this checkpoint is not.** It measures no scientific effect. There is no
    gate trace, no depth profile, no autocorrelation, no spectrum, no spatial
    correlation and no POD here: each of those arrives in a later slice together with
    its tested estimator (SA1–SA3). The heatmap shows the stored samples at the
    instrument's own coordinates — no beam-path mapping, no CFD overlay, no nominal
    rotor markers. These `.BDD` velocity files carry **no tachometer, echo or energy
    channel**, so measured mixer speed, SNR and receiver saturation cannot be read
    from this notebook at all — that absence is a property of the data, not a
    pending feature.
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
            f"({decoding.window_revolutions} nominal 500-RPM revolutions), the pass's "
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
            f"({decoding.window_revolutions} nominal 500-RPM revolutions) · common "
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

    **Not shown here, on purpose.** Gate traces, per-gate profiles, autocorrelation,
    spectra/spectrograms, spatial correlation and POD are absent: each is added only
    alongside the tested estimator and sampling guard that produce it (SA1–SA3). The
    primary/exploratory label on every view is the same rule the later slices inherit.
    """)
    return


if __name__ == "__main__":
    app.run()
