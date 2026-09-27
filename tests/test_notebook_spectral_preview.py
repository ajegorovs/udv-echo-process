"""SA2.3 — the notebook's spectral wiring, checked as a contract rather than by eye.

SA2.2 already proves the estimator. This file proves only what SA2.3 adds: that the *notebook*
in ``notebooks/signal_explorer.py`` exposes already-reviewed backend results and does no spectral
arithmetic of its own. The authority is ``docs/dop3000/sa2-3-notebook-preview-plan.md`` (§A–§N);
the names asserted here are the ones the plan publishes (the widget, view and result fields it
lists), never the notebook's private locals.

Two layers:

* **Static (AST)** — what a text search cannot say honestly. ``periodogram_of_view`` is imported
  and called from the periodogram module; the call names its quantity, unit and detrending; the
  notebook carries no FFT, taper or normalization arithmetic; target rows are asked of
  ``target_frequency_support``; the view vocabulary is not re-spelled. These read the source as
  Python, so a rename of a private helper does not break them and a copied ``np.fft`` block does.

* **Behavioural** — the cells are *executed* through marimo's own ``Cell.run`` (its supported
  unit-testing entry point). The two wiring cells — the estimate and the target-support
  question — are driven with a synthetic, exactly-uniform view. The *rendering* cells are executed
  too: the readout, the target panel and the figure, on that synthetic view (once with a refused
  axis and once with a constant trace) and on the **real committed E128 recording**, decoded
  read-only through the notebook's own ``decode_pass`` loader and cut by its own ``primary_view``.
  This is what verifies wiring the AST cannot: the spectrum the notebook builds is the backend's
  estimate of the selected view (one ``WindowView``, one spectrum, §A), the picked detrending
  travels through (§C), a view switch moves the provenance (§M), the figure draws a target marker
  **only** where the backend reports the target supported (§G/§F), and a refused axis is rendered
  as its refusal with **no plot at all** while a constant is drawn as a *defined zero* spectrum
  (§K) — the distinction the stage exists to keep. The displayed markdown and the drawn figures are
  read back from the rendered output, so removing a guard from a rendering cell fails here rather
  than passing silently.

The cells are discovered by *what they call* (the published backend entry points) or by what they
read (the rendering cells, which call nothing the backend owns), never by their function name, and
intermediate values are read from the ``defs`` mapping ``Cell.run`` returns. No notebook source is
edited here, and no backend file is touched; the one committed recording read is the E128
primary-comparison view, opened read-only through the notebook's own loader.
"""

from __future__ import annotations

import ast
import builtins
import importlib.util
import os
import subprocess
import sys
import types
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from udv_echo_process.analysis._sparse_pass import decode_pass
from udv_echo_process.analysis._sparse_view import SparseView, WindowView, view_rule
from udv_echo_process.analysis.sparse_gate_stats import gate_statistics, primary_view
from udv_echo_process.analysis.sparse_passes import pass_by_name
from udv_echo_process.analysis.sparse_periodogram import (
    SpectralEstimate,
    SpectralVerdict,
)
from udv_echo_process.analysis.sparse_recurrence import Detrending
from udv_echo_process.analysis.sparse_spectral_capability import PROBE_TARGETS
from udv_echo_process.analysis.sparse_target_support import (
    TargetFrequencySupport,
    target_frequency_support,
)

#: The repository root, from this file's own location — never a hard-coded path.
ROOT = Path(__file__).resolve().parents[1]
#: The one notebook SA2.3 extends. ``SA23_NOTEBOOK`` lets the same checks be pointed at an older
#: revision of the file (e.g. the pre-SA2.3 baseline) to show they are not vacuous.
NOTEBOOK = Path(
    os.environ.get("SA23_NOTEBOOK", ROOT / "notebooks" / "signal_explorer.py")
)

#: §F: the nominal rotor reference, the exact fraction the calibration states.
ROTOR_HZ = 25.0 / 3.0
#: §F: the recurrence-scale probe.
RECURRENCE_HZ = 1.0

#: Names that would mean the notebook had grown its own spectral arithmetic. Exact matches only,
#: so ``periodogram_of_view`` (a call to the backend) is not mistaken for a re-implementation.
FORBIDDEN_SPECTRAL_NAMES = frozenset(
    {
        "fft",
        "rfft",
        "irfft",
        "fft2",
        "rfft2",
        "fftn",
        "fftfreq",
        "rfftfreq",
        "fftshift",
        "hann",
        "hanning",
        "hamming",
        "blackman",
        "bartlett",
        "kaiser",
        "get_window",
        "welch",
        "spectrogram",
        "stft",
        "csd",
        "coherence",
        "cohere",
        "periodogram",
        "hann_window",
        "taper",
        "enbw",
    }
)

#: §L: every field a displayed spectrum must make recoverable, each read from the object that
#: already owns it (``ViewProvenance`` or ``SpectralEstimate`` itself).
PROVENANCE_FIELDS = frozenset(
    {
        "provenance",
        "job",
        "point_label",
        "order",
        "relative_path",
        "source_sha256",
        "view",
        "view_rule",
        "gate_index",
        "depth_mm",
        "quantity",
        "unit",
        "detrending",
        "estimator_name",
        "taper_name",
        "taper_convention",
    }
)

#: The three view constructors: the notebook must keep exactly ONE place that decides a window.
VIEW_CONSTRUCTORS = frozenset({"primary_view", "full_record_view", "exploration_view"})


# --------------------------------------------------------------------------------------
# reading the notebook: source, AST, and the marimo cells themselves
# --------------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _source() -> str:
    return NOTEBOOK.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(NOTEBOOK))


