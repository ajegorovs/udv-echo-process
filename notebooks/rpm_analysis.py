import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell(hide_code=True)
def imports():
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import plotly.graph_objects as go

    from udv_echo_process import EchoRpmInputError
    from udv_echo_process.analysis import (
        rpm_from_channel,
        rpm_from_echo,
        setpoint_rpm_from_stem,
    )
    from udv_echo_process.io import load, sniff
    from udv_echo_process.models import ChannelKey, EchoRpmSettings
    from udv_echo_process.parser import extract
    from udv_echo_process.process import LinearInterpSpec, resample
    from udv_echo_process.provenance import select_channel
    from udv_echo_process.run_all import collect_artifact_results

    return (
        ChannelKey,
        EchoRpmInputError,
        EchoRpmSettings,
        LinearInterpSpec,
        Path,
        collect_artifact_results,
        extract,
        go,
        load,
        mo,
        np,
        resample,
        rpm_from_channel,
        rpm_from_echo,
        select_channel,
        setpoint_rpm_from_stem,
        sniff,
    )


@app.cell(hide_code=True)
def intro(mo):
    mo.md("""
    # Echo RPM — how the analysis is done

    The rotor speed of a **single-sensor echo** recording comes out of one
    quantity: the **FFT of the gate-averaged amplitude trace**, whose dominant
    non-DC mode is the rotor's twice-per-revolution modulation.

    ```text
    values (profile, gate)  ->  mean over gates      = one trace y(t)
    y(t)                    ->  |rfft| magnitude     = amplitude spectrum
    spectrum[1:]            ->  argmax               = dominant non-DC mode
    peak_freq_hz / 2 * 60                            = RPM
    ```

    Four contract points decide whether that number means anything, and this
    notebook exercises each of them on the committed fixtures:

    1. **Frequency calibration** — the FFT axis uses the *full-span* effective
       interval `(t[-1] - t[0]) / (N - 1)`, never the median adjacent interval
       (the timestamps are quantized, so the median is a quantum, not a period).
    2. **Regularity guard** — `rfft` assumes uniform spacing; the measured
       worst-case interval deviation must stay inside
       `EchoRpmSettings.uniform_rtol`.
    3. **DC is excluded** — a large DC offset is the global maximum of real echo
       data, and reporting it as a 0 RPM mode would be meaningless.
    4. **The `/2` factor is rig-specific** — two echo features per revolution on
       this campaign, so it is fixed in the estimator contract, not a knob.

    Thin wrapper: every number below comes from
    `src/udv_echo_process/analysis/rpm.py`; the cells only select inputs and
    draw. The terminal result is an `EchoRpmEstimate` — no derived artifact, no
    provenance node, no support/quality change.
    """)
    return


@app.cell(hide_code=True)
def method_step_1(mo):
    mo.md("""
    ## 1. Pick a recording and a channel

    Candidates are the **immediate files** of `data/echo` whose leading bytes
    `io.sniff()` recognizes — discovery is by content, not by extension, and not
    recursive (the same rule the batch sweep uses).
    """)
    return


@app.cell(hide_code=True)
def recording_candidates(Path, sniff):
    _echo_dir = Path("data/echo")
    candidates = (
        [
            str(p)
            for p in sorted(_echo_dir.iterdir())
            if p.is_file() and sniff(p.read_bytes()[:128]) is not None
        ]
        if _echo_dir.is_dir()
        else []
    )
    return (candidates,)


@app.cell(hide_code=True)
def file_picker(candidates, mo):
    file_picker = mo.ui.dropdown(
        options=candidates,
        value=candidates[0] if candidates else None,
        label="Echo recording (content-sniffed)",
        full_width=True,
    )
    file_picker
    return (file_picker,)


@app.cell(hide_code=True)
def load_recording(file_picker, load, mo, Path, setpoint_rpm_from_stem):
    bundle = load(file_picker.value) if file_picker.value else None
    _head = mo.md("_No recording selected._")
    if bundle is not None:
        _asset = bundle.recording.source_asset
        _n = len(bundle.recording.streams)
        _stem = Path(file_picker.value).stem
        try:
            _sp = f"{setpoint_rpm_from_stem(_stem)} RPM (from the filename)"
        except ValueError as _err:
            _sp = f"— ({_err})"
        _head = mo.md(
            f"**{_asset.file_name}** · {_asset.source}  \n"
            f"{_n} recording stream(s) · {bundle.recording.acquisition_mode.value} · "
            f"setpoint {_sp}  \n"
            f"`artifact_id` sha256:{_asset.content_sha256[:12]}…"
        )
    _head
    return (bundle,)


