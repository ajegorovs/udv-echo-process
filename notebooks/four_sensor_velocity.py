import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def imports():
    import time
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go
    from plotly.colors import qualitative
    from plotly.subplots import make_subplots

    from udv_echo_process.analysis.time_modes import (
        decompose_time_modes,
        gate_amplitudes,
        modes_for_variance_share,
    )
    from udv_echo_process.io import load
    from udv_echo_process.models.support import QualityFlag
    from udv_echo_process.models.time_modes import TimeModesSettings
    from udv_echo_process.process import TvFilterSpec
    from udv_echo_process.process.filter import filter as filter_bundle
    from udv_echo_process.provenance import select_channel

    return (
        Path,
        QualityFlag,
        TimeModesSettings,
        TvFilterSpec,
        decompose_time_modes,
        filter_bundle,
        gate_amplitudes,
        go,
        load,
        make_subplots,
        mo,
        modes_for_variance_share,
        np,
        qualitative,
        select_channel,
        time,
    )


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Four-sensor velocity preview — one recording, all four channels

    The 2x2 orthogonal mounting of the four-sensor fixture (device channels 6, 7, 8, 9):

    1. **Overview** — all four channels as heatmaps on **one shared colour scale**, with
       both cursors drawn on every panel (vertical = selected time, horizontal = selected
       gate).
    2. **Pair overlays** — the pairs the mounting's 90-degree symmetry makes comparable, each
       pair drawn on top of each other: **outer 6 vs 8** and **inner 7 vs 9**, first against
       gate depth and then against time. This is the comparison the fixture exists for.
    3. **Time modes** — each channel's own heatmap decomposed along **time** (SVD), one channel
       at a time, with the mean kept: the stationary depth structure this recording holds
       throughout (mode 1) and the perturbations about it (modes 2-4), with the share of the
       field energy each one carries.

    **The sidebar** carries the two cursors and an optional **total-variation filter along
     time**. One parameter set drives all four channels; with it on, every figure says so in its
     title and the data drawn are the library's filtered payload rather than the stored
     profiles. It is off by default, and the note beside the controls reports exactly what the
     layer accepted, what it changed and what it recorded in provenance.

    **What this notebook refuses to do.** The four channels are *multiplexed*: one channel
    is visited at a time, ~112 ms apart in the order 6 -> 7 -> 8 -> 9, so no two channels
    are ever sampled at the same instant. Nothing here is shifted, interpolated or resampled
    to make a view possible:

    - the heatmap and pair-overlay panels plot each channel on **its own recorded timestamps**;
    - at the selected time each channel shows its **nearest stored profile**, and the panel
      states that profile's own timestamp and its offset from the cursor, so the stagger is
      visible instead of hidden;
    - depth is the one coordinate all four channels share (the same 55-gate grid,
      20.00 -> 79.13 mm), so depth comparisons need no alignment at all;
    - the time-mode decomposition is **per channel** — it mixes no channels, so it needs no
      alignment either — and it claims no coherent structure: the stationary part is one mode,
      but the perturbations' energy is spread across most of the remaining modes (see its own
      caption below the figure);
    - the optional filter is **not** a way around any of that: it is index-based and may not span
      the visit gap, so it trims within a visit and never interpolates across the stagger.

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
    return (bundle,)