@lru_cache(maxsize=1)
def _app_module() -> types.ModuleType:
    """The notebook imported as a module. This registers cells; it decodes nothing."""
    spec = importlib.util.spec_from_file_location("sa23_signal_explorer", NOTEBOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def _cells() -> dict[str, Any]:
    """Every marimo cell in the notebook, keyed by its cell function name."""
    import marimo

    return {
        name: value
        for name, value in vars(_app_module()).items()
        if isinstance(value, marimo.Cell)
    }


def _cell_defs() -> dict[str, set[str]]:
    return {name: set(cell.defs) for name, cell in _cells().items()}


def _cell_refs() -> dict[str, set[str]]:
    return {name: set(cell.refs) for name, cell in _cells().items()}


def _function_nodes() -> dict[str, ast.FunctionDef]:
    return {
        node.name: node for node in _tree().body if isinstance(node, ast.FunctionDef)
    }


def _called_names(node: ast.AST) -> set[str]:
    """The simple name of every function called anywhere under ``node``."""
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            target = child.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def _referenced_names(node: ast.AST) -> set[str]:
    """Every ``Name`` load and every attribute tail — the identifiers a cell *reads*."""
    read: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            read.add(child.id)
        elif isinstance(child, ast.Attribute):
            read.add(child.attr)
    return read


def _cells_calling(*callees: str) -> list[str]:
    wanted = set(callees)
    return sorted(
        name for name, node in _function_nodes().items() if _called_names(node) & wanted
    )


def _cells_referencing(*names: str) -> list[str]:
    wanted = set(names)
    return sorted(
        name
        for name, node in _function_nodes().items()
        if _referenced_names(node) & wanted
    )


def _calls_to(callee: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(_tree())
        if isinstance(child, ast.Call)
        and (
            (isinstance(child.func, ast.Name) and child.func.id == callee)
            or (isinstance(child.func, ast.Attribute) and child.func.attr == callee)
        )
    ]


def _imports_from(module_suffix: str) -> set[str]:
    """Names imported by ``from <...module_suffix> import ...``, plus aliased modules."""
    imported: set[str] = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.endswith(module_suffix):
                imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.endswith(module_suffix):
                    imported.add(alias.asname or alias.name)
    return imported


def _require_notebook_cell(callee: str) -> str:
    """The one cell that calls ``callee`` — the SA2.3 surface this file exists to check."""
    cells = _cells_calling(callee)
    if not cells:
        pytest.fail(
            f"no notebook cell calls `{callee}` yet: SA2.3 has not landed the spectral surface "
            f"`{NOTEBOOK.name}` is contracted to expose (§B/§F of the plan)"
        )
    return cells[0]


# --------------------------------------------------------------------------------------
# running one cell with synthetic inputs — marimo's own Cell.run
# --------------------------------------------------------------------------------------


def _synthetic_view(
    *,
    view: SparseView = SparseView.PRIMARY,
    profiles: int = 138,
    dt_s: float = 0.02,
    gates: int = 3,
    trace: str = "tone",
    duplicate_stamp: bool = False,
) -> WindowView:
    """The smallest honest labelled view around a synthetic trace, on an exact uniform axis.

    ``dt_s`` fixes the adopted rate and therefore Nyquist: the default is fine enough that
    ``ROTOR_HZ`` is well inside the band, and the coarse axes used below put it above Nyquist so
    the backend's refusal path is exercised on a view built here rather than on committed data.
    """
    stamps = np.arange(profiles, dtype=float) * dt_s
    if duplicate_stamp:
        stamps = stamps.copy()
        stamps[3] = stamps[4]
    depths = np.arange(gates, dtype=float) * 2.0 + 10.0
    values = np.zeros((profiles, gates), dtype=float)
    if trace == "tone":
        values[:, 0] = np.cos(
            2.0 * np.pi * 3.0 * dt_s * np.arange(profiles, dtype=float)
        )
    elif trace == "constant":
        values[:, 0] = 4.0
    else:  # pragma: no cover - a typo in a test, not a data case
        raise AssertionError(f"unknown synthetic trace {trace!r}")
    return WindowView(
        view=SparseView(view),
        view_rule=view_rule(SparseView(view)),
        relative_path="synthetic-SA23.BDD",
        source_sha256="a" * 64,
        job="job-sa23",
        point_label="point-sa23",
        order=2,
        values=values,
        time_s=stamps,
        depths_mm=depths,
        support_mask=np.ones(gates, dtype=bool),
        native_gates=gates,
        native_depth_extent_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        pass_support_mm=(float(depths[0]) - 2.0, float(depths[-1]) + 2.0),
        start_index=0,
        stop_index=profiles,
        window_start_s=float(stamps[0]),
        window_end_s=float(stamps[-1]),
        window_s=float(stamps[-1] - stamps[0]),
    )


class _Point:
    """A decoded point's published surface, as far as the spectral cells read it (§B)."""

    quantity = "radial_velocity"  # deliberately NOT the backend default, so a defaulted call fails
    unit = "m/s"
    label = "point-sa23"
    source_sha256 = "a" * 64
    binding = types.SimpleNamespace(
        identity="synthetic-SA23", relative_path="synthetic-SA23.BDD", order=2
    )


class _Widget:
    def __init__(self, value: Any) -> None:
        self.value = value


def _import_registry() -> dict[str, Any]:
    """The notebook's own imports, materialised: cells with no refs define nothing but imports.

    Reading them from the notebook rather than re-declaring them here keeps this file honest —
    if SA2.3 imports a symbol, it is resolvable without editing this test.
    """
    from udv_echo_process.analysis.sparse_passes import COMMITTED_PASSES, pass_by_name

    registry: dict[str, Any] = {
        "COMMITTED_PASSES": COMMITTED_PASSES,
        "pass_by_name": pass_by_name,
    }
    for cell in _cells().values():
        refs = set(cell.refs)
        if refs - set(builtins.__dict__) - {"mo", "marimo"}:
            continue
        outcome = _safely(lambda cell=cell: cell.run())
        if outcome is None:
            # a display cell that needs a live widget is simply not an import source
            continue
        _output, defs = outcome
        registry.update(dict(defs))
    return registry


def _safely(execute: Any) -> Any:
    """Run ``execute`` and return ``None`` on any failure — used only for optional probing."""
    try:
        return execute()
    except Exception:  # noqa: BLE001 - an optional probe must never abort the import registry
        return None


#: Cells whose execution would decode a committed recording. The synthetic tests never need one,
#: so their resolution is refused rather than paying for a pass to be read from disk.
_DECODING_DEFS = frozenset({"decoding", "decode_pass"})


def _run_cell(cell_name: str, leaves: dict[str, Any]) -> tuple[Any, Any]:
    """Execute one notebook cell with synthetic leaves, resolving the rest from the notebook.

    ``Cell.run`` accepts exactly the cell's own reference names, so each is resolved here: a
    supplied leaf wins, then a symbol the notebook imported, then a value another cell defines
    (executed recursively through this same resolver), then a builtin. A reference that would
    drag in the pass decoder is refused — these tests describe wiring, not data.
    """
    cells = _cells()
    if cell_name not in cells:
        pytest.fail(f"the notebook has no cell named {cell_name!r}")
    cell = cells[cell_name]
    registry = _import_registry()
    builtin_names = set(builtins.__dict__)

    def resolve(name: str, stack: tuple[str, ...]) -> Any:
        if name in leaves:
            return leaves[name]
        if name in registry:
            value = registry[name]
            if callable(value) and getattr(value, "__name__", "") == "decode_pass":
                raise RuntimeError(f"{name!r} would decode a committed pass")
            return value
        if hasattr(builtins, name):
            return getattr(builtins, name)
        if name in _DECODING_DEFS:
            raise RuntimeError(f"{name!r} would decode a committed pass")
        if name in stack:
            raise RuntimeError(f"cyclic reference while resolving {name!r}")
        for other, other_cell in cells.items():
            if name in set(other_cell.defs):
                if set(other_cell.refs) & _DECODING_DEFS:
                    raise RuntimeError(
                        f"resolving {name!r} would run {other!r}, which decodes"
                    )
                _output, defs = _run_cell(other, leaves)
                if name in defs:
                    return defs[name]
                break
        raise RuntimeError(
            f"cell {cell_name!r} reads {name!r}, which this synthetic harness cannot supply"
        )

    kwargs = {
        name: resolve(name, ()) for name in cell.refs if name not in builtin_names
    }
    try:
        return cell.run(**kwargs)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - reported below as this test's own failure
        pytest.fail(f"running cell {cell_name!r} with synthetic inputs raised {exc!r}")


def _spectral_leaves(
    view: WindowView, *, detrending: Detrending = Detrending.MEAN
) -> dict[str, Any]:
    stats = gate_statistics(view)
    position = int(np.asarray(stats.depths_mm).size) // 2
    return {
        "sparse_view": view,
        "sparse_view_error": "",
        "point": _Point(),
        "gate_stats": stats,
        "position": position,
        "position_note": "",
        "detrending_picker": _Widget(detrending),
        "gate_picker": _Widget(position),
        "dataset_picker": _Widget(E128_PASS),
    }


def _estimates_in(defs: Any) -> list[SpectralEstimate]:
    return [value for value in defs.values() if isinstance(value, SpectralEstimate)]


# --------------------------------------------------------------------------------------
# rendering: the display cells, and the text and figures they actually produce
# --------------------------------------------------------------------------------------


class _PlotlyCapture:
    """A seam on ``mo.ui.plotly``: records the figure, then hands it to the real marimo."""

    def __init__(self, sink: _CapturingMo) -> None:
        self._sink = sink

    def plotly(self, figure: Any) -> Any:
        import marimo

        self._sink.figures.append(figure)
        return marimo.ui.plotly(figure)


class _CapturingMo:
    """The real ``marimo`` module, with the two seams a rendering test needs recorded.

    ``mo.md`` is recorded before it is rendered and ``mo.ui.plotly`` before it is wrapped, so a
    test can read back exactly what a cell displayed and whether it drew a figure at all. Every
    other attribute — ``mo.vstack``, ``mo.callout``, ``mo.ui`` and the rest — is the real marimo,
    so the cells compose their output the way they do in the notebook.

    Every ``mo.md`` call is recorded, including a rendering cell's initial fallback line that a
    later branch overwrites (the figure cell's "no PSD is drawn" placeholder). A test therefore
    reads ``figures`` to decide whether a plot was drawn, and the branch-specific markdown for what
    was said about it.
    """

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.figures: list[Any] = []
        self.ui = _PlotlyCapture(self)

    def md(self, text: str) -> Any:
        import marimo

        self.texts.append(text)
        return marimo.md(text)

    def __getattr__(self, name: str) -> Any:
        import marimo

        return getattr(marimo, name)

    @property
    def rendered(self) -> str:
        """Every markdown string this cell asked marimo to render, in call order."""
        return "\n".join(self.texts)


def _render(cell_name: str, leaves: dict[str, Any]) -> tuple[_CapturingMo, Any, Any]:
    """Execute a rendering cell and return the seam, the cell output and its ``defs``."""
    capture = _CapturingMo()
    supplied = dict(leaves)
    supplied["mo"] = capture
    output, defs = _run_cell(cell_name, supplied)
    return capture, output, defs


def _rendering_cell(*required_refs: str) -> str:
    """The one cell that renders a result (it defines nothing) and reads ``required_refs``.

    The rendering cells call no backend entry point, so *what they call* cannot name them; *what
    they read* can, because each reads a ref only its own display owns (``spectral_error`` for the
    readout, the pair of target-support names for the panel and the figure, ``psd_zoom_max_hz``
    for the figure alone).
    """
    matches = sorted(
        name
        for name, cell in _cells().items()
        if not set(cell.defs) and set(required_refs) <= set(cell.refs)
    )
    if len(matches) != 1:
        pytest.fail(
            f"expected exactly one rendering cell reading {sorted(required_refs)}, got {matches}"
        )
    return matches[0]


def _marker_positions(figure: Any) -> list[float]:
    """The x of every vertical target marker the figure drew, sorted."""
    shapes = figure.layout.shapes or ()
    return sorted(float(shape.x0) for shape in shapes if shape.type == "line")


# --------------------------------------------------------------------------------------
# the committed E128 recording — the real case, decoded through the notebook's own loader
# --------------------------------------------------------------------------------------

#: The pass the default selection lives in, and the point label of the recording the plan's §F
#: above-Nyquist case is about (``emissions-128``).
E128_PASS = "sparse-mixer-live-2"
E128_LABEL = "e128"

#: The labels ``PROBE_TARGETS`` names, read from the module rather than re-spelled here.
PROBE_LABELS = frozenset(label for label, _hz in PROBE_TARGETS)


@lru_cache(maxsize=1)
def _committed_decoding() -> Any:
    """The default pass decoded once, read-only, through the notebook's own ``decode_pass``."""
    ref = pass_by_name(E128_PASS)
    return decode_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)


