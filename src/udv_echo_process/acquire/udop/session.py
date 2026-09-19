"""The compatibility name of the facade: ``udop.session`` re-exports ``acquire.driver``.

The facade's code — ``class Win32Actuator(ParametersSurface, RecordingSurface, StoreSurface)``,
the class's own methods, and the module-level names it publishes — lives in
:mod:`udv_echo_process.acquire.driver`, and that is deliberate: ``acquire.driver`` is the module
this repository's callers import from (``runner.py``, ``live.py``, ``tools/live/``) and the module
every fake in it scripts the window layer through
(``monkeypatch.setattr(driver, "_gui", fake)``), so the class bodies have to read *its* globals.

Patch 4 had it the other way round: the code sat here and ``acquire/driver.py`` published *this*
module under its own name with ``sys.modules[__name__] = session``. That worked, and it was runtime
module surgery — ``import udv_echo_process.acquire.driver`` handed back a module whose ``__name__``
is ``udv_echo_process.acquire.udop.session``, whose ``__file__`` is this file, and which tracebacks
pointed at; the module a reader opened was not the module that ran.

What is left here is the *name*, for the callers and the architecture table that already write it
(``docs/dop3000/acquisition-architecture.md`` §5): the facade's published surface, re-exported name
for name from ``udv_echo_process.acquire.driver``. ``from udv_echo_process.acquire.udop.session
import Win32Actuator`` therefore resolves to the facade's own class — the same object
``driver.Win32Actuator`` is — and ``session.AcquisitionError``, ``session._gui``,
``session._CursorPoint`` and the rest are the same objects ``driver.<name>`` are too
(``tests/test_acquire_udop.py`` pins that identity and the surface).

Two things this module deliberately does **not** do. It does not import ``driver`` at any other
point or in the other direction — ``acquire/driver.py`` never imports this module, the surfaces
never import it either, and ``udop/__init__.py`` does not import it eagerly, so no import cycle
exists. And nothing should *patch* through it: a name rebound on this module is a name on a copy,
so the module-graph correction's other half is that a test which shortens a workflow timing knob
patches the surface whose loop reads it — ``udop.parameters`` for the dialog fill, the popup's
wait and cadence, the entry-dialog wait and the dialog replacement, ``udop.recording`` for the
overlay settle and the poll cadence.
"""

from __future__ import annotations

from udv_echo_process.acquire.driver import *  # the facade's published surface, name for name
from udv_echo_process.acquire.driver import __all__ as _facade_all

#: ``driver.__all__``, name for name: this module publishes the facade's surface and nothing of
#: its own, so the two ``__all__``\\ s cannot drift apart.
__all__ = list(_facade_all)