@app.cell(hide_code=True)
def channel_series(bundle, np, qualitative):
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
    # ONE colour per channel, taken from plotly's qualitative palette positionally so it
    # matches what the per-channel grids' own colour cycle assigns: channel_ids order is the
    # acquisition's visit order, so index 0..3 is ch6..ch9 in both places. Pinned here
    # because a two-trace panel would otherwise take the cycle's first two colours and ch8
    # would arrive in ch7's red.
    channel_colors = {
        _ch: qualitative.Plotly[_index % len(qualitative.Plotly)]
        for _index, _ch in enumerate(channel_ids)
    }
    # The rig's pairing, from the operator's channel map recorded in
    # `data/4-sensor-velocity/README.md`: channels 6 and 8 are the OUTER probes, both 30 mm
    # from the vessel centre line in the two orthogonal mounts, and 7 and 9 are the INNER
    # ones, both at 20 mm. That is a hardware claim, not something the numbers say, so it is
    # written out here with its source rather than inferred — and only pairs whose members
    # all exist in this recording are kept.
    candidate_pairs = (
        ("outer pair · 6 vs 8 (30 mm)", (6, 8)),
        ("inner pair · 7 vs 9 (20 mm)", (7, 9)),
    )
    channel_pairs = tuple(
        (_label, _members)
        for _label, _members in candidate_pairs
        if all(_member in channel_ids for _member in _members)
    )
    return (
        channel_colors,
        channel_ids,
        channel_pairs,
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
    return (
        get_cursor_gate_mm,
        get_cursor_time_s,
        set_cursor_gate_mm,
        set_cursor_time_s,
    )


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


@app.cell
def tv_filter_controls(mo):
    # The optional time-wise filter, as this notebook's own sidebar section. ONE parameter set
    # drives ALL FOUR channels: the control is the filter, not a per-channel tuning, and a
    # per-channel weight would quietly make the pair overlays incomparable.
    #
    # No kernel is written here. Every parameter below is handed to the library transform
    # `process/filter.py::filter` — the same `ChannelBundle -> ChannelBundle` call the
    # single-channel notebooks drive from their own controls (`notebooks/channel_preview.py`,
    # `filter_controls` / `filter_run`), which is where the ROF solver, the segment rules and
    # the uniformity guard already live.
    #
    # The SCOPE is the cost control: the library filters one gate for ~400 solver calls
    # (0.12 s measured for the four channels) and all 55 for ~22 000 (~7 s), so the default is
    # the gate being read — the same gate the pair time overlay draws — and the whole field
    # stays one click away for a pass that should inform the field-level views.
    #
    # Labels are kept short on purpose: the sidebar is narrow, and a long label wraps one word
    # per line there. What the labels leave out is measured and reported in the note beside the
    # figures: λ is in mm/s and moves a cell by at most 2λ (at λ = 1 the largest change is
    # exactly 2.00 mm/s), and 40 ms is the `max_gap` that makes each 4-profile visit its own
    # segment.
    tv_enabled = mo.ui.checkbox(
        value=False,
        label="TV filter along time · all 4 channels",
    )
    tv_scope = mo.ui.dropdown(
        options={"the cursor's gate": "gate", "all gates": "all"},
        value="the cursor's gate",
        label="scope",
    )
    tv_weight = mo.ui.slider(
        start=0.05,
        stop=20.0,
        step=0.05,
        value=1.0,
        label="λ [mm/s] · larger = smoother",
    )
    tv_iterations = mo.ui.number(
        start=10,
        stop=5000,
        step=10,
        value=200,
        label="iterations · solver cap",
    )
    tv_max_gap_ms = mo.ui.slider(
        start=1.0,
        stop=500.0,
        step=1.0,
        value=40.0,
        label="max_gap [ms] · visit = 40",
    )
    mo.sidebar(
        [
            mo.md("### Time-wise filter"),
            tv_enabled,
            tv_scope,
            tv_weight,
            tv_iterations,
            tv_max_gap_ms,
        ]
    )
    return tv_enabled, tv_iterations, tv_max_gap_ms, tv_scope, tv_weight


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


@app.cell
def tv_filter_apply(
    QualityFlag,
    TvFilterSpec,
    bundle,
    channel_ids,
    filter_bundle,
    mo,
    np,
    select_channel,
    selected_depth_mm,
    selected_gate,
    time,
    tv_enabled,
    tv_iterations,
    tv_max_gap_ms,
    tv_scope,
    tv_weight,
    unit,
    values,
):
    # Apply the sidebar's filter to the CURSOR'S GATE of all four channels (by default), with
    # the same parameters, through the library transform — `process/filter.py::filter`, whose
    # optional `gates=` selection scopes one pass — and publish what every figure below draws:
    # `signal_values` plus `signal_label`, the one-line description each figure carries.
    #
    # Why the gate scope is the default (owner direction, 2026-10-16): what is being read is a
    # gate — the pair time overlay at the cursor's gate — and a whole-field pass costs 22 000
    # solver calls (7.2 s measured for the four channels) against 400 calls (0.12 s measured)
    # for one gate. The scope is a *selection* argument on the transform — the shape `resample`
    # takes for its target grid — so it is deliberately not in the recorded `params_json`,
    # which is built from the spec alone; a scoped pass and a whole-field pass stay
    # distinguishable by the derived artifact's data-derived id. Unnamed gates keep their
    # values and quality bit for bit, which the filter tests pin.
    #
    # What it can and cannot do on THIS fixture is measured, not assumed:
    #   * the stored profiles are multiplexed — four profiles ~25 ms apart, then a ~372 ms visit
    #     gap — and `max_gap_s` decides what the layer may treat as one series. At 40 ms each
    #     visit is its own 4-sample segment, so TV trims *within* a visit and cannot smooth
    #     across the gap. That is a fact about the acquisition, not a defect to filter out.
    #   * TV is index-based and needs a truly uniform cadence, so a `max_gap_s` that spans the
    #     visit gap makes the library REFUSE the series. The refusal is shown below rather than
    #     hidden, and the figures then stay on the raw profiles.
    #   * ROF preserves each segment's mean, so the processed gate's time mean — and the
    #     depth-averaged mean the captions quote — survives the filter.
    #   * with `max_gap` far below the within-visit step, every segment falls under TV's
    #     2-sample minimum and nothing is filtered at all; the note says so rather than
    #     implying an edit that never happened.
    _scope = tv_scope.value
    _gates = (selected_gate,) if _scope == "gate" else None
    _scope_short = (
        f"gate {selected_gate} only"
        if _gates
        else f"all {int(values[channel_ids[0]].shape[1])} gates"
    )
    _scope_long = (
        f"the cursor's gate only (gate {selected_gate} = {selected_depth_mm:.2f} mm)"
        if _gates
        else "every gate"
    )
    tv_report = mo.md(
        "Filter off — every figure and table below draws the **raw stored profiles**; the "
        "sidebar carries the option."
    )
    filter_spec = None
    signal_values = values
    signal_label = "raw stored profiles — no filter"
    if tv_enabled.value:
        filter_spec = TvFilterSpec(
            weight=float(tv_weight.value),
            iterations=int(tv_iterations.value),
            max_gap_s=float(tv_max_gap_ms.value) / 1000.0,
        )
        _keys = {
            _ch: _stream.acquisition.channel
            for _ch, _stream in zip(channel_ids, bundle.recording.streams, strict=True)
        }
        _filtered = {}
        _filtered_cells = 0
        _rows = []
        _last = None
        _started = time.perf_counter()
        try:
            for _ch in channel_ids:
                _out = filter_bundle(
                    select_channel(bundle, _keys[_ch]),
                    filter_spec,
                    gates=_gates,
                )
                _last = _out
                _payload = np.asarray(_out.artifact.data.values, dtype=float)
                _filtered[_ch] = _payload
                _bits = np.asarray(_out.artifact.data.support.quality, dtype=np.uint32)
                _filtered_cells += int(
                    np.count_nonzero(_bits & np.uint32(int(QualityFlag.FILTERED)))
                )
                _stored_sel = values[_ch] if _gates is None else values[_ch][:, _gates]
                _filtered_sel = _payload if _gates is None else _payload[:, _gates]
                _delta = _filtered_sel - _stored_sel
                _rows.append(
                    f"| ch{_ch} | {np.sqrt((_delta ** 2).mean()):.3f} | "
                    f"{np.abs(_delta).max():.2f} | "
                    f"{float(_stored_sel.mean()):.2f} → {float(_filtered_sel.mean()):.2f} |"
                )
        except ValueError as _refusal:
            _last = None
            tv_report = mo.md(
                "⚠️ **`filter.tv` refused this filter — the figures below stay on the raw "
                "profiles.**\n\n"
                f"``{_refusal}``\n\n"
                "TV is index-based and requires a truly uniform cadence, and this recording's "
                "visit gaps are up to ~372 ms, so a `max_gap` above that turns four visits into "
                "one non-uniform series. The layer refuses it rather than smoothing across a "
                "hole. **Keep `max_gap` below the visit gap (~40 ms).**"
            )
        _elapsed_s = time.perf_counter() - _started
        if _last is not None:
            _processed_cells = sum(
                int((values[_ch] if _gates is None else values[_ch][:, _gates]).size)
                for _ch in channel_ids
            )
            signal_values = _filtered
            signal_label = (
                f"TV λ={filter_spec.weight:g} mm/s · {filter_spec.iterations} it · {_scope_short}"
            )
            _operation = _last.graph.operations[-1]
            tv_report = mo.md(
                f"**Filter on — `{_operation.kind}` on {_scope_long}, one parameter set on all "
                f"four channels.** {_filtered_cells} of {_processed_cells} cells carry "
                f"`FILTERED`; segments are split at {float(tv_max_gap_ms.value):g} ms, i.e. one "
                "4-profile visit each, so the trim happens *within* a visit and never across the "
                "visit gap."
                + (" Every other gate is untouched, bit for bit." if _gates else "")
                + f"\n\n| channel | rms Δ [{unit}] | max abs Δ [{unit}] | "
                f"mean of the processed cells [{unit}] |\n"
                "| --- | ---: | ---: | ---: |\n" + "\n".join(_rows)
                + f"\n\nMeasured {_elapsed_s:.3f} s for this pass over the four channels"
                + (
                    "; over all gates the same pass takes ~7 s, because the cost is the library "
                    "calling the ROF solver once per 4-sample visit rather than the solver itself."
                    if _gates
                    else "."
                )
                + f"\n\nRecorded in provenance: `{_operation.operation_id[:19]}…` · "
                f"`{_operation.implementation.callable}` "
                f"v{_operation.implementation.version} · params "
                f"``{_operation.params_json}`` (the gate scope is a transform argument, so it "
                "is not part of the recorded params)."
                + (
                    "\n\n⚠️ No segment reached TV's 2-sample minimum, so nothing changed — "
                    "raise `max_gap` toward the within-visit step (~25 ms) for the filter to act."
                    if _filtered_cells == 0
                    else ""
                )
            )
    tv_report
    return signal_label, signal_values


@app.cell(hide_code=True)
def overview_heatmaps(
    bundle,
    channel_ids,
    gate_depths_mm,
    make_subplots,
    mo,
    np,
    quantity,
    selected_depth_mm,
    selected_gate,
    selected_time_s,
    signal_label,
    signal_values,
    time_span_s,
    times,
    unit,
):
    # All four channels on ONE shared symmetric colour scale. The panels exist to be
    # compared, so a per-panel autoscale would hide exactly the level difference the
    # 6 <-> 8 / 7 <-> 9 comparison is about; a scale symmetric about zero also keeps the
    # sign of the signed axial velocity comparable across panels. Each panel draws its own
    # channel's recorded timestamps — no resampling — and both cursors, so the views below are
    # located on all four at once. What is drawn is `signal_values`: the raw stored profiles,
    # or the filtered payload when the sidebar filter is on. The title says which.
    _scale = max(float(np.nanmax(np.abs(_v))) for _v in signal_values.values()) or 1.0
    _count = len(channel_ids)
    _cols = 2 if _count > 1 else 1
    _rows = (_count + _cols - 1) // _cols
    _titles = [f"ch{_ch}" for _ch in channel_ids]
    _titles += [""] * (_rows * _cols - _count)
    _title = (
        f"{bundle.recording.source_asset.file_name} · {quantity} [{unit}] · {_count} "
        f"channels on one shared scale ±{_scale:.0f} {unit} · cursor t = "
        f"{selected_time_s:.4f} s, gate {selected_gate} = {selected_depth_mm:.2f} mm · "
        f"{signal_label}"
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
            z=signal_values[_ch].T,
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
def pair_profiles_at_time(
    channel_colors,
    channel_ids,
    channel_pairs,
    gate_depths_mm,
    go,
    make_subplots,
    mo,
    nearest_profile,
    np,
    profile_offset_s,
    selected_depth_mm,
    selected_time_s,
    signal_label,
    signal_values,
    times,
    unit,
):
    # The pair overlays, first on the coordinate the channels genuinely share: the two probes
    # the mounting's 90-degree symmetry makes equivalent, drawn ON TOP OF EACH OTHER — outer
    # (6 vs 8) left, inner (7 vs 9) right. Depth needs no alignment at all, so each member
    # contributes its stored profile nearest the cursor time and the legend carries that
    # profile's own timestamp. The shared y range is what makes a level difference visible and
    # the curves carry the shape difference; a systematic level factor is a per-mount hardware
    # question, so it is read as an open cause from the caption below, never as "different".
    # Drawn from `signal_values`, like every figure here — raw unless the filter is on.
    _profile = {_ch: signal_values[_ch][nearest_profile[_ch]] for _ch in channel_ids}
    _span = max(float(np.nanmax(np.abs(_p))) for _p in _profile.values()) or 1.0
    _fig = make_subplots(
        rows=1,
        cols=len(channel_pairs),
        shared_yaxes=True,
        horizontal_spacing=0.07,
        subplot_titles=[_label for _label, _members in channel_pairs],
    )
    for _col, (_label, _members) in enumerate(channel_pairs, start=1):
        for _ch in _members:
            _fig.add_trace(
                go.Scatter(
                    x=gate_depths_mm,
                    y=_profile[_ch],
                    mode="lines+markers",
                    name=(
                        f"ch{_ch} · {times[_ch][nearest_profile[_ch]]:.4f} s "
                        f"(Δ {profile_offset_s[_ch] * 1e3:+.0f} ms)"
                    ),
                    line=dict(width=1.8, color=channel_colors[_ch]),
                    marker=dict(size=4),
                    hovertemplate="depth %{x:.2f} mm<br>%{y:.2f} "
                    + unit
                    + "<extra></extra>",
                ),
                row=1,
                col=_col,
            )
        _fig.add_vline(
            x=selected_depth_mm,
            line=dict(color="#43A047", width=1.5, dash="dash"),
            row=1,
            col=_col,
        )
    _fig.update_xaxes(range=[float(gate_depths_mm[0]), float(gate_depths_mm[-1])])
    _fig.update_yaxes(range=[-_span, _span])
    _title = (
        f"pair overlays at t = {selected_time_s:.4f} s · velocity vs gate depth · shared y "
        f"±{_span:.0f} {unit} · dashed = gate {selected_depth_mm:.2f} mm · {signal_label}"
    )
    for _annotation in _fig.layout.annotations:
        _annotation.font.size = 12
    _fig.update_layout(
        title=dict(text=_title, font=dict(size=13)),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, x=0, font=dict(size=11)),
        height=660,
        margin=dict(t=95, b=120, l=65, r=25),
    )
    mo.ui.plotly(_fig)
    return


@app.cell(hide_code=True)
def pair_traces_at_gate(
    channel_colors,
    channel_ids,
    channel_pairs,
    go,
    make_subplots,
    mo,
    np,
    quantity,
    selected_depth_mm,
    selected_gate,
    selected_time_s,
    signal_label,
    signal_values,
    time_span_s,
    times,
    unit,
    values,
):
    # The same two pairs overlaid on the TIME axis, at the cursor's gate: the STORED samples as
    # grey markers with the plotted curve drawn over them — raw when the filter is off, the
    # filtered curve when it is on, which is the before/after view in the cell that reads it.
    #
    # Each channel keeps its own recorded timestamps — nothing is shifted onto the other's
    # samples — so what this overlay shows is level, envelope and pattern on a shared axis, never
    # a sample-by-sample pairing: at the same index the two members of a pair sit a quarter to a
    # half visit cycle apart, and against a periodic flow that is a different process state
    # rather than a small error. The markers are `values` (the imported signal, never
    # overwritten); the line is `signal_values`, and the title says which one that is.
    _stored = {_ch: values[_ch][:, selected_gate] for _ch in channel_ids}
    _trace = {_ch: signal_values[_ch][:, selected_gate] for _ch in channel_ids}
    _span = max(float(np.nanmax(np.abs(_t))) for _t in _trace.values()) or 1.0
    _span = max(_span, max(float(np.nanmax(np.abs(_t))) for _t in _stored.values()))
    _fig = make_subplots(
        rows=1,
        cols=len(channel_pairs),
        shared_yaxes=True,
        horizontal_spacing=0.07,
        subplot_titles=[_label for _label, _members in channel_pairs],
    )
    for _col, (_label, _members) in enumerate(channel_pairs, start=1):
        for _ch in _members:
            _fig.add_trace(
                go.Scatter(
                    x=times[_ch],
                    y=_stored[_ch],
                    mode="markers",
                    name="stored sample",
                    legendgroup="stored",
                    showlegend=_col == 1 and _ch == _members[0],
                    marker=dict(size=3, color="#9E9E9E", opacity=0.75),
                    hovertemplate=(
                        "stored t %{x:.4f} s<br>%{y:.2f} " + unit + "<extra></extra>"
                    ),
                ),
                row=1,
                col=_col,
            )
            _fig.add_trace(
                go.Scatter(
                    x=times[_ch],
                    y=_trace[_ch],
                    mode="lines",
                    name=(
                        f"ch{_ch} · t {times[_ch][0]:.2f}–{times[_ch][-1]:.2f} s on its own "
                        "stamps"
                    ),
                    legendgroup=f"ch{_ch}",
                    line=dict(width=1.4, color=channel_colors[_ch]),
                    hovertemplate="t %{x:.4f} s<br>%{y:.2f} " + unit + "<extra></extra>",
                ),
                row=1,
                col=_col,
            )
        _fig.add_vline(
            x=selected_time_s,
            line=dict(color="#43A047", width=1.5, dash="dot"),
            row=1,
            col=_col,
        )
    _fig.update_xaxes(range=[time_span_s[0], time_span_s[1]])
    _fig.update_yaxes(range=[-_span, _span])
    _title = (
        f"gate {selected_gate} = {selected_depth_mm:.2f} mm · grey markers = stored samples · "
        f"{quantity} pair overlays vs time, each channel on its own recorded stamps · "
        f"shared y ±{_span:.0f} {unit} · {signal_label}"
    )
    for _annotation in _fig.layout.annotations:
        _annotation.font.size = 12
    _fig.update_layout(
        title=dict(text=_title, font=dict(size=13)),
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, x=0, font=dict(size=11)),
        height=660,
        margin=dict(t=95, b=120, l=65, r=25),
    )
    mo.ui.plotly(_fig)
    return