def _e128_leaves() -> dict[str, Any]:
    """The real E128 recording's primary-comparison view, as the notebook's cells receive it.

    Fresh each call (the cells' ``leaves`` are mutated as results are merged), but only the cheap
    view/statistics work repeats: the pass is decoded once and cached above.
    """
    decoding = _committed_decoding()
    point = decoding.by_label(E128_LABEL)
    view = primary_view(
        point, window_s=decoding.window_s, support_mm=decoding.support_mm
    )
    stats = gate_statistics(view)
    position = int(np.asarray(stats.depths_mm).size) // 2
    return {
        "sparse_view": view,
        "sparse_view_error": "",
        "point": point,
        "gate_stats": stats,
        "position": position,
        "position_note": "",
        "detrending_picker": _Widget(Detrending.MEAN),
        "gate_picker": _Widget(position),
        "dataset_picker": _Widget(E128_PASS),
        "psd_zoom_max_hz": _Widget(0.0),
    }


def _run_spectral_chain(leaves: dict[str, Any]) -> dict[str, Any]:
    """Run the estimate cell, then the target-support cell, merging what each defines."""
    _output, defs = _run_cell(
        _require_notebook_cell("periodogram_of_view"), dict(leaves)
    )
    leaves.update(defs)
    _output, defs = _run_cell(
        _require_notebook_cell("target_frequency_support"), dict(leaves)
    )
    leaves.update(defs)
    return leaves


