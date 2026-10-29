"""Composing an existing menu dispatch, because menus are not this integration's to rebuild.

`live.bridge_actuator` reads ``module.dispatch`` **before** it asks for ``guarded_cycle`` and hands it
to :class:`~udv_echo_process.acquire.bridge.BridgeMenu`, which is what lets a channel verification
open the Parameters dialog without a hover. With no ``dispatch`` on the configured module the driver
falls back to hovering — a foreground gesture — even when the cycle is a working routine cycle. So a
host that exports only ``guarded_cycle`` is **not** background-usable, and this module exists so the
proven menu dispatch can be reused instead of re-derived:

    from bridge_host.api import activation_report, guarded_cycle
    from bridge_host.menu import legacy_dispatch

    dispatch = legacy_dispatch("<explicit path to the proven menu dispatch module>")

That three-line module is the composition the run points ``--bridge-runner`` at. Nothing is
reimplemented: the legacy module's own callable is returned unchanged, and the path stays
machine-local because this function only ever receives it as an argument.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping
from pathlib import Path

from bridge_host.contract import HostRefusal

__all__ = ["MENU_DISPATCH_EXPORT", "legacy_dispatch"]

#: The export name `live.bridge_actuator` looks for on the configured module.
MENU_DISPATCH_EXPORT = "dispatch"


def legacy_dispatch(
    module_path: str | Path, *, export: str = MENU_DISPATCH_EXPORT
) -> Callable[[object], Mapping]:
    """Load a menu dispatch from an explicit path and return its callable unchanged.

    A path that does not exist, a module that cannot be executed, and a module with no callable
    ``dispatch`` are three different findings, so each is refused by its own name rather than being
    reported as "no menu support".
    """
    location = Path(module_path)
    if not location.is_file():
        raise HostRefusal(f"host_menu_dispatch_missing:{location}")
    spec = importlib.util.spec_from_file_location("udv_bridge_menu_dispatch", location)
    if spec is None or spec.loader is None:
        raise HostRefusal(f"host_menu_dispatch_unloadable:{location.name}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - a module that will not load is a refusal
        raise HostRefusal(
            f"host_menu_dispatch_unloadable:{type(exc).__name__}"
        ) from None
    candidate = getattr(module, export, None)
    if not callable(candidate):
        raise HostRefusal(f"host_menu_dispatch_invalid:{export}")
    return candidate