@app.cell(hide_code=True)
def channel_picker(bundle, mo):
    _ids = (
        [s.acquisition.channel.device_channel for s in bundle.recording.streams]
        if bundle is not None
        else []
    )
    channel_picker = mo.ui.dropdown(
        options=_ids,
        value=_ids[0] if _ids else None,
        label="Channel",
        full_width=True,
    )
    channel_picker
    return (channel_picker,)


@app.cell(hide_code=True)
def select_selected(bundle, channel_picker, select_channel, ChannelKey):
    selected = (
        select_channel(bundle, ChannelKey(device_channel=channel_picker.value))
        if bundle is not None and channel_picker.value is not None
        else None
    )
    return (selected,)


@app.cell(hide_code=True)
def selected_overview(selected, mo, np):
    _md = mo.md("_Select a recording + channel._")
    if selected is not None:
        _art = selected.artifact
        _t = _art.data.time_s
        _dt = np.diff(_t)
        _md = mo.md(
            f"`ch{_art.acquisition.channel.device_channel}` · "
            f"**{_art.descriptor.quantity.value}** ({_art.descriptor.unit}) · "
            f"{_t.size} profiles × {_art.data.gate_depths_mm.size} gates  \n"
            f"- time: {_t[0]:.4f} → {_t[-1]:.4f} s · recording "
            f"`…{_art.acquisition.recording_id[:12]}…`  \n"
            f"- adjacent intervals: median {np.median(_dt) * 1e3:.3f} ms · "
            f"full-span {(_t[-1] - _t[0]) / (_t.size - 1) * 1e3:.4f} ms · "
            f"distinct quanta {np.unique(np.round(_dt * 1e6).astype(int)).size}"
        )
    _md
    return


@app.cell(hide_code=True)
def method_step_2(mo):
    mo.md("""
    ## 2. The signal the estimator actually sees

    Not the raw matrix — the **mean across gates**. Each gate sees the same
    travelling echo wave at a different phase, so the gate average is where the
    rotor modulation survives as one clean periodic trace.
    """)
    return


@app.cell(hide_code=True)
def gate_mean_trace(selected, go, mo, np):
    gate_mean_fig = None
    if selected is not None:
        _art = selected.artifact
        _t = _art.data.time_s
        _trace = np.asarray(_art.data.values).mean(axis=1)
        _fig = go.Figure(
            go.Scatter(
                x=_t,
                y=_trace,
                mode="lines",
                line=dict(width=1, color="#1f77b4"),
                name="mean over gates",
            )
        )
        _fig.update_layout(
            title=f"ch{_art.acquisition.channel.device_channel} — gate-averaged "
            f"{_art.descriptor.quantity.value} (the FFT input)",
            xaxis_title="time [s]",
            yaxis_title=f"mean {_art.descriptor.quantity.value} "
            f"[{_art.descriptor.unit}]",
            height=360,
        )
        gate_mean_fig = mo.ui.plotly(_fig)
    gate_mean_fig
    return


@app.cell(hide_code=True)
def method_step_3(mo):
    mo.md("""
    ## 3. The guard — one knob, and it is an input check

    `EchoRpmSettings` has exactly one parameter: `uniform_rtol`, the maximum
    allowed relative deviation of an adjacent interval from the axis' median.
    Move it around the committed recordings' **3.125 %** deviation to watch the
    estimator accept or refuse the very same input. It is not an algorithm knob:
    refusing an irregular axis is the point (a burst/visit-sampled recording
    deviates by ~46x and is refused in §6).
    """)
    return


@app.cell(hide_code=True)
def guard_slider(mo):
    guard_rtol = mo.ui.slider(
        start=0.0,
        stop=0.05,
        step=0.0005,
        value=0.05,
        label="uniform_rtol (hard ceiling 0.05)",
        show_value=True,
        full_width=True,
    )
    guard_rtol
    return (guard_rtol,)