# ======================================================================================
# static contract — §N items 1, 2, 6, 7 and the rendering guards §K/§L
# ======================================================================================


def test_the_notebook_imports_the_periodogram_backend_and_calls_it() -> None:
    """§N(1): the notebook imports and calls ``periodogram_of_view`` — nothing else computes it."""
    assert "periodogram_of_view" in _imports_from("sparse_periodogram"), (
        "the notebook must import `periodogram_of_view` from `analysis.sparse_periodogram`"
    )
    assert _cells_calling("periodogram_of_view"), (
        "no cell calls `periodogram_of_view`: the spectrum would have no backend behind it"
    )


def test_the_periodogram_call_names_its_view_depth_quantity_unit_and_detrending() -> (
    None
):
    """§B: the call is explicit — the same depth resolution SA1 uses, and the measured quantity.

    ``quantity`` and ``unit`` must be *read* (an attribute of the selected point), not literal
    defaults, so the spectrum names what it measured instead of trusting the signature. The
    detrending must come from the control, not from a constant.
    """
    calls = _calls_to("periodogram_of_view")
    assert calls, "no call to `periodogram_of_view` in the notebook"
    for call in calls:
        keywords = {keyword.arg for keyword in call.keywords if keyword.arg}
        assert {"depth_mm", "quantity", "unit", "detrending"} <= keywords, (
            f"the periodogram call {ast.unparse(call)[:120]!r} must name depth_mm, quantity, "
            "unit and detrending explicitly (§B)"
        )
        for name in ("quantity", "unit"):
            argument = next(k.value for k in call.keywords if k.arg == name)
            assert not isinstance(argument, ast.Constant), (
                f"`{name}` must be read from the selected point, not passed as a constant"
            )
            attributes = {
                child.attr
                for child in ast.walk(argument)
                if isinstance(child, ast.Attribute)
            }
            assert name in attributes, (
                f"`{name}` must be read off the selected point (as `point.{name}`, optionally "
                f"wrapped), got {ast.unparse(argument)!r}"
            )
        detrending = next(k.value for k in call.keywords if k.arg == "detrending")
        assert not isinstance(detrending, ast.Constant), (
            "`detrending` must come from the detrending control, not a hard-coded value (§C)"
        )


def test_the_notebook_carries_no_spectral_arithmetic_of_its_own() -> None:
    """§N(2), the stage's spine: no FFT, no taper construction, no PSD normalization in a cell."""
    offenders: dict[str, list[str]] = {}
    for node in ast.walk(_tree()):
        seen: set[str] = set()
        if isinstance(node, ast.Name):
            seen.add(node.id)
        elif isinstance(node, ast.Attribute):
            seen.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            seen.update(alias.name for alias in node.names)
        hit = seen & FORBIDDEN_SPECTRAL_NAMES
        if hit:
            offenders.setdefault(ast.unparse(node)[:80], sorted(hit))
    assert not offenders, (
        "the notebook must draw only what the backend returns; it may not construct a taper, "
        f"transform or normalize a density itself. Found: {offenders}"
    )


def test_the_notebook_keeps_one_view_checkpoint_and_no_second_window_selector() -> None:
    """§A: ``sparse_view`` is the input; SA2.3 adds no independent spectral time-window selector."""
    constructors = _cells_calling(*VIEW_CONSTRUCTORS)
    assert len(constructors) == 1, (
        "exactly one cell may decide *which block of samples to ask for*; found "
        f"{constructors} calling the view constructors"
    )
    periodogram_cells = _cells_calling("periodogram_of_view")
    assert periodogram_cells, "no cell calls `periodogram_of_view`"
    for name in periodogram_cells:
        assert "sparse_view" in _referenced_names(_function_nodes()[name]), (
            f"cell {name!r} must take its samples from the shared `sparse_view`, not cut its own"
        )


def test_target_rows_are_asked_of_the_backend_with_their_own_label() -> None:
    """§F: every target row is a ``target_frequency_support`` question, labelled, not re-derived."""
    assert "target_frequency_support" in _imports_from("sparse_target_support"), (
        "the notebook must import `target_frequency_support` from `analysis.sparse_target_support`"
    )
    calls = _calls_to("target_frequency_support")
    assert calls, "no cell asks `target_frequency_support` for its rows"
    for call in calls:
        keywords = {keyword.arg for keyword in call.keywords if keyword.arg}
        assert "label" in keywords, (
            f"the target question {ast.unparse(call)[:120]!r} must carry its own label (§F)"
        )


def test_the_target_marker_loop_is_guarded_by_the_backends_supported_field() -> None:
    """§G: a target marker is drawn *only* inside the measurable band — the guard is structural.

    The behavioural marker-count tests below fail if the guard is removed; this says where the
    guard must be, so it cannot be moved to a place the data never reaches. Every ``add_vline`` the
    figure cell draws must sit directly under an ``if`` that tests the backend's own
    ``TargetFrequencySupport.supported`` — the same field the caption promises to have used — and
    not ``band_supported`` or a locally re-derived condition.
    """
    marker_cells = [
        name
        for name in _cells_calling("add_vline")
        if "target_support_rows" in _referenced_names(_function_nodes()[name])
    ]
    assert len(marker_cells) == 1, (
        f"exactly one cell may draw the target markers, found {marker_cells}"
    )
    node = _function_nodes()[marker_cells[0]]

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(node):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    vlines = [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and getattr(call.func, "attr", None) == "add_vline"
    ]
    assert vlines, f"cell {marker_cells[0]!r} draws no target marker at all"
    for call in vlines:
        guard = parents.get(call)
        while guard is not None and not isinstance(guard, ast.If):
            guard = parents.get(guard)
        assert isinstance(guard, ast.If), (
            f"`{ast.unparse(call)[:80]!r}` must sit inside a conditional, or a refused target is "
            "drawn inside the PSD axes (§G)"
        )
        tested = {
            child.attr
            for child in ast.walk(guard.test)
            if isinstance(child, ast.Attribute)
        }
        assert "supported" in tested, (
            "the marker guard must test the backend's own `supported` field (§G), found "
            f"`{ast.unparse(guard.test)!r}`"
        )