@app.cell(hide_code=True)
def pair_captions(mo):
    mo.md("""
    **Reading the pair overlays.** Each pair's two probes sample the same radii in the two
    orthogonal mounts, so under a 90-degree-symmetric flow they should agree — these two
    figures are where that either shows or does not.

    - **Shape and level are separate readings.** Measured over all 400 profiles of this
      recording ([`data/4-sensor-velocity/README.md`](../../data/4-sensor-velocity/README.md)),
      the pairs' **time-mean depth profiles** agree in **shape** (r = +0.94 outer, +0.95
      inner) and differ in **level** by **1.31** (outer) and **1.24** (inner) — the level
      difference the shared y range makes visible here. A systematic per-mount level factor
      has causes outside the flow being measured (probe sensitivity, coupling, mount
      standoff), so it stays an **open cause**, and no pair is declared the same or different
      in this notebook.
    - **The depth overlay needs no alignment; the time overlay cannot have one.** Depth is
      the coordinate all four channels share, so the depth overlay is a like-for-like
      comparison. On the time axis the two traces were never sampled at the same instant —
      read that panel for level, envelope and pattern, and take any sample-by-sample pairing
      to the alignment decision this notebook deliberately does not make.
    - **The legend is the provenance.** Every trace names the stored profile or the recorded
      span it is drawn from, so a curve can always be traced back to samples rather than to
      an interpolation.
    """)
    return


