"""The pure UI layer: normalized observations, and the interpreters that read them.

This package is Layers 1 and 2 of the target layering
(``docs/dop3000/acquisition-architecture.md`` §5): the *pure* half of what
:mod:`udv_echo_process.acquire.driver` used to mix with Win32 transport. Nothing here sends a
message, moves a cursor, enumerates a window, or treats a handle as a semantic identity — an
``hwnd`` appears only as an action reference for the resolve that produced it.

``driver.py`` imports every name below back into its own namespace, so
``from udv_echo_process.acquire.driver import screen_mode`` and ``driver.layout_refusal`` keep
working while the code underneath moves. That compatibility import is the whole reason the
package can be split without touching a call site.

| module | what it is | status |
|---|---|---|
| ``ui/model.py`` | normalized observations — ``Rect``, ``UiNode``/``UiTree``, ``SurfaceKind``, ``ParameterPanelState``, the observation records | landed by Patch 2 |
| ``ui/layout.py`` | the pure surface/layout interpreter moved out of ``driver.py`` | landed by Patch 2 |
| ``ui/strip.py`` | pure strip observation and classification — the row, the state, and the ambiguous four-button row that binds nothing (ledger B10) | landed by Patch 2 (widget slice) |
| ``ui/dialog.py`` | the ``Operating parameters`` table binding, the widget-aware extraction (a combo's own value, never the edit beside it — ledger B09) and the channel comparison (ledger B17) | landed by Patch 2 (widget slice) |
| ``ui/menu.py`` | the ``Parameters`` anchor and its expected popup, and nothing generic — no name is assigned to a menubar button by position (ledger B03) | landed by Patch 2 (widget slice) |

Two rules the package exists to enforce, both quoted from the architecture document:

- **OBSERVE → INTERPRET → ACT**: a live gesture never decides what surface it is acting on, so
  the module that presses must not be the module that classifies (§3, invariant 1);
- **a refusal is a first-class outcome**: an unrecognised surface ends the workflow with a named
  reason, and no absence is promoted to an observation (invariant 2).

The evidence levels used in these docstrings are the ones the document defines: *cloud-verified*
(a committed fixture or a test in this repository proves it), *live-reported* (a device
observation is recorded but cannot be reproduced here) and *device-pending* (nothing here may
claim it — see ``docs/dop3000/device-verification.md``).
"""

from __future__ import annotations

__all__ = ["dialog", "layout", "menu", "model", "strip"]