def test_the_forbidden_name_guard_is_narrow_and_leaves_benign_array_operations_alone() -> (
    None
):
    """§N(2), kept honest: the guard flags a copied transform, not an honest read of an array.

    ``FORBIDDEN_SPECTRAL_NAMES`` is matched by exact name, deliberately. Widening it with names
    the notebook legitimately uses — ``mean``, ``asarray``, ``sum``, ``abs`` and the like — would
    forbid the display arithmetic a rendering cell is allowed to do (reading a backend array,
    indexing a stored column) instead of the re-implementation the stage forbids. This test pins
    that boundary so the guard cannot be "strengthened" into a name-only false positive.
    """
    benign = frozenset(
        {
            "mean",
            "sum",
            "abs",
            "cos",
            "sin",
            "sqrt",
            "array",
            "asarray",
            "arange",
            "zeros",
            "ones",
            "max",
            "min",
            "size",
            "shape",
            "reshape",
            "clip",
            "isfinite",
            "nan",
            "where",
            "diff",
            "column_stack",
        }
    )
    overlap = sorted(benign & FORBIDDEN_SPECTRAL_NAMES)
    assert not overlap, (
        "the forbidden-name guard must not swallow benign array operations; it now matches "
        f"{overlap}, which would forbid an honest read of a backend array (§N(2))"
    )
    assert {
        "fft",
        "rfft",
        "hann",
        "welch",
        "periodogram",
        "taper",
    } <= FORBIDDEN_SPECTRAL_NAMES, (
        "the guard must still catch a copied transform, taper or density estimator (§N(2))"
    )


def test_the_notebook_reads_the_verdict_and_the_admission_it_must_render() -> None:
    """§K: refusal rendering needs the verdict vocabulary and the admission's own statement."""
    referenced = set()
    for node in ast.walk(_tree()):
        referenced |= _referenced_names(node)
    assert "SpectralVerdict" in referenced, (
        "the notebook must branch on the estimator's verdict, or a refused axis cannot be kept "
        "distinct from a measured zero (§K)"
    )
    assert "admission" in referenced, (
        "a refused axis is rendered from its `SpectralAdmission` and its failed conditions (§K)"
    )


def test_every_displayed_spectrum_makes_its_provenance_recoverable() -> None:
    """§L: job, point/order, source path and digest, view, gate/depth, quantity, detrending, taper."""
    referenced = set()
    for node in ast.walk(_tree()):
        referenced |= _referenced_names(node)
    missing = sorted(PROVENANCE_FIELDS - referenced)
    assert not missing, (
        "a displayed spectrum must make every one of these recoverable, each read from the object "
        f"that owns it (§L); the notebook never reads: {missing}"
    )


def test_the_stale_gate_guard_still_holds_for_the_spectral_consumers() -> None:
    """§K: the note resolves a gate the new view dropped — and the spectrum obeys it.

    No consumer may index with the raw widget: it may read past the end after a view change. The
    spectral cells therefore resolve their depth through ``position`` and show ``position_note``
    beside the result rather than silently drawing a spectrum for a different gate.
    """
    refs = _cell_refs()
    defines = {name: set(cell.defs) for name, cell in _cells().items()}
    picker_cells = {name for name, defs in defines.items() if "gate_picker" in defs}
    note_cells = {name for name, defs in defines.items() if "position_note" in defs}
    allowed = picker_cells | note_cells

    readers = {name for name, names in refs.items() if "gate_picker" in names}
    stray = sorted(readers - allowed)
    assert not stray, (
        "only the gate picker cell and the guard cell may read `gate_picker` directly, or a "
        f"consumer indexes past the end of the current view (§K); offending cells: {stray}"
    )

    spectral = set(_cells_calling("periodogram_of_view", "target_frequency_support"))
    assert spectral, "no spectral cell found to check"
    for name in _cells_calling("periodogram_of_view"):
        assert "position" in refs[name], (
            f"cell {name!r} must resolve its depth through the guarded `position`, not a raw "
            "index — the cell computing the spectrum is where the fallback gate is obeyed (§K)"
        )
    spectral_and_plot = spectral | set(_cells_referencing("psd", "frequency_hz"))
    note_shown = any("position_note" in refs[name] for name in spectral_and_plot)
    assert note_shown, (
        "the note that says a fallback gate is shown must sit beside the spectrum it applies to "
        "(§K), not only beside SA1's trace"
    )


# ======================================================================================
# behavioural wiring — the cells executed with a synthetic view
# ======================================================================================


def test_the_spectral_cell_returns_the_backends_estimate_of_the_selected_view() -> None:
    """§A/§L/§B: one ``WindowView``, one spectrum — cut from the view that was selected.

    The estimate must carry the view's own identity (job, point, order, path, digest, view), the
    quantity and unit the selected point reports (not the signature defaults), and the gate depth
    the statistics result reports at the guarded position.
    """
    cell_name = _require_notebook_cell("periodogram_of_view")
    view = _synthetic_view()
    leaves = _spectral_leaves(view)
    _output, defs = _run_cell(cell_name, leaves)

    estimates = _estimates_in(defs)
    assert len(estimates) == 1, (
        f"cell {cell_name!r} must produce exactly one SpectralEstimate, got {len(estimates)}"
    )
    estimate = estimates[0]

    assert estimate.verdict is SpectralVerdict.DEFINED, estimate.message
    assert estimate.provenance.job == view.job
    assert estimate.provenance.point_label == view.point_label
    assert estimate.provenance.order == view.order
    assert estimate.provenance.relative_path == view.relative_path
    assert estimate.provenance.source_sha256 == view.source_sha256
    assert estimate.view == view.view.value, (
        "the spectrum must carry the view it was cut from"
    )
    # §B: the measured quantity is the selected point's, not the signature default
    assert estimate.quantity == _Point.quantity
    assert estimate.unit == _Point.unit
    # §B: the same depth resolution SA1 performs
    stats = leaves["gate_stats"]
    assert estimate.depth_mm == pytest.approx(
        float(stats.depths_mm[leaves["position"]])
    )
    assert estimate.gate_index == int(leaves["position"])
    # and it is one spectrum over one view: no second, re-derived sample block
    assert estimate.profiles == view.time_s.size


