"""Tests locking in the public package surface.

The top-level ``__all__`` and the ``analysis``/``parser`` module surfaces
must stay consistent with what each module actually defines, so a rename or
a dropped export is caught here (import-time test over the whole surface).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import udv_echo_process
from udv_echo_process import analysis, parser, viz

ROOT = Path(__file__).resolve().parent.parent
SINGLE_RAW = ROOT / "data/echo/650.ADD"


def _importable(mod: object, name: str) -> bool:
    return hasattr(mod, name)


def test_top_level_all_imports_clean() -> None:
    for name in udv_echo_process.__all__:
        assert _importable(udv_echo_process, name), f"missing top-level export: {name}"


def test_top_level_mirrors_analysis_and_parser_surfaces() -> None:
    """Ported features exported by analysis/ and every parser public name
    should be reachable from the package root (top-level mirrors the
    subpackages)."""
    for name in analysis.__all__:
        assert name in udv_echo_process.__all__, (
            f"analysis export not at top level: {name}"
        )
    for name in parser.__all__:
        assert name in udv_echo_process.__all__, (
            f"parser export not at top level: {name}"
        )


def test_parser_all_declared_and_existing() -> None:
    for name in parser.__all__:
        assert _importable(parser, name), f"missing parser export: {name}"


def test_analysis_all_declared_and_existing() -> None:
    for name in analysis.__all__:
        assert _importable(analysis, name), f"missing analysis export: {name}"


def test_viz_surface() -> None:
    """viz's plot functions plus the promoted discovery helper are public."""
    for name in (
        "plot_recording",
        "plot_channel_stats",
        "plot_all",
        "discover_data_files",
    ):
        assert _importable(viz, name), f"missing viz export: {name}"
    # The old private name is gone.
    assert not hasattr(viz, "_discover_data_files")


def test_retired_legacy_surfaces_are_gone() -> None:
    """Phase 9 removed the pre-rework models and bundled specs — no alias lingers.

    The legacy ``ChannelSeries``/``MultiplexedMeasurement`` stack, the mutable
    ``Model`` base / ``shape_2d`` helper and the bundled ``FilterParams`` /
    ``InterpParams`` bags were removed (not adapted) in the ground-up rework;
    nothing may re-export them from the package root or the models layer.
    """
    from udv_echo_process import models as models_module

    for name in (
        "ChannelSeries",
        "MultiplexedMeasurement",
        "Model",
        "shape_2d",
    ):
        assert not hasattr(udv_echo_process, name), f"stale top-level export: {name}"
        assert not hasattr(models_module, name), f"stale models export: {name}"
    for name in ("FilterMethod", "FilterParams", "InterpMethod", "InterpParams"):
        assert not hasattr(udv_echo_process, name), f"stale bundled spec: {name}"


def test_echo_rpm_surface_is_exported() -> None:
    """The artifact-model echo-RPM terminal surface is public everywhere.

    ``EchoRpmEstimate``/``EchoRpmSettings`` are domain models (re-exported by
    ``analysis``) while ``EchoRpmInputError``/``rpm_from_channel`` belong to the
    analysis layer alone, mirroring the states/profiles terminal surfaces.
    """
    from udv_echo_process import analysis as analysis_module
    from udv_echo_process import models as models_module

    for name in ("EchoRpmEstimate", "EchoRpmSettings"):
        assert name in models_module.__all__, f"missing models export: {name}"
        assert name in analysis_module.__all__, f"missing analysis export: {name}"
        assert name in udv_echo_process.__all__, f"missing top-level export: {name}"
    for name in ("EchoRpmInputError", "rpm_from_channel"):
        assert name in analysis_module.__all__, f"missing analysis export: {name}"
        assert name in udv_echo_process.__all__, f"missing top-level export: {name}"


def test_modules_import_under_udv_echo_process_namespace() -> None:
    """Every module in the package imports cleanly on its own."""
    pkg_dir = Path(importlib.import_module("udv_echo_process").__file__).parent
    for py in pkg_dir.rglob("*.py"):
        if py.name.startswith("_"):
            continue
        rel = py.relative_to(pkg_dir.parent).with_suffix("")
        mod_name = ".".join(rel.parts)
        importlib.import_module(mod_name)


def test_import_all_names_actually_resolve() -> None:
    """``from udv_echo_process import *`` resolves every name in __all__."""
    ns: dict[str, object] = {}
    exec("from udv_echo_process import *", ns)  # noqa: S102 — deliberate surface check
    for name in udv_echo_process.__all__:
        assert name in ns, f"star import missing: {name}"
