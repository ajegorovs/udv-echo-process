import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo

    import numpy as np
    import plotly.graph_objects as go

    from marimo_inspection import TraceScrubber
    from udv_echo_process.io import discover_data_files, load

    return TraceScrubber, discover_data_files, go, load, mo, np


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # Single-channel signal preview

    Explore one channel of a `.BDD` recording on the new `io/` + `models/`
    stack. Two views to understand the raw signal before any sync /
    interpolation design:

    1. **Overview** — full time×gate heatmap + basic value/time stats. No
       time-averaged gate profile: the echo is a travelling wave (peak sweeping
       left→right across gates), so per-gate time statistics mix phases.
    2. **Time-step scrub** — the `i`-th profile (intensity/velocity vs gate
       distance). The slider steps by 1; the buttons jump ±1 and ±1%/10% of
       the frame count for faster scanning.

    Thin wrapper — all parsing stays in `src/udv_echo_process`; this is a
    prototype for understanding the signal.
    """)
    return


@app.cell(hide_code=True)
def _(discover_data_files, mo):
    _files = [str(p) for p in discover_data_files()]
    file_picker = mo.ui.dropdown(
        options=_files,
        value=_files[0] if _files else None,
        label="Recording (.BDD, content-sniffed)",
    )
    file_picker
    return (file_picker,)


@app.cell(hide_code=True)
def _(file_picker, load, mo):
    measurement = load(file_picker.value) if file_picker.value else None
    _ids = list(measurement.by_channel()) if measurement is not None else []
    channel_picker = mo.ui.dropdown(
        options=_ids,
        value=_ids[0] if _ids else None,
        label="Channel",
    )
    _head = (
        mo.md(
            f"**{measurement.file_path.name}** · {measurement.source}  \n"
            f"{measurement.describe()}"
        )
        if measurement is not None
        else mo.md("_No recording selected._")
    )
    _head
    return channel_picker, measurement


@app.cell(hide_code=True)
def _(channel_picker, measurement, mo, np):
    cs = measurement.by_channel()[channel_picker.value] if measurement is not None else None
    _stat_md = mo.md("_Select a recording + channel._")
    if cs is not None:
        _t = cs.time_s
        _v = cs.values
        _fin = np.isfinite(_v)
        _dt_s = np.diff(_t)
        _g0, _g1 = cs.gate_depths_mm[0], cs.gate_depths_mm[-1]
        _lines = [
            f"`ch{cs.channel}` · **{cs.meas_type.value}** · "
            f"{cs.time_count} profiles × {cs.gate_count} gates",
            f"- gate depths: {_g0:.2f} → {_g1:.2f} mm "
            f"({cs.gate_count} gates)",
            f"- time: {_t[0]:.4f} → {_t[-1]:.4f} s "
            f"({_dt_s.size} intervals, median dt {np.median(_dt_s) * 1e3:.3f} ms)"
            if _dt_s.size
            else "- time: single profile",
            f"- values: finite {int(_fin.sum())}/{_fin.size} · "
            f"min {np.nanmin(_v):.3g} · mean {np.nanmean(_v):.3g} · "
            f"max {np.nanmax(_v):.3g}",
            f"- config: {cs.config.describe()}",
        ]
        # NB: no time-meaned gate profile here — for a travelling wave
        # (echo peak sweeping across gates) time-averaging mixes phases and is
        # meaningless; use the scrubber below instead.
        _stat_md = mo.md("\n".join(_lines))
    _stat_md
    return (cs,)


@app.cell(hide_code=True)
def _(cs, go, mo, np):
    heat = None
    if cs is not None:
        _t = cs.time_s
        _v = cs.values
        # Overview "all at once": downsample rows so the figure stays light.
        _stride = max(1, _t.size // 800)
        _z = _v[::_stride]
        _diverging = cs.meas_type.value == "velocity"
        _kw = {}
        if _diverging:
            _m = float(np.nanmax(np.abs(_z))) or 1.0
            _kw = dict(zmin=-_m, zmax=_m, colorscale="RdBu_r")
        else:
            _kw = dict(colorscale="Viridis")
        _fig = go.Figure(
            go.Heatmap(
                x=cs.gate_depths_mm,
                y=_t[::_stride],
                z=_z,
                colorbar={"title": cs.meas_type.value},
                **_kw,
            )
        )
        _fig.update_layout(
            title=f"ch{cs.channel} — {cs.meas_type.value} over time "
            f"(every {_stride}th profile shown)",
            xaxis_title="Gate depth [mm]",
            yaxis_title="time [s]",
            height=520,
        )
        heat = mo.ui.plotly(_fig)
    heat
    return


@app.cell(hide_code=True)
def _(TraceScrubber, cs, np):
    scrub = None
    if cs is not None:
        if cs.meas_type.value == "echo":
            # echo: explicit module range, known a priori
            _y_lo, _y_hi = 0.0, 2000.0
        else:
            # velocity: fixed axis over the channel-wide raw range (mm/s) so
            # frames never re-scale between steps; outliers stretch as-is
            _y_lo = float(np.nanmin(cs.values))
            _y_hi = float(np.nanmax(cs.values))
        scrub = TraceScrubber().update(
            x=cs.gate_depths_mm,
            values=cs.values,
            times=cs.time_s,
            title=(
                f"ch{cs.channel} — {cs.meas_type.value} profile vs gate "
                f"depth · {cs.time_count} frames · "
                f"y: [{_y_lo:.6g}, {_y_hi:.6g}]"
            ),
            y_lo=_y_lo,
            y_hi=_y_hi,
        )
    scrub
    return


@app.cell(hide_code=True)
def interp_intro(mo):
    mo.md("""
    ### Interpolation preview — `process/sync.py` `resample()`

    Stage 3 landed: `resample(series, spec, *, times | dt_s) -> ChannelSeries`
    interpolates each gate along time (`docs/interpolation-design.md` §7/§8).
    Here you can **see** it on the selected channel:

    - **Method regime** — `linear` (default; cannot overshoot, honest across
      the ~370 ms inter-visit gaps of the 4-sensor fixture), `monotone`
      (PCHIP, shape-preserving), `cubic` / `bspline` (smooth, may overshoot —
      use on the uniform echo fixture).
    - **Target grid** — uniform `dt` (bridges the gaps) or the original knot
      times (round-trip: resampled values reproduce the measured ones).
    - Views: heatmap comparison (original vs resampled) and a per-gate trace
      overlay (measured markers vs resampled curve). Zoom/pan in the figures.
    """)
    return


@app.cell(hide_code=True)
def interp_controls(cs, mo, np):
    from udv_echo_process.process import InterpMethod, InterpParams, InterpSpec, resample

    # --- interpolation controls ------------------------------------------------
    interp_method = mo.ui.dropdown(
        options=[m.value for m in InterpMethod],
        value=InterpMethod.LINEAR.value,
        label="Interpolation method",
    )
    # dt default = native median cadence of the selected channel
    _dt_native_ms = float(np.median(np.diff(cs.time_s))) * 1e3 if cs is not None else 1.0
    interp_dt_ms = mo.ui.slider(
        start=0.1,
        stop=max(0.5, round(_dt_native_ms * 8, 1)),
        value=round(_dt_native_ms, 2),
        step=0.1,
        label="dt [ms] — target cadence",
    )
    interp_grid = mo.ui.dropdown(
        options=["dt grid", "knot times (round-trip)"],
        value="dt grid",
        label="Target grid",
    )
    spline_order = mo.ui.number(
        start=1,
        stop=6,
        step=1,
        value=3,
        label="B-spline order (BSPLINE only)",
    )
    _gate_count = cs.gate_count if cs is not None else 1
    gate_idx = mo.ui.slider(
        start=0,
        stop=_gate_count - 1,
        value=_gate_count // 2,
        step=1,
        label="Gate (trace view)",
    )

    return (
        InterpMethod,
        InterpParams,
        InterpSpec,
        gate_idx,
        interp_dt_ms,
        interp_grid,
        interp_method,
        resample,
        spline_order,
    )


@app.cell(hide_code=True)
def interp_run(
    InterpMethod,
    InterpParams,
    InterpSpec,
    cs,
    interp_dt_ms,
    interp_grid,
    interp_method,
    mo,
    resample,
    spline_order,
):
    # --- run resample and summarize --------------------------------------------
    resampled = None
    interp_note = None
    interp_grid_desc = "—"
    if cs is not None:
        _method = InterpMethod(interp_method.value)
        _spec = InterpSpec(
            method=_method,
            params=InterpParams(spline_order=int(spline_order.value)),
        )
        if interp_grid.value == "dt grid":
            _target = dict(dt_s=float(interp_dt_ms.value) / 1000.0)
            interp_grid_desc = f"dt = {interp_dt_ms.value:.3f} ms"
        else:
            _target = dict(times=cs.time_s)
            interp_grid_desc = "knot times (round-trip)"
        try:
            resampled = resample(cs, _spec, **_target)
            _span = resampled.time_s[-1] - resampled.time_s[0]
            interp_note = mo.md(
                f"**{_method.value}** on `{interp_grid_desc}` → "
                f"`resampled` = {resampled.time_count} samples over "
                f"[{resampled.time_s[0]:.4f}, {resampled.time_s[-1]:.4f}] s "
                f"(span {_span:.3f} s)"
            )
        except ValueError as _err:
            interp_note = mo.md(f"⚠️ `resample` failed: {_err}")
    interp_note

    return interp_grid_desc, resampled


@app.cell(hide_code=True)
def interp_heatmap(
    InterpMethod,
    cs,
    go,
    interp_grid_desc,
    interp_method,
    mo,
    np,
    resampled,
):
    from plotly.subplots import make_subplots

    # --- heatmap: original vs resampled ---------------------------------------
    interp_heat = None
    if resampled is not None:
        _t0, _v0 = cs.time_s, cs.values
        _t1, _v1 = resampled.time_s, resampled.values
        _s0 = max(1, _t0.size // 500)
        _s1 = max(1, _t1.size // 500)
        _all = np.concatenate([_v0, _v1])
        if cs.meas_type.value == "velocity":
            _m = float(np.nanmax(np.abs(_all))) or 1.0
            _zmin, _zmax, _cmap = -_m, _m, "RdBu_r"
        else:
            _zmin, _zmax, _cmap = (
                float(np.nanmin(_all)),
                float(np.nanmax(_all)),
                "Viridis",
            )
        _fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            subplot_titles=("measured", "resampled"),
        )
        _fig.add_trace(
            go.Heatmap(
                x=cs.gate_depths_mm,
                y=_t0[::_s0],
                z=_v0[::_s0],
                zmin=_zmin,
                zmax=_zmax,
                colorscale=_cmap,
                showscale=False,
            ),
            row=1,
            col=1,
        )
        _fig.add_trace(
            go.Heatmap(
                x=resampled.gate_depths_mm,
                y=_t1[::_s1],
                z=_v1[::_s1],
                zmin=_zmin,
                zmax=_zmax,
                colorscale=_cmap,
                colorbar=dict(title=cs.meas_type.value),
            ),
            row=2,
            col=1,
        )
        _fig.update_layout(
            title=(
                f"ch{cs.channel} — {cs.meas_type.value}: measured vs "
                f"{InterpMethod(interp_method.value).value} · {interp_grid_desc}"
            ),
            xaxis_title="Gate depth [mm]",
            height=760,
        )
        interp_heat = mo.ui.plotly(_fig)
    interp_heat

    return


@app.cell(hide_code=True)
def interp_trace(
    InterpMethod,
    cs,
    gate_idx,
    go,
    interp_grid_desc,
    interp_method,
    mo,
    resampled,
):
    # --- per-gate trace: measured markers vs resampled curve -------------------
    interp_trace = None
    if resampled is not None:
        # clamp in case the recording changed since the gate slider was set
        _g = min(gate_idx.value, cs.gate_count - 1)
        _depth = cs.gate_depths_mm[_g]
        # measured: markers at the actual sampled times
        _meas = go.Scatter(
            x=cs.time_s,
            y=cs.values[:, _g],
            mode="markers",
            name=f"measured ch{cs.channel} gate {_g}",
            marker=dict(size=4, opacity=0.7, color="black"),
        )
        # resampled: continuous line (per-gate interpolation along time)
        _line = go.Scatter(
            x=resampled.time_s,
            y=resampled.values[:, _g],
            mode="lines",
            name=f"{InterpMethod(interp_method.value).value} · {interp_grid_desc}",
            line=dict(width=1.5, color="#d62728"),
        )
        _fig = go.Figure([_meas, _line])
        _fig.update_layout(
            title=(
                f"gate {_g} (depth {_depth:.2f} mm) — measured vs resampled "
                f"[{InterpMethod(interp_method.value).value} · {interp_grid_desc}]"
            ),
            xaxis_title="time [s]",
            yaxis_title=cs.meas_type.value,
            height=420,
            legend=dict(orientation="h", y=1.12),
            hovermode="x unified",
        )
        interp_trace = mo.ui.plotly(_fig)
    interp_trace

    return


if __name__ == "__main__":
    app.run()