@pytest.mark.parametrize("detrending", [Detrending.MEAN_AND_LINEAR, Detrending.NONE])
def test_the_picked_detrending_travels_into_the_spectrum(
    detrending: Detrending,
) -> None:
    """§C: the control is the source of the detrending, and the result states which one ran."""
    cell_name = _require_notebook_cell("periodogram_of_view")
    leaves = _spectral_leaves(_synthetic_view(), detrending=detrending)
    _output, defs = _run_cell(cell_name, leaves)

    estimates = _estimates_in(defs)
    assert estimates, f"cell {cell_name!r} produced no SpectralEstimate"
    assert estimates[0].detrending is detrending, (
        "the spectrum must carry the detrending the control selected, not a remembered value"
    )


def test_switching_the_view_moves_the_spectral_provenance_and_the_axes() -> None:
    """§M: primary-comparison and full-record are never interchanged under one label.

    The two synthetic views differ only in label, span and profile count; the spectra must differ
    in exactly those, so a full-record spectrum cannot be shown under the primary label.
    """
    cell_name = _require_notebook_cell("periodogram_of_view")
    primary = _synthetic_view(view=SparseView.PRIMARY, profiles=138, dt_s=0.02)
    full = _synthetic_view(view=SparseView.FULL_RECORD, profiles=200, dt_s=0.02)

    _out_p, defs_p = _run_cell(cell_name, _spectral_leaves(primary))
    _out_f, defs_f = _run_cell(cell_name, _spectral_leaves(full))

    estimates_p = _estimates_in(defs_p)
    estimates_f = _estimates_in(defs_f)
    assert estimates_p and estimates_f, "both view switches must produce a spectrum"
    first, second = estimates_p[0], estimates_f[0]
    assert first.view == SparseView.PRIMARY.value
    assert second.view == SparseView.FULL_RECORD.value
    assert first.profiles != second.profiles
    assert first.span_s != second.span_s
    assert first.provenance.source_sha256 == second.provenance.source_sha256, (
        "one recording, two views: the source digest must not move with the cut"
    )


def test_target_rows_carry_the_backends_own_above_nyquist_refusal() -> None:
    """§F/§N(4): the rotor reference above a coarse axis's Nyquist is refused by the backend.

    The cell is run against a view whose adopted Nyquist sits below 8.333 Hz — the E128 situation,
    reproduced on a synthetic axis so no committed recording is decoded. The 1 Hz probe must be
    supported and the rotor probe refused *with the backend's own reason*, which the UI quotes
    rather than paraphrases; the notebook may draw no rotor marker inside a band that cannot
    contain it (§G).
    """
    cell_name = _require_notebook_cell("target_frequency_support")
    coarse = _synthetic_view(profiles=138, dt_s=0.0872)
    leaves = _spectral_leaves(coarse)

    calls: list[tuple[float, str | None, TargetFrequencySupport]] = []

    def spy(admission: Any, target_hz: float, *, label: str | None = None) -> Any:
        result = target_frequency_support(admission, target_hz, label=label)
        calls.append((float(target_hz), label, result))
        return result

    leaves["target_frequency_support"] = spy
    # the estimate the target cell will read is the one its own sibling cell produces
    est_name = _require_notebook_cell("periodogram_of_view")
    _est_out, est_defs = _run_cell(est_name, dict(leaves))
    leaves.update({name: value for name, value in est_defs.items()})

    _output, _defs = _run_cell(cell_name, leaves)
    assert len(calls) >= 2, (
        f"the target panel must ask at least the 1 Hz and rotor probes, got {[c[0] for c in calls]}"
    )
    rotor = [c for c in calls if abs(c[0] - ROTOR_HZ) < 1e-6]
    low = [c for c in calls if abs(c[0] - RECURRENCE_HZ) < 1e-6]
    assert low, f"no probe at {RECURRENCE_HZ} Hz among {[c[0] for c in calls]}"
    assert rotor, (
        f"no probe at the rotor reference {ROTOR_HZ!r} Hz among {[c[0] for c in calls]}"
    )
    assert low[0][2].supported is True
    assert rotor[0][2].band_supported is False
    assert "Nyquist" in rotor[0][2].reason, (
        "the rotor row must carry the backend's own above-Nyquist reason (§F): "
        f"{rotor[0][2].reason!r}"
    )
    assert all(label for _hz, label, _result in calls), (
        "every target row is asked with its own label, so the panel quotes the design's name "
        f"rather than a formatted frequency (§F): {[c[1] for c in calls]}"
    )


def test_a_refused_axis_is_a_refusal_while_a_constant_is_a_zero_spectrum() -> None:
    """§K, the distinction the stage keeps: *defined zero* versus *undefined/refused*.

    A refused axis must return an explicit refusal — an empty density, an unadmitted admission and
    the conditions it failed — never a fabricated zero line. A constant signal, by contrast, is a
    legitimately defined zero density, and must be returned as a spectrum so it is drawn as zero.
    """
    cell_name = _require_notebook_cell("periodogram_of_view")

    refused_view = _synthetic_view(duplicate_stamp=True)
    _output, defs = _run_cell(cell_name, _spectral_leaves(refused_view))
    refused = _estimates_in(defs)
    assert refused, "the refused axis produced no estimate object at all"
    refusal = refused[0]
    assert refusal.verdict is SpectralVerdict.REFUSED_AXIS, (
        "an axis the estimator refused must be returned as a refusal, not a spectrum"
    )
    assert refusal.psd.size == 0 and refusal.frequency_hz.size == 0, (
        "a refusal carries no density: a zero spectrum would read as a measured zero (§K)"
    )
    assert refusal.admission.admitted is False
    failed = [
        item.condition.value
        for item in refusal.admission.conditions
        if item.satisfied is False
    ]
    assert failed, (
        "the refusal must name the conditions it failed, so the UI can render them"
    )

    constant_view = _synthetic_view(trace="constant")
    _output, defs = _run_cell(cell_name, _spectral_leaves(constant_view))
    zero = _estimates_in(defs)
    assert zero, "the constant trace produced no estimate object"
    defined = zero[0]
    assert defined.verdict is SpectralVerdict.DEFINED, (
        "a constant trace is a well-defined zero spectrum, not an estimator refusal (§K)"
    )
    assert float(np.max(np.abs(defined.psd))) <= 1e-24, (
        "its density must be zero everywhere"
    )


# ======================================================================================
# rendering the executed result — the display cells, §K/§L/§F/§G
# ======================================================================================


