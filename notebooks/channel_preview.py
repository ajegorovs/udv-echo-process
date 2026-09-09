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


if __name__ == "__main__":
    app.run()
