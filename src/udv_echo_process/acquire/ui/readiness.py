"""Whether the application can be driven at all: its top-level error state, read once and refused everywhere.

A message box is a **top-level** window of class ``#32770``, not a child of the main form, so every census this package
owns — the overlay guard, ``EnumChildWindows``, the layout fingerprint — walks past it. Measured 2026-10-26: a Delphi
access violation sat in front of the application for an hour while every menu call reported ``executed: 0`` after its
full timeout, three diagnoses were chased, and the guard had no way to say *the application is showing an error*. While
such a box is up the box's own modal loop filters the messages this route acts with, so nothing can succeed and a retry
only spends a live slot.

The first guard lived in the sweep runner alone (``9b481d0``: ``Win32Actuator.application_error`` read by
``SweepRunner._overlay_guard``), which left a single point, a preflight and a bridge cycle free to act past the same
box. This module is the one home for both halves, so the answer cannot differ by caller:

- :func:`application_error_text` — the **reader**. It asks the owning process of the application's own window, scans
  top-level windows, and classifies **only the target's**. Another process's box is not this application's error, and a
  target window that is not an error surface is not read at all. A caption it cannot read is not a clear screen: the box
  is reported with a truthful fallback sentence, and a window it cannot identify at all is raised rather than skipped.
- :func:`application_error_refusal` — the **guard**, one optional-capability check with three answers: no capability (a
  legacy or pure double — not an error state), a caption (a refusal, in these words), or an unusable answer (a named
  refusal, because ``None`` is the only answer that claims a clear screen).

It imports nothing from this package, touches no platform API of its own — the enumerator and the process
module are handed to it, exactly as :mod:`udv_echo_process.acquire.ui.combo` takes the reads and selects it
drives — so both halves are exercised on any host against injected Windows APIs. That is what the tests do, and
they assert the exact handles and process ids asked rather than a caption a fake was scripted to give.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, cast

#: The window class of every message box on this platform (the ``#32770`` dialog class).
ERROR_BOX_CLASS = "#32770"

#: What a reader says when the application's own window cannot be shown to be the target's.
_NO_TARGET = (
    "the application's window {window:#x} reports no owning process, so a top-level error box "
    "of the target cannot be told from any other process's"
)

#: What a caption says when the box is there and its text is not readable — never ``""``.
UNREADABLE_BOX = (
    "an error box the application is showing whose text could not be read "
    f"(window class {ERROR_BOX_CLASS})"
)

#: The one refusal sentence for a box that *is* readable. One wording for every caller, because
#: the operator reads it in the runner's log, in a live command's error and in a bridge refusal
#: alike, and three copies would drift apart.
ERROR_SHOWING = (
    "the application is showing an error and cannot be driven: {text} - it faulted, and while "
    "that box is up the application's modal loop filters the posted messages this driver acts "
    "with; restart the application"
)

#: The refusal for a state that could not be read at all — a raised read, an unusable capability.
#: The detail is carried verbatim: a caller must be able to see the cause, not a summary of it.
ERROR_UNREADABLE = "the application's error state could not be read ({detail}), so its state is not known"

#: The four *details* a refusal can carry, named on their own because one of them has to be
#: re-stated by a forwarding boundary: a wrapper that is asked for the capability must refuse in
#: the same words the guard would use if the inner half were asked directly, and two copies of a
#: sentence drift. Each names what was wrong, because "no error" and "a check that answered
#: nothing" are opposite findings.
DETAIL_NOT_CALLABLE = "the application_error capability is not callable: {kind}"
DETAIL_EMPTY_ANSWER = (
    "the check answered an empty string, and an empty answer states no screen"
)
DETAIL_MALFORMED_ANSWER = "the check answered {kind}, which is not a clear screen"
DETAIL_RAISED = "{kind}: {message}"
DETAIL_DECLARATION_UNREADABLE = (
    "the application_error declaration could not be read: {error!r}"
)

#: The three ways an *offered* capability is unusable rather than clear.
ERROR_NOT_CALLABLE = ERROR_UNREADABLE.format(detail=DETAIL_NOT_CALLABLE)
ERROR_EMPTY_ANSWER = ERROR_UNREADABLE.format(detail=DETAIL_EMPTY_ANSWER)
ERROR_MALFORMED_ANSWER = ERROR_UNREADABLE.format(detail=DETAIL_MALFORMED_ANSWER)


#: Sentinel for "the attribute is not declared anywhere on this object".
_MISSING = object()


def application_error_offered(source: object) -> bool:
    """Whether ``source`` *offers* ``application_error`` — even one that cannot be read.

    ``inspect.getattr_static`` walks the instance dictionary and the type's MRO and returns the raw
    attribute, so a declared ``property`` is found *without being read*, while a name that only
    arrives through ``__getattr__`` is reported as not declared. That distinction is the whole
    reason this exists: a declaration that raises ``AttributeError`` when read is a capability that
    could not be read, while a name nobody declares is simply absent — and the two must not
    collapse into one answer.

    It is public because it is asked in two places, and only these two: by the guard below, and by
    ``acquire.bridge.BridgeActuator``'s own forwarding boundary, which must tell a legacy inner
    half (absent — no refusal, unchanged) from an offered capability it cannot read (re-raised, so
    the guard refuses). A wrapper with nothing but ``__getattr__`` declares nothing, which is how
    the second case used to reach a runner looking exactly like the first.
    """
    try:
        return (
            inspect.getattr_static(source, "application_error", _MISSING)
            is not _MISSING
        )
    except Exception:  # noqa: BLE001 - an object that cannot be inspected declares nothing usable
        return False


class ErrorStateUnreadable(RuntimeError):
    """The top-level state of the target process could not be established.

    Raised — never answered as ``None`` — when a top-level window cannot be identified, so it
    cannot be shown not to be an error box of the application. A window that no longer exists is
    *not* this exception: it is not showing anything, and it is skipped.
    """


def _read(read: Callable[[int], str], hwnd: int) -> str:
    """One caption read, as text — a read that fails answers nothing, and never raises here.

    A caption is *detail* in both callers: a box whose own text cannot be read is still a box, and
    the refusal is already the answer. What must not happen is an exception from reading a caption
    hiding the fact that the application is showing one.
    """
    try:
        return str(read(hwnd) or "")
    except Exception:  # noqa: BLE001 - an unreadable caption is detail, not the finding
        return ""


def _still_there(gui: Any, hwnd: int) -> bool:
    """Whether ``hwnd`` still names a window; an unanswerable existence check is not "gone"."""
    try:
        return bool(gui.IsWindow(hwnd))
    except Exception:  # noqa: BLE001 - "could not tell" must not read as "does not exist"
        return True


def _caption_of(hwnd: int, *, gui: Any, read_text: Callable[[int], str]) -> str:
    """The box's own words: the snapshot, else the query boundary, else its children's labels.

    ``GetWindowText`` returns ``""`` for nearly every widget in this application — the repository's
    oldest reading lesson — so the caller's own message-level read (``WM_GETTEXT``) is asked
    *before* the box is called unreadable. Only when all of it is empty does the fallback sentence
    stand, because a box with no readable text is still a box.
    """
    caption = _read(gui.GetWindowText, hwnd) or _read(read_text, hwnd)
    labels: list[str] = [caption] if caption.strip() else []

    def take(child: int, _param: object) -> bool:
        label = (_read(gui.GetWindowText, child) or _read(read_text, child)).strip()
        if label and label not in labels:
            labels.append(label)
        return True

    try:
        gui.EnumChildWindows(hwnd, take, None)
    except Exception:  # noqa: BLE001, S110 - the box is already refused; children are detail
        pass
    text = " / ".join(label for label in labels if label.strip())
    return text or UNREADABLE_BOX


def application_error_text(
    *,
    gui: Any,
    process: Any,
    window: int,
    read_text: Callable[[int], str],
) -> str | None:
    """The text of a top-level error box **the target process** is showing, or ``None``.

    ``window`` is any window the target owns — in practice its main form — and the process id is
    read from it, so "this application's error" is a fact about the target rather than about
    whatever happens to be in front of it. Then, per top-level window:

    - its owning process is read first, and **only the target's windows are classified at all** —
      another application's error box is not this application's refusal (the earlier reader asked
      every window for its class, and took the first ``#32770`` it found);
    - a target window that is not of the error-box class is not read any further, so no caption is
      asked of a panel that is not an error surface;
    - a target error box that is not visible is not showing anything and is skipped;
    - a target error box that *is* visible is returned with its caption, or with
      :data:`UNREADABLE_BOX` when no text could be read anywhere in it.

    Raises :class:`ErrorStateUnreadable` — never returns ``None`` — when the scan itself failed or
    a window could not be identified: "clear" has to be established, not assumed. A window that
    vanished mid-scan is skipped instead (:func:`_still_there`), because a handle that no longer
    exists cannot be showing a box.
    """
    api = process
    _thread, target_pid = api.GetWindowThreadProcessId(window)
    if not target_pid:
        raise ErrorStateUnreadable(_NO_TARGET.format(window=window))

    handles: list[int] = []

    def collect(hwnd: int, _param: object) -> bool:
        handles.append(hwnd)
        return True

    # Not wrapped: an enumeration that failed is a state nobody read, and the caller must say so.
    gui.EnumWindows(collect, None)

    unreadable: list[str] = []
    for hwnd in handles:
        try:
            _t, owner = api.GetWindowThreadProcessId(hwnd)
        except Exception as exc:  # noqa: BLE001 - reported below, unless the window is gone
            if _still_there(gui, hwnd):
                unreadable.append(f"window {hwnd:#x}: {type(exc).__name__}: {exc}")
            continue
        if owner != target_pid:
            continue
        try:
            class_name = gui.GetClassName(hwnd)
        except Exception as exc:  # noqa: BLE001 - a target window nobody can classify
            unreadable.append(f"window {hwnd:#x}: {type(exc).__name__}: {exc}")
            continue
        if class_name != ERROR_BOX_CLASS:
            continue
        try:
            visible = gui.IsWindowVisible(hwnd)
        except Exception as exc:  # noqa: BLE001 - a box that cannot be shown not to be up
            unreadable.append(f"window {hwnd:#x}: {type(exc).__name__}: {exc}")
            continue
        if not visible:
            continue
        return _caption_of(hwnd, gui=gui, read_text=read_text)

    if unreadable:
        raise ErrorStateUnreadable(
            "the application's top-level state could not be established: "
            + "; ".join(unreadable)
        )
    return None


def resolve_application_error(source: object) -> Callable[[], object] | None:
    """The ``application_error`` capability ``source`` offers, or ``None`` when it offers **none**.

    "Offers none" is the absence case and nothing else: the name is not declared anywhere on
    ``source`` (:func:`application_error_offered`), so a legacy or pure double is unchanged. When
    the name *is* offered, the lookup's own answer is returned — including a value that is not
    callable, which the caller classifies rather than this function guessing. The one answer never
    returned is ``None`` from a successful lookup, which the guard reserves for a clear screen: see
    the paragraph below.

    Raises :class:`ErrorStateUnreadable` whose message is the **detail** sentence a refusal embeds
    (:data:`ERROR_UNREADABLE`'s inner clause) when the offered name cannot be read at all, and when
    the lookup *succeeds* with ``None`` — a declared ``None`` is an offered capability that cannot be
    called, not the absence above, because ``None`` is the guard's own word for a clear screen. That
    is what lets a forwarding boundary re-raise it unchanged: the guard then says the same thing
    about a wrapper that it says about the inner half, instead of the failure collapsing into absence.
    """
    offered = application_error_offered(source)
    try:
        resolved = source.application_error  # type: ignore[attr-defined]
    except AttributeError as exc:  # no capability, unless the declaration itself failed
        if offered:
            raise ErrorStateUnreadable(
                DETAIL_DECLARATION_UNREADABLE.format(error=exc)
            ) from exc
        return None
    except Exception as exc:  # a capability that cannot even be resolved is the detail
        raise ErrorStateUnreadable(
            DETAIL_RAISED.format(kind=type(exc).__name__, message=exc)
        ) from exc
    if resolved is None:
        # The lookup *succeeded* and answered ``None`` — an offered capability that cannot be
        # called, which is not the absence above. It is raised rather than returned because
        # ``None`` is the guard's own word for a clear screen: a declared ``None`` must not be
        # credited as one, and the detail sentence is what both callers already embed once.
        raise ErrorStateUnreadable(DETAIL_NOT_CALLABLE.format(kind="NoneType"))
    return cast("Callable[[], object]", resolved)


def application_error_refusal(source: object) -> str | None:
    """Why no step may be taken while the application is showing an error; ``None`` when it is not.

    ``source`` is anything that may carry the capability: a sweep actuator, the live facade
    itself, a bridge wrapper (which delegates it to its inner half), or a recording surface. The
    check is **optional**, so a legacy or pure double is not a refusal:

    - **no capability** — ``None``. Not an error state, and never an error about the absence.
      "Absent" means *not declared* — see :func:`application_error_offered` and
      :func:`resolve_application_error`, which keep a declared ``property`` that raises
      ``AttributeError`` from being read as a missing capability.
    - **a caption** — a refusal in :data:`ERROR_SHOWING`, carrying the box's own words.
    - **unusable** — the name is there and is not callable, the lookup or the call raised, or it
      answered something that is neither ``None`` nor a non-blank caption. Each is a named refusal
      (:data:`ERROR_NOT_CALLABLE`, :data:`ERROR_UNREADABLE`, :data:`ERROR_EMPTY_ANSWER`,
      :data:`ERROR_MALFORMED_ANSWER`), because ``None`` is the only answer that claims a clear
      screen and a broken check must not be read as one.

    ``source`` is asked, not its type: a wrapper that declares the capability and forwards it
    (``acquire.bridge.BridgeActuator`` does) answers with the half that owns it, so a caller
    guarding the wrapper cannot skip the capability underneath — and a wrapper whose inner half
    cannot be read refuses here instead of looking like a double without the feature.
    """
    try:
        check = resolve_application_error(source)
    except ErrorStateUnreadable as exc:
        # Already a detail sentence, so it is embedded once rather than prefixed with a second one.
        return ERROR_UNREADABLE.format(detail=str(exc))
    if check is None:
        return None
    if not callable(check):
        return ERROR_NOT_CALLABLE.format(kind=type(check).__name__)
    try:
        answer = check()
    except ErrorStateUnreadable as exc:
        # A forwarding boundary raises the detail sentence it could not resolve, so it is embedded
        # once — the same words a direct reader gets, not a sentence wrapped around a sentence.
        return ERROR_UNREADABLE.format(detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - an unread state is not a clean one
        return ERROR_UNREADABLE.format(
            detail=DETAIL_RAISED.format(kind=type(exc).__name__, message=exc)
        )
    if answer is None:
        return None
    if isinstance(answer, str):
        text = answer.strip()
        return ERROR_SHOWING.format(text=text) if text else ERROR_EMPTY_ANSWER
    return ERROR_MALFORMED_ANSWER.format(kind=f"{type(answer).__name__}: {answer!r}")