@app.cell(hide_code=True)
def run_estimate(
    selected, guard_rtol, EchoRpmInputError, EchoRpmSettings, rpm_from_channel, mo, np
):
    estimate = None
    estimate_error = None
    if selected is not None:
        try:
            estimate = rpm_from_channel(
                selected, settings=EchoRpmSettings(uniform_rtol=float(guard_rtol.value))
            )
        except EchoRpmInputError as _err:
            estimate_error = str(_err)
    _md = mo.md("_Select a recording + channel._")
    if estimate is not None:
        _md = mo.md(
            f"**accept** — `uniform_rtol` {guard_rtol.value:.4f} ≥ measured "
            f"{estimate.max_relative_interval_deviation:.5f}  \n"
            f"- effective interval `time_step_s` = {estimate.time_step_s:.9f} s "
            f"({estimate.time_step_s * 1e3:.4f} ms)  \n"
            f"- peak bin {estimate.peak_index} of {estimate.spectrum.size - 1} "
            f"non-DC bins · {estimate.peak_freq_hz:.4f} Hz  \n"
            f"- **RPM = {estimate.peak_freq_hz:.4f} / 2 × 60 = "
            f"{estimate.rpm:.4f}**"
        )
    elif estimate_error is not None:
        _md = mo.md(f"**refuse** — `EchoRpmInputError`  \n```text\n{estimate_error}\n```")
    _md
    return estimate, estimate_error


@app.cell(hide_code=True)
def estimate_panel(estimate, selected, mo):
    _md = mo.md("_No estimate._")
    if estimate is not None and selected is not None:
        _source_id = selected.artifact.artifact_id
        _md = mo.md(f"""
        ### Result — `EchoRpmEstimate`

        The result is **terminal**: it names the artifact it read and adds
        nothing to the graph — no derived artifact, no operation record, no
        support or quality change.

        - `artifact_id` ties the estimate to its source:
          {'same artifact' if estimate.artifact_id == _source_id else 'MISMATCH'}
          (`…{_source_id[:12]}…`)
        - provenance after the call: {len(selected.graph.operations)} operation(s)
          on this channel's graph — the estimate introduced none
        - `settings` actually used: `{estimate.settings.model_dump_json()}`
        - `frequencies_hz` / `spectrum`: shape {estimate.frequencies_hz.shape} ·
          owned, C-contiguous, read-only
        - profile_count {estimate.profile_count} · gate_count
          {estimate.gate_count} · descriptor
          `{estimate.descriptor.quantity.value}`
        """)
    _md
    return


@app.cell(hide_code=True)
def method_step_4(mo):
    mo.md("""
    ### The spectrum, and why DC is excluded

    The estimator searches **every rFFT bin except the DC bin**. On real echo
    data the DC bin is the global maximum, so a raw `argmax` would always report
    0 Hz → 0 RPM; the marker below shows where DC sits relative to the selected
    peak.
    """)
    return


@app.cell(hide_code=True)
def spectrum_plot(estimate, go, mo):
    spectrum_fig = None
    if estimate is not None:
        _f = estimate.frequencies_hz
        _s = estimate.spectrum
        _fig = go.Figure()
        _fig.add_trace(
            go.Scatter(
                x=_f,
                y=_s,
                mode="lines",
                name="|rfft| mean over gates",
                line=dict(width=1.2, color="#1f77b4"),
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=[0.0],
                y=[float(_s[0])],
                mode="markers",
                name=f"DC bin (excluded) — {float(_s[0]):.4g}",
                marker=dict(size=11, color="#7f7f7f", symbol="x"),
            )
        )
        _fig.add_trace(
            go.Scatter(
                x=[float(_f[estimate.peak_index])],
                y=[float(_s[estimate.peak_index])],
                mode="markers+text",
                name=f"peak — {estimate.peak_freq_hz:.3f} Hz",
                text=[f"{estimate.rpm:.1f} RPM"],
                textposition="top center",
                marker=dict(size=12, color="#d62728"),
            )
        )
        _fig.update_layout(
            title="Amplitude spectrum (unnormalised magnitude, not a PSD)",
            xaxis_title="frequency [Hz]",
            yaxis_title="mean |rfft| [counts]",
            height=400,
            legend=dict(orientation="h", y=1.15),
        )
        spectrum_fig = mo.ui.plotly(_fig)
    spectrum_fig
    return


