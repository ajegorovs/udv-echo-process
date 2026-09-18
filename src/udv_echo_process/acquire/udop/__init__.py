"""The UDOP workflow surfaces — the only layer that combines observations with actions.

Patch 4 splits the live workflows out of the flat ``acquire/driver.py`` by surface, all of them
**moved verbatim**:

- ``parameters.py`` — the ``Parameters`` popup and the ``Operating parameters`` dialog
  composition: the menubar anchor's real-cursor hover, the popup's entry, the dialog an entry
  opened, the dialog table read, and the measurement channel's selection and read-back;
- ``recording.py`` — the strip lifecycle: the state read, the held press, the guarded view waits,
  the overlay answering and recovery, and the record/stop/store cycle;
- ``store.py`` — the Store dialog: the name, the working directory, the accept and the stored
  file;
- ``session.py`` — the facade: the one live class this package publishes
  (:class:`~udv_echo_process.acquire.udop.session.Win32Actuator`), composed out of one piece per
  surface. ``acquire.driver`` is that same module, so no caller moves.

**No workflow is proven here.** Every moved gesture stays *device-pending*
(``docs/dop3000/device-verification.md``): a workflow that was paid for with a live slot is moved,
never re-derived — and a move is not a verification. The cloud-only validation contract
(``docs/dop3000/acquisition-architecture.md`` §8) is what bounds what this package may claim.

This module holds the one type the four surfaces share: :class:`AcquisitionError`, the failure a
cycle raises when nothing was stored under the point's name. It is defined in the package's own
namespace so that no surface has to import a sibling to raise it, and ``acquire.driver``
re-exports it — so ``driver.AcquisitionError`` is the object it always was, and
``acquire.win32._acquisition_error()``, which resolves the class from the facade inside the raise,
resolves it unchanged.
"""

from __future__ import annotations

__all__ = ["AcquisitionError"]


class AcquisitionError(RuntimeError):
    """The cycle could not be completed; nothing was stored under this point's name."""