@app.cell(hide_code=True)
def svd_time_modes(
    TimeModesSettings,
    bundle,
    channel_ids,
    decompose_time_modes,
    gate_amplitudes,
    gate_depths_mm,
    go,
    make_subplots,
    mo,
    np,
    signal_label,
    signal_values,
    unit,
):
    # TIME-DIRECTION SVD (POD) OF EACH CHANNEL'S OWN HEATMAP, WITH THE MEAN KEPT
    # (`center=False`, owner direction 2026-10-16). The rig is a stationary stirred flow carrying
    # perturbations, so the decomposition is read as a stationary part plus secondary effects:
    # mode 1 is the stationary direction, modes 2-4 the perturbations about it. Measured on this
    # recording, mode 1 is the time-mean profile to r = +0.999 (99.9-100% of the mean field's
    # energy sits inside it) and the modes after it are essentially orthogonal to that mean
    # (|cos| <= 0.02) — so the secondary modes are perturbations, not a re-run of the stationary
    # part. The centred form (`center=True`, the library default) is the other reading: it removes
    # each gate's time mean first and gives pure fluctuations about it.
    #
    # One decomposition per channel, never across channels: the four probes are never sampled at
    # the same instant, so a joint decomposition would need the alignment decision this notebook
    # does not make, while a per-channel one needs no alignment at all. Nothing is resampled
    # either — the SVD reads `signal_values`: each channel's stored profiles as they are, or the
    # filtered payload the sidebar filter publishes (still on each channel's own recorded stamps;
    # the title says which).
    #
    # The acquisition's burst structure (four profiles ~25 ms apart, then a ~372 ms gap) does not
    # have to be regular for the decomposition to be exact — SVD needs no uniform axis, which is
    # why it is the one time-direction method here that a gappy multiplexed series does not
    # obstruct.
    #
    # Each curve is a mode's amplitude at each gate, scaled to that mode's per-gate RMS over the
    # channel's 400 stored profiles, so the curves are in velocity units and the four panels share
    # one y range. Mode 1 is drawn heavier: the amplitude ratio between the stationary field and
    # the secondary modes is part of the reading, so nothing is rescaled to hide it.
    time_modes = {
        _ch: decompose_time_modes(
            signal_values[_ch],
            unit=unit,
            settings=TimeModesSettings(n_modes=4, center=False),
        )
        for _ch in channel_ids
    }
    _amplitudes = {_ch: gate_amplitudes(time_modes[_ch]) for _ch in channel_ids}
    # ONE colour per mode, pinned, because mode identity must not change between panels the way a
    # colour cycle would re-assign it — and deliberately NOT from the channel palette, so no
    # reader confuses a mode curve with a channel curve in the figures above.
    _mode_colors = ("#1A237E", "#B71C1C", "#1B5E20", "#6A1B9A")
    _mode_widths = (2.6, 1.4, 1.4, 1.4)
    _span = max(float(np.max(np.abs(_a))) for _a in _amplitudes.values()) or 1.0
    _count = len(channel_ids)
    _cols = 2 if _count > 1 else 1
    _rows = (_count + _cols - 1) // _cols
    _titles = [
        f"ch{_ch} · stationary {time_modes[_ch].explained_variance_ratio[0] * 100:.0f}% · "
        f"modes 2-4 {float(time_modes[_ch].explained_variance_ratio[1:4].sum()) * 100:.1f}%"
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
        for _mode in range(time_modes[_ch].settings.n_modes):
            _fig.add_trace(
                go.Scatter(
                    x=gate_depths_mm,
                    y=_amplitudes[_ch][_mode],
                    mode="lines",
                    name=f"mode {_mode + 1}" + (" · stationary" if _mode == 0 else ""),
                    legendgroup=f"mode{_mode}",
                    showlegend=_index == 0,
                    line=dict(width=_mode_widths[_mode], color=_mode_colors[_mode]),
                    hovertemplate=(
                        "gate %{x:.2f} mm<br>%{y:.2f} "
                        + unit
                        + " rms<extra>ch"
                        + str(_ch)
                        + "</extra>"
                    ),
                ),
                row=_row + 1,
                col=_col + 1,
            )
    _fig.update_xaxes(range=[float(gate_depths_mm[0]), float(gate_depths_mm[-1])])
    _fig.update_yaxes(range=[-_span, _span])
    # Plotly clips an over-long figure title, so this one stays short; what it does not spell out
    # (each channel decomposed on its own; the per-mode shares; that the mean is kept) is in the
    # table below it.
    _title = (
        f"{bundle.recording.source_asset.file_name} · time-direction SVD per channel · mean "
        f"kept · per-gate RMS [{unit}] · {signal_label}"
    )
    for _annotation in _fig.layout.annotations:
        _annotation.font.size = 12
    _fig.update_layout(
        title=dict(text=_title, font=dict(size=13)),
        legend=dict(orientation="h", yanchor="bottom", y=-0.28, x=0, font=dict(size=11)),
        height=760,
        margin=dict(t=95, b=110, l=65, r=25),
    )
    mo.ui.plotly(_fig)
    return (time_modes,)


@app.cell(hide_code=True)
def svd_mode_readout(
    channel_ids,
    mo,
    modes_for_variance_share,
    time_modes,
    unit,
):
    # The table the mode figure needs, straight from the model and the library: the "of it"
    # columns are `modes_for_variance_share(..., offset=1)` — the helper's kept-separately
    # reading, which is exactly this question (how many PERTURBATION modes carry 90% / 95% of
    # the non-stationary energy) — and the mean column is the model's own `mean_profile`, which
    # reports each gate's time mean in the uncentred reading too (checked live on this kernel:
    # `mean_profile.mean()` = the field mean = 27.7399 mm/s on ch6).
    _header = (
        "| channel | mode 1 · stationary | mode 2 | mode 3 | modes 2-4 | non-stationary "
        "| of it, 90% at | of it, 95% at | time&depth mean |"
    )
    _sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    _rows = []
    for _ch in channel_ids:
        _result = time_modes[_ch]
        _shares = _result.explained_variance_ratio
        _rows.append(
            f"| ch{_ch} | **{_shares[0] * 100:.1f}%**"
            f" | {_shares[1] * 100:.2f}% | {_shares[2] * 100:.2f}%"
            f" | {float(_shares[1:4].sum()) * 100:.1f}%"
            f" | {float(_shares[1:].sum()) * 100:.1f}%"
            f" | {modes_for_variance_share(_result, 0.90, offset=1)}"
            f" | {modes_for_variance_share(_result, 0.95, offset=1)}"
            f" | {float(_result.mean_profile.mean()):.1f} {unit} |"
        )
    _mode_table = "\n".join([_header, _sep, *_rows])
    mo.md(
        f"""
    **Reading the time modes.**

    - **The mean is in the decomposition.** Each channel's stored ``(profile, gate)`` matrix is
      factored as ``X = U · S · Vᵀ`` with nothing subtracted, so **mode 1 is the stationary field**
      — the depth structure this recording holds throughout — and **modes 2-4 are the perturbations
      about it**. On this recording mode 1 reproduces the per-gate time-mean profile at r = +0.999
      (99.9-100% of the mean field's energy sits inside it) and the modes after it are essentially
      orthogonal to that mean (|cos| <= 0.02), which is what makes the split readable as
      "stationary + secondary effects" rather than as one arbitrary basis.
    - **What is drawn.** **x** is the shared gate depth (20.00 -> 79.13 mm, 55 gates, the same grid
      in all four channels); **y** is that mode's amplitude at the gate, scaled to the
      **root-mean-square over that channel's 400 stored profiles**, so the curves are in {unit} and
      the four panels share one y range. Mode 1 is the heavy curve; the ratio between the stationary
      field and the secondary modes is part of the reading, so nothing is rescaled to flatten it.

    {_mode_table}

    - **The perturbations are broadband, not a few structures.** The "of it" columns count
      **additional** modes carrying 90% / 95% of the non-stationary energy, and they run into most
      of the remaining 51 modes — so the secondary effects are not one or two dominant structures,
      and no significance test is attached to any single mode (there is no spectral gap that would
      justify one).
    - **The shares are also sampling.** A visit carries four profiles ~25 ms apart and recurs every
      ~448 ms, so near-duplicate marginal samples weigh as much as a lone one: the shares reflect
      the visit pattern as well as the flow. That is also why a mode's temporal coefficient is
      **not** a spectrum — its axis is unevenly sampled and is not drawn here.
    - **One channel at a time.** Each panel is that channel's own decomposition. It says nothing
      about whether the *same* structure varies in another channel: testing that compares two
      probes' modes across the 112-224 ms stagger, i.e. it needs the alignment decision this
      notebook does not make. What is comparable without alignment is the mode *shape* on the shared
      depth axis, which is what the 2x2 layout is for (6 <-> 8 and 7 <-> 9).
    - **The sign is a convention.** numpy's SVD sign is unspecified, so every mode was flipped until
      its largest-magnitude gate is positive — which for mode 1 puts the stationary profile in the
      same orientation as the time mean (whose largest gate is positive too). Within one channel's
      decomposition the relative signs of two modes are then meaningful; across channels they are
      not (the mounts' sign convention is not decoded — see the notes at the end).
    - **With the sidebar filter on, every number here describes the *filtered* field** (the figure's
      title carries the parameters). Measured at λ = 1 mm/s on this recording, a per-visit TV pass
      leaves the stationary direction and mode 2 essentially untouched (|cos| = 1.000 and 0.9997
      against the unfiltered decomposition) and moves the stationary share up a little — ch6 86.1 →
      86.9%, ch8 81.8 → 82.9%, ch7 73.4 → 74.2%, ch9 72.3 → 73.3% — because it removes a little
      within-visit energy from the perturbation modes. ROF preserves each segment's mean, so the
      time&depth mean column does not move; and a mode's *sign* is only comparable inside one
      decomposition, so a filtered and an unfiltered decomposition can differ by a flip (ch9's mode
      3 does).
    - **The other reading, if the question changes.** The variation *about* the mean alone is a
      different decomposition of the same matrix: ``TimeModesSettings(center=True)`` (the library
      default) removes each gate's time mean first and returns pure fluctuation modes. State which
      one is being read — they are not interchangeable, and the mean-removed form cannot show where
      the mean sits.

    The decomposition, its scaling and these limits live in
    [`src/udv_echo_process/analysis/time_modes.py`](../../src/udv_echo_process/analysis/time_modes.py)
    with the result model in
    [`src/udv_echo_process/models/time_modes.py`](../../src/udv_echo_process/models/time_modes.py).
    """
    )
    return


@app.cell(hide_code=True)
def notes(mo):
    mo.md("""
    **Reading these views.**

    - **Shared scales on purpose.** The heatmaps share one colour scale (± max |velocity|), the
      pair overlays share their y range, and the mode grid shares one range across the four
      panels. That is what lets a reader compare channels at all: with per-panel autoscaling the
      mount-to-mount level factor would be invisible, and level is half of the 6 <-> 8 / 7 <-> 9
      question.
    - **Depth is the shared coordinate; time is not.** All four channels stored the same 55-gate
      grid, so a gate index means the same depth everywhere — the pair *depth* overlay is therefore
      a genuine without-alignment comparison. The time axes differ by the acquisition's visit
      offsets, which is why the pair *time* overlay shows each channel's own stamps and why the
      cursor table prints the nearest-profile offset for every channel.
    - **The filter is a pre-processing choice, not a view.** With it on, every figure and table
      below describes the filtered field and each title says so. Two structural facts decide what
      it can do here: TV is index-based and needs a uniform cadence, so the layer refuses a segment
      that would span the ~372 ms visit gap rather than smoothing across the hole; and inside a
      4-profile visit it has only four samples to work with. The note above the figures reports the
      segments it used, what it changed (and it reports when it changed nothing, which happens if
      `max_gap` is set below the within-visit step), and the provenance record it wrote.
    - **Stagger, not error.** The offsets in the cursor table are the acquisition's multiplexed
      visit order 6 -> 7 -> 8 -> 9: visit starts are 112 ms apart, and because a visit carries four
      profiles (~25 ms apart) before a ~372 ms gap, a channel's *nearest* profile sits at most half
      a visit cycle away — up to ~112 ms for the next channel in the order, and up to ~224 ms for
      6 against 8, the orthogonal-mount pair. At the 200 RPM the file name claims, 224 ms is most
      of a revolution, so an index-aligned overlay of two channels would compare different flow
      states — which is what those offsets make visible.
    - **Sign.** The velocity is the instrument's signed axial component, and the sign convention of
      a mount rotated 90 degrees is not decoded here; the shared symmetric scales keep the
      magnitudes comparable and show the signs as stored, nothing more.
    - **Not here, deliberately.** No time alignment, no interpolation, no averaging across
      channels, no *difference* curve between a pair's members (an overlay shows both signals, not
      their difference — a difference curve would need the alignment the time axis cannot justify)
      and no placement figure. The placement figure and the level-factor question are recorded as
      selected next work in `docs/plans/four-sensor-velocity-notebook-review.md`.
    """)
    return


if __name__ == "__main__":
    app.run()