@pytest.mark.parametrize("real_recording", [False, True], ids=["synthetic", "e128"])
def test_the_readout_renders_the_provenance_timebase_and_admission_it_carries(
    real_recording: bool,
) -> None:
    """§L/§D: every field a displayed spectrum must make recoverable is *shown*, not just held.

    The readout cell is executed and its rendered markdown read back, so a spectrum that carries
    the provenance but never displays it fails here. Every asserted string is a field of the
    returned ``SpectralEstimate`` (or the ``ViewProvenance`` / ``SpectralAdmission`` it carries) —
    the readout is not allowed to paraphrase a value into existence. Run once on the synthetic
    view and once on the real committed E128 recording.
    """
    leaves = _e128_leaves() if real_recording else _spectral_leaves(_synthetic_view())
    leaves = _run_spectral_chain(leaves)
    estimate = _estimates_in(leaves)[0]

    cell = _rendering_cell("spectral_estimate", "spectral_error", "gate_stats")
    capture, _output, _defs = _render(cell, leaves)
    text = capture.rendered

    prov = estimate.provenance
    for shown in (
        prov.job,
        prov.point_label,
        str(prov.order),
        prov.relative_path,
        prov.source_sha256,
        prov.view.value,
        prov.view_rule,
    ):
        assert shown in text, (
            f"cell {cell!r} must display the provenance field {shown!r} it was handed (§L)"
        )
    assert f"{estimate.depth_mm:.3f}" in text, "the gate depth must be shown (§L)"
    for shown in (estimate.quantity, estimate.unit, estimate.psd_unit):
        assert shown in text, (
            f"the measured quantity/unit {shown!r} must be shown (§B/§L)"
        )
    for shown in (
        estimate.detrending.value,
        estimate.estimator_name,
        estimate.taper_name,
        estimate.taper_convention,
        estimate.normalization_rule,
        estimate.one_sided_rule,
        estimate.admission.reason,
        estimate.verdict.value,
        f"{estimate.admission.spectral_uniformity_tol:g}",
    ):
        assert shown in text, (
            f"the result field {shown!r} must be displayed from the object that owns it (§L)"
        )
    for shown in (
        estimate.span_s,
        estimate.dt_eff_s,
        estimate.effective_sample_rate_hz,
        estimate.nyquist_hz,
        estimate.delta_f_hz,
    ):
        assert f"{shown:.6g}" in text, (
            f"the timebase quantity {shown!r} must be shown from the characterization (§D)"
        )
    assert f"**{estimate.profiles}**" in text, "the profile count N must be shown (§D)"
    assert "not presented as one" in text or "not a `ViewProvenance` field" in text, (
        "the pass is the notebook's selection and must be shown as such, never as a provenance "
        "field of the spectrum (§L)"
    )


def test_the_real_committed_e128_view_admits_the_estimator_and_refuses_the_rotor_target() -> (
    None
):
    """§F/§N(8): the real committed E128 recording — not a synthetic stand-in — is the case.

    E128's primary-comparison Nyquist sits below the 8.333-Hz rotor reference while the estimator
    is still admitted for the axis: the rotor row is refused by the *band* condition only, and the
    1 Hz probe is supported. The view is decoded read-only through the notebook's own loader, so
    the Nyquist here is the committed recording's, not an axis built in this file.
    """
    leaves = _run_spectral_chain(_e128_leaves())
    estimate = _estimates_in(leaves)[0]
    assert "emissions-128" in estimate.provenance.relative_path, (
        "this test is about the committed emissions-128 recording, not a synthetic axis"
    )
    assert estimate.verdict is SpectralVerdict.DEFINED, estimate.message
    assert estimate.admission.admitted is True, (
        "E128's axis passes the spectral admission; only the rotor target is refused"
    )
    assert estimate.nyquist_hz == pytest.approx(5.734, abs=0.01), (
        f"E128's own adopted Nyquist must be ≈5.73 Hz, got {estimate.nyquist_hz!r}"
    )
    assert estimate.nyquist_hz < ROTOR_HZ

    rows = {row.target_label: row for row in leaves["target_support_rows"]}
    assert set(rows) == set(PROBE_LABELS), sorted(rows)
    assert rows["recurrence-1hz"].supported is True
    rotor = rows["rotor-8.333hz"]
    assert rotor.supported is False
    assert rotor.band_supported is False
    assert rotor.analysis_supported is True, (
        "the estimator is admitted for E128, so the rotor row is a band refusal, not an "
        "estimator inability"
    )
    assert "Nyquist" in rotor.reason


def test_the_real_e128_figure_draws_only_the_supported_target_marker() -> None:
    """§G/§N(8): on the committed E128 axis exactly the 1 Hz marker is drawn, never 8.333 Hz.

    The backend reports the rotor target unsupported above this axis's Nyquist and the figure must
    draw **no** 8.333-Hz line inside the PSD axes. Removing the ``supported`` guard in the marker
    loop adds that line, so this count is what bites when the guard is dropped.
    """
    leaves = _run_spectral_chain(_e128_leaves())
    cell = _rendering_cell("target_support_rows", "psd_zoom_max_hz")
    capture, _output, _defs = _render(cell, leaves)

    assert len(capture.figures) == 1, (
        f"the admitted E128 axis must be drawn by cell {cell!r} (§K)"
    )
    markers = _marker_positions(capture.figures[0])
    assert len(markers) == 1, (
        "exactly the 1 Hz marker may be drawn on the committed E128 axis; a second marker means "
        f"the rotor target was drawn despite the backend refusing it (§G): {markers}"
    )
    assert markers[0] == pytest.approx(RECURRENCE_HZ)
    assert all(abs(x - ROTOR_HZ) > 1e-6 for x in markers), (
        "the refused 8.333-Hz target must not appear inside the PSD axes (§G)"
    )


