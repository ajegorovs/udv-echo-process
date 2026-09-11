import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def imports():
    import marimo as mo

    import numpy as np
    import plotly.graph_objects as go

    from marimo_inspection import TraceScrubber
    from udv_echo_process.io import discover_data_files, load

    return TraceScrubber, discover_data_files, go, load, mo, np


@app.cell(hide_code=True)
def intro(mo):
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
def file_picker(discover_data_files, mo):
    _files = [str(p) for p in discover_data_files()]
    file_picker = mo.ui.dropdown(
        options=_files,
        value=_files[0] if _files else None,
        label="Recording (.BDD, content-sniffed)",
    )
    file_picker
    return (file_picker,)


@app.cell(hide_code=True)
def channel_picker(file_picker, load, mo):
    bundle = load(file_picker.value) if file_picker.value else None
    if bundle is not None:
        _recording = bundle.recording
        _asset = _recording.source_asset
        _ids = [s.acquisition.channel.device_channel for s in _recording.streams]
    else:
        _ids = []
    channel_picker = mo.ui.dropdown(
        options=_ids,
        value=_ids[0] if _ids else None,
        label="Channel",
    )
    _head = (
        mo.md(
            f"**{_asset.file_name}** · {_asset.source}  \n"
            f"{len(_recording.streams)} channel(s) · "
            f"{_recording.acquisition_mode.value} · "
            f"sha256:{_asset.content_sha256[:12]}…"
        )
        if bundle is not None
        else mo.md("_No recording selected._")
    )
    # render the channel selector together with the header so it is reachable
    mo.vstack([_head, channel_picker])
    return bundle, channel_picker


