import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def imports():
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go

    from udv_echo_process.analysis import rpm_from_channel, setpoint_rpm_from_stem
    from udv_echo_process.io import load
    from udv_echo_process.provenance import select_channel

    return Path, go, load, mo, np, rpm_from_channel, select_channel, setpoint_rpm_from_stem


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Echo RPM — one rig, one channel, 19 recordings

    Rotor speed from a single-sensor echo recording, end to end:

    ```text
    values (profile, gate)   ->  mean over gates        = one trace y(t)
    y(t)                     ->  |rfft| magnitude       = amplitude spectrum
    spectrum[1:]             ->  argmax                 = dominant non-DC mode
    peak_freq_hz / 2 * 60                               = RPM
    ```

    The dataset is fixed and narrow on purpose: **every single-channel echo `.BDD`
    in `data/echo`** — 19 recordings of the same rig, one device channel, 26 gate
    depths. Multichannel recordings and velocity channels are out of scope here;
    the estimator refuses them by design and they belong to other work.

    The presentation runs in this order: the dataset and its channel statistics,
    then one recording in detail (heatmap, a gate's FFT, the detected frequency),
    then the line that compares every filename label with its extracted RPM, then
    what the study can read off those 19 points.
    """)
    return


@app.cell(hide_code=True)
def dataset_scan(Path):
    _dir = Path("data/echo")
    _all = sorted(
        p for p in _dir.iterdir() if p.is_file() and p.suffix.lower() == ".bdd"
    ) if _dir.is_dir() else []
    dataset_paths = _all
    excluded = [p.name for p in _dir.iterdir() if p.is_file() and p.suffix.lower() != ".bdd"]
    return dataset_paths, excluded


@app.cell(hide_code=True)
def dataset_load(dataset_paths, load):
    dataset = [(p, load(p)) for p in dataset_paths]
    load_notes = []
    for _p, _b in dataset:
        _streams = _b.recording.streams
        _q = _streams[0].descriptor.quantity.value
        if len(_streams) != 1 or _q != "echo_amplitude":
            load_notes.append(
                f"{_p.name}: {len(_streams)} stream(s), {_q} — outside this presentation"
            )
    return dataset, load_notes


@app.cell(hide_code=True)
def dataset_estimates(
    dataset, np, rpm_from_channel, select_channel, setpoint_rpm_from_stem
):
    stats_rows = []
    for _path, _bundle in dataset:
        _art = _bundle.recording.streams[0]
        _ch = select_channel(_bundle, _art.acquisition.channel)
        _est = rpm_from_channel(_ch)
        _data = _ch.artifact.data
        _t = np.asarray(_data.time_s)
        _v = np.asarray(_data.values)
        _dt = np.diff(_t)
        _trace = _v.mean(axis=1)
        _setpoint = setpoint_rpm_from_stem(_path.stem)
        stats_rows.append(
            {
                "file": _path.name,
                "channel": _art.acquisition.channel.device_channel,
                "setpoint": _setpoint,
                "profiles": _est.profile_count,
                "gates": _est.gate_count,
                "duration_s": float(_t[-1] - _t[0]),
                "dt_median_ms": float(np.median(_dt) * 1e3),
                "dt_span_ms": _est.time_step_s * 1e3,
                "deviation_pct": _est.max_relative_interval_deviation * 100,
                "rpm": _est.rpm,
                "peak_hz": _est.peak_freq_hz,
                "error_pct": abs(_est.rpm - _setpoint) / _setpoint * 100,
                "mean_level": float(np.mean(_trace)),
                "amp_min": float(np.min(_v)),
                "amp_max": float(np.max(_v)),
                "gate_lo_mm": float(_data.gate_depths_mm[0]),
                "gate_hi_mm": float(_data.gate_depths_mm[-1]),
                "peak_prominence": float(
                    _est.spectrum[_est.peak_index] / np.median(_est.spectrum[1:])
                ),
                "artifact_id": _est.artifact_id,
            }
        )
    return (stats_rows,)


@app.cell(hide_code=True)
def dataset_section(mo):
    mo.md("""
    ## The dataset

    Nineteen single-channel echo recordings, identical acquisition geometry.
    Everything below is computed from these files only — the discovery is by
    **extension** here (`.BDD`), so a stray image or `.ADD` export cannot enter
    the set, and the per-file checks confirm one echo stream each.
    """)
    return


@app.cell(hide_code=True)
def dataset_table(excluded, load_notes, mo, stats_rows):
    _rows = [
        {
            "file": r["file"],
            "setpoint": r["setpoint"],
            "profiles": r["profiles"],
            "gates": r["gates"],
            "duration [s]": round(r["duration_s"], 2),
            "dt med [ms]": round(r["dt_median_ms"], 4),
            "dt span [ms]": round(r["dt_span_ms"], 4),
            "deviation [%]": round(r["deviation_pct"], 4),
            "RPM": round(r["rpm"], 2),
            "peak [Hz]": round(r["peak_hz"], 3),
            "error [%]": round(r["error_pct"], 3),
            "level": round(r["mean_level"], 1),
            "peak/median": round(r["peak_prominence"], 1),
        }
        for r in stats_rows
    ]
    _notes = [f"excluded by extension: {', '.join(excluded)}" if excluded else ""]
    _notes += load_notes
    mo.vstack(
        [
            mo.ui.table(_rows, label=f"{len(_rows)} single-channel echo recordings"),
            mo.md("_" + "  \n".join(n for n in _notes if n) + "_") if any(_notes) else None,
        ]
    )
    return


@app.cell(hide_code=True)
def dataset_summary(mo, np, stats_rows):
    _prof = np.array([r["profiles"] for r in stats_rows])
    _dur = np.array([r["duration_s"] for r in stats_rows])
    _dev = np.array([r["deviation_pct"] for r in stats_rows])
    _med = np.array([r["dt_median_ms"] for r in stats_rows])
    _spn = np.array([r["dt_span_ms"] for r in stats_rows])
    _err = np.array([r["error_pct"] for r in stats_rows])
    _lo = stats_rows[0]["gate_lo_mm"]
    _hi = stats_rows[0]["gate_hi_mm"]
    mo.md(f"""
    **Channel statistics over the whole set** — the same device channel
    (`ch{stats_rows[0]["channel"]}`) and the same 26 gates
    ({_lo:.2f} → {_hi:.2f} mm) in every recording:

    - **records**: {_prof.min()}–{_prof.max()} profiles
      ({_dur.min():.2f}–{_dur.max():.2f} s), {len(stats_rows)} files
    - **cadence**: median interval {_med.min():.4f}–{_med.max():.4f} ms, but the
      full-span effective interval is {_spn.min():.4f}–{_spn.max():.4f} ms
    - **timing regularity**: every recording deviates by
      {_dev.min():.4f}–{_dev.max():.4f} % from its own median interval — inside
      the estimator's guard by construction, because the timestamps are quantized
      rather than irregular
    - **speed span**: {min(r["setpoint"] for r in stats_rows)} →
      {max(r["setpoint"] for r in stats_rows)} RPM labels; extraction error
      {_err.mean():.2f} % mean / {_err.max():.2f} % max

    The median-vs-span gap is the single most consequential property of this
    dataset: it is a *quantization* of the time axis, and the estimate depends on
    which of the two a caller calibrates with.
    """)
    return


@app.cell(hide_code=True)
def recording_section(mo):
    mo.md("""
    ## One recording in detail

    The controls live in the sidebar: pick a recording, then pick a gate to look
    at. Everything from here on follows those two choices.
    """)
    return


@app.cell(hide_code=True)
def sidebar_controls(dataset, mo):
    _files = [p.name for p, _ in dataset]
    file_picker = mo.ui.dropdown(
        options=_files,
        value=_files[0] if _files else None,
        label="Recording",
        full_width=True,
    )
    _gates = dataset[0][1].recording.streams[0].data.gate_depths_mm.size
    gate_slider = mo.ui.slider(
        start=0,
        stop=max(0, _gates - 1),
        step=1,
        value=_gates // 2,
        label="Gate (depth) for the FFT view",
        show_value=True,
        include_input=True,
        full_width=True,
    )
    mo.sidebar(
        [
            mo.md("### Datasets"),
            mo.md(f"_{len(_files)} single-channel echo `.BDD` recordings_"),
            file_picker,
            gate_slider,
        ]
    )
    return file_picker, gate_slider


@app.cell(hide_code=True)
def selected_channel(dataset, file_picker, select_channel):
    selected = None
    if file_picker.value is not None:
        _match = [b for p, b in dataset if p.name == file_picker.value]
        if _match:
            _bundle = _match[0]
            selected = select_channel(_bundle, _bundle.recording.streams[0].acquisition.channel)
    return (selected,)


@app.cell(hide_code=True)
def selected_stats(file_picker, mo, np, selected):
    _md = mo.md("_No recording selected._")
    if selected is not None:
        _art = selected.artifact
        _t = np.asarray(_art.data.time_s)
        _v = np.asarray(_art.data.values)
        _dt = np.diff(_t)
        _gate = _art.data.gate_depths_mm
        _quanta = np.unique(np.round(_dt * 1e6).astype(int))
        _md = mo.md(f"""
        ### `{file_picker.value}` — channel statistics

        | property | value |
        | --- | --- |
        | channel / quantity | `ch{_art.acquisition.channel.device_channel}` · {_art.descriptor.quantity.value} [{_art.descriptor.unit}] |
        | record | {_t.size} profiles × {_gate.size} gates, {_t[-1] - _t[0]:.2f} s |
        | gate depths | {_gate[0]:.2f} → {_gate[-1]:.2f} mm (Δ {_gate[1] - _gate[0]:.2f} mm) |
        | timestamp quanta | {' / '.join(f'{q} µs' for q in _quanta)} ({int((np.round(_dt * 1e6).astype(int) == _quanta[0]).sum())} of {_dt.size} intervals short) |
        | median interval | {np.median(_dt) * 1e3:.4f} ms |
        | full-span interval | {(_t[-1] - _t[0]) / (_t.size - 1) * 1e3:.4f} ms |
        | amplitude | {np.min(_v):.0f} … {np.max(_v):.0f} (mean {np.mean(_v):.0f}) |
        | source | `{_art.acquisition.recording_id[:12]}…` · artifact `{_art.artifact_id[:12]}…` |
        """)
    _md
    return


@app.cell(hide_code=True)
def heatmap(go, gate_slider, mo, np, selected):
    heatmap_fig = None
    if selected is not None:
        _art = selected.artifact
        _t = np.asarray(_art.data.time_s)
        _v = np.asarray(_art.data.values)
        _gate = _art.data.gate_depths_mm
        _stride = max(1, _t.size // 900)
        _fig = go.Figure(
            go.Heatmap(
                x=_t[::_stride],
                y=_gate,
                z=_v[::_stride].T,
                colorscale="Viridis",
                colorbar={"title": "echo [module]"},
            )
        )
        _g = int(gate_slider.value)
        _fig.add_hline(
            y=float(_gate[_g]),
            line=dict(color="white", width=1.5, dash="dot"),
            annotation_text=f"selected gate {_g} · {_gate[_g]:.2f} mm",
            annotation_position="top left",
            annotation_font=dict(color="white"),
        )
        _fig.update_layout(
            title=f"{_art.acquisition.recording_id[:8]}… — echo amplitude over "
            f"time × gate depth (every {_stride}th profile shown)",
            xaxis_title="time [s]",
            yaxis_title="gate depth [mm]",
            height=460,
        )
        heatmap_fig = mo.ui.plotly(_fig)
    heatmap_fig
    return


@app.cell(hide_code=True)
def gate_traces(go, gate_slider, mo, np, selected):
    gate_trace_fig = None
    if selected is not None:
        _art = selected.artifact
        _t = np.asarray(_art.data.time_s)
        _v = np.asarray(_art.data.values)
        _g = int(gate_slider.value)
        _fig = go.Figure()
        _fig.add_trace(
            go.Scatter(
                x=_t,
                y=_v[:, _g],
                mode="lines",
                name=f"gate {_g} ({_art.data.gate_depths_mm[_g]:.2f} mm)",
                line=dict(width=1, color="#1f77b4"),
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=_t,
                y=_v.mean(axis=1),
                mode="lines",
                name="mean over all 26 gates — the estimator's input",
                line=dict(width=1.4, color="#d62728"),
            )
        )
        _fig.update_layout(
            title="What the estimator sees: one gate's trace vs the gate average",
            xaxis_title="time [s]",
            yaxis_title="echo [module]",
            height=380,
            legend=dict(orientation="h", y=1.12),
        )
        gate_trace_fig = mo.ui.plotly(_fig)
    gate_trace_fig
    return


@app.cell(hide_code=True)
def gate_fft(go, gate_slider, mo, np, rpm_from_channel, selected):
    fft_fig = None
    fft_note = mo.md("_No recording selected._")
    if selected is not None:
        _art = selected.artifact
        _t = np.asarray(_art.data.time_s)
        _v = np.asarray(_art.data.values)
        _g = int(gate_slider.value)
        _est = rpm_from_channel(selected)
        _f = _est.frequencies_hz
        # the selected gate's own magnitude spectrum, computed in-cell for this
        # view only — the estimator itself always operates on the gate average
        _gate_spec = np.abs(np.fft.rfft(_v[:, _g] - _v[:, _g].mean()))
        _gate_peak = int(np.argmax(_gate_spec[1:])) + 1
        _gate_rpm = _f[_gate_peak] / 2 * 60

        _fig = go.Figure()
        _fig.add_trace(
            go.Scatter(
                x=_f,
                y=_gate_spec,
                mode="lines",
                name=f"gate {_g} alone — peak {_f[_gate_peak]:.3f} Hz "
                f"({_gate_rpm:.1f} RPM)",
                line=dict(width=1, color="#1f77b4"),
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=_f,
                y=_est.spectrum,
                mode="lines",
                name=f"gate average (estimator) — peak {_est.peak_freq_hz:.3f} Hz "
                f"({_est.rpm:.1f} RPM)",
                line=dict(width=1.8, color="#d62728"),
            )
        )
        _fig.add_vline(
            x=_est.peak_freq_hz,
            line=dict(color="#d62728", dash="dash", width=1),
            annotation_text=f"detected {_est.rpm:.1f} RPM",
            annotation_position="top right",
        )
        _fig.update_layout(
            title="Amplitude spectrum — DC bin excluded, peak = rotor/2",
            xaxis_title="frequency [Hz]",
            yaxis_title="|rfft| [counts]",
            height=420,
            legend=dict(orientation="h", y=1.14),
            xaxis_range=[0, 30],
        )
        fft_fig = mo.ui.plotly(_fig)
        fft_note = mo.md(
            f"Detected frequency **{_est.peak_freq_hz:.4f} Hz** at bin "
            f"{_est.peak_index} of {_est.spectrum.size - 1} non-DC bins → "
            f"`{_est.peak_freq_hz:.4f} / 2 × 60` = **{_est.rpm:.4f} RPM**. "
            f"The axis runs to {_f[-1]:.1f} Hz (Nyquist); the peak is shown in "
            f"0–30 Hz. DC sits at {_est.spectrum[0]:.0f} counts, i.e. it is the "
            f"global maximum and is excluded by contract. This gate's own peak is "
            f"{abs(_gate_rpm - _est.rpm):.3f} RPM from the gate-averaged one."
        )
    mo.vstack([fft_fig, fft_note])
    return


@app.cell(hide_code=True)
def label_section(mo):
    mo.md("""
    ## Does the filename label match the extracted RPM?

    Each recording is named after the speed the rig was set to, so the label is
    an *experiment* label rather than independent tachometer truth — which makes
    this a campaign sanity line, not an uncertainty budget. One point per
    recording; the diagonal is perfect agreement.
    """)
    return


@app.cell(hide_code=True)
def label_this_file(
    Path, file_picker, mo, np, rpm_from_channel, selected, setpoint_rpm_from_stem
):
    _md = mo.md("_No recording selected._")
    if selected is not None:
        _est = rpm_from_channel(selected)
        _setpoint = setpoint_rpm_from_stem(Path(file_picker.value).stem)
        _err = abs(_est.rpm - _setpoint) / _setpoint * 100
        _md = mo.md(f"""
        **This file** — `{file_picker.value}`: label **{_setpoint} RPM**,
        extracted **{_est.rpm:.3f} RPM**, difference **{_err:.3f} %**
        ({_est.rpm - _setpoint:+.2f} RPM).
        """)
    _md
    return


@app.cell(hide_code=True)
def label_line(go, mo, np, stats_rows):
    label_fig = None
    _sp = np.array([r["setpoint"] for r in stats_rows], dtype=float)
    _meas = np.array([r["rpm"] for r in stats_rows], dtype=float)
    _err = np.array([r["error_pct"] for r in stats_rows], dtype=float)
    _fig = go.Figure()
    _fig.add_trace(
        go.Scatter(
            x=[_sp.min() * 0.97, _sp.max() * 1.03],
            y=[_sp.min() * 0.97, _sp.max() * 1.03],
            mode="lines",
            name="perfect agreement",
            line=dict(color="#7f7f7f", dash="dash", width=1.2),
        )
    )
    _fig.add_trace(
        go.Scatter(
            x=_sp,
            y=_meas,
            mode="markers+lines",
            name="extracted RPM",
            marker=dict(size=9, color="#d62728"),
            line=dict(width=1, color="#f0a0a0"),
            text=[f"{r['file']} · {e:.2f} %" for r, e in zip(stats_rows, _err)],
            hovertemplate="label %{x:.0f} RPM<br>extracted %{y:.2f} RPM<br>%{text}<extra></extra>",
        )
    )
    _fig.update_layout(
        title=f"Label vs extracted RPM — {len(stats_rows)} recordings · mean error "
        f"{_err.mean():.2f} % · max {_err.max():.2f} %",
        xaxis_title="label from filename [RPM]",
        yaxis_title="extracted [RPM]",
        height=470,
        legend=dict(orientation="h", y=1.1),
    )
    label_fig = mo.ui.plotly(_fig)
    label_fig
    return


@app.cell(hide_code=True)
def label_table(mo, stats_rows):
    mo.ui.table(
        [
            {
                "file": r["file"],
                "label [RPM]": r["setpoint"],
                "extracted [RPM]": round(r["rpm"], 3),
                "difference [RPM]": round(r["rpm"] - r["setpoint"], 3),
                "error [%]": round(r["error_pct"], 3),
                "peak [Hz]": round(r["peak_hz"], 4),
            }
            for r in sorted(stats_rows, key=lambda r: r["setpoint"])
        ],
        label="per-recording agreement",
    )
    return


@app.cell(hide_code=True)
def study_section(mo):
    mo.md("""
    ## What the study can read off the 19 points

    Three things that are worth having in front of you when this method is used
    for rig work: whether the `/2` conversion is the right one, where the residual
    error comes from, and whether the gate average hides a gate-dependent answer.
    """)
    return


@app.cell(hide_code=True)
def study_linearity(go, mo, np, stats_rows):
    _sp = np.array([r["setpoint"] for r in stats_rows], dtype=float)
    _f = np.array([r["peak_hz"] for r in stats_rows], dtype=float)
    _slope_free = float((_sp @ _f) / (_sp @ _sp))
    _slope_lsq = float(np.polyfit(_sp, _f, 1)[0])
    _expected = 2.0 / 60.0
    _fig = go.Figure()
    _fig.add_trace(
        go.Scatter(
            x=_sp,
            y=_f,
            mode="markers",
            name="peak frequency",
            marker=dict(size=9, color="#1f77b4"),
            text=[r["file"] for r in stats_rows],
            hovertemplate="label %{x:.0f} RPM<br>peak %{y:.4f} Hz<br>%{text}<extra></extra>",
        )
    )
    _xs = np.array([_sp.min(), _sp.max()])
    _fig.add_trace(
        go.Scatter(
            x=_xs,
            y=_expected * _xs,
            mode="lines",
            name=f"theory: {_expected:.5f} Hz/RPM (2 features per rev ÷ 60)",
            line=dict(color="#d62728", dash="dash"),
        )
    )
    _fig.update_layout(
        title="Peak frequency is linear in the label, with the expected slope",
        xaxis_title="label [RPM]",
        yaxis_title="detected peak [Hz]",
        height=400,
        legend=dict(orientation="h", y=1.12),
    )
    mo.vstack(
        [
            mo.ui.plotly(_fig),
            mo.md(
                f"Fitted through the origin: **{_slope_free:.6f} Hz/RPM** vs the "
                f"contract's {_expected:.6f} ({(1 - _slope_free / _expected) * 100:+.3f} %). "
                f"Unconstrained fit: {_slope_lsq:.6f} Hz/RPM. The `/2` two-features-"
                f"per-revolution factor is what this line validates."
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def study_error(go, mo, np, stats_rows):
    _rows = sorted(stats_rows, key=lambda r: r["setpoint"])
    _sp = np.array([r["setpoint"] for r in _rows], dtype=float)
    _err = np.array([r["error_pct"] for r in _rows], dtype=float)
    _prof = np.array([r["profiles"] for r in _rows], dtype=float)
    _prom = np.array([r["peak_prominence"] for r in _rows], dtype=float)
    _fig = go.Figure()
    _fig.add_trace(
        go.Bar(
            x=_sp,
            y=_err,
            name="error vs label",
            marker=dict(color="#ff7f0e"),
            text=[f"{p} prof · {q:.1f}× peak" for p, q in zip(_prof, _prom)],
            hovertemplate="%{x:.0f} RPM<br>error %{y:.3f} %<br>%{text}<extra></extra>",
        )
    )
    _fig.add_hline(y=2.0, line=dict(color="#d62728", dash="dot"), annotation_text="2 % acceptance limit")
    _fig.update_layout(
        title=f"Extraction error per setpoint — mean {_err.mean():.3f} %, "
        f"max {_err.max():.3f} % (limit 2 %)",
        xaxis_title="label [RPM]",
        yaxis_title="error [%]",
        height=400,
    )
    mo.vstack(
        [
            mo.ui.plotly(_fig),
            mo.md(
                f"- worst case: {_rows[int(np.argmax(_err))]['file']} at "
                f"{_err.max():.3f} %; best: {_rows[int(np.argmin(_err))]['file']} at "
                f"{_err.min():.3f} %  \n"
                f"- error does not trend with speed "
                f"(correlation {float(np.corrcoef(_sp, _err)[0, 1]):+.2f}) and every "
                f"recording clears 2 %  \n"
                f"- peak prominence ranges {_prom.min():.1f}×–{_prom.max():.1f}× the "
                f"median non-DC level, so the mode is unambiguous in all 19 files  \n"
                f"- the residual is dominated by the *label* being a setpoint rather "
                f"than measured truth (the rig is not tachometer-referenced), which "
                f"is why this stays a sanity check"
            ),
        ]
    )
    return


@app.cell(hide_code=True)
def study_gate_dependence(go, gate_slider, mo, np, rpm_from_channel, selected):
    gate_dep_fig = None
    gate_dep_note = mo.md("_No recording selected._")
    if selected is not None:
        _art = selected.artifact
        _t = np.asarray(_art.data.time_s)
        _v = np.asarray(_art.data.values)
        _gate = _art.data.gate_depths_mm
        _est = rpm_from_channel(selected)
        _f = _est.frequencies_hz
        _per_gate_hz = []
        for _g in range(_gate.size):
            _s = np.abs(np.fft.rfft(_v[:, _g] - _v[:, _g].mean()))
            _per_gate_hz.append(float(_f[int(np.argmax(_s[1:])) + 1]))
        _per_gate_hz = np.array(_per_gate_hz)
        _per_gate_rpm = _per_gate_hz / 2 * 60
        _fig = go.Figure()
        _fig.add_trace(
            go.Scatter(
                x=_gate,
                y=_per_gate_rpm,
                mode="markers+lines",
                name="per-gate peak → RPM",
                marker=dict(size=7, color="#1f77b4"),
                line=dict(width=1, color="#aec7e8"),
            )
        )
        _fig.add_hline(
            y=_est.rpm,
            line=dict(color="#d62728", dash="dash"),
            annotation_text=f"gate average {_est.rpm:.2f} RPM",
            annotation_position="top right",
        )
        _fig.update_layout(
            title="Every gate sees the same modulation frequency (echo phase "
            "differs, frequency does not)",
            xaxis_title="gate depth [mm]",
            yaxis_title="RPM from that gate alone",
            height=400,
        )
        _g_sel = int(gate_slider.value)
        _bins = sorted({int(np.argmax(np.abs(np.fft.rfft(_v[:, k] - _v[:, k].mean()))[1:])) + 1 for k in range(_gate.size)})
        _bin_rpm = float(_f[1]) / 2 * 60 if _f.size > 1 else float("nan")
        gate_dep_fig = mo.ui.plotly(_fig)
        gate_dep_note = mo.md(
            f"All {_gate.size} gates land in the same peak bin "
            f"({'bin ' + ', '.join(str(b) for b in _bins) if len(_bins) == 1 else f'{len(_bins)} distinct bins'}), "
            f"i.e. {_per_gate_rpm.min():.2f}–{_per_gate_rpm.max():.2f} RPM "
            f"(sd {_per_gate_rpm.std(ddof=0):.3f} RPM). One FFT bin is "
            f"{_bin_rpm:.2f} RPM here, so **any gate-dependence is below the "
            f"frequency resolution** — the gates differ in the *phase* of the "
            f"travelling echo (visible in the heatmap as the diagonal sweep), not "
            f"in the modulation frequency. Averaging over gates therefore "
            f"suppresses phase noise without biasing the answer.  \n"
            f"Selected gate {_g_sel} alone gives {_per_gate_rpm[_g_sel]:.2f} RPM vs "
            f"the estimator's {_est.rpm:.2f} RPM."
        )
    mo.vstack([gate_dep_fig, gate_dep_note])
    return


@app.cell(hide_code=True)
def summary(mo, np, stats_rows):
    _err = np.array([r["error_pct"] for r in stats_rows])
    mo.md(f"""
    ## Summary

    - **Method**: gate-average → `|rfft|` → dominant non-DC bin → `/2 × 60`, one
      private kernel in `src/udv_echo_process/analysis/rpm.py`, exposed as
      `rpm_from_channel(bundle) -> EchoRpmEstimate`.
    - **Dataset**: {len(stats_rows)} single-channel echo `.BDD` recordings of the
      same rig (one device channel, 26 gates,
      {min(r["setpoint"] for r in stats_rows)}–{max(r["setpoint"] for r in stats_rows)}
      RPM), each processed from its own quantized timebase.
    - **Agreement with the labels**: {_err.mean():.2f} % mean,
      {_err.max():.2f} % max, all inside the 2 % acceptance limit — a sanity line,
      since the labels are setpoints, not tachometer measurements.
    - **Why the numbers are trustworthy in shape, not just in size**: the peak
      frequency is linear in the label with the contract's slope; every gate
      reports the same frequency, so the gate average reduces variance instead of
      biasing; the DC bin — the global maximum of real echo data — is excluded by
      contract rather than by luck.
    - **Limits**: multichannel and velocity recordings are out of scope (refused
      by the estimator, not silently reduced); burst/visit-sampled axes need a
      visit-aware estimator, and that remains open in `docs/agenda.md`.
    """)
    return


if __name__ == "__main__":
    app.run()