@app.cell(hide_code=True)
def method_step_5(mo):
    mo.md("""
    ### Why the full span, not the median

    The timestamps are quantized: adjacent intervals take only a couple of
    values, so the **median is a quantum, not the sampling period**. The cell
    below recomputes the same peak under the median calibration (display-only
    arithmetic, to make the error visible) — this is exactly the ~0.6 % shift the
    estimator's contract exists to avoid.
    """)
    return


@app.cell(hide_code=True)
def timebase_panel(estimate, selected, mo, np):
    _md = mo.md("_No estimate._")
    if estimate is not None and selected is not None:
        _t = np.asarray(selected.artifact.data.time_s)
        _dt = np.diff(_t)
        _quanta_us = np.unique(np.round(_dt * 1e6).astype(int))
        _median_dt = float(np.median(_dt))
        _n = estimate.profile_count
        _peak = int(estimate.peak_index)
        # display-only illustration: recalibrate the SAME peak bin on the median
        # quantum instead of the full span
        _median_freq = _peak / (_n * _median_dt)
        _rpm_median_cal = _median_freq / 2 * 60
        _shift_pct = (estimate.rpm - _rpm_median_cal) / estimate.rpm * 100
        _md = mo.md(f"""
        | quantity | value |
        | --- | --- |
        | adjacent-interval quanta (rounded) | {' / '.join(f'{q} µs' for q in _quanta_us)} |
        | short intervals | {int((np.round(_dt * 1e6).astype(int) == _quanta_us[0]).sum())} of {_dt.size} |
        | median adjacent interval | {_median_dt * 1e3:.4f} ms |
        | full-span effective interval (`time_step_s`) | {estimate.time_step_s * 1e3:.4f} ms |
        | measured deviation from median | {estimate.max_relative_interval_deviation * 100:.4f} % |
        | bin width at this span | {estimate.frequencies_hz[1]:.6f} Hz |
        | peak | bin {_peak} of {estimate.spectrum.size - 1} non-DC bins · {estimate.peak_freq_hz:.4f} Hz |
        | RPM — full span (contract) | **{estimate.rpm:.3f}** |
        | RPM — same peak, median-calibrated | {_rpm_median_cal:.3f} |

        The median calibration of the identical peak lands
        **{abs(_shift_pct):.3f} %** away. That is the error a one-quantum
        frequency axis introduces on a record of this length, and it is why the
        contract pins the full span.
        """)
    _md
    return


@app.cell(hide_code=True)
def method_step_6(mo):
    mo.md("""
    ## 4. The same recording, on the legacy `.ADD` path

    The two pipelines are independent by design — there is **no `.ADD` → bundle
    adapter** — but the estimator core is shared, so the paired `.ADD` twin of
    the selected recording must reproduce the artifact-model number to
    floating-point precision.
    """)
    return


@app.cell(hide_code=True)
def legacy_compare(
    estimate,
    extract,
    file_picker,
    mo,
    np,
    Path,
    rpm_from_echo,
    setpoint_rpm_from_stem,
):
    _md = mo.md("_No estimate._")
    if estimate is not None:
        _add = Path(file_picker.value).with_suffix(".ADD")
        if _add.is_file():
            _rpm, _f_peak, _n = rpm_from_echo(extract(_add))
            _sp = setpoint_rpm_from_stem(_add.stem)
            _md = mo.md(
                f"""
                | path | API | RPM | peak [Hz] | samples |
                | --- | --- | --- | --- | --- |
                | `{Path(file_picker.value).name}` | `rpm_from_channel` → `EchoRpmEstimate` | {estimate.rpm:.6f} | {estimate.peak_freq_hz:.6f} | {estimate.profile_count} |
                | `{_add.name}` | `rpm_from_echo` → `(rpm, f_peak, n)` | {_rpm:.6f} | {_f_peak:.6f} | {_n} |

                - relative difference: **{abs(_rpm - estimate.rpm) / _rpm:.3g}** (one shared
                  private kernel, called from both entry points)
                - setpoint from the filename: {_sp} RPM → artifact error
                  {abs(estimate.rpm - _sp) / _sp * 100:.3f} %
                - the setpoint is an experiment *label*, not independent tachometer
                  ground truth, so this is a campaign sanity check, not an
                  uncertainty claim
                """
            )
        else:
            _md = mo.md(f"_No paired `.ADD` twin at `{_add}`._")
    _md
    return