@app.cell(hide_code=True)
def overview(bundle, channel_picker, go, mo, np):
    from udv_echo_process.models import ChannelKey
    from udv_echo_process.provenance import select_channel

    selected = (
        select_channel(bundle, ChannelKey(device_channel=channel_picker.value))
        if bundle is not None and channel_picker.value is not None
        else None
    )
    data = selected.artifact.data if selected is not None else None
    _stat_md = mo.md("_Select a recording + channel._")
    heat = None
    if selected is not None:
        _art = selected.artifact
        _ch = _art.acquisition.channel.device_channel
        _quantity = _art.descriptor.quantity.value
        _t = data.time_s
        _v = data.values
        _fin = np.isfinite(_v)
        _dt_s = np.diff(_t)
        _g0, _g1 = data.gate_depths_mm[0], data.gate_depths_mm[-1]
        # NB: no time-meaned gate profile here — the echo peak sweeps across
        # gates, so time-averaging mixes phases; use the scrubber below instead.
        _lines = [
            f"`ch{_ch}` · **{_quantity}** ({_art.descriptor.unit}) · "
            f"{data.time_s.size} profiles × {data.gate_depths_mm.size} gates",
            f"- gate depths: {_g0:.2f} → {_g1:.2f} mm ({data.gate_depths_mm.size} gates)",
            f"- time: {_t[0]:.4f} → {_t[-1]:.4f} s ({_dt_s.size} intervals, "
            f"median dt {np.median(_dt_s) * 1e3:.3f} ms)"
            if _dt_s.size
            else "- time: single profile",
            f"- values: finite {int(_fin.sum())}/{_fin.size} · "
            f"min {np.nanmin(_v):.3g} · mean {np.nanmean(_v):.3g} · "
            f"max {np.nanmax(_v):.3g}",
            f"- config: {_art.config.describe()}",
        ]
        _stat_md = mo.md("\n".join(_lines))
        # heatmap of the measured values: x = time, y = gate depth, z = value.
        # Keep the figure light by striding the long (time) axis; every gate
        # stays a row (z is transposed to (G, T)).
        _stride = max(1, _t.size // 800)
        _z = _v[::_stride].T
        if _quantity == "axial_velocity":
            _m = float(np.nanmax(np.abs(_z))) or 1.0
            _kw = dict(zmin=-_m, zmax=_m, colorscale="RdBu_r")
        else:
            _kw = dict(colorscale="Viridis")
        _fig = go.Figure(
            go.Heatmap(
                x=_t[::_stride],
                y=data.gate_depths_mm,
                z=_z,
                colorbar={"title": f"{_quantity} [{_art.descriptor.unit}]"},
                **_kw,
            )
        )
        _fig.update_layout(
            title=(
                f"ch{_ch} — {_quantity} over time "
                f"(every {_stride}th profile shown)"
            ),
            xaxis_title="time [s]",
            yaxis_title="Gate depth [mm]",
            height=520,
        )
        heat = mo.ui.plotly(_fig)
    # final expression: channel info above the measured heatmap
    mo.vstack([x for x in (_stat_md, heat) if x is not None])
    return data, selected


@app.cell(hide_code=True)
def scrubber(TraceScrubber, np, selected):
    scrub = None
    if selected is not None:
        _art = selected.artifact
        _data = _art.data
        _quantity = _art.descriptor.quantity.value
        if _quantity == "echo_amplitude":
            # echo: explicit module range, known a priori
            _y_lo, _y_hi = 0.0, 2000.0
        else:
            # velocity: fixed axis over the channel-wide raw range (mm/s) so
            # frames never re-scale between steps; outliers stretch as-is
            _y_lo = float(np.nanmin(_data.values))
            _y_hi = float(np.nanmax(_data.values))
        scrub = TraceScrubber().update(
            x=_data.gate_depths_mm,
            values=np.array(_data.values),  # writeable copy (model arrays are RO)
            times=_data.time_s,
            title=(
                f"ch{_art.acquisition.channel.device_channel} — {_quantity} "
                f"profile vs gate depth · {_data.time_s.size} frames · "
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

    Landed API: `resample(bundle: ChannelBundle, spec: InterpSpec, *, times |
    dt_s) -> ChannelBundle` interpolates each gate along time (plan §7.3). A
    `ChannelBundle` is one channel's artifact plus its provenance graph —
    `select_channel(bundle, ChannelKey(...))` is the bridge from a recording.

    - **Method** — `linear` (honest across the ~370 ms inter-visit gaps of the
      4-sensor fixture: it cannot overshoot), `monotone` (PCHIP), `cubic` /
      `bspline` (smooth, may overshoot, uniform cadence only — use on the echo
      fixture).
    - **Target grid** — a uniform `dt` (bridges the gaps) or the original knot
      times (round-trip: resampled values reproduce the measured ones).
    - **Extrapolation** — `error` (refuse), `missing` (`MISSING` + reason),
      `nearest` (edge-clamped `EXTRAPOLATED`); the margin slider pushes the grid
      past the measured span to exercise it.
    - View: a per-gate trace overlay (measured markers vs resampled curve).
    """)
    return


@app.cell(hide_code=True)
def interp_controls(mo, np, selected):
    from udv_echo_process.process import (
        BsplineInterpSpec,
        CubicInterpSpec,
        LinearInterpSpec,
        MonotoneInterpSpec,
        resample,
    )

    # --- interpolation controls ------------------------------------------------
    interp_method = mo.ui.dropdown(
        options=["linear", "monotone", "cubic", "bspline"],
        value="linear",
        label="Interpolation method",
    )
    # dt default = native median cadence of the selected channel
    _native_dt_s = (
        float(np.median(np.diff(selected.artifact.data.time_s)))
        if selected is not None and selected.artifact.data.time_s.size > 1
        else 0.001
    )
    interp_dt_ms = mo.ui.slider(
        start=0.1,
        stop=max(0.5, round(_native_dt_s * 8e3, 1)),
        value=round(_native_dt_s * 1e3, 2),
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
    # --- extrapolation testing -------------------------------------------------
    # extrapolation only ever triggers when the target grid leaves the measured
    # span [time_s[0], time_s[-1]]; the margin slider pushes the grid past one or
    # both ends so the policy dropdown below is actually exercised.
    interp_extrap = mo.ui.dropdown(
        options=["error", "missing", "nearest"],
        value="error",
        label="Extrapolation policy (out-of-span rows)",
    )
    interp_extrap_side = mo.ui.dropdown(
        options=["both ends", "start only", "end only"],
        value="both ends",
        label="Extrapolate beyond",
    )
    _span_ms = (
        float(selected.artifact.data.time_s[-1] - selected.artifact.data.time_s[0])
        * 1e3
        if selected is not None and selected.artifact.data.time_s.size > 1
        else 1000.0
    )
    interp_margin_ms = mo.ui.slider(
        start=0.0,
        stop=float(max(100.0, min(_span_ms / 4.0, 5000.0))),
        value=0.0,
        step=5.0,
        label="Margin past the measured span [ms] (0 = off)",
    )
    # final expression: render the control stack as this cell's output
    mo.vstack(
        [
            interp_method,
            interp_dt_ms,
            interp_grid,
            spline_order,
            interp_extrap,
            interp_extrap_side,
            interp_margin_ms,
        ]
    )
    return (
        BsplineInterpSpec,
        CubicInterpSpec,
        LinearInterpSpec,
        MonotoneInterpSpec,
        interp_dt_ms,
        interp_extrap,
        interp_extrap_side,
        interp_grid,
        interp_margin_ms,
        interp_method,
        resample,
        spline_order,
    )


@app.cell(hide_code=True)
def interp_run(
    BsplineInterpSpec,
    CubicInterpSpec,
    LinearInterpSpec,
    MonotoneInterpSpec,
    interp_dt_ms,
    interp_extrap,
    interp_extrap_side,
    interp_grid,
    interp_margin_ms,
    interp_method,
    mo,
    np,
    resample,
    selected,
    spline_order,
):
    # --- run resample and summarize --------------------------------------------
    resampled = None
    interp_note = None
    interp_grid_desc = "—"
    if selected is not None:
        _data = selected.artifact.data
        _extrap = interp_extrap.value  # "error" | "missing" | "nearest"
        _branch = {
            "linear": LinearInterpSpec,
            "monotone": MonotoneInterpSpec,
            "cubic": CubicInterpSpec,
            "bspline": BsplineInterpSpec,
        }[interp_method.value]
        _kwargs: dict = dict(
            extrapolation=_extrap,
            max_bracket_span_s=max(1.0, float(_data.time_s[-1] - _data.time_s[0])),
            long_gap="missing",
        )
        if interp_method.value == "bspline":
            _kwargs["order"] = int(spline_order.value)
        if interp_method.value in ("cubic", "bspline"):
            _kwargs["uniform_rtol"] = 0.05
        _spec = _branch(**_kwargs)
        _lo, _hi = float(_data.time_s[0]), float(_data.time_s[-1])
        _margin_ms = float(interp_margin_ms.value)
        _side = interp_extrap_side.value
        _at_start = _margin_ms > 0.0 and _side in ("start only", "both ends")
        _at_end = _margin_ms > 0.0 and _side in ("end only", "both ends")
        _n_out = 0
        try:
            if interp_grid.value == "dt grid":
                _dt = float(interp_dt_ms.value) / 1000.0
                if _at_start or _at_end:
                    _lo2 = _lo - _margin_ms / 1000.0 if _at_start else _lo
                    _hi2 = _hi + _margin_ms / 1000.0 if _at_end else _hi
                    _times = np.arange(_lo2, _hi2, _dt)
                    if _times.size == 0 or _times[-1] < _hi2 - 1e-12 * max(
                        1.0, abs(_hi2)
                    ):
                        _times = np.concatenate([_times, [_hi2]])
                    _target = dict(times=_times)
                    _n_out = int(np.count_nonzero((_times < _lo) | (_times > _hi)))
                    _side_desc = _side
                else:
                    _target = dict(dt_s=_dt)
                    _side_desc = ""
                _grid_base = f"dt = {interp_dt_ms.value:.3f} ms"
            else:
                _pre = (
                    np.array([_lo - _margin_ms / 1000.0])
                    if _at_start
                    else np.array([])
                )
                _post = (
                    np.array([_hi + _margin_ms / 1000.0]) if _at_end else np.array([])
                )
                if _at_start or _at_end:
                    _target = dict(times=np.concatenate([_pre, _data.time_s, _post]))
                    _n_out = int(_pre.size + _post.size)
                    _side_desc = _side
                else:
                    _target = dict(times=_data.time_s)
                    _side_desc = ""
                _grid_base = "knot times (round-trip)"
            interp_grid_desc = _grid_base + (
                f" + {_margin_ms:.0f} ms ({_side_desc})"
                if (_at_start or _at_end)
                else ""
            )
            resampled = resample(selected, _spec, **_target)
            _out = resampled.artifact.data
            _span = _out.time_s[-1] - _out.time_s[0]
            _policy_desc = {
                "error": "would raise — never a silent clamp",
                "missing": "out-of-span rows are MISSING (NaN, OUT_OF_RANGE)",
                "nearest": "out-of-span rows edge-clamped as EXTRAPOLATED",
            }[_extrap]
            _lines = [
                f"**{interp_method.value}** on `{interp_grid_desc}` → "
                f"`resampled` = {_out.time_s.size} samples over "
                f"[{_out.time_s[0]:.4f}, {_out.time_s[-1]:.4f}] s "
                f"(span {_span:.3f} s)",
            ]
            _lines.append(
                f"- extrapolation **{_extrap}**: {_n_out} of {_out.time_s.size} "
                f"rows lie outside the measured span [{_lo:.4f}, {_hi:.4f}] s "
                f"→ {_policy_desc}"
                if _n_out
                else "- extrapolation: grid stays inside the measured span "
                "(margin 0 or untriggered) — policy not exercised"
            )
            interp_note = mo.md("\n".join(_lines))
        except ValueError as _err:
            resampled = None
            interp_note = mo.md(f"⚠️ `resample` failed: {_err}")
    interp_note
    return interp_grid_desc, resampled


@app.cell(hide_code=True)
def interp_gate(data, mo):
    # --- gate selector for the per-gate trace ---------------------------------
    # Its own cell on purpose: a cell cannot read the .value of a UI element it
    # created in the same run — the interp_trace cell below consumes gate_idx.
    # marimo dict options are {displayed label: returned value}; the initial
    # value is given as one of the displayed labels (option names).
    if data is not None:
        _mid = data.gate_depths_mm.size // 2
        gate_idx = mo.ui.dropdown(
            options={
                f"gate {_g} — {data.gate_depths_mm[_g]:.2f} mm": _g
                for _g in range(data.gate_depths_mm.size)
            },
            value=f"gate {_mid} — {data.gate_depths_mm[_mid]:.2f} mm",
            label="Gate (trace view)",
        )
    else:
        gate_idx = mo.ui.dropdown(
            options={"gate 0": 0}, value="gate 0", label="Gate (trace view)"
        )
    gate_idx
    return (gate_idx,)


@app.cell(hide_code=True)
def interp_trace(
    data,
    gate_idx,
    go,
    interp_grid_desc,
    interp_method,
    mo,
    resampled,
    selected,
):
    # --- per-gate trace: measured markers vs resampled curve -------------------
    # gate is chosen with the interp_gate dropdown (defined in its own cell above)
    interp_trace = None
    if resampled is not None and data is not None:
        _g = int(gate_idx.value)
        _depth = data.gate_depths_mm[_g]
        _out = resampled.artifact.data
        # measured: markers at the actual sampled times
        _meas = go.Scatter(
            x=data.time_s,
            y=data.values[:, _g],
            mode="markers",
            name=f"measured gate {_g}",
            marker=dict(size=4, opacity=0.7, color="black"),
        )
        # resampled: continuous line (per-gate interpolation along time)
        _line = go.Scatter(
            x=_out.time_s,
            y=_out.values[:, _g],
            mode="lines",
            name=f"{interp_method.value} · {interp_grid_desc}",
            line=dict(width=1.5, color="#d62728"),
        )
        _fig = go.Figure([_meas, _line])
        _fig.update_layout(
            title=(
                f"gate {_g} (depth {_depth:.2f} mm) — measured vs resampled "
                f"[{interp_method.value} · {interp_grid_desc}]"
            ),
            xaxis_title="time [s]",
            yaxis_title=selected.artifact.descriptor.quantity.value,
            height=420,
            legend=dict(orientation="h", y=1.12),
            hovermode="x unified",
        )
        interp_trace = mo.ui.plotly(_fig)
    interp_trace
    return


@app.cell(hide_code=True)
def filter_intro(mo):
    mo.md("""
    ### Filter preview — `process/filter.py` `filter()` / `filter_sequence()`

    Landed API: `filter(bundle: ChannelBundle, spec: FilterSpec) -> ChannelBundle`
    (and `filter_sequence`, a plain fold). One filter pass over the selected
    data (below): the measured channel for the index-window methods (MEDIAN /
    MEAN / SAVGOL — they smooth the measurements, not an interpolation), or the
    uniform `resampled` grid from the interpolation section when you also want
    TV (TV is index-based and requires a uniform cadence — the layer rejects it
    on the gappy raw series by design). Only `values` and the accumulated
    quality change, per gate; the time grid and gates are untouched.
    """)
    return


@app.cell(hide_code=True)
def filter_controls(mo, resampled):
    from udv_echo_process.process import (
        MeanFilterSpec,
        MedianFilterSpec,
        SavgolFilterSpec,
        TvFilterSpec,
        filter as filter_bundle,
    )

    # --- one-filter controls --------------------------------------------------
    _meas_label = "measured — selected channel (raw cadence)"
    _filter_opts = {_meas_label: "selected"}
    if resampled is not None:
        _filter_opts["resampled — uniform dt grid"] = "resampled"
    filter_source = mo.ui.dropdown(
        options=_filter_opts,
        value=_meas_label,
        label="Apply filter to",
    )
    filter_method = mo.ui.dropdown(
        options=["median", "mean", "savgol", "tv"],
        value="median",
        label="Filter method",
    )
    # odd-only slider: MEDIAN/SAVGOL require an odd window, MEAN accepts any
    filter_window = mo.ui.slider(
        start=3, stop=51, step=2, value=5, label="window [samples]"
    )
    filter_polyorder = mo.ui.number(
        start=0, stop=8, step=1, value=2, label="polyorder (SAVGOL only, < window)"
    )
    filter_weight = mo.ui.slider(
        start=0.05,
        stop=20.0,
        step=0.05,
        value=1.0,
        label="weight λ (TV only — larger = smoother)",
    )
    filter_iterations = mo.ui.number(
        start=10, stop=5000, step=10, value=200, label="iterations (TV only)"
    )
    # largest time gap a window may span; a larger gap starts a new segment
    filter_max_gap_ms = mo.ui.slider(
        start=1.0,
        stop=500.0,
        step=1.0,
        value=40.0,
        label="max_gap_s [ms] — largest gap a window may cross",
    )
    mo.vstack(
        [
            filter_source,
            filter_method,
            filter_window,
            filter_polyorder,
            filter_weight,
            filter_iterations,
            filter_max_gap_ms,
        ]
    )
    return (
        MeanFilterSpec,
        MedianFilterSpec,
        SavgolFilterSpec,
        TvFilterSpec,
        filter_bundle,
        filter_iterations,
        filter_max_gap_ms,
        filter_method,
        filter_polyorder,
        filter_source,
        filter_weight,
        filter_window,
    )


@app.cell(hide_code=True)
def filter_run(
    MeanFilterSpec,
    MedianFilterSpec,
    SavgolFilterSpec,
    TvFilterSpec,
    filter_bundle,
    filter_iterations,
    filter_max_gap_ms,
    filter_method,
    filter_polyorder,
    filter_source,
    filter_weight,
    filter_window,
    mo,
    np,
    resampled,
    selected,
):
    # --- apply the chosen filter, summarize ------------------------------------
    filter_input = None
    filtered = None
    filter_spec_desc = "—"
    filter_src_desc = "—"
    filter_note = None
    if selected is not None:
        _method = filter_method.value
        _gap_s = float(filter_max_gap_ms.value) / 1000.0
        try:
            if _method == "median":
                _spec = MedianFilterSpec(
                    window=int(filter_window.value), max_gap_s=_gap_s
                )
            elif _method == "mean":
                _spec = MeanFilterSpec(window=int(filter_window.value), max_gap_s=_gap_s)
            elif _method == "savgol":
                _spec = SavgolFilterSpec(
                    window=int(filter_window.value),
                    polyorder=int(filter_polyorder.value),
                    max_gap_s=_gap_s,
                )
            else:
                _spec = TvFilterSpec(
                    weight=float(filter_weight.value),
                    iterations=int(filter_iterations.value),
                    max_gap_s=_gap_s,
                )
            if filter_source.value == "resampled" and resampled is None:
                raise ValueError(
                    "resampled is not available — run the interpolation section first"
                )
            filter_input = selected if filter_source.value == "selected" else resampled
            filter_src_desc = (
                "measured (raw cadence)"
                if filter_source.value == "selected"
                else "resampled (uniform dt grid)"
            )
            filtered = filter_bundle(filter_input, _spec)
            _knobs = []
            if _method in ("median", "mean", "savgol"):
                _knobs.append(f"window {_spec.window}")
            if _method == "savgol":
                _knobs.append(f"polyorder {_spec.polyorder}")
            if _method == "tv":
                _knobs.append(f"weight {_spec.weight:g}")
                _knobs.append(f"iterations {_spec.iterations}")
            _knobs.append(f"max_gap {float(filter_max_gap_ms.value):g} ms")
            filter_spec_desc = f"{_method} · " + ", ".join(_knobs)
            _in = filter_input.artifact.data
            _out = filtered.artifact.data
            _d = _out.values - _in.values
            _ok = np.isfinite(_d)
            _d_fin = _d[_ok]
            _lines = [
                f"**{_method}** over **{filter_src_desc}** → "
                f"`filtered` = {_out.time_s.size} × {_out.gate_depths_mm.size} "
                f"(grid unchanged: {_in.time_s[0]:.4f} → "
                f"{_in.time_s[-1]:.4f} s)",
                f"- Δ (after − before), finite pairs {int(_ok.sum())}/{_ok.size}: "
                f"mean |Δ| {np.mean(np.abs(_d_fin)):.4g} · "
                f"max |Δ| {np.max(np.abs(_d_fin)):.4g}",
                f"- provenance: {len(filtered.graph.operations)} operation(s), "
                f"last kind `{filtered.graph.operations[-1].kind}`",
            ]
            filter_note = mo.md("\n".join(_lines))
        except ValueError as _err:
            filtered = None
            filter_input = None
            filter_note = mo.md(f"⚠️ `filter` rejected: {_err}")
    filter_note
    return filter_input, filter_spec_desc, filter_src_desc, filtered


@app.cell(hide_code=True)
def filter_heatmaps(
    filter_input,
    filter_spec_desc,
    filter_src_desc,
    filtered,
    mo,
    np,
):
    # --- heatmaps: before vs after (shared color scale) -----------------------
    from plotly.subplots import make_subplots

    filter_heat = None
    if filtered is not None and filter_input is not None:
        _in = filter_input.artifact.data
        _out = filtered.artifact.data
        _quantity = filter_input.artifact.descriptor.quantity.value
        _stride = max(1, _in.time_s.size // 700)
        _t = _in.time_s[::_stride]
        _z_in = _in.values[::_stride].T
        _z_out = _out.values[::_stride].T
        _both = np.concatenate([_z_in.ravel(), _z_out.ravel()])
        if _quantity == "axial_velocity":
            _m = float(np.nanmax(np.abs(_both))) or 1.0
            _kw = dict(zmin=-_m, zmax=_m, colorscale="RdBu_r")
        else:
            _kw = dict(
                zmin=float(np.nanmin(_both)),
                zmax=float(np.nanmax(_both)),
                colorscale="Viridis",
            )
        _fig = make_subplots(
            rows=1,
            cols=2,
            subplot_titles=(
                f"before — {filter_src_desc}",
                f"after — {filter_spec_desc}",
            ),
            shared_yaxes=True,
            horizontal_spacing=0.08,
        )
        _fig.add_heatmap(
            x=_t,
            y=_in.gate_depths_mm,
            z=_z_in,
            colorbar={"title": _quantity},
            showscale=True,
            **_kw,
            row=1,
            col=1,
        )
        _fig.add_heatmap(
            x=_t,
            y=_out.gate_depths_mm,
            z=_z_out,
            showscale=False,
            **_kw,
            row=1,
            col=2,
        )
        _fig.update_layout(
            height=480,
            margin=dict(t=60, b=40, l=10, r=10),
            hovermode="closest",
        )
        _fig.update_xaxes(title_text="time [s]", row=1, col=1)
        _fig.update_xaxes(title_text="time [s]", row=1, col=2)
        _fig.update_yaxes(title_text="gate depth [mm]", row=1, col=1)
        filter_heat = mo.ui.plotly(_fig)
    filter_heat
    return


@app.cell(hide_code=True)
def filter_gate_trace(
    filter_input,
    filter_source,
    filter_spec_desc,
    filter_src_desc,
    filtered,
    gate_idx,
    go,
    mo,
):
    # --- per-gate trace: before vs after on the selected gate ------------------
    # gate is chosen with the interp section's Gate dropdown (gate_idx above)
    filter_gate_trace = None
    if filtered is not None and filter_input is not None:
        _in = filter_input.artifact.data
        _out = filtered.artifact.data
        _g = int(gate_idx.value)
        _depth = _in.gate_depths_mm[_g]
        _before = go.Scatter(
            x=_in.time_s,
            y=_in.values[:, _g],
            mode="markers" if filter_source.value == "selected" else "lines",
            name="before — " + filter_src_desc,
            marker=dict(size=3.5, opacity=0.6, color="black"),
            line=dict(width=1, color="gray"),
        )
        _after = go.Scatter(
            x=_out.time_s,
            y=_out.values[:, _g],
            mode="lines",
            name="after — " + filter_spec_desc,
            line=dict(width=1.8, color="#2ca02c"),
        )
        _fig = go.Figure([_before, _after])
        _fig.update_layout(
            title=(
                f"gate {_g} — {_depth:.2f} mm · before vs after "
                f"({filter_spec_desc})"
            ),
            xaxis_title="time [s]",
            yaxis_title=filter_input.artifact.descriptor.quantity.value,
            height=380,
            legend=dict(orientation="h", y=1.12),
            hovermode="x unified",
        )
        filter_gate_trace = mo.ui.plotly(_fig)
    filter_gate_trace
    return


if __name__ == "__main__":
    app.run()
