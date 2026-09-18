"""The Win32 mechanics: the transport, the cursor, and the control tree.

Layer 3 of the target layering (``docs/dop3000/acquisition-architecture.md`` §5) — the part of
:mod:`udv_echo_process.acquire.driver` that needs a live window, moved out of it verbatim by
Patch 3. The layer above it decides *what* to do; nothing here decides anything:

| module | what it is | status |
|---|---|---|
| ``win32/messages.py`` | ``SendMessageTimeoutW`` and the posted gestures: the bounded send, the held click, the text commit, the combo select and the combo read-back | landed by Patch 3 |
| ``win32/cursor.py`` | the foreground checks, the real cursor move and restore, ``ClipCursor`` — and the package's one lazy ``win32gui``/``ctypes.windll`` resolution | landed by Patch 3 |
| ``win32/tree.py`` | enumerating the main window and its children, their visibility, and the normalization onto ``acquire/ui/model``'s node type | landed by Patch 3 |

Three rules the package exists to enforce, all three quoted from the architecture document:

- **No DOP experiment policy here** (§5): nothing in this package knows a UDOP parameter, the
  strip's views or roles, the ``Operating parameters`` dialog's fields, a campaign or a store
  path. It imports no ``campaign``/``runner``/``verify``, and its one ``acquire/ui`` import is
  ``tree.ui_nodes`` — the *node type*, no rule (:mod:`udv_echo_process.acquire.win32.tree`);
- **the platform boundary is this package** (§5, §7): ``ctypes.windll``, ``win32gui`` and
  ``win32con`` are touched nowhere else in the project's importable code, and only *inside
  functions* — so ``import udv_echo_process.acquire`` still works on a machine with no Windows
  and no ``pywin32``, and importing this package runs no ``windll`` load, no ``FindWindow`` and
  no other ``user32`` call;
- **mechanics take their transport as a parameter** (this patch): every function that needs the
  desktop takes the ``gui``/``user32``/``post``/``send`` it uses as a keyword-only argument that
  defaults to this package's own laziness. ``driver.py`` hands over its own names, which is what
  keeps every existing caller and test working unchanged — including the repository's fakes,
  which have always scripted the window layer by monkeypatching ``driver._gui`` /
  ``driver._user32`` / ``driver._post``.

:mod:`udv_echo_process.acquire.driver` imports every name in these modules back into its own
namespace, so ``driver._send``, ``driver._CursorPoint``, ``driver._main_hwnd`` and the rest of
the flat module's surface still resolve (``docs/dop3000/acquisition-architecture.md`` §5,
*compatibility first*).

The mechanisms themselves — what commits a value, in which order, and which failure modes
silently invalidate a point — have one authoritative copy in
``docs/dop3000/udop-automation.md`` and are linked, never restated here.
"""

from __future__ import annotations

__all__ = ["cursor", "messages", "tree"]


def _acquisition_error() -> type[RuntimeError]:
    """The facade's own ``AcquisitionError``, resolved **inside the raise**.

    The class is ``driver``'s public failure type (``cli.py`` and ``tools/live/**`` catch
    ``driver.AcquisitionError``) and the facade imports this package, so a module-level import
    of it here would be a cycle. Asking for it where it is raised costs one lookup on the
    failure path, keeps the class the *same* object a caller already catches, and leaves this
    package importable on its own — importing ``acquire.win32`` never imports ``acquire.driver``.
    """
    from udv_echo_process.acquire.driver import AcquisitionError

    return AcquisitionError
