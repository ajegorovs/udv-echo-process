import marimo

__generated_with = "0.24.0"
app = marimo.App(width="full")


@app.cell
def _():
    import marimo as mo

    from udv_echo_process import (
        ExtractedData,
        discover_data_files,
        extract,
        plot_channel_stats,
        plot_recording,
    )

    return (
        ExtractedData,
        discover_data_files,
        extract,
        mo,
        plot_channel_stats,
        plot_recording,
    )


@app.cell
def _(mo):
    mo.md("""
    # UDV echo explorer

    Thin interactive wrapper around the `udv_echo_process` building blocks —
    `extract`, `plot_recording`, `plot_channel_stats`, `discover_data_files`.
    All computation stays in `src/`; cells here only wire widgets to it.

    Works for every discoverable recording: single- or multi-sensor, echo or
    velocity, raw or `_Stat` statistical summaries.
    """)
    return


@app.cell
def _(discover_data_files, mo):
    _recordings = [str(p) for p in discover_data_files()]
    file_picker = mo.ui.dropdown(
        options=_recordings,
        value=_recordings[0] if _recordings else None,
        label="Recording (.ADD)",
    )
    file_picker
    return (file_picker,)


@app.cell
def _(extract, file_picker, mo):
    data = extract(file_picker.value) if file_picker.value else None
    summary = (
        mo.md(f"`{data.file_path.name}` — {data.describe()}")
        if data is not None
        else mo.md("_No recording selected._")
    )
    summary
    return (data,)


@app.cell
def _(data, mo):
    channels = (
        mo.ui.multiselect(
            options=sorted(data.by_channel()),
            label="Channel(s)",
            value=sorted(data.by_channel()),
        )
        if data is not None
        else mo.ui.multiselect(options=[], label="Channel(s)", value=[])
    )
    channels
    return (channels,)


@app.cell
def _(ExtractedData, channels, data):
    filtered = (
        ExtractedData(
            file_path=data.file_path,
            header=data.header,
            comment=data.comment,
            frames=[f for f in data.frames if f.channel in channels.value],
        )
        if data is not None and channels.value
        else None
    )
    return (filtered,)


@app.cell
def _(filtered, mo, plot_recording):
    heatmap_fig = (
        mo.mpl.interactive(plot_recording(filtered, return_fig=True))
        if filtered is not None
        else None
    )
    heatmap_fig
    return (heatmap_fig,)


@app.cell
def _(mo):
    mo.md("""
    ### Gate-depth profiles — mean ± 1 std across time
    """)
    return


@app.cell
def _(filtered, mo, plot_channel_stats):
    profiles_fig = (
        mo.mpl.interactive(plot_channel_stats(filtered, return_fig=True))
        if filtered is not None
        else None
    )
    profiles_fig
    return (profiles_fig,)


if __name__ == "__main__":
    app.run()