def test_the_target_readout_quotes_the_backends_own_reason_for_the_real_e128_row() -> (
    None
):
    """§F wording rule: the rendered panel carries the backend's reason verbatim, not a paraphrase.

    For E128 the 8.333-Hz row is refused *at or above this axis's Nyquist*; the panel must quote
    ``band_reason`` and ``analysis_reason`` exactly and must not turn the refusal into a claim about
    the flow (``unsupported at 8.333 Hz`` ⇏ ``no 8.333-Hz signal``).
    """
    leaves = _run_spectral_chain(_e128_leaves())
    rows = {row.target_label: row for row in leaves["target_support_rows"]}
    rotor = rows["rotor-8.333hz"]

    cell = _rendering_cell("target_support_rows", "target_support_error")
    capture, _output, _defs = _render(cell, leaves)
    text = capture.rendered
    # The cell interpolates its per-row detail lines as a single f-string, so the reason appears
    # inside a Python list repr and its apostrophes are backslash-escaped. The words are still the
    # backend's; unescape the repr before demanding the quote be verbatim (see the note in the
    # report on the cell's list-repr rendering).
    verbatim = text.replace("\\'", "'").replace('\\"', '"')

    assert rotor.band_reason in verbatim, (
        f"cell {cell!r} must quote the backend's band reason verbatim (§F)"
    )
    assert rotor.analysis_reason in verbatim, (
        "the analysis reason must be quoted verbatim too (§F)"
    )
    assert "8.33333 Hz is at or above this axis" in verbatim, (
        "the backend's own wording must survive into the rendered row (§F)"
    )
    assert rotor.reason in verbatim
    assert "unsupported" in text, "the refused row must read as unsupported"
    assert rows["recurrence-1hz"].reason in verbatim, (
        "the supported 1 Hz row must be shown too"
    )


def test_the_stale_gate_note_is_rendered_beside_the_spectrum_it_applies_to() -> None:
    """§K: the fallback-gate note is *shown* next to the spectrum, not merely computed (§L note).

    The readout and the figure both receive ``position_note``; each must display it beside its own
    result, so a reader never sees a spectrum for a fallback gate without being told.
    """
    note = (
        "the gate position selected before this view change (99) is not in this view, which has "
        "3 supported gate(s): the middle one is shown"
    )
    for cell in (
        _rendering_cell("spectral_estimate", "spectral_error", "gate_stats"),
        _rendering_cell("target_support_rows", "psd_zoom_max_hz"),
    ):
        leaves = _run_spectral_chain(_spectral_leaves(_synthetic_view()))
        leaves["position_note"] = note
        capture, _output, _defs = _render(cell, leaves)
        assert note in capture.rendered, (
            f"cell {cell!r} must show the stale-gate note beside the spectrum it applies to (§K)"
        )


def test_a_refused_axis_is_rendered_as_its_refusal_with_no_plot_at_all() -> None:
    """§K: a refused axis draws **no plot** — not an empty line and not a zero line.

    The figure cell is executed against a synthetic refused axis: it must draw no figure at all and
    must state the refusal from the admission — its reason and the conditions it failed — rather
    than a fabricated zero spectrum. The readout must say the same and publish no density.
    """
    leaves = _run_spectral_chain(
        _spectral_leaves(_synthetic_view(duplicate_stamp=True))
    )
    refusal = _estimates_in(leaves)[0]
    assert refusal.verdict is SpectralVerdict.REFUSED_AXIS, (
        "this test needs a refused axis, not a defined spectrum"
    )
    assert refusal.psd.size == 0 and refusal.frequency_hz.size == 0

    figure_cell = _rendering_cell("target_support_rows", "psd_zoom_max_hz")
    capture, _output, _defs = _render(figure_cell, leaves)
    assert capture.figures == [], (
        f"cell {figure_cell!r} must draw no plot for a refused axis — a zero line is a "
        "measurement that was not made (§K)"
    )
    text = capture.rendered
    assert "Spectrum refused" in text, (
        "the figure cell must state the refusal, not the fallback 'no PSD is drawn' line"
    )
    assert refusal.verdict.value in text
    assert refusal.admission.reason in text
    failed = [item for item in refusal.admission.conditions if item.satisfied is False]
    assert failed, "the refusal must name the conditions it failed"
    for item in failed:
        assert item.condition.value in text, (
            "the failed condition must be named in the refusal"
        )
        assert item.rule in text, "the rule the condition failed must be quoted"

    readout_cell = _rendering_cell("spectral_estimate", "spectral_error", "gate_stats")
    readout_capture, _output, _defs = _render(readout_cell, leaves)
    readout_text = readout_capture.rendered
    assert refusal.verdict.value in readout_text
    assert "No density is published" in readout_text, (
        "the readout must state that a refused axis carries no density"
    )


def test_a_constant_signal_is_rendered_as_a_zero_spectrum_not_a_refusal() -> None:
    """§K, the other half: a constant trace is a *defined zero* spectrum and is drawn as zero.

    The figure cell is executed against a constant trace: it must draw the spectrum (so the zero is
    shown as a measured zero), with both in-band targets marked, and must not be worded as a
    refusal. The drawn density must be zero everywhere, matching the estimate it came from.
    """
    leaves = _run_spectral_chain(_spectral_leaves(_synthetic_view(trace="constant")))
    defined = _estimates_in(leaves)[0]
    assert defined.verdict is SpectralVerdict.DEFINED, (
        "a constant is a well-defined zero spectrum, not an estimator refusal"
    )

    cell = _rendering_cell("target_support_rows", "psd_zoom_max_hz")
    capture, _output, _defs = _render(cell, leaves)
    assert len(capture.figures) == 1, (
        f"a defined zero spectrum is a measurement and must be drawn by cell {cell!r} (§K)"
    )
    figure = capture.figures[0]
    psd_traces = [trace for trace in figure.data if str(trace.name).startswith("PSD")]
    assert len(psd_traces) == 1, "the figure must carry the backend's PSD as one trace"
    drawn = np.asarray(psd_traces[0].y, dtype=float)
    assert drawn.size == defined.psd.size
    assert float(np.max(np.abs(drawn))) <= 1e-24, (
        "the drawn density must be zero everywhere — the zero spectrum, shown as zero"
    )
    assert "Spectrum refused" not in capture.rendered, (
        "a defined zero must not be worded as an estimator refusal — the branch is on the verdict "
        "(§K)"
    )
    assert f"verdict `{defined.verdict.value}`" in str(figure.layout.title.text), (
        "the drawn figure must name the verdict it was drawn under"
    )
    assert len(_marker_positions(figure)) == len(PROBE_LABELS), (
        "both probe targets are inside this fine synthetic axis's band, so both markers are drawn"
    )


# ======================================================================================
# the notebook is a program marimo itself accepts
# ======================================================================================


def test_marimo_check_accepts_the_notebook() -> None:
    """The notebook must at least parse and satisfy marimo's own static checks (§N)."""
    result = subprocess.run(
        [sys.executable, "-m", "marimo", "check", "--strict", str(NOTEBOOK)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        "`marimo check --strict` failed:\n"
        + (result.stdout or "")
        + (result.stderr or "")
    )
