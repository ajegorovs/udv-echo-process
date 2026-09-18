"""The lazy Win32 handles and the two ctypes structs they read and write.

Patch 3 moves the Win32 mechanics out of :mod:`udv_echo_process.acquire.driver` in three
commits; this file is the first of them, because the transport that lands with it needs the
handles: :func:`_gui` (``win32gui``/``win32con``) and :func:`_user32`
(``ctypes.windll.user32`` with the message *and* cursor signatures bound: one function,
moved whole rather than split, so a 64-bit ``lParam`` is still not truncated). Both are
**lazily resolved inside the function**, so importing this module — and every module in this
package — runs no ``windll`` load and no user32 call at all, and works on a host with no
Windows and no ``pywin32``.

The cursor, the clip and the foreground precondition land in this file's second commit; they
are absent here rather than half-written.
"""

from __future__ import annotations

import ctypes
from functools import lru_cache

__all__ = [
    "_ClipRect",
    "_CursorPoint",
    "_gui",
    "_user32",
]

class _CursorPoint(ctypes.Structure):
    """``POINT`` for ``GetCursorPos``/``SetCursorPos``.

    Declared here rather than imported from ``ctypes.wintypes``: that module is not
    importable on a host without Windows headers, and this module has to import
    cleanly anywhere (the ``ctypes`` description is portable).
    """

    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _ClipRect(ctypes.Structure):
    """``RECT`` for ``GetClipCursor`` — the rectangle the cursor is confined to.

    An empty rectangle (``right <= left`` or ``bottom <= top``) is *no clip*: on a
    desktop that is not clipped ``GetClipCursor`` answers the screen rectangle, which
    contains every point the driver ever asks for. Declared here rather than imported
    from ``ctypes.wintypes`` for the same reason as :class:`_CursorPoint`.
    """

    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@lru_cache(maxsize=1)
def _gui():
    """``(win32gui, win32con)`` — loaded inside a function so the module imports anywhere."""
    import win32con
    import win32gui

    return win32gui, win32con


@lru_cache(maxsize=1)
def _user32():
    """``user32`` with its message and cursor signatures bound once.

    ``ctypes.windll`` only exists on Windows, so it is touched here — never at import
    time — and the argument types are declared so a 64-bit ``lParam`` (a buffer address)
    is not truncated.
    """
    u32 = ctypes.windll.user32  # type: ignore[attr-defined]
    u32.SendMessageTimeoutW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_size_t),
    )
    u32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    u32.PostMessageW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_size_t,
    )
    u32.PostMessageW.restype = ctypes.c_ssize_t
    # The real-cursor gesture the menubar needs (``SetCursorPos`` + ``mouse_event``,
    # with the read-back that proves the jump took). ``mouse_event``'s ``dwExtraInfo``
    # is a ``ULONG_PTR``, so ``c_size_t``; its restype is ``None``.
    u32.GetCursorPos.argtypes = (ctypes.POINTER(_CursorPoint),)
    u32.GetCursorPos.restype = ctypes.c_int
    u32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    u32.SetCursorPos.restype = ctypes.c_int
    u32.mouse_event.argtypes = (
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_size_t,
    )
    u32.mouse_event.restype = None
    # The cursor *clip*: this application confines the pointer while its blocking popups
    # are up (docs/dop3000/udop-automation.md §6), and ``SetCursorPos`` to a point outside
    # that rectangle is silently clamped to the clip's edge — which is what parked a live
    # run's cursor in the open menu's bottom-left corner. ``ClipCursor(NULL)`` releases
    # the clip, so it is declared with a void pointer (only ``None`` is ever passed).
    u32.GetClipCursor.argtypes = (ctypes.POINTER(_ClipRect),)
    u32.GetClipCursor.restype = ctypes.c_int
    u32.ClipCursor.argtypes = (ctypes.c_void_p,)
    u32.ClipCursor.restype = ctypes.c_int
    return u32