@app.cell(hide_code=True)
def method_step_7(mo):
    mo.md("""
    ## 5. What the estimator refuses — and what a refusal is NOT

    A burst/visit-sampled recording cannot be calibrated by one rFFT interval:
    its axis is *structurally* sampled (short intra-burst steps, long
    inter-burst gaps), so the estimator refuses it instead of compacting it onto
    its median cadence. Turn the switch on to see the trap this refusal exists to
    prevent **and** the mechanism that actually refuses it.
    """)
    return


@app.cell(hide_code=True)
def refusal_controls(Path, mo):
    _fixtures = {
        "4-channel echo — burst/visit sampled (misnamed .jpg)": (
            "data/echo-4-sensors-2x2/20260723_143754.jpg"
        ),
        "4-channel velocity — wrong quantity": "data/4-sensor-velocity/200RPM.BDD",
    }
    _available = {k: v for k, v in _fixtures.items() if Path(v).is_file()}
    refusal_fixture = mo.ui.dropdown(
        options=_available,
        value=next(iter(_available)) if _available else None,
        label="Fixture to refuse",
        full_width=True,
    )
    refusal_trap = mo.ui.switch(
        value=False,
        label="force-bridge the long gaps (resample) — demonstrates the trap",
    )
    mo.vstack([refusal_fixture, refusal_trap])
    return refusal_fixture, refusal_trap


@app.cell(hide_code=True)
def refusal_run(
    EchoRpmInputError,
    LinearInterpSpec,
    load,
    mo,
    np,
    refusal_fixture,
    refusal_trap,
    resample,
    rpm_from_channel,
    select_channel,
):
    _md = mo.md("_No fixture selected._")
    if refusal_fixture.value:
        _bundle = load(refusal_fixture.value)
        _streams = _bundle.recording.streams
        _lines = [f"### {len(_streams)} stream(s) — per-channel outcome", ""]
        for _s in _streams:
            _ch = _s.acquisition.channel.device_channel
            _sel = select_channel(_bundle, _s.acquisition.channel)
            try:
                _est = rpm_from_channel(_sel)
                _lines.append(f"- `ch{_ch}`: **accepted** → {_est.rpm:.4f} RPM")
            except EchoRpmInputError as _err:
                _short = str(_err).split("(")[0].strip()
                _lines.append(f"- `ch{_ch}`: **refused** — {_short}")
        _md = mo.md("\n".join(_lines))

        if refusal_trap.value:
            _s0 = _streams[0]
            _sel0 = select_channel(_bundle, _s0.acquisition.channel)
            _t = np.asarray(_sel0.artifact.data.time_s)
            _gap = float(np.max(np.diff(_t)))
            _dt = float(np.median(np.diff(_t)))
            _spec = LinearInterpSpec(
                extrapolation="nearest",
                max_bracket_span_s=_gap * 1.01,
                long_gap="missing",
            )
            _bridged = resample(_sel0, _spec, dt_s=_dt)
            _trap_dev = float("nan")
            _trap_peak = float("nan")
            try:
                _trap_est = rpm_from_channel(_bridged)
                _trap_dev = _trap_est.max_relative_interval_deviation
                _trap_peak = _trap_est.peak_freq_hz
                _trap_txt = (
                    f"**accepted → {_trap_est.rpm:.4f} RPM** on every channel "
                    f"(burst-envelope rate, not rotor speed)"
                )
            except EchoRpmInputError as _err:
                _trap_txt = f"refused: {_err}"

            _tight = LinearInterpSpec(
                extrapolation="nearest",
                max_bracket_span_s=_dt * 6.0,
                long_gap="missing",
            )
            _tight_out = resample(_sel0, _tight, dt_s=_dt)
            _n_missing = int(
                (~np.isfinite(np.asarray(_tight_out.artifact.data.values))).sum()
            )

            _md = mo.md("\n".join(_lines) + f"""

            ---

            #### With the gaps force-bridged

            - `resample(..., max_bracket_span_s={_gap * 1.01:.4f})` builds an
              **exactly uniform** grid, so the measured deviation is
              {_trap_dev:.2e} and the regularity guard is trivially satisfied.
              The guard is *not* what refuses this recording.
            - outcome: {_trap_txt}. The peak lands at {_trap_peak:.3f} Hz — the
              burst repetition rate of the acquisition structure, not the rotor
              rate (a genuine 300 RPM needs ~10 Hz here) — and nothing on the
              result marks it as meaningless.
            - the mechanism that does refuse it: with
              `max_bracket_span_s={_dt * 6.0:.4f}` (below the gap) the bridged rows
              arrive as **{_n_missing} `MISSING` cells**, and the fully-valid-input
              rule stops them before any spectrum is computed.
            """)
    _md
    return


