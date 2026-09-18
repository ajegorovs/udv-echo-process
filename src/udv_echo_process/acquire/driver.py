"""The compatibility name of the facade: ``acquire.driver`` **is** ``udop/session.py``.

Since Patch 2 this module has been where a caller imports ``Win32Actuator`` from, and every fake in
this repository scripts the window layer by patching ``driver._gui``, ``driver._user32`` and
``driver._post`` — the very names the facade's own method bodies read. Patch 4 moved the live
workflows, and the facade with them, into :mod:`udv_echo_process.acquire.udop`, and a module that
merely *re-exported* the facade would hand those callers a **copy** of every name: the class would
read ``udop.session._gui``, a patch on ``driver._gui`` would silently stop reaching the body it was
written for, and the same is true of the re-exported timing knobs
(``monkeypatch.setattr(driver, "_MENU_POLL_S", 0.0)``).

So this module publishes the facade under its own name instead: after the import below,
``sys.modules['udv_echo_process.acquire.driver']`` **is**
:mod:`udv_echo_process.acquire.udop.session` — the same module object, with the same ``__all__``,
the same globals and the same names. Nothing else lives here, nothing imports this module for a
side effect, and ``from udv_echo_process.acquire.driver import Win32Actuator`` /
``AcquisitionError`` / ``screen_mode`` / ``_CursorPoint`` / ``WM_LBUTTONDOWN`` resolves exactly as
it did at Patch 3's tip (``docs/dop3000/acquisition-architecture.md`` §5, *compatibility first*;
``tests/test_acquire_udop.py`` pins the identity and the re-exported surface). The platform boundary
is unchanged: importing this module imports no ``ctypes.windll`` and no ``win32gui``.
"""

from __future__ import annotations

import sys

from udv_echo_process.acquire.udop import session as _session

#: ``acquire.driver`` is the facade module itself, not a copy of its names. The facade's bodies —
#: and every subclass of ``Win32Actuator`` — read ``_session``'s globals, so a patch on either name
#: has to be a patch on the same object; that is the whole reason this module is not a re-export
#: shell. ``acquire.win32._acquisition_error()``, which resolves the failure class from this module
#: inside the raise, gets the same class object the facade raises.
sys.modules[__name__] = _session
