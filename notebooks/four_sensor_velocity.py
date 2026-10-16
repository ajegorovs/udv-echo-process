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

    from udv_echo_process.io import load

    return Path, go, load, make_subplots, mo, np


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Four-sensor velocity preview — one recording, all four channels

    The 2x2 orthogonal mounting of the four-sensor fixture (device channels 6, 7, 8, 9) in
    four views:

    1. **Overview** — all four channels as heatmaps on **one shared colour scale**, with
       both cursors drawn on every panel (vertical = selected time, horizontal = selected
       gate).
    2. **Depth profiles at the selected time** — 2x2, velocity vs gate depth.
    3. **Gate traces at the selected gate** — 2x2, velocity vs time.

    **What this notebook refuses to do.** The four channels are *multiplexed*: one channel
    is visited at a time, ~112 ms apart in the order 6 -> 7 -> 8 -> 9, so no two channels
    are ever sampled at the same instant. Nothing here is shifted, interpolated or resampled
    to make a view possible:

    - the heatmap and trace panels plot each channel on **its own recorded timestamps**;
    - at the selected time each channel shows its **nearest stored profile**, and the panel
      states that profile's own timestamp and its offset from the cursor, so the stagger is
      visible instead of hidden;
    - depth is the one coordinate all four channels share (the same 55-gate grid,
      20.00 -> 79.13 mm), so depth comparisons need no alignment at all.

    **What to expect.** Channels 6 and 8 both sit 30 mm from the vessel centre line, in the
    two orthogonal mounts, and 7 and 9 both sit at 20 mm, so the mounting's 90-degree
    symmetry makes 6 <-> 8 and 7 <-> 9 the pairs to compare. Measured on this recording
    those pairs agree in *shape* (mean depth profile r = +0.94 / +0.95) but differ in
    *level* by 1.31 / 1.24 — a mount-to-mount factor that is not the flow symmetry and is
    still to be explained. See
    [`data/4-sensor-velocity/README.md`](../../data/4-sensor-velocity/README.md).
    """)
    return


@app.cell(hide_code=True)
def recording(Path, load, mo):
    # ONE hardcoded recording (the owner's stated starting point, 2026-10-16). The path is
    # resolved against this notebook's own directory first, so an export, or a run from a
    # different working directory, loads the same committed file rather than failing.
    RECORDING_RELATIVE = "data/4-sensor-velocity/200RPM.BDD"
    _notebook_dir = (
        Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
    )
    _candidates = (_notebook_dir.parent, Path.cwd(), _notebook_dir)
    _root = next(
        (_candidate for _candidate in _candidates if (_candidate / RECORDING_RELATIVE).is_file()),
        None,
    )
    if _root is None:
        raise FileNotFoundError(
            f"{RECORDING_RELATIVE} not found from any of "
            f"{[str(_candidate) for _candidate in _candidates]}"
        )
    recording_path = _root / RECORDING_RELATIVE
    bundle = load(recording_path)
    _asset = bundle.recording.source_asset
    mo.md(
        f"**{_asset.file_name}** · `{recording_path.relative_to(_root)}` · "
        f"{bundle.recording.acquisition_mode.value} acquisition · "
        f"{len(bundle.recording.streams)} channel(s) · "
        f"sha256:{_asset.content_sha256[:12]}…"
    )
    return bundle, recording_path


@app.cell(hide_code=True)
def channel_series(bundle, np):
    # The four channels in the recording's own stream order, which is the acquisition's
    # visit order. `load` has already frozen and owned every array, so these are read-only
    # views of the decoded signal and nothing here copies or rewrites it.
    _streams = bundle.recording.streams
    channel_ids = tuple(int(_s.acquisition.channel.device_channel) for _s in _streams)
    times = {
        _ch: np.asarray(_s.data.time_s, dtype=float)
        for _ch, _s in zip(channel_ids, _streams, strict=True)
    }
    values = {
        _ch: np.asarray(_s.data.values, dtype=float)
        for _ch, _s in zip(channel_ids, _streams, strict=True)
    }
    quantity = _streams[0].descriptor.quantity.value
    unit = _streams[0].descriptor.unit
    gate_depths_mm = np.asarray(_streams[0].data.gate_depths_mm, dtype=float)
    # A gate index is only a shared coordinate if every channel stored the same grid. That
    # is a measurement, not an assumption, so it is checked here and reported below.
    same_gate_grid = all(
        np.array_equal(gate_depths_mm, np.asarray(_s.data.gate_depths_mm, dtype=float))
        for _s in _streams
    )
    time_span_s = (
        min(float(_t[0]) for _t in times.values()),
        max(float(_t[-1]) for _t in times.values()),
    )
    return (
        channel_ids,
        gate_depths_mm,
        quantity,
        same_gate_grid,
        time_span_s,
        times,
        unit,
        values,
    )


@app.cell(hide_code=True)
def cursor_memory(mo):
    # PRESENTATION state only, in the `signal_explorer.py` shape: each cursor is remembered
    # as its PHYSICAL coordinate (a time in seconds, a depth in millimetres), not as the
    # widget's own index, so a control whose bounds or options change still reopens where
    # the reader left it. `allow_self_loops=True` is required because each widget's
    # `on_change` writes the state the same cell reads.
    get_cursor_time_s, set_cursor_time_s = mo.state(None, allow_self_loops=True)
    get_cursor_gate_mm, set_cursor_gate_mm = mo.state(None, allow_self_loops=True)
    return get_cursor_gate_mm, get_cursor_time_s, set_cursor_gate_mm, set_cursor_time_s


@app.cell(hide_code=True)
def cursor_pickers(
    channel_ids,
    gate_depths_mm,
    get_cursor_gate_mm,
    get_cursor_time_s,
    mo,
    np,
    set_cursor_gate_mm,
    set_cursor_time_s,
    times,
):
    # The two cursors, both as sliders (the `signal_explorer.py` shape — this notebook
    # replaced the single-channel notebook's gate *dropdown*). The time slider indexes the
    # FIRST channel's stored profiles: the four channels have four different time axes, so
    # no single profile index exists for all of them, and the visit order makes the first
    # one the natural reference. Each slider reopens on the reader's remembered coordinate.
    _reference_channel = channel_ids[0]
    _t_ref = times[_reference_channel]
    time_default = int(_t_ref.size) // 2
    _remembered_time_s = get_cursor_time_s()
    if _remembered_time_s is not None:
        _hit = np.flatnonzero(np.isclose(_t_ref, float(_remembered_time_s)))
        if _hit.size:
            time_default = int(_hit[0])

    def _remember_time(_picked, _times=_t_ref):
        # The slider value is an index; what is remembered is the time it stands for.
        _index = int(_picked)
        if 0 <= _index < _times.size:
            set_cursor_time_s(float(_times[_index]))

    gate_default = int(gate_depths_mm.size) // 2
    _remembered_gate_mm = get_cursor_gate_mm()
    if _remembered_gate_mm is not None:
        _hit = np.flatnonzero(np.isclose(gate_depths_mm, float(_remembered_gate_mm)))
        if _hit.size:
            gate_default = int(_hit[0])

    def _remember_gate(_picked, _depths=gate_depths_mm):
        _index = int(_picked)
        if 0 <= _index < _depths.size:
            set_cursor_gate_mm(float(_depths[_index]))

    time_cursor = mo.ui.slider(
        start=0,
        stop=max(1, int(_t_ref.size) - 1),
        value=time_default,
        step=1,
        label=(
            f"Time — ch{_reference_channel} stored profile index · "
            f"t {_t_ref[0]:.3f}–{_t_ref[-1]:.3f} s"
        ),
        full_width=True,
        show_value=True,
        on_change=_remember_time,
    )
    gate_cursor = mo.ui.slider(
        start=0,
        stop=max(1, int(gate_depths_mm.size) - 1),
        value=gate_default,
        step=1,
        label=(
            f"Gate — shared gate index · depth {gate_depths_mm[0]:.2f}–"
            f"{gate_depths_mm[-1]:.2f} mm ({gate_depths_mm.size} gates)"
        ),
        full_width=True,
        show_value=True,
        on_change=_remember_gate,
    )
    mo.sidebar([mo.md("### Time"), time_cursor, mo.md("### Gate"), gate_cursor])
    return gate_cursor, time_cursor


@app.cell(hide_code=True)
def cursor_resolution(
    channel_ids,
    gate_cursor,
    gate_depths_mm,
    mo,
    np,
    same_gate_grid,
    time_cursor,
    times,
):
    # Resolve both cursors once, here, and let every figure below read the result. The
    # selected time is the reference channel's own stored timestamp — a sample some channel
    # really recorded. Each other channel then contributes its NEAREST stored profile and
    # the offset is stated: that offset is the acquisition's multiplexing stagger
    # (~112 ms per channel), not a defect, and a view that hid it by shifting one channel
    # onto another would be the alignment decision this notebook does not make.
    time_index = int(time_cursor.value)
    selected_gate = int(gate_cursor.value)
    selected_time_s = float(times[channel_ids[0]][time_index])
    selected_depth_mm = float(gate_depths_mm[selected_gate])
    nearest_profile = {
        _ch: int(np.argmin(np.abs(times[_ch] - selected_time_s))) for _ch in channel_ids
    }
    profile_offset_s = {
        _ch: float(times[_ch][nearest_profile[_ch]] - selected_time_s)
        for _ch in channel_ids
    }
    _grid_note = (
        "all four channels stored the **same gate grid**, so a gate index is the same "
        "depth in every panel"
        if same_gate_grid
        else "**the channels did not store the same gate grid** — a gate index is not the "
        "same depth in every panel, and the figures below say so"
    )
    mo.md(
        f"cursor → **t = {selected_time_s:.4f} s** "
        f"(ch{channel_ids[0]} stored profile {time_index} of "
        f"{times[channel_ids[0]].size - 1}) · **gate {selected_gate} = "
        f"{selected_depth_mm:.2f} mm**\n\n"
        "the nearest stored profile of each channel to that time (no interpolation):\n\n"
        "| channel | nearest profile | its own timestamp [s] | offset from cursor [ms] |\n"
        "| --- | ---: | ---: | ---: |\n"
        + "\n".join(
            f"| ch{_ch} | {nearest_profile[_ch]} | "
            f"{times[_ch][nearest_profile[_ch]]:.4f} | "
            f"{profile_offset_s[_ch] * 1e3:+.1f} |"
            for _ch in channel_ids
        )
        + f"\n\n{_grid_note}."
    )
    return (
        nearest_profile,
        profile_offset_s,
        selected_depth_mm,
        selected_gate,
        selected_time_s,
    )


@app.cell(hide_code=True)
def overview_heatmaps(
    bundle,
    channel_ids,
    gate_depths_mm,
    go,
    make_subplots,
    mo,
    np,
    quantity,
    selected_depth_mm,
    selected_gate,
    selected_time_s,
    time_span_s,
    times,
    unit,
    values,
):
    # All four channels on ONE shared symmetric colour scale. The panels exist to be
    # compared, so a per-panel autoscale would hide exactly the level difference the
    # 6 <-> 8 / 7 <-> 9 comparison is about; a scale symmetric about zero also keeps the
    # sign of the signed axial velocity comparable across panels. Each panel draws its own
    # channel's recorded timestamps — no resampling — and both cursors, so the two views
    # below are located on all four at once.
    _scale = max(float(np.nanmax(np.abs(_v))) for _v in values.values()) or 1.0
    _count = len(channel_ids)
    _cols = 2 if _count > 1 else 1
    _rows = (_count + _cols - 1) // _cols
    _titles = [f"ch{_ch}" for _ch in channel_ids]
    _titles += [""] * (_rows * _cols - _count)
    _title = (
        f"{bundle.recording.source_asset.file_name} · {quantity} [{unit}] · {_count} "
        f"channels on one shared scale ±{_scale:.0f} {unit} · cursor t = "
        f"{selected_time_s:.4f} s, gate {selected_gate} = {selected_depth_mm:.2f} mm"
    )
    _fig = make_subplots(
        rows=_rows,
        cols=_cols,
        shared_xaxes=True,
        shared_yaxes=True,
        horizontal_spacing=0.06,
        vertical_spacing=0.12,
        subplot_titles=_titles,
    )
    for _index, _ch in enumerate(channel_ids):
        _row, _col = divmod(_index, _cols)
        _fig.add_heatmap(
            x=times[_ch],
            y=gate_depths_mm,
            z=values[_ch].T,
            colorscale="RdBu_r",
            zmin=-_scale,
            zmax=_scale,
            showscale=_index == _cols - 1,
            colorbar=dict(title=f"{quantity} [{unit}]", len=0.45),
            hovertemplate=(
                "t %{x:.4f} s<br>gate %{y:.2f} mm<br>%{z:.2f} "
                + unit
                + "<extra>ch"
                + str(_ch)
                + "</extra>"
            ),
            row=_row + 1,
            col=_col + 1,
        )
        # Cursor colour measured for this palette in the single-channel notebook: RdBu_r is
        # near-white exactly where the velocity data sits, so the line has to be darker than
        # the map, and green leaves 0.0% of heatmap pixels within 15 dL of it.
        _cursor = "#43A047"
        _fig.add_vline(
            x=selected_time_s,
            line=dict(color=_cursor, width=2, dash="dot"),
            row=_row + 1,
            col=_col + 1,
        )
        _fig.add_hline(
            y=selected_depth_mm,
            line=dict(color=_cursor, width=2, dash="dash"),
            row=_row + 1,
            col=_col + 1,
        )
    _fig.update_xaxes(range=[time_span_s[0], time_span_s[1]])
    _fig.update_yaxes(range=[float(gate_depths_mm[0]), float(gate_depths_mm[-1])])
    # Plotly wraps neither a figure title nor a subplot title: a long one is clipped by the
    # plot area in the export, so both are kept short, with the figure title at font 13. What
    # the title no longer spells out (every stored profile, each channel on its own recorded
    # timestamps) is stated in the readouts above and below this figure.
    for _annotation in _fig.layout.annotations:
        _annotation.font.size = 12
    _fig.update_layout(
        title=dict(text=_title, font=dict(size=13)),
        height=760,
        margin=dict(t=95, b=55, l=65, r=25),
    )
    mo.ui.plotly(_fig)
    return


@app.cell(hide_code=True)
def depth_profiles_at_time(
    channel_ids,
    gate_depths_mm,
    go,
    make_subplots,
    mo,
    nearest_profile,
    np,
    profile_offset_s,
    selected_depth_mm,
    selected_time_s,
    times,
    unit,
    values,
):
    # 2x2: one stored profile per channel, velocity against gate depth. The profile is the
    # channel's nearest to the cursor time and is NOT interpolated; each panel states the
    # timestamp it actually used and its offset from the cursor, so nothing pretends the
    # four probes looked at the same instant. X and Y are shared across the panels, which is
    # what makes the pair shapes and levels directly comparable.
    _profile = {_ch: values[_ch][nearest_profile[_ch]] for _ch in channel_ids}
    _span = max(float(np.nanmax(np.abs(_p))) for _p in _profile.values()) or 1.0
    _count = len(channel_ids)
    _cols = 2 if _count > 1 else 1
    _rows = (_count + _cols - 1) // _cols
    # Short panel titles on purpose: a plotly subplot title is not wrapped, so a long one
    # runs into its neighbour's. The exact timestamps and offsets are in the cursor table
    # directly above this figure.
    _titles = [
        f"ch{_ch} · {times[_ch][nearest_profile[_ch]]:.4f} s "
        f"(Δ {profile_offset_s[_ch] * 1e3:+.0f} ms)"
        for _ch in channel_ids
    ]
    _titles += [""] * (_rows * _cols - _count)
    _fig = make_subplots(
        rows=_rows,
        cols=_cols,
        shared_xaxes=True,
        shared_yaxes=True,
        horizontal_spacing=0.06,
        vertical_spacing=0.16,
        subplot_titles=_titles,
    )
    for _index, _ch in enumerate(channel_ids):
        _row, _col = divmod(_index, _cols)
        _fig.add_trace(
            go.Scatter(
                x=gate_depths_mm,
                y=_profile[_ch],
                mode="lines+markers",
                name=f"ch{_ch}",
                line=dict(width=1.6),
                marker=dict(size=4),
                hovertemplate="depth %{x:.2f} mm<br>%{y:.2f} " + unit + "<extra></extra>",
            ),
            row=_row + 1,
            col=_col + 1,
        )
        # The selected gate, marked on every panel: it is the depth the trace view below
        # reads, so the two views say the same thing about where the cursor is.
        _fig.add_vline(
            x=selected_depth_mm,
            line=dict(color="#43A047", width=1.5, dash="dash"),
            row=_row + 1,
            col=_col + 1,
        )
    _fig.update_xaxes(range=[float(gate_depths_mm[0]), float(gate_depths_mm[-1])])
    _fig.update_yaxes(range=[-_span, _span])
    _title = (
        f"one stored profile per channel at t = {selected_time_s:.4f} s · velocity vs gate "
        f"depth · shared y ±{_span:.0f} {unit} · dashed = gate {selected_depth_mm:.2f} mm"
    )
    for _annotation in _fig.layout.annotations:
        _annotation.font.size = 12
    _fig.update_layout(
        title=dict(text=_title, font=dict(size=13)),
        showlegend=False,
        height=700,
        margin=dict(t=95, b=55, l=65, r=25),
    )
    mo.ui.plotly(_fig)
    return


@app.cell(hide_code=True)
def gate_traces_at_gate(
    channel_ids,
    gate_depths_mm,
    go,
    make_subplots,
    mo,
    np,
    quantity,
    selected_depth_mm,
    selected_gate,
    selected_time_s,
    time_span_s,
    times,
    unit,
    values,
):
    # 2x2: the selected gate across time, one channel per panel, each on its OWN recorded
    # timestamps inside a shared x range and a shared symmetric y range. The visited-burst
    # structure of the acquisition (~4 profiles at ~25 ms, then a ~372 ms gap) is visible
    # here as it is stored; the four panels are not and cannot be sample-aligned.
    _trace = {_ch: values[_ch][:, selected_gate] for _ch in channel_ids}
    _span = max(float(np.nanmax(np.abs(_t))) for _t in _trace.values()) or 1.0
    _count = len(channel_ids)
    _cols = 2 if _count > 1 else 1
    _rows = (_count + _cols - 1) // _cols
    # Short panel titles, as in the profile grid above: the "each channel on its own
    # recorded timestamps" statement lives in the figure title and the notes below, where it
    # is not clipped by the plot area.
    _titles = [
        f"ch{_ch} · {times[_ch][0]:.2f}–{times[_ch][-1]:.2f} s" for _ch in channel_ids
    ]
    _titles += [""] * (_rows * _cols - _count)
    _fig = make_subplots(
        rows=_rows,
        cols=_cols,
        shared_xaxes=True,
        shared_yaxes=True,
        horizontal_spacing=0.06,
        vertical_spacing=0.16,
        subplot_titles=_titles,
    )
    for _index, _ch in enumerate(channel_ids):
        _row, _col = divmod(_index, _cols)
        _fig.add_trace(
            go.Scatter(
                x=times[_ch],
                y=_trace[_ch],
                mode="lines",
                name=f"ch{_ch}",
                line=dict(width=1.1),
                hovertemplate="t %{x:.4f} s<br>%{y:.2f} " + unit + "<extra></extra>",
            ),
            row=_row + 1,
            col=_col + 1,
        )
        _fig.add_vline(
            x=selected_time_s,
            line=dict(color="#43A047", width=1.5, dash="dot"),
            row=_row + 1,
            col=_col + 1,
        )
    _fig.update_xaxes(range=[time_span_s[0], time_span_s[1]])
    _fig.update_yaxes(range=[-_span, _span])
    _title = (
        f"gate {selected_gate} = {selected_depth_mm:.2f} mm · {quantity} vs time, each "
        f"channel on its own recorded stamps · shared y ±{_span:.0f} {unit} · dotted = "
        f"cursor t = {selected_time_s:.4f} s"
    )
    for _annotation in _fig.layout.annotations:
        _annotation.font.size = 12
    _fig.update_layout(
        title=dict(text=_title, font=dict(size=13)),
        showlegend=False,
        height=700,
        margin=dict(t=95, b=55, l=65, r=25),
    )
    mo.ui.plotly(_fig)
    return


@app.cell(hide_code=True)
def notes(mo):
    mo.md("""
    **Reading these four views.**

    - **Shared scales on purpose.** The heatmaps share one colour scale (± max |velocity|)
      and each 2x2 grid shares its y range. That is what lets a reader compare channels at
      all: with per-panel autoscaling the mount-to-mount level factor would be invisible, and
      level is half of the 6 <-> 8 / 7 <-> 9 question.
    - **Depth is the shared coordinate; time is not.** All four channels stored the same
      55-gate grid, so a gate index means the same depth everywhere — the depth-profile grid
      is therefore a genuine without-alignment comparison. The time axes differ by the
      acquisition's visit offsets, which is why the trace panels show each channel's own
      stamps and why the cursor table prints the nearest-profile offset for every channel.
    - **Stagger, not error.** The offsets in the cursor table are the acquisition's
      multiplexed visit order 6 -> 7 -> 8 -> 9: visit starts are 112 ms apart, and because a
      visit carries four profiles (~25 ms apart) before a ~372 ms gap, a channel's *nearest*
      profile sits at most half a visit cycle away — up to ~112 ms for the next channel in
      the order, and up to ~224 ms for 6 against 8, the orthogonal-mount pair. At the 200 RPM
      the file name claims, 224 ms is most of a revolution, so an index-aligned overlay of
      two channels would compare different flow states — which is what those offsets make
      visible.
    - **Sign.** The velocity is the instrument's signed axial component, and the sign
      convention of a mount rotated 90 degrees is not decoded here; the shared symmetric
      scale keeps the magnitudes comparable and shows the signs as stored, nothing more.
    - **Not here, deliberately.** No time alignment, no interpolation, no averaging across
      channels, no pair difference curves and no placement figure. The placement figure and
      the level-factor question are recorded as selected next work in
      `docs/plans/four-sensor-velocity-notebook-review.md`.
    """)
    return


if __name__ == "__main__":
    app.run()
