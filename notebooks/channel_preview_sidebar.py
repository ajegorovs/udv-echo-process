import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def imports():
    import marimo as mo

    import numpy as np
    import plotly.graph_objects as go

    from udv_echo_process.io import discover_data_files, load

    return discover_data_files, go, load, mo, np


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Single-channel signal preview — sidebar cursors

    Explore one channel of a `.BDD` recording on the new `io/` + `models/`
    stack. The whole selection cascade lives in the sidebar — recording →
    channel → time → gate — so the cursors stay reachable from any scroll
    position:

    1. **Overview** — full time×gate heatmap + basic value/time stats. Both
       cursors are drawn on it: a vertical line at the selected **time**, a
       horizontal line at the selected **gate**. No time-averaged gate profile:
       the echo is a travelling wave (peak sweeping left→right across gates),
       so per-gate time statistics mix phases.
    2. **Time slice** — intensity/velocity vs gate distance at the selected
       time. Phase-coherent, unlike a time average. Deliberately has no gate
       annotation: both cursors are drawn only on the overview heatmap.
    3. **Gate trace** — the selected gate across time, reused by the
       interpolation and filter sections below (`interp_trace`,
       `filter_gate_trace`).

    Thin wrapper — all parsing stays in `src/udv_echo_process`; this is a
    prototype for understanding the signal.

    **Sidebar variant of `channel_preview.py`**: the recording → channel
    selection moved into the sidebar and the custom scrubber was replaced by
    the time cursor, so the two files are no longer cell-for-cell identical.
    """)
    return


@app.cell(hide_code=True)
def file_picker(discover_data_files, mo):
    # LEVEL 1 of the sidebar cascade. Created and displayed here; its value is
    # read by the channel_picker cell below, never in this cell.
    _files = [str(p) for p in discover_data_files()]
    file_picker = mo.ui.dropdown(
        options=_files,
        value=_files[0] if _files else None,
        label="Recording (.BDD, content-sniffed)",
        full_width=True,  # fill the sidebar instead of clipping the file name
    )
    mo.sidebar([mo.md("### Recording"), file_picker])
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
        full_width=True,
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
    # LEVEL 2 of the cascade — options come from the recording loaded above.
    # The header stays with the control: the sidebar is where the selection lives.
    mo.sidebar([mo.md("### Channel"), channel_picker, _head])
    return bundle, channel_picker


@app.cell(hide_code=True)
def cursor_stores(mo):
    # Cursor positions, remembered per recording so the cascade below does not
    # silently reset them when the file or the channel changes. Update the
    # dicts IMMUTABLY ({**old, key: val}) — in-place mutation is not reactive.
    get_time_default, set_time_default = mo.state({})
    get_gate_default, set_gate_default = mo.state({})
    return (
        get_gate_default,
        get_time_default,
        set_gate_default,
        set_time_default,
    )


@app.cell(hide_code=True)
def channel_select(bundle, channel_picker, mo, np):
    from udv_echo_process.models import ChannelKey
    from udv_echo_process.provenance import select_channel

    selected = (
        select_channel(bundle, ChannelKey(device_channel=channel_picker.value))
        if bundle is not None and channel_picker.value is not None
        else None
    )
    data = selected.artifact.data if selected is not None else None
    _stat_md = mo.md("_Select a recording + channel._")
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
        # gates, so time-averaging mixes phases; use the time cursor below.
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
    _stat_md
    return data, selected


@app.cell(hide_code=True)
def time_picker(data, file_picker, get_time_default, mo, set_time_default):
    # LEVEL 3 of the sidebar cascade: the time cursor, as a profile index.
    # Created here but DISPLAYED by the `time_controls` cell below, which composes
    # it with its step buttons into a single sidebar block. Its .value is read by
    # the cells below, never in this one. The starting index is remembered per
    # recording so a cascade does not silently reset the cursor, and it is clamped
    # so a stale index from a longer recording cannot exceed the new one.
    if data is not None:
        _n = int(data.time_s.size)
        _saved = int(get_time_default().get(file_picker.value, _n // 2))
        _key = file_picker.value
        time_cursor = mo.ui.slider(
            start=0,
            stop=max(1, _n - 1),
            value=max(0, min(_saved, _n - 1)),
            step=1,
            label=(
                f"Time cursor — profile index · t "
                f"{data.time_s[0]:.3f} → {data.time_s[-1]:.3f} s"
            ),
            full_width=True,
            show_value=True,
            on_change=lambda i: set_time_default({**get_time_default(), _key: int(i)}),
        )
    else:
        time_cursor = mo.ui.slider(
            start=0,
            stop=1,
            value=0,
            step=1,
            label="Time cursor",
            full_width=True,
            show_value=True,
        )
    return (time_cursor,)


@app.cell(hide_code=True)
def _(data, file_picker, mo, set_time_default, time_cursor):
    # Step buttons for the Time cursor, over the SAME mo.state the slider writes
    # (`cursor_stores` above), so slider and buttons can never disagree.
    # This cell must stay SEPARATE from `time_picker`: marimo never re-runs the
    # cell that called a state setter, so a slider sharing a cell with its own
    # buttons would never re-seed. It reads `time_cursor.value`; the sidebar block
    # itself is composed by the `time_controls` cell below.
    _n_profiles = int(data.time_s.size) if data is not None else 1
    _hi = max(1, _n_profiles - 1)
    _here = max(0, min(int(time_cursor.value), _hi))
    _page = max(1, _n_profiles // 10)
    _key = file_picker.value


    def _step(_delta):
        # Functional updater: the index is read from the state at CLICK time, so a
        # rapid pair of clicks advances twice instead of merging into one write.
        return lambda _count: set_time_default(
            lambda store: {
                **store,
                _key: max(0, min(int(store.get(_key, _here)) + _delta, _hi)),
            }
        )


    time_page_back = mo.ui.button(label=f"−{_page}", on_click=_step(-_page))
    time_step_back = mo.ui.button(label="−1", on_click=_step(-1))
    time_step_fwd = mo.ui.button(label="+1", on_click=_step(1))
    time_page_fwd = mo.ui.button(label=f"+{_page}", on_click=_step(_page))
    return time_page_back, time_page_fwd, time_step_back, time_step_fwd


@app.cell(hide_code=True)
def _(
    mo,
    time_cursor,
    time_page_back,
    time_page_fwd,
    time_step_back,
    time_step_fwd,
):
    # One sidebar block for LEVEL 3: the slider and its step buttons together.
    # A `mo.sidebar` call that is not THIS cell's final expression is silently
    # dropped, so the composed element IS the last statement.
    mo.sidebar(
        mo.vstack(
            [
                mo.md("### Time"),
                time_cursor,
                mo.hstack(
                    [time_page_back, time_step_back, time_step_fwd, time_page_fwd],
                    justify="space-between",
                ),
            ]
        )
    )
    return


@app.cell(hide_code=True)
def gate_picker(data, file_picker, get_gate_default, mo, set_gate_default):
    # LEVEL 4 of the cascade: the gate cursor — same rules as the time cursor.
    # `options` is {label: value}, so `value=` takes a LABEL, not the index.
    if data is not None:
        _depths = data.gate_depths_mm
        _n = int(_depths.size)
        _labels = {_g: f"gate {_g} — {_depths[_g]:.2f} mm" for _g in range(_n)}
        _mid = _n // 2
        _saved = int(get_gate_default().get(file_picker.value, _mid))
        _key = file_picker.value
        gate_cursor = mo.ui.dropdown(
            options={_labels[_g]: _g for _g in range(_n)},
            value=_labels[_saved if _saved in _labels else _mid],
            label="Gate cursor (trace view)",
            full_width=True,
            on_change=lambda g: set_gate_default({**get_gate_default(), _key: int(g)}),
        )
    else:
        gate_cursor = mo.ui.dropdown(
            options={"gate 0": 0}, value="gate 0", label="Gate cursor", full_width=True
        )
    mo.sidebar([mo.md("### Gate"), gate_cursor])
    return (gate_cursor,)


@app.cell(hide_code=True)
def overview(data, gate_cursor, go, mo, np, selected, time_cursor):
    # Cursor-bearing heatmap of the measured values: x = time, y = gate depth,
    # z = value. Both cursors are drawn on it — a vertical line at the selected
    # time, a horizontal line at the selected gate depth — so the two views
    # below are located on the map. Keep the figure light by striding the long
    # (time) axis; every gate stays a row (z is transposed to (G, T)).
    heat = None
    if selected is not None:
        _art = selected.artifact
        _ch = _art.acquisition.channel.device_channel
        _quantity = _art.descriptor.quantity.value
        _t = data.time_s
        _v = data.values
        _i = int(time_cursor.value)
        _g = int(gate_cursor.value)
        _t_sel = float(_t[_i])
        _d_sel = float(data.gate_depths_mm[_g])
        _stride = max(1, _t.size // 800)
        _z = _v[::_stride].T
        # The crosshair colour is chosen per colormap, next to it so the two cannot
        # drift apart. Measured against the real heatmap pixels (CIELAB):
        if _quantity == "axial_velocity":
            _m = float(np.nanmax(np.abs(_z))) or 1.0
            _kw = dict(zmin=-_m, zmax=_m, colorscale="RdBu_r")
            # RdBu_r is near-white through the middle AND the velocity data sits
            # there (palette median lightness ~92), so the line must be DARKER than
            # the map: green leaves 0.0% of pixels within 15 dL.
            _line = "#43A047"
        else:
            _kw = dict(colorscale="Viridis")
            # Viridis sweeps purple -> blue -> green -> yellow, so a green crosshair
            # lands on its own mid-band (worst-case dE 13.6) and disappears. Red
            # separates by HUE everywhere (worst-case dE 90.4) because Viridis holds
            # no red at all — dL alone would wrongly rank the reds as worse.
            _line = "#FF1744"
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
                f"(every {_stride}th profile shown) · cursors: "
                f"t = {_t_sel:.4f} s, gate {_g}"
            ),
            xaxis_title="time [s]",
            yaxis_title="Gate depth [mm]",
            height=520,
        )
        _fig.add_vline(x=_t_sel, line=dict(color=_line, width=2.5, dash="dot"))
        _fig.add_hline(y=_d_sel, line=dict(color=_line, width=2.5, dash="dash"))
        heat = mo.ui.plotly(_fig)
    heat
    return


@app.cell(hide_code=True)
def cursor_readout(data, gate_cursor, mo, np, selected, time_cursor):
    # The crosshair's numbers, in the sidebar below the two controls — a bare
    # slider index says nothing on a 4900-profile recording.
    #
    # This is its own cell ON PURPOSE: a `mo.sidebar` call that is not the
    # cell's FINAL EXPRESSION is silently dropped — no error, no warning, the
    # entry simply never appears (verified on marimo 0.24.0 with a probe
    # notebook, for both a mid-cell call and a second call in one cell). So it
    # cannot live in `overview`, whose output is the heatmap.
    _readout: list = []
    if selected is not None:
        _i = int(time_cursor.value)
        _g = int(gate_cursor.value)
        _val = data.values[_i, _g]
        _readout = [
            mo.md(
                f"cursor → t = **{float(data.time_s[_i]):.4f} s** "
                f"(profile {_i}/{data.time_s.size - 1}) · gate **{_g}** = "
                f"{float(data.gate_depths_mm[_g]):.2f} mm · value "
                + (f"{_val:.4g}" if np.isfinite(_val) else "`missing`")
            )
        ]
    mo.sidebar(_readout)
    return


@app.cell(hide_code=True)
def time_slice(data, go, mo, selected, time_cursor):
    # Cursor view 1: one time slice across every gate. A single profile is
    # phase-coherent where a time average is not — the echo peak sweeps
    # left→right across gates. Deliberately decoupled from the gate cursor: the
    # crosshair belongs on the overview heatmap only, so this view does not
    # re-run when the gate moves.
    time_slice = None
    if selected is not None:
        _art = selected.artifact
        _i = int(time_cursor.value)
        _t_sel = float(data.time_s[_i])
        _fig = go.Figure(
            go.Scatter(
                x=data.gate_depths_mm,
                y=data.values[_i],
                mode="lines+markers",
                name=f"profile {_i}",
                line=dict(width=1.6),
                marker=dict(size=5),
            )
        )
        _fig.update_layout(
            title=(
                f"ch{_art.acquisition.channel.device_channel} — "
                f"{_art.descriptor.quantity.value} at t = {_t_sel:.4f} s "
                f"(profile {_i} of {data.time_s.size})"
            ),
            xaxis_title="gate depth [mm]",
            yaxis_title=(
                f"{_art.descriptor.quantity.value} [{_art.descriptor.unit}]"
            ),
            height=380,
        )
        time_slice = mo.ui.plotly(_fig)
    time_slice
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
        show_value=True,
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
        show_value=True,
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
def interp_trace(
    data,
    gate_cursor,
    go,
    interp_grid_desc,
    interp_method,
    mo,
    resampled,
    selected,
):
    # --- per-gate trace: measured markers vs resampled curve -------------------
    # gate is the sidebar Gate cursor (gate_picker above)
    interp_trace = None
    if resampled is not None and data is not None:
        _g = int(gate_cursor.value)
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
        start=3,
        stop=51,
        step=2,
        value=5,
        label="window [samples]",
        show_value=True,
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
        show_value=True,
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
        show_value=True,
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
    gate_cursor,
    go,
    mo,
):
    # --- per-gate trace: before vs after on the selected gate ------------------
    # gate is the sidebar Gate cursor (gate_picker above)
    filter_gate_trace = None
    if filtered is not None and filter_input is not None:
        _in = filter_input.artifact.data
        _out = filtered.artifact.data
        _g = int(gate_cursor.value)
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