@app.cell(hide_code=True)
def method_step_8(mo):
    mo.md("""
    ## 6. The batch sweep

    `collect_artifact_results` walks the sniffed paths, requires exactly one
    recording stream per file (a multi-stream recording raises instead of
    silently reporting channel 0), estimates each one and returns sorted
    `RpmResult` rows. Setpoints come from the filename.
    """)
    return


@app.cell(hide_code=True)
def batch_sweep(candidates, collect_artifact_results, mo, np, go):
    sweep_rows = []
    sweep_error = None
    try:
        sweep_rows = collect_artifact_results(candidates)
    except ValueError as _err:
        sweep_error = str(_err)
    sweep_table = None
    sweep_fig = None
    if sweep_rows:
        sweep_table = mo.ui.table(
            [
                {
                    "setpoint [RPM]": r.setpoint_rpm,
                    "measured [RPM]": round(r.measured_rpm, 3),
                    "peak [Hz]": round(r.peak_freq_hz, 4),
                    "error [%]": round(r.rel_error_pct, 3),
                    "samples": r.n_samples,
                }
                for r in sweep_rows
            ],
            label=f"{len(sweep_rows)} single-channel echo recordings",
        )
        _sp = np.array([r.setpoint_rpm for r in sweep_rows])
        _meas = np.array([r.measured_rpm for r in sweep_rows])
        _err = np.array([r.rel_error_pct for r in sweep_rows])
        _fig = go.Figure()
        _fig.add_trace(
            go.Scatter(x=_sp, y=_sp, mode="lines", name="ideal", line=dict(dash="dash"))
        )
        _fig.add_trace(
            go.Scatter(x=_sp, y=_meas, mode="markers", name="measured", marker=dict(size=9))
        )
        _fig.update_layout(
            title=f"Sweep — mean error {_err.mean():.2f} %, max {_err.max():.2f} % "
            f"(limit 2 %)",
            xaxis_title="setpoint from filename [RPM]",
            yaxis_title="measured [RPM]",
            height=380,
        )
        sweep_fig = mo.ui.plotly(_fig)
    _md = mo.md(f"⚠️ sweep failed: `{sweep_error}`") if sweep_error else None
    mo.vstack([x for x in (_md, sweep_table, sweep_fig) if x is not None])
    return sweep_rows, sweep_table


@app.cell(hide_code=True)
def summary(mo, sweep_rows):
    _md = mo.md("""
    ## What this notebook establishes

    - One method: gate-average → `|rfft|` → dominant non-DC bin → `/2 × 60`.
    - One kernel, two entry points: `rpm_from_channel` (artifact model) and
      `rpm_from_echo` (legacy `.ADD`), numerically identical on paired fixtures.
    - The result is terminal and auditable: `settings`, `artifact_id`,
      `time_step_s`, the measured interval deviation, `peak_index`, `rpm` and the
      owned read-only trace arrays, with the model rejecting any estimate whose
      axis, peak or RPM does not replay from those fields.
    - What is refused, and why: an irregular (burst/visit-sampled) axis, a
      non-echo channel, any invalid support cell, and < 2 profiles — with
      resampling explicitly *not* a way to make an unfittable recording valid.

    Still open (see `docs/agenda.md`): multi-channel / burst-sampled echo RPM
    needs a visit-aware estimator and independently known ground truth.
    """)
    if sweep_rows:
        _md = mo.vstack(
            [
                _md,
                mo.md(
                    f"_{len(sweep_rows)} recordings swept in this view; "
                    f"largest campaign error "
                    f"{max(r.rel_error_pct for r in sweep_rows):.2f} %._"
                ),
            ]
        )
    _md
    return


if __name__ == "__main__":
    app.run()
