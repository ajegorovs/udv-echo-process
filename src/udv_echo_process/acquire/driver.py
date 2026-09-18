"""Drive the running UDOP application over Win32 messages: the live actuator.

This is the Windows half of :mod:`udv_echo_process.acquire` — the implementation that
satisfies :class:`~udv_echo_process.acquire.actuator.Actuator`. Everything here is a
*port* of three verified reference scripts, not a redesign: ``recon/udop_roles.py``
(resolving controls by class + position — never by control id, because ids change on
every launch: 43/43 classes at the same positions, 1/43 ids in common — and never by a
screen coordinate stated in logic), ``recon/40_sweep_depth100.py`` (the cycle:
``set_text_commit``, ``click_hold``, ``strip_view``, ``wait_view``, ``overlay_guard``,
``overwrite_warning``, ``record_stop_store``, ``get_text``, ``children_of``) and
``recon/41_burst_sampling_volume.py`` (the menubar: the popup opens on a **real-cursor
hover** — ``SetCursorPos`` onto the button's centre plus one ``mouse_event`` move, the
gesture that recipe opened this menu with — and its entries are ordered by their screen
``top`` before one is chosen — enumeration order is not screen order).

Three properties are load-bearing, each paid for once in the lab:

1. **Every send is bounded** (``SendMessageTimeoutW`` + ``SMTO_ABORTIFHUNG``): a plain
   ``SendMessage`` to a busy target thread blocks the caller indefinitely. Key and
   command events are *posted*.
2. **A strip press is held** (:data:`…actuator.PRESS_HOLD_MS`) and **a numeric write is
   committed** with the key event — ``WM_SETTEXT`` alone changes the control's text
   while the application keeps its own value.
3. **An overlay is checked before every press** (posted clicks ignore modality), and
   nothing here ``WM_CLOSE``\\ s a popup: an open popup is reported through
   :meth:`Win32Actuator.layout_note` and the run refuses to start instead.

``ctypes.windll`` and ``win32gui``/``win32con`` are touched **only inside functions** —
:func:`~udv_echo_process.acquire.win32.cursor._user32` and ``_gui``, in ``acquire/win32/cursor.py``
as of Patch 3 — so this module and that package both import cleanly on any host.
``pywinauto``, ``watchdog`` and ``PIL`` are not dependencies of this file.

Two further rules are enforced inside the cycle, both of them about *not measuring
something other than the point*:

4. **The measurement channel is verified once per run, before the first recording is
   spent** (:meth:`Win32Actuator.ensure_channel`) — a different channel's block decodes as a
   valid point that is not this point (docs/16 §12), and the guard costs a modal dialog. Every
   stored file is then checked against the run's channel by the decode, which *refuses* a file
   carrying no data for the channel it is asked for, so a per-point dialog proved nothing the
   file does not prove.
   It is one knob (:class:`~udv_echo_process.acquire.config.ChannelSetting`); the
   driver selects it in ``Parameters → Operating parameters`` and reads the
   selection back **from the dialog** — index *and* text — then re-opens the
   dialog to confirm the application kept it. A wrong channel produces a file
   that decodes as a valid point and is not the point (docs/16 §12, the channel
   trap), so a selection that cannot be verified fails the point instead.
5. **The Store dialog's ``Working directory`` is asserted, never assumed**
   (:meth:`Win32Actuator._ensure_working_directory`). The field decides where the
   point lands; if it differs from the directory the caller expects, it is written
   and read back, and an unresolved mismatch fails the point naming both paths.
   Watching a folder the application is not writing to surfaces as a false
   "no file appeared" failure (docs/16 §12b).

The menubar is the one step posted messages cannot drive at all: this application's
menubar ignores them (a posted move opened nothing, and neither did a posted press held
for :data:`…actuator.PRESS_HOLD_MS` — two live runs, both aborted safely with nothing
pressed), while the same button opened its menu under the operator's real cursor in
``recon/41_burst_sampling_volume.py``. That gesture moves the cursor, so it is gated:
``allow_real_input=False`` refuses the menubar step **by name** for an unattended or
locked-desktop run and never falls back to a posted message (which is known not to open
this menu).

The other property every real-cursor gesture has to survive is that **this application
clips the cursor while its blocking popups are up** (``ClipCursor``; the Store dialog
clips the pointer to its own rect, docs/dop3000/udop-automation.md §6). A ``SetCursorPos``
to a point outside the clip rectangle is **silently clamped to the clip's edge**, and the
live run that motivated this is exactly that: the operator's cursor was restored into the
open menu's clip and landed in the menu's bottom-left corner, and the *next* attempt's
hover of the menubar button at ``(204, 40)`` — outside the menu's rect — could not be
placed at all. An unhandled clip is therefore a **systemic** hazard for every real-cursor
move in this driver, not a one-off, so:

* every real move reads the clip with ``GetClipCursor`` first and, when the target lies
  outside a non-empty clip, releases it with ``ClipCursor(NULL)`` before moving
  (:meth:`Win32Actuator._move_real_cursor`);
* a move that still does not take is released and retried once, and a move that fails
  with a clip up is raised **naming the clip rectangle and the target point** — never as
  a locked desktop, which is a different failure with a different remedy;
* the operator's cursor is restored *through* the same rule
  (:meth:`Win32Actuator._restore_cursor`): a clip that does not contain the operator's own
  position is released before the restore, so a restore can never be trapped inside a
  popup's rectangle — which is what put the live run's cursor in the menu's corner.

The popup that hover opens is read **structurally**, because no control in this
application carries a caption: ``GetWindowText`` answers an empty string for every
``TSp_*`` widget — the live read of the open menu shows its overlay panel and its three
entries all caption-less — so an entry can never be found by a title. Matching one was
the live bug. Instead:

* the **overlay** is the panel that became visible when the menubar was hovered (the
  panel set is snapshotted first; the reference's own predicate, ``left == 169 and
  h > 120`` on the panel it read live at ``(169, 55, 401, 250)``, is the fallback when
  that diff is ambiguous);
* the **entries** are the ``TSp_Button`` widgets lying inside that overlay, ordered by
  screen ``top`` — enumeration order is *not* screen order — and the first is
  ``Operating parameters`` (measured tops 61, 95, 130, 165, 205);
* the **entry is taken with a posted held press on the entry's own handle**
  (:meth:`Win32Actuator._press_entry` — ``WM_LBUTTONDOWN`` with ``MK_LBUTTON``, the
  recipe's hold, ``WM_LBUTTONUP``): the gesture ``recon/41_burst_sampling_volume.py``
  used to open ``Operating parameters``, read its fields, change a combo and accept,
  repeatedly. It is neither a cursor move nor a click, and there is deliberately no
  second gesture — this application's ordinary controls and its popup entries both
  answer posted input, and a re-derived alternative gesture is what the live runs spent
  three fix cycles on. The only step that needs the **real** cursor is the hover that
  opens the menu (:meth:`Win32Actuator._hover_centre`), and it is gated by
  ``allow_real_input``;
* **the overlay must be visible before an entry is pressed.** The popup panel is
  *pre-created* in the control tree with ``IsWindowVisible == False`` and is shown on the
  hover, so **presence is not visibility** — a rule that accepts presence presses
  coordinates into empty screen, which is what the live run did. Every entry press is
  therefore preceded by a visibility check on the overlay *and* on the entry, and a
  panel that is in the tree but hidden is named in the refusal instead of being pressed
  (:meth:`Win32Actuator._require_visible_popup`);
* the **dialog** an entry opened is identified **structurally**
  (:meth:`Win32Actuator._dialog_panels`, the reference's own predicate: a panel that is
  not the parameter column, wider than 400 px, holding input controls of its own or at
  least fifteen direct children or a ``TSp_Browse``). Among dialogs, the operating one is
  the dialog holding the **channel combo**, and a dialog without it is closed with its
  LEFT button before the next entry by screen order is pressed. Its default button is
  never pressed — on the wrong dialog that button is what would commit the wrong dialog's
  values, and the wrong dialog is exactly the one that has not been identified yet.
  Requiring the channel combo as the *dialog* test (rather than as the test that tells
  two dialogs apart) was stricter than the evidence and could reject a correctly opened
  dialog. Every attempt **records what the application actually did**, whether the press
  worked or not: the gesture, whether the overlay was visible, whether the popup closed,
  which panel appeared that was not up before, and that panel's rect and top-level child
  classes (:attr:`Win32Actuator.last_entry_attempt`). "The entry opened no dialog" is not
  a diagnosis; the next live run has to be told what happened instead.

**Where the mechanics live.** The *pure* half moved to :mod:`udv_echo_process.acquire.ui` in
Patch 2 (``ui/model.py``, ``ui/layout.py``, then the widget interpreters ``ui/strip.py``,
``ui/dialog.py`` and ``ui/menu.py``); the **Win32 mechanics** moved in Patch 3 into
:mod:`udv_echo_process.acquire.win32`:
- ``win32/messages.py`` — the bounded send, the posted held click, the text commit, the
  combo select and the combo read-back;
- ``win32/cursor.py`` — the foreground check, the real cursor move and restore,
  ``ClipCursor``, and the package's one lazy ``win32gui``/``ctypes.windll`` resolution
  (the handles landed with the transport, in the first commit of this patch);
- ``win32/tree.py`` — the enumeration of the main window and its children, the visibility
  rule and the ``acquire/ui/model`` node projection.

Every one of those names is imported back at the top of this file, so ``driver.screen_mode``,
``driver.layout_shape_reasons``, ``driver.dialog_value_fields``, ``driver._strip_row``,
``driver.PARAMETERS_MENU``, ``driver._send``, ``driver._CursorPoint``, ``driver._click_hold`` and
the rest keep resolving for every caller and every test written against the flat module
(``docs/dop3000/acquisition-architecture.md`` §5, "compatibility first").

What stays here is what composes a *reading* or a *gesture* out of those mechanics, and this
commit of Patch 4 has just taken the first workflow out of it: the recording surface — the strip
lifecycle and the record/stop/store cycle — is ``acquire/udop/recording.py``'s now, moved
verbatim and composed back into this class as :class:`RecordingSurface`. The Store dialog and the
``Parameters`` interaction follow in the next commits of the slice, and ``udop/session.py`` is
the facade they will all be composed by. Each moved body reaches its collaborators through
``self``, so it is called with this module's **own**
transport names (``_gui``, ``_user32``, ``_post``, and this module's ``_send``) passed in
explicitly, which is what keeps every fake in this repository — each of which scripts the window
layer by patching ``driver._gui`` / ``driver._user32`` / ``driver._post`` — biting at the same
place it always did. The moved workflows are **device-pending**: a move is not a verification
(``docs/dop3000/device-verification.md``, V2/V4/V5/V6).
The two corrections this slice makes are *decisions*, and both refuse earlier than the code they
replace: an unprovable ``Parameters`` anchor publishes no binding at all (so the menubar hover is
unreachable rather than mis-aimed), and an ambiguous strip row refuses before the held press is
posted.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

from udv_echo_process.acquire.actuator import (
    DIALOG_ANCHORS,
    DIALOG_COLUMN_ROWS,
    DIALOG_FIELD_ORDER,
    DIALOG_ONLY_PARAMETERS,
    PARAM_COLUMN_ORDER,
    PRESS_HOLD_MS,
    PROCESS_MODE_PREFIXES,
    STARTABLE_VIEWS,
    STORE_TIMEOUT_S,
    VIEW_TIMEOUT_S,
    Actuator,
    DialogControl,
    DialogField,
    OverlayKind,
    ParamRole,
    PreflightReport,
    ProcessMode,
    ScreenFingerprint,
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    ordered_writes,
    overlay_answer,
    process_mode,
)
from udv_echo_process.acquire.config import (
    MAX_CHANNEL,
    MIN_CHANNEL,
    ChannelSetting,
    ParameterSet,
)
from udv_echo_process.acquire.snapshot import (
    DialogParameters,
    FactSource,
    InstrumentFact,
    InstrumentSnapshot,
    routed,
    unreadable,
)

# The workflow surfaces Patch 4 splits out of this class. ``recording.py`` is the strip lifecycle
# (moved by the first commit of the slice) and is composed into :class:`Win32Actuator` below;
# ``_OVERLAY_SETTLE_S`` and ``_POLL_S`` are its own cadences, re-exported here under the names
# this module published. ``AcquisitionError`` is the ``udop`` package's one failure class now
# (``acquire/udop/__init__.py``, so no surface has to import a sibling to raise it), so it is
# imported here rather than defined below.
from udv_echo_process.acquire.udop import AcquisitionError
from udv_echo_process.acquire.udop.recording import (
    _OVERLAY_SETTLE_S,
    _POLL_S,
    RecordingSurface,
)

# The pure half of this module, moved to ``acquire/ui`` by Patch 2 and imported back here on
# purpose: every name below is still reachable as ``driver.<name>`` for the callers and the
# tests that were written against the flat module — ``docs/dop3000/acquisition-architecture.md``
# §5's *compatibility first* rule. The move changed no caller, and the gesture bodies further
# down this file are byte-identical to the ones the live sessions proved.
from udv_echo_process.acquire.ui.dialog import (
    _DIALOG_INPUT_CLASSES,
    _DIALOG_MIN_CHILDREN,
    _DIALOG_MIN_W,
    DIALOG_COLUMN_GAP,
    _column_bands,
    _contains,
    _is_dialog_panel,
    channel_mismatch,
    dialog_channel_text,
    dialog_refusal,
    dialog_value_fields,
    text_at,
)
from udv_echo_process.acquire.ui.dialog import bottom_row as _bottom_row
from udv_echo_process.acquire.ui.dialog import dialog_fact as _dialog_fact
from udv_echo_process.acquire.ui.dialog import dialog_only_reason as _dialog_only_reason
from udv_echo_process.acquire.ui.layout import (
    _BAND_MARGIN_FRACTION,
    EXPECTED_CONTROL_COUNT,
    EXPECTED_PANEL_COUNT,
    MAIN_CLASS,
    MODE_ASSISTED,
    MODE_MANUAL,
    _client_bottom,
    _client_top,
    _point_in_rect,
    layout_evidence,
    layout_refusal,
    layout_shape_reasons,
    normalized_path,
    observation_of,
    panel_mode,
    parameter_panel_absent_clause,
    process_mode_clause,
    same_directory,
    screen_mode,
)

# The menubar's own interpreter — the ``Parameters`` anchor, its refusal, the popup's entry order
# and signature — and the strip's — the row, the state and the ambiguous-row refusal. Both are
# Patch 2's widget slice, imported under the names this module published so that ``driver._inside``,
# ``driver._entry_buttons``, ``driver._strip_row`` and ``driver.PARAMETERS_MENU`` keep resolving.
from udv_echo_process.acquire.ui.menu import (
    MEASURED_BAR,
    MENU_ORDER,
    PARAMETERS_ENTRY,
    PARAMETERS_MENU,
    _inside,
    anchor_button,
    anchor_clause,
)
from udv_echo_process.acquire.ui.menu import (
    PARAMETERS_POPUP_LEFT as _OVERLAY_LEFT,
)
from udv_echo_process.acquire.ui.menu import (
    PARAMETERS_POPUP_MIN_H as _OVERLAY_MIN_H,
)
from udv_echo_process.acquire.ui.menu import entry_buttons as _entry_buttons
from udv_echo_process.acquire.ui.menu import observation_text as _observation_text
from udv_echo_process.acquire.ui.strip import (
    has_slider,
    strip_state_of,
)
from udv_echo_process.acquire.ui.strip import (
    press_refusal as strip_press_refusal,
)
from udv_echo_process.acquire.ui.strip import (
    strip_row as _strip_row,
)

# The Win32 mechanics — the transport, the cursor and the control tree — moved to
# ``acquire/win32`` by Patch 3 and imported back here on purpose: every name below still
# resolves as ``driver.<name>``, exactly as it did when it was defined in this file, so no
# caller and no test has to change (``docs/dop3000/acquisition-architecture.md`` §5,
# *compatibility first*).
# The facade hands its own transport names (``_gui``, ``_user32``, ``_post``, and this
# module's ``_send``) to every mechanic it calls, so a caller or a test that fakes
# ``driver._gui`` — which is how this repository's fakes have always scripted the window
# layer — is still faking what the mechanic uses. Nothing in ``acquire/win32`` imports this
# module at import time (``win32._acquisition_error`` resolves the failure class inside the
# raise).
from udv_echo_process.acquire.win32.cursor import (
    _CURSOR_SETTLE_S,
    _FOREGROUND_POLL_S,
    _FOREGROUND_WAIT_S,
    _HOVER_MOVE_DX,
    _HOVER_MOVE_DY,
    _HOVER_OPEN_S,
    _HOVER_SETTLE_S,
    MOUSEEVENTF_MOVE,
    _activate_window,
    _clip_rect,
    _ClipRect,
    _cursor_position,
    _CursorPoint,
    _foreground_window,
    _gui,
    _hover_centre,
    _move_real_cursor,
    _release_clip,
    _require_foreground,
    _restore_cursor,
    _thread_of,
    _user32,
)
from udv_echo_process.acquire.win32.messages import (
    _CLICK_SETTLE_S,
    _COMBO_NONE_ABOVE,
    _COMBO_SETTLE_S,
    _COMMIT_RECIPE,
    _TEXT_COMMIT_SETTLE_S,
    _TEXT_SETTLE_S,
    _VK_RETURN_DOWN_LPARAM,
    _VK_RETURN_UP_LPARAM,
    CB_GETCOUNT,
    CB_GETCURSEL,
    CB_GETLBTEXT,
    CB_SETCURSEL,
    CBN_SELCHANGE,
    EN_CHANGE,
    MK_LBUTTON,
    SEND_TIMEOUT_MS,
    SMTO_ABORTIFHUNG,
    VK_RETURN,
    WM_COMMAND,
    WM_GETTEXT,
    WM_KEYDOWN,
    WM_KEYUP,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MOUSEMOVE,
    WM_SETTEXT,
    _click_hold,
    _combo_index,
    _combo_items,
    _combo_select,
    _control_id,
    _get_text,
    _post,
    _send,
    _set_text_commit,
)
from udv_echo_process.acquire.win32.tree import (
    _children_of,
    _descendants_of,
    _hidden_panels,
    _is_visible,
    _main_hwnd,
    _visible_children,
)

__all__ = [
    "CBN_SELCHANGE",
    "CB_GETCOUNT",
    "CB_GETCURSEL",
    "CB_GETLBTEXT",
    "CB_SETCURSEL",
    "DIALOG_ANCHORS",
    "DIALOG_COLUMN_GAP",
    "DIALOG_COLUMN_ROWS",
    "EN_CHANGE",
    "EXPECTED_CONTROL_COUNT",
    "EXPECTED_PANEL_COUNT",
    "MAIN_CLASS",
    "MEASURED_BAR",
    "MENU_ORDER",
    "MK_LBUTTON",
    "MODE_ASSISTED",
    "MODE_MANUAL",
    "MOUSEEVENTF_MOVE",
    "PARAMETERS_ENTRY",
    "PARAMETERS_MENU",
    "SEND_TIMEOUT_MS",
    "SMTO_ABORTIFHUNG",
    "STARTABLE_VIEWS",
    "VK_RETURN",
    "WM_COMMAND",
    "WM_GETTEXT",
    "WM_KEYDOWN",
    "WM_KEYUP",
    "WM_LBUTTONDOWN",
    "WM_LBUTTONUP",
    "WM_MOUSEMOVE",
    "WM_SETTEXT",
    "_BAND_MARGIN_FRACTION",
    "_CLICK_SETTLE_S",
    "_COMBO_NONE_ABOVE",
    "_COMBO_SETTLE_S",
    "_COMMIT_RECIPE",
    "_CURSOR_SETTLE_S",
    "_DIALOG_INPUT_CLASSES",
    "_DIALOG_MIN_CHILDREN",
    "_DIALOG_MIN_W",
    "_FOREGROUND_POLL_S",
    "_FOREGROUND_WAIT_S",
    "_HOVER_MOVE_DX",
    "_HOVER_MOVE_DY",
    "_HOVER_OPEN_S",
    "_HOVER_SETTLE_S",
    "_OVERLAY_SETTLE_S",
    "_POLL_S",
    "_TEXT_COMMIT_SETTLE_S",
    "_TEXT_SETTLE_S",
    "_VK_RETURN_DOWN_LPARAM",
    "_VK_RETURN_UP_LPARAM",
    "AcquisitionError",
    "StripState",
    "Win32Actuator",
    "_ClipRect",
    "_CursorPoint",
    "_activate_window",
    "_bottom_row",
    "_children_of",
    "_click_hold",
    "_client_bottom",
    "_client_top",
    "_clip_rect",
    "_column_bands",
    "_combo_index",
    "_combo_items",
    "_combo_select",
    "_contains",
    "_control_id",
    "_cursor_position",
    "_descendants_of",
    "_dialog_fact",
    "_dialog_only_reason",
    "_entry_buttons",
    "_foreground_window",
    "_get_text",
    "_gui",
    "_hidden_panels",
    "_hover_centre",
    "_inside",
    "_is_dialog_panel",
    "_is_visible",
    "_main_hwnd",
    "_move_real_cursor",
    "_observation_text",
    "_point_in_rect",
    "_post",
    "_release_clip",
    "_require_foreground",
    "_restore_cursor",
    "_send",
    "_set_text_commit",
    "_strip_row",
    "_thread_of",
    "_user32",
    "_visible_children",
    "anchor_button",
    "anchor_clause",
    "channel_items",
    "channel_mismatch",
    "dialog_channel_text",
    "dialog_refusal",
    "dialog_value_fields",
    "has_slider",
    "layout_evidence",
    "layout_refusal",
    "layout_shape_reasons",
    "normalized_path",
    "overlay_answer",
    "panel_mode",
    "process_mode_clause",
    "same_directory",
    "screen_mode",
    "strip_press_refusal",
    "strip_state_of",
    "text_at",
]

#: The left column's combo boxes, top -> bottom.
COMBO_ORDER: tuple[str, ...] = ("Sensitivity", "Emitting power")

# The message vocabulary (``WM_*``/``CB_*``/``CBN_*``/``EN_*``/``MK_*``/``SMTO_*``/
# ``VK_*``), the bounded-send timeout, the write recipe's settles and the
# cursor/foreground settles moved to ``acquire/win32`` in Patch 3 with the bodies that
# send and time them (``win32/messages.py``, ``win32/cursor.py``) and are imported at the
# top of this file under their own names, so ``driver.WM_LBUTTONDOWN``,
# ``driver.SEND_TIMEOUT_MS``, ``driver._HOVER_SETTLE_S`` and the rest keep resolving —
# including the deliberately unused ``WM_MOUSEMOVE`` the tests name to assert that no
# move is ever posted. The constants below stay here: the loops that read them are this
# module's own.
# ``PARAMETERS_MENU``, ``PARAMETERS_ENTRY`` and the popup overlay's own geometry
# (``_OVERLAY_LEFT``/``_OVERLAY_MIN_H``: a caption-less ``TSp_Panel`` at ``(169, 55, 401, 250)``,
# 195 px tall, which is the reference's own predicate ``left == 169 and h > 120`` from
# ``recon/41_burst_sampling_volume.py``) are ``acquire/ui/menu.py``'s as of Patch 2's widget
# slice. They are imported at the top of this file under these same names — the menubar *is*
# the one surface whose binding that module owns — and the popup's signature is named again in
# :meth:`Win32Actuator._poll_parameters_overlay`, where it is applied.


#: How long the dialog is given to state its values before the read gives up on it. Measured:
#: an application that has just started builds the table **empty** the first time it is opened
#: and states it on the next open, so a read that took the first empty answer as the answer would
#: record three unreadable facts on an instrument that states them perfectly well; a read that
#: waited forever would hang a live run on a dialog that is never going to fill. Two seconds is
#: several times the measured fill (the second open states everything immediately).
DIALOG_FILL_TIMEOUT_S = 2.0


#: How many popup entries are tried, and how long one entry's press is given to produce a
#: dialog before the next entry. Both are bounded: a misidentified overlay must never turn
#: the entry loop into a walk across the menubar. The measured overlay holds five entries
#: (screen tops 61, 95, 130, 165, 205) and the first is ``Operating parameters``, so the
#: bound costs nothing in practice — it exists so that a wrong overlay cannot be walked
#: through entry by entry. The dialog window is the reference's own
#: (``while time.time() - t0 < 8: time.sleep(0.5)`` — it polls at :data:`_MENU_POLL_S`), so
#: a slow dialog is never mistaken for no dialog.
_ENTRY_DIALOG_TIMEOUT_S = 8.0
#: How long to let the application replace its parameters dialog after a channel write
#: before reading the channel back from the one that is still up. The reference re-resolved
#: the dialog at the same point (`recon/41`); measured live 2026-09-17 the replacement is
#: already there when the write's own settle (``_COMBO_SETTLE_S``) is over, so this is a
#: ceiling, not a wait.
_DIALOG_REPLACE_S = 2.0
#: How long the popup, the dialog and a selection read-back are given, and the cadence
#: they are polled at — the reference recipe's own numbers (``while time.time() - t0 < 8:
#: time.sleep(0.5)``, ``recon/41_burst_sampling_volume.py``), not a longer window.
_MENU_TIMEOUT_S, _MENU_POLL_S = 8.0, 0.5
#: The gesture a popup entry is taken with, named in the diagnostics the caller reports:
#: the **posted held press** on the entry's own handle — the reference's own gesture
#: (``click_hold(entry_hwnd)``, ``recon/41_burst_sampling_volume.py``), which opened
#: ``Operating parameters``, read its fields, changed a combo and accepted, repeatedly.
#: It is not a cursor move and not a click, and there is no second gesture: a re-derived
#: alternative is what three fix cycles went into.
GESTURE_POSTED_PRESS = "posted held press"
# ``_OVERLAY_SETTLE_S`` and ``_POLL_S`` — the settle after an accepted overlay answer and the
# cadence the polling loops run at — were defined here too. They are
# ``acquire/udop/recording.py``'s as of Patch 4, moved there with the loops that read them (this
# is the surface that answers overlays), and are imported at the top of this file under these same
# names, so ``driver._OVERLAY_SETTLE_S`` and ``driver._POLL_S`` keep resolving.


# ``AcquisitionError`` was defined here. It is the ``udop`` package's as of Patch 4 — the one
# failure class the four workflow surfaces share, defined in ``acquire/udop/__init__.py`` so that
# no surface has to import a sibling to raise it — and it is imported at the top of this file
# under the same name, so ``driver.AcquisitionError`` is the class it always was (and
# ``acquire.win32._acquisition_error()``, which resolves it from the facade inside the raise,
# resolves it unchanged).


# ``_CursorPoint``, ``_ClipRect``, ``_gui`` and ``_user32`` were defined here: the two
# ctypes structs, and the lazy ``win32gui``/``ctypes.windll`` resolution whose
# signatures (including the 64-bit ``lParam``) must not be re-derived. They are
# ``acquire/win32/cursor.py``'s as of Patch 3, imported at the top of this file under
# these same names, so ``driver._CursorPoint`` and ``driver._user32`` keep resolving —
# and are still the names a caller or a test replaces when it scripts the window layer.


# ``_send`` and ``_post`` were defined here: the bounded ``SendMessageTimeoutW`` and
# the posted-message pair every gesture in this file is built from. They are
# ``acquire/win32/messages.py``'s as of Patch 3, imported at the top of this file under
# these same names and handed to the mechanics as a parameter, so ``driver._post`` is
# still the name a caller or a test replaces to watch what is posted.


# ``_visible_children``, ``_is_visible`` and ``_hidden_panels`` were defined here: the
# enumeration with a real area, the single visibility question and the walk that
# *names* what the filter left out (a pre-created panel is evidence, never a target).
# They are ``acquire/win32/tree.py``'s as of Patch 3, imported at the top of this file
# under these same names.


# ``dialog_value_fields``, ``_dialog_only_reason``, ``_dialog_fact``, ``_strip_row`` and
# ``_bottom_row`` were defined here: the dialog's value table, its two fact rules, the strip's own
# row and the dialog's bottom button band. They are pure interpreters over an already-resolved tree
# and moved to ``acquire/ui/dialog.py`` and ``acquire/ui/strip.py`` in Patch 2's widget slice,
# imported at the top of this file under these same names so ``driver.dialog_value_fields`` and
# ``driver._strip_row`` keep resolving for every caller and every test written against the flat
# module (``docs/dop3000/acquisition-architecture.md`` §5, *compatibility first*).


# ------------------------------------------------------------------------ the layout gate

def channel_items() -> tuple[str, ...]:
    """The channel combo's items, as the application shows them: ``'1'``..``'10'``.

    Derived from the one range (:data:`…config.MIN_CHANNEL`/:data:`…config.MAX_CHANNEL`),
    never listed again: a second copy of the channel list is exactly the parallel
    constant this module must not have.
    """
    return tuple(str(n) for n in range(MIN_CHANNEL, MAX_CHANNEL + 1))


# ``_entry_buttons`` and ``_observation_text`` were defined here: the popup's entries in screen
# order and the prose one entry press is reported with. Both are pure, and both are
# ``acquire/ui/menu.py``'s as of Patch 2's widget slice — imported at the top of this file under
# these same names, so ``driver._entry_buttons`` keeps resolving.


def _descendants(roles: Mapping, root: int) -> list[dict]:
    """Every already-resolved control inside ``root``, breadth first.

    The tree comes from the resolution's own parent map, so this walks the *same*
    snapshot the roles were resolved from instead of re-enumerating the window.
    """
    by_parent: dict[int, list[dict]] = {}
    for node in roles["raw"]:
        by_parent.setdefault(roles["parent_of"].get(node["hwnd"], 0), []).append(node)
    out: list[dict] = []
    queue = list(by_parent.get(root, []))
    while queue:
        node = queue.pop(0)
        out.append(node)
        queue.extend(by_parent.get(node["hwnd"], []))
    return out


def _same_directory(reported: str, expected: Path) -> bool:
    """Is the dialog's working directory the one the caller meant?

    Compared, never written: the cycle asserts this field and *sets* it when it differs, which
    is precisely what a preflight must not do. Windows paths are case-insensitive and the
    dialog pads its text, so the comparison normalises both sides rather than the caller.
    """
    return normalized_path(reported) == normalized_path(str(expected))


class Win32Actuator(RecordingSurface):
    """The live :class:`Actuator`: UDOP driven over posted Win32 messages.

    Bindings are re-resolved from scratch on every call — the strip panel is draggable
    and morphs (``98x40`` -> ``352x40`` -> ``413x123``), so a cached handle or rect would
    go stale on the first press.
    """

    def __init__(
        self,
        class_name: str = MAIN_CLASS,
        *,
        channel: int | None = None,
        note_sink: Callable[[str], None] | None = None,
        allow_real_input: bool = True,
    ) -> None:
        """``channel`` is the measurement channel — the one knob.

        ``None`` takes it from :class:`~udv_echo_process.acquire.config.ChannelSetting`
        (explicit here > ``UDV_CHANNEL`` > the default), so retargeting the whole run is
        an environment variable and nothing else. The value is validated on construction,
        not at the first press.

        ``allow_real_input`` gates the one step posted messages cannot drive: the menubar.
        ``True`` (the default) hovers the ``Parameters`` button with the operator's real
        cursor, which is the gesture this application's menubar answers, and puts the
        cursor back; ``False`` refuses the menubar step with a named
        :class:`AcquisitionError` **before anything is moved**, for unattended or
        locked-desktop runs. There is no posted fallback: the menubar is known not to
        answer one. The popup **entry** behind it is taken with the posted held press on
        the entry's own handle, which needs no cursor at all — so `allow_real_input` does
        not touch the entry path.
        """
        self._class_name = class_name
        self._channel_setting = (
            ChannelSetting() if channel is None else ChannelSetting(channel=channel)
        )
        self._note_sink = note_sink
        self._allow_real_input = bool(allow_real_input)
        #: Diagnostics only — never used as a binding.
        self.last_roles: dict | None = None
        self.last_press_screen: tuple[int, int] | None = None
        #: The screen point the last real-cursor hover used (diagnostics only).
        self.last_hover_screen: tuple[int, int] | None = None
        #: What the application actually did on the last popup-entry press: the gesture
        #: used, whether the overlay was **visible**, whether the popup closed, any panel
        #: that was not up before (its rect and its top-level child classes) and the dialog
        #: that was found (:meth:`_observe_entry_attempt`). Diagnostics only, never a
        #: binding — the next live run must be told what the application did, not merely
        #: that a step failed.
        self.last_entry_attempt: dict | None = None
        self.warnings: list[str] = []

    # ------------------------------------------------------------------ plumbing

    def _note(self, message: str) -> None:
        self.warnings.append(message)
        if self._note_sink is not None:
            self._note_sink(message)

    def _send(
        self,
        hwnd: int,
        msg: int,
        wp: int = 0,
        lp: int = 0,
        timeout_ms: int = SEND_TIMEOUT_MS,
    ) -> int:
        """Bounded send; see :func:`~udv_echo_process.acquire.win32.messages._send`."""
        return _send(hwnd, msg, wp, lp, timeout_ms, user32=_user32)

    def _get_text(self, hwnd: int) -> str:
        """The control's own text (``WM_GETTEXT``, bounded)."""
        return _get_text(hwnd, send=self._send)

    def _control_id(self, hwnd: int) -> int:
        """The id only as the field *inside* ``WM_COMMAND`` — never as an identity."""
        return _control_id(hwnd, gui=_gui)

    def _set_text_commit(self, hwnd: int, text: str, parent: int | None = None) -> None:
        """Write ``text`` and **commit** it: the recipe in ``NUMERIC_WRITE_RECIPE``.

        ``WM_SETTEXT`` alone changes the control's text while the application keeps its
        own value; the ``EN_CHANGE`` command and the ``VK_RETURN`` key event are what make
        the model take the new value (docs/14 §4, docs/16 §12a). The four sends, their two
        settles and the order they are in are
        :func:`~udv_echo_process.acquire.win32.messages._set_text_commit`, where the recipe
        is also compared against :data:`~udv_echo_process.acquire.actuator.NUMERIC_WRITE_RECIPE`
        so the port cannot drift from it.
        """
        _set_text_commit(hwnd, text, parent, send=self._send, post=_post, gui=_gui)

    def _combo_select(self, hwnd: int, index: int, parent: int | None = None) -> None:
        """Select a combo entry: ``CB_SETCURSEL`` + ``CBN_SELCHANGE``, **no Enter**.

        A combo commits on the change notification; a key event here would re-trigger
        whatever the Enter handler does. The selection, the notification and the
        reference's own settle are
        :func:`~udv_echo_process.acquire.win32.messages._combo_select`.
        """
        _combo_select(hwnd, index, parent, send=self._send, post=_post, gui=_gui)

    def _click_hold(self, hwnd: int, hold_ms: int = PRESS_HOLD_MS) -> None:
        """Press and **hold** a control: down, ``hold_ms``, up.

        An instant down/up in the same millisecond is ignored by the strip (that is
        exactly what every early attempt sent, docs/16 §1). ``lParam`` is in the target's
        client coordinates, so the centre comes from ``GetClientRect`` and is converted to
        screen only so a failure can be reported in real screen terms. The message
        sequence, the hold and the settle are
        :func:`~udv_echo_process.acquire.win32.messages._click_hold`; the screen point it
        read comes back here, where it stays a diagnostic and never a binding.
        """
        self.last_press_screen = _click_hold(hwnd, hold_ms, post=_post, gui=_gui)

    def _clip_rect(self) -> tuple[int, int, int, int] | None:
        """The rectangle the cursor is currently confined to, or ``None`` for no clip.

        This application sets ``ClipCursor`` while its blocking popups are up
        (docs/dop3000/udop-automation.md §6), and a ``SetCursorPos`` outside that rectangle
        is silently clamped to its edge — the live-run hazard. The read is
        :func:`~udv_echo_process.acquire.win32.cursor._clip_rect`; an empty rectangle, a
        failed read and a host without the call all answer ``None``.
        """
        return _clip_rect(user32=_user32)

    def _release_clip(self) -> bool:
        """``ClipCursor(NULL)``: drop the application's own confinement of the cursor.

        Called only when the driver is about to move the cursor somewhere the clip forbids
        (a move, or a restore) — never as a matter of course, so an open dialog keeps the
        clip it wants. A release that fails is not raised here: the caller's read-back and
        its failure message are what report it, naming the clip it could not clear.
        """
        return _release_clip(user32=_user32)

    def _cursor_position(self) -> tuple[int, int]:
        """The operator's cursor position, in screen coordinates.

        Read before any real move, so the move can be undone (:meth:`_restore_cursor`).
        An unreadable position is refused rather than ignored — a cursor moved with no way
        back is the operator's cursor taken — by
        :func:`~udv_echo_process.acquire.win32.cursor._cursor_position`.
        """
        return _cursor_position(user32=_user32)

    def _restore_cursor(self, position: tuple[int, int]) -> None:
        """Put the operator's cursor back where :meth:`_cursor_position` found it.

        **Not into a clip.** The rule — a clip that does not contain the operator's position
        is released with ``ClipCursor(NULL)`` before the restore, a clip that already
        contains it is left alone, and nothing is raised because this runs from a
        ``finally`` — is :func:`~udv_echo_process.acquire.win32.cursor._restore_cursor`,
        which is handed this driver's own transport, its diagnostic sink (``self._note``)
        and the edge-inclusive clip test.
        """
        _restore_cursor(
            position,
            note=self._note,
            inside=_point_in_rect,
            clip=self._clip_rect,
            release=self._release_clip,
            read_position=self._cursor_position,
            user32=_user32,
        )

    def _move_real_cursor(
        self, point: tuple[int, int], *, what: str, why: str
    ) -> tuple[int, int]:
        """Move the **real** cursor onto ``point``, clearing any clip that traps it.

        The rule — read the clip first, release it when ``point`` lies outside it, retry
        once, then refuse **naming the clip rectangle and the target point** rather than
        blaming a locked desktop — is
        :func:`~udv_echo_process.acquire.win32.cursor._move_real_cursor`, which is handed
        this driver's own transport, its diagnostic sink and the edge-inclusive clip test.
        """
        return _move_real_cursor(
            point,
            what=what,
            why=why,
            note=self._note,
            inside=_point_in_rect,
            clip=self._clip_rect,
            release=self._release_clip,
            read_position=self._cursor_position,
            user32=_user32,
        )

    def _foreground_window(self) -> int:
        """The foreground window's handle — the menubar hover's **precondition**.

        A method, so the fake can script a window sitting in front: a precondition that
        cannot be scripted cannot be tested, and this one is invisible from the control
        tree (measured live 2026-09-17: `recon/53`).
        """
        return _foreground_window(user32=_user32)

    @staticmethod
    def _thread_of(hwnd: int) -> int:
        """The thread that owns ``hwnd``.

        ``win32process.GetWindowThreadProcessId`` is ``pywin32``'s home for this call and
        returns ``(threadId, processId)`` — **thread first**, despite the name — but the
        driver reaches Windows through ``ctypes`` here, so bringing a window forward needs
        no extra import: see
        :func:`~udv_echo_process.acquire.win32.cursor._thread_of`.
        """
        return _thread_of(hwnd, user32=_user32)

    def _activate_window(self, hwnd: int) -> None:
        """Ask Windows to make ``hwnd`` the foreground window.

        The documented route, because ``SetForegroundWindow`` returns 0 from a process the
        user is not interacting with (the foreground lock): attach our thread's input to the
        current foreground thread, ask, detach — and check what the call *did* by reading the
        foreground window back, never by trusting the return value. The route is
        :func:`~udv_echo_process.acquire.win32.cursor._activate_window`.
        """
        _activate_window(hwnd, user32=_user32)

    def _require_foreground(self, hwnd: int) -> None:
        """Assert the application is the **foreground** window before hovering it.

        **Measured live 2026-09-17:** with a console window in front the same gesture that
        had opened the menubar minutes earlier opened nothing, because an inactive window
        ignores hover — its first mouse event activates it and the menu opens only on the
        *second* — and the failure was indistinguishable from "this gesture does not work".
        The precondition (bring the window forward, re-read the foreground window, refuse
        naming what is in front) and that measurement in full are
        :func:`~udv_echo_process.acquire.win32.cursor._require_foreground`; the refusal is
        the facade's own :class:`AcquisitionError`.
        """
        _require_foreground(
            hwnd,
            self._class_name,
            foreground=self._foreground_window,
            activate=self._activate_window,
            gui=_gui,
        )

    def _hover_centre(self, hwnd: int) -> tuple[int, int]:
        """Hover ``hwnd`` with the **real** cursor; return the screen point hovered.

        The menubar is the one control in this application that posted messages cannot
        drive: a posted ``WM_MOUSEMOVE`` opened nothing, and a posted press held for
        :data:`…actuator.PRESS_HOLD_MS` opened nothing either (two live runs, both
        aborting safely with nothing pressed), while the same button opened its menu
        under the operator's real cursor in ``recon/41_burst_sampling_volume.py``. The
        gesture — the control's centre in **screen** coordinates, ``SetCursorPos``, the
        recipe's 0.3 s settle, one ``mouse_event`` relative move, then the recipe's 1.0 s
        settle — is :func:`~udv_echo_process.acquire.win32.cursor._hover_centre`, which is
        handed this driver's own move (so the clip this application sets on an open popup
        cannot clamp the cursor short of the button: the menubar button is *outside* any
        open popup's clip, which is precisely the move the live run could not make) and the
        two sentences the step is reported with. The cursor now sits on the control, so the
        caller puts it back with :meth:`_restore_cursor`.
        """
        point = _hover_centre(
            hwnd,
            what=f"the {PARAMETERS_MENU!r} button",
            why="this menubar answers nothing else, so nothing is posted to it",
            move=self._move_real_cursor,
            gui=_gui,
            user32=_user32,
        )
        self.last_hover_screen = point
        return point

    # ------------------------------------------------------------------ binding

    def _main_hwnd(self) -> int:
        """Handle of the visible main window (largest if several exist)."""
        return _main_hwnd(self._class_name, gui=_gui)

    @staticmethod
    def _children_of(parent: int, roles: dict) -> list[dict]:
        """The already-enumerated children whose parent is ``parent``."""
        return _children_of(parent, roles, gui=_gui)

    def _param_rows(
        self, left_panel: dict | None, kids: Sequence[dict], children_of
    ) -> list[dict]:
        """The parameter column's value fields, top -> bottom, each with its inner edit.

        A field's identity is its position in this fixed order, never its id: the
        ``TSp_Value_Button`` widgets in the left panel, ordered by ``top``, each holding a
        ``TSp_Edit``/``TEdit`` (docs/16 §12, ``recon/udop_roles.py``).
        """
        if left_panel is None:
            return []
        rows: list[dict] = []
        for button in sorted(
            (
                k
                for k in kids
                if k["cls"] == "TSp_Value_Button" and _inside(left_panel, k)
            ),
            key=lambda k: k["top"],
        ):
            inner = sorted(children_of(button["hwnd"]), key=lambda k: k["left"])
            edit = next((c for c in inner if c["cls"] in ("TSp_Edit", "TEdit")), None)
            if edit is not None:
                rows.append({"button": button, "edit": edit})
        if len(rows) >= len(PARAM_COLUMN_ORDER):
            return rows
        # Fallback: plain edits inside the column's rect, in the same fixed order.
        flat = [
            {"button": None, "edit": k}
            for k in sorted(
                (
                    k
                    for k in kids
                    if k["cls"] in ("TSp_Edit", "TEdit") and _inside(left_panel, k)
                ),
                key=lambda k: k["top"],
            )
        ]
        return flat if len(flat) > len(rows) else rows

    def _resolve(self) -> dict:
        """Map roles to live controls, the way ``udop_roles.resolve()`` does.

        Class + position inside the client area only: the layout fingerprint, the panel
        list, the menu bar, the parameter column, the combos, the strip panel (by its
        buttons' position in the plot area, then by its own button row) and the open-popup
        flag. Nothing keys on a control id and nothing on a screen coordinate in logic.
        """
        win32gui, _ = _gui()
        win = self._main_hwnd()
        kids = _visible_children(win, gui=_gui)
        _l, _t, cw, ch = win32gui.GetClientRect(
            win
        )  # GetClientRect is always (0,0,w,h)
        ox, oy = win32gui.ClientToScreen(win, (0, 0))  # the client's screen origin
        parent_of = win32gui.GetParent

        def children_of(p: int) -> list[dict]:
            return [k for k in kids if win32gui.GetParent(k["hwnd"]) == p]

        roles: dict = {
            "window": win,
            "client": (cw, ch),
            "origin": (ox, oy),
            "raw": kids,
            # The class the window reports. Checked by the shape gate rather than assumed from
            # the class `_main_hwnd` filtered on, so a captured tree can be asked the same
            # question (plan §24.3's first clause).
            "class_name": win32gui.GetClassName(win),
            # The resolved tree, so "nested inside X" is a property of the snapshot
            # rather than another enumeration of the window.
            "parent_of": {k["hwnd"]: parent_of(k["hwnd"]) for k in kids},
        }

        # --- panels -------------------------------------------------------------------
        # Every cluster sits inside its own TSp_Panel, and the panels are ordered
        # top-to-bottom deterministically: group by parent panel, never by fractions of the
        # window (the strip sits at a fixed client y whether the client is 819 or 1027 px
        # tall, so a percentage cut moves relative to it as the window is resized).
        panels = sorted(
            (
                k
                for k in kids
                if k["cls"] == "TSp_Panel" and parent_of(k["hwnd"]) == win
            ),
            key=lambda k: k["top"],
        )
        roles["panels"] = panels
        index_of = {k["hwnd"]: i for i, k in enumerate(panels)}
        buttons = [k for k in kids if k["cls"] == "TSp_Button"]
        host_count = {
            i: sum(1 for b in buttons if index_of.get(parent_of(b["hwnd"])) == i)
            for i in range(len(panels))
        }
        plot = next((k for k in kids if k["cls"] == "TDop_Plot"), None)
        menu_idx = 0 if panels else None
        status_idx = (len(panels) - 1) if len(panels) > 1 else None
        #: The band the resolver found the menubar in, exposed to the shape gate so the clause
        #: "the menubar band resolves at the client's top" is asked of the same panel the
        #: resolver chose, rather than of an index the gate would have to re-derive (plan §24.2).
        roles["menu_band"] = panels[menu_idx] if menu_idx is not None else None

        # --- panels that are dialogs, not the measurement layout ------------------------
        # A dialog is a panel owning a real edit plus a TSp_Browse button, wherever the
        # operator dragged it. One with TSp_Value_Button children is the values dialog
        # (`Record settings`); one without them is the Store dialog. Detected structurally,
        # so the file-exists warning and the store dialog are never confused.
        value_dialogs: set[int] = set()
        browse_dialogs: set[int] = set()
        for p in panels:
            direct = children_of(p["hwnd"])
            has_edit = any(k["cls"] in ("TEdit", "TSp_Edit") for k in direct)
            if not (has_edit and any(k["cls"] == "TSp_Browse" for k in direct)):
                continue
            if any(k["cls"] == "TSp_Value_Button" for k in direct):
                value_dialogs.add(p["hwnd"])
            else:
                browse_dialogs.add(p["hwnd"])
        roles["value_dialogs"], roles["browse_dialogs"] = value_dialogs, browse_dialogs
        dialog_panels = value_dialogs | browse_dialogs

        # --- the recording strip --------------------------------------------------------
        # The strip is the button panel in the MIDDLE of the plot area. "The panel with the
        # most buttons" is wrong the moment a popup is open: an open menu is itself a panel
        # full of buttons near the menu bar, and it wins that vote.
        def strip_score(i: int) -> float | None:
            if not host_count.get(i):
                return None
            if plot is None:
                return float(host_count[i])
            band = [b for b in buttons if index_of.get(parent_of(b["hwnd"])) == i]
            centre_y = sum(b["top"] + b["h"] / 2 for b in band) / len(band)
            frac = (centre_y - plot["top"]) / max(1, plot["h"])
            return frac if 0.30 <= frac <= 0.70 else None

        scored = {
            i: s
            for i in range(len(panels))
            if i not in (menu_idx, status_idx)
            and panels[i]["hwnd"] not in dialog_panels
            and (s := strip_score(i)) is not None
        }
        rec_idx = max(scored, key=lambda i: host_count[i]) if scored else None
        strip_panel = panels[rec_idx] if rec_idx is not None else None
        if strip_panel is not None and not any(
            k["cls"] == "TSp_Button" for k in children_of(strip_panel["hwnd"])
        ):
            strip_panel = None
        if strip_panel is None:
            # Fallback: a short panel (not the menu, not the status bar, not a dialog) that
            # directly owns strip buttons.
            strip_panel = max(
                (
                    p
                    for i, p in enumerate(panels)
                    if i not in (menu_idx, status_idx)
                    and p["hwnd"] not in dialog_panels
                    and p["h"] <= 200
                    and host_count.get(i)
                ),
                key=lambda p: p["h"],
                default=None,
            )
        roles["strip_panel"] = strip_panel
        roles["open_popup"] = any(
            i not in (menu_idx, status_idx, rec_idx)
            and host_count.get(i)
            and panels[i]["hwnd"] not in dialog_panels
            for i in range(len(panels))
        )

        # --- the `Parameters` anchor, and nothing else ------------------------------------
        # The bar is carried as **evidence** — every button of the band, left -> right — and the
        # one binding this driver publishes is the anchor the pure signature proves
        # (:func:`…ui.menu.anchor_button`). No name is assigned by position: the variants do not
        # paint the same bar and the entries carry no tree text, so an index map silently renames
        # every later role when one entry is absent (ledger B03). A bar the signature cannot
        # prove publishes **no** anchor at all, which is what makes the menubar hover unreachable
        # rather than mis-aimed.
        ordered_menu = sorted(
            (b for b in buttons if index_of.get(parent_of(b["hwnd"])) == menu_idx),
            key=lambda b: b["left"],
        )
        roles["menu_buttons"] = ordered_menu
        roles["menu"] = {}
        anchor = anchor_button(observation_of(roles))
        if anchor is not None and anchor.hwnd is not None:
            roles["menu"] = {
                PARAMETERS_MENU: next(
                    b for b in ordered_menu if b["hwnd"] == anchor.hwnd
                )
            }

        # --- the left parameter column ----------------------------------------------------
        # The column is the tall panel whose *client-relative* left is 0 (`left == 0` in the
        # reference); fall back to the tallest panel that is neither the menu bar nor the
        # status bar.
        candidates = [
            p
            for i, p in enumerate(panels)
            if i not in (menu_idx, status_idx) and p["hwnd"] not in dialog_panels
        ]
        left_panel = next(
            (p for p in candidates if (p["left"] - ox) == 0 and p["h"] > 500), None
        ) or max(
            # The fallback must not pick a panel that *is* a dialog: with the sidebar hidden
            # behind an open dialog, the tallest remaining panel is the dialog itself, and
            # taking it as the sidebar made `_dialog_panels()` report no dialog at all — which
            # is how a live run concluded "nothing to close" while a dialog sat on the screen
            # (measured 2026-09-17, `recon/54`). The real column is 190 px wide, so it never
            # fails the dialog test itself.
            (
                p
                for p in candidates
                if not _is_dialog_panel(p, children_of(p["hwnd"]))
            ),
            key=lambda p: p["h"],
            default=None,
        )
        roles["left_panel"] = left_panel
        rows = self._param_rows(left_panel, kids, children_of)
        roles["param_rows"] = rows
        roles["params"] = {
            PARAM_COLUMN_ORDER[i]: row
            for i, row in enumerate(rows[: len(PARAM_COLUMN_ORDER)])
        }
        roles["combos"] = dict(
            zip(
                COMBO_ORDER,
                sorted(
                    (
                        k
                        for k in kids
                        if k["cls"] == "TComboBox" and _inside(left_panel, k)
                    ),
                    key=lambda k: k["top"],
                ),
            )
        )
        roles["plot"] = plot

        # --- the strip's own structure, and the layout fingerprint -------------------------
        strip_kids = children_of(strip_panel["hwnd"]) if strip_panel is not None else []
        row = _strip_row(strip_panel, strip_kids) if strip_panel is not None else []
        roles["strip_row"] = row
        # The slider's mark is read once, here, and carried on the map: it is one of the two facts
        # the view is classified from (``ui/strip.py`` :func:`…ui.strip.has_slider`), and a state
        # read that had to enumerate the panel again could not be taken from a captured tree.
        roles["strip_slider"] = has_slider(strip_kids)
        roles["state"] = classify_strip_view(len(row), roles["strip_slider"]).value
        # The gate and its evidence, both pure over this tree (plan §24.3, §24.5 D4). The shape
        # decides and the counts do not: 43 and 44 are two legitimate layouts, so the totals are
        # carried in `layout_evidence` — into the reading, the note and the record — where a
        # reader compares them, instead of being a number a run is stopped by.
        roles["layout_shape_reasons"] = layout_shape_reasons(roles)
        roles["layout_evidence"] = layout_evidence(roles)
        self.last_roles = roles
        return roles

    def _require_store_dialog(self) -> tuple[dict, list[dict]]:
        """The Store dialog panel and its children, or a failure."""
        found = self._find_overlay()
        if found is None or found[0] is not OverlayKind.STORE_DIALOG:
            raise AcquisitionError("the Store dialog is not up")
        return found[1], self._children_of(found[1]["hwnd"], self._resolve())

    def _dialog_button(
        self,
        panel: dict,
        kids: Sequence[dict],
        which: DialogControl,
        hold_ms: int = PRESS_HOLD_MS,
    ) -> dict:
        """Press one end of a dialog's bottom pair (never by title, never by rect).

        The pair is taken **from the right**, which is the reference's own rule
        (``recon/41_burst_sampling_volume.py``, ``bottom[-1] if accept else bottom[-2]``):
        Accept is the rightmost button of the band and Cancel is the one immediately left
        of it. Never the leftmost of the band — the live operating dialog's band also
        holds the two indicator buttons "No emission on Probe In/Out" and "Use US coupling
        parameters" to the left of the pair, so pressing "the leftmost button of the
        bottom row" pressed an indicator and left the dialog open, which is what a live
        read-only run did (measured 2026-09-17).
        """
        row = _bottom_row(panel, kids)
        if len(row) < 2:
            raise AcquisitionError(
                f"the dialog at {panel['rect'][:2]} has {len(row)} button(s) in its "
                f"bottom band ({[b['rect'] for b in row]}): Cancel and Accept are the "
                "last two by position, so neither can be identified and nothing is pressed"
            )
        target = row[-2] if which is DialogControl.SAFE else row[-1]
        self._click_hold(target["hwnd"], hold_ms)
        return target

    # -------------------------------------------------- the measurement channel

    @property
    def channel(self) -> int:
        """The measurement channel this driver is bound to (the single knob)."""
        return self._channel_setting.channel

    def _combo_index(self, hwnd: int) -> int:
        """The combo's selected index, or ``-1`` when it has no selection.

        ``CB_GETCURSEL`` answers ``CB_ERR`` (-1) through an unsigned result, so a value above
        :data:`_COMBO_NONE_ABOVE` means *no selection*, never a huge index. This is the
        control's own belief, which is why it is never the only read-back
        (:meth:`_channel_readback`); the read is
        :func:`~udv_echo_process.acquire.win32.messages._combo_index`.
        """
        return _combo_index(hwnd, send=self._send)

    def _combo_items(self, hwnd: int) -> tuple[str, ...]:
        """Every item the combo holds, in order (``CB_GETCOUNT`` + ``CB_GETLBTEXT``).

        The item *list* is how the channel combo is identified, so it is read rather
        than assumed; a nonsense count is an empty list, not a spin. The read is
        :func:`~udv_echo_process.acquire.win32.messages._combo_items`.
        """
        return _combo_items(hwnd, send=self._send)

    def _channel_combo(self, panel: dict, roles: Mapping | None = None) -> tuple[dict, int]:
        """The channel combo inside ``panel``: ``(combo, its parent's hwnd)``.

        Identity is the **item list**: a ``TComboBox`` inside this dialog whose items are
        the application's channels, ``'1'``..``'10'`` (:func:`channel_items`). Never an id
        (ids change on every launch), never a screen coordinate stated in logic, never
        "the first combo" — the operating dialog holds several combos (burst, sampling
        volume, sensitivity) and they are told apart by what they list.

        The nesting through a ``TSp_Value_Button`` that an earlier revision demanded is
        **dropped**: the live read of the operating dialog shows its channel combo as the
        dialog's own header field — ``TComboBox`` at ``(1083, 373)`` directly under the
        627x384 panel, i.e. ``Operating parameters for channel [n ▼]`` — not inside a value
        field, so the nesting was an assumption that could reject a correctly opened
        dialog. Two matches are an ambiguity, not a choice to make; none is a failure that
        names every combo the dialog holds and what it lists, which is the diagnosis a
        live run needs.
        """
        roles = self._resolve() if roles is None else roles
        wanted = channel_items()
        matches: list[tuple[dict, int]] = []
        found: list[str] = []
        for node in _descendants(roles, panel["hwnd"]):
            if node["cls"] != "TComboBox":
                continue
            items = self._combo_items(node["hwnd"])
            found.append(f"TComboBox at {node['rect'][:2]} listing {list(items)}")
            if items == wanted:
                parent = roles["parent_of"].get(node["hwnd"])
                matches.append((node, 0 if parent is None else parent))
        if not matches:
            raise AcquisitionError(
                f"no channel combo in the dialog at {panel['rect'][:2]}: the measurement "
                f"channel lives in a TComboBox listing {list(wanted)}, and the "
                f"{len(found)} combo(s) this dialog holds list "
                f"{'; '.join(found) or 'nothing at all'}"
            )
        if len(matches) > 1:
            raise AcquisitionError(
                f"{len(matches)} combos in the dialog at {panel['rect'][:2]} list "
                f"{list(wanted)}; the channel combo is ambiguous, so nothing is selected"
            )
        return matches[0]

    def _channel_readback(self, combo: dict) -> tuple[int, str]:
        """The dialog's own statement of the channel: the combo's index **and** text.

        Both, because either alone lies: ``CB_GETCURSEL`` reports only what the control
        believes, and a combo's painted text has been seen to keep showing the previous
        entry after a write (docs/16 §2). A read-back that does not name the configured
        channel is a selection that did not take.
        """
        return self._combo_index(combo["hwnd"]), self._get_text(combo["hwnd"])

    def _channel_matches(self, index: int, text: str) -> bool:
        """True when a dialog read-back names the configured channel exactly."""
        wanted = self._channel_setting
        return index == wanted.combo_index and text.strip() == str(wanted.channel)

    def _close_any_dialog(self) -> None:
        """Close whatever dialog is up, re-resolving it first — never a stale handle.

        Written because a live failure *left the dialog on the operator's screen* (measured
        2026-09-17, twice): the application had replaced the dialog on a channel write, the
        driver's panel handle was dead, and its close attempt therefore pressed nothing and
        raised "0 buttons in its bottom band". A close path that can itself fail on a stale
        handle is not a close path, so this resolves the panel afresh, presses the safe end,
        and reports — rather than raising — when even that cannot be done.
        """
        for _attempt in range(2):
            found = self._dialog_panels()
            if not found:
                return
            try:
                self._close_parameters_dialog(found[0])
            except AcquisitionError as exc:
                self._note(
                    f"a dialog is still up at {found[0]['rect'][:2]} and could not be "
                    f"closed: {exc}"
                )
                return

    def _panel_map(self, roles: Mapping | None = None) -> dict[int, dict]:
        """Every visible ``TSp_Panel`` right now, by handle.

        The panels are re-read, never remembered: the popup is a panel the application
        shows and hides, so the snapshot taken before the hover is only worth anything
        compared with a *fresh* one. Nothing here is keyed on a caption — these widgets
        have none (see the module docstring).
        """
        roles = self._resolve() if roles is None else roles
        return {k["hwnd"]: k for k in roles["raw"] if k["cls"] == "TSp_Panel"}

    def _poll_parameters_overlay(self, before: Mapping[int, dict]) -> dict:
        """The ``Parameters`` popup overlay: the panel that appeared on the hover.

        Identified by **appearance**, because a caption can never identify it: every
        caption-less ``TSp_*`` widget in this application answers ``GetWindowText`` with
        the empty string, so the overlay is the ``TSp_Panel`` that is visible now and was
        **not** in the ``before`` snapshot taken just before the menubar was hovered.

        When the diff is ambiguous — more than one new panel, or none yet — the reference
        recipe's own predicate decides (``recon/41_burst_sampling_volume.py``:
        ``left == 169 and h > 120``, the panel it read live at ``(169, 55, 401, 250)``;
        the popup is reused or re-shown by some menus, and then it was visible before the
        second hover and the diff alone would find nothing). Polled, never assumed: the
        recipe waited the same way and the popup takes a moment to paint. A popup that
        has shown neither within :data:`_MENU_TIMEOUT_S` is reported by name — and a panel
        that is in the tree but **hidden** is named in that failure too, because the
        overlay this application pre-creates is exactly that (:func:`_is_visible`): an
        accepted-but-hidden panel is a menu that is not on screen.
        """
        deadline = time.monotonic() + _MENU_TIMEOUT_S
        while True:
            panels = self._panel_map()
            # The reference's own predicate first (`recon/41`, verbatim): the panel the
            # application painted for this menu is the visible one at `left == 169` whose
            # height exceeds 120 (live: `(169, 55, 401, 250)`). Heeding it first is what the
            # handoff asks for — the appearance diff below is this driver's addition, and an
            # addition should never outrank the proven rule.
            recorded = sorted(
                (
                    p
                    for p in panels.values()
                    if p["left"] == _OVERLAY_LEFT
                    and p["h"] > _OVERLAY_MIN_H
                    and self._is_visible(p["hwnd"])
                ),
                key=lambda p: p["top"],
            )
            if recorded:
                return recorded[0]
            # Fallback for an overlay this application paints somewhere else (a different
            # theme or scale): the panel that appeared on the hover, when exactly one did.
            fresh = [
                p
                for hwnd, p in panels.items()
                if hwnd not in before and self._is_visible(p["hwnd"])
            ]
            if len(fresh) == 1:
                return fresh[0]
            if time.monotonic() >= deadline:
                break
            time.sleep(_MENU_POLL_S)
        hidden = self._hidden_panels()
        named = (
            "; the panels present in the tree with IsWindowVisible == False are "
            + ", ".join(f"{p['rect']}" for p in hidden[:4])
            + " — a pre-created, unpainted overlay is not an open menu, so nothing is "
            "pressed into it"
            if hidden
            else ""
        )
        raise AcquisitionError(
            f"the {PARAMETERS_MENU!r} popup did not appear within {_MENU_TIMEOUT_S:.0f} s "
            f"of its hover, so no {PARAMETERS_ENTRY!r} entry could be pressed: no *visible* "
            "panel appeared that was not visible before the hover, and none is a visible "
            f"panel matching the overlay the live application paints{named}"
        )

    def _is_visible(self, hwnd: int) -> bool:
        """Whether a control is *visible* — the precondition of every entry press.

        The overlay this application opens on a menubar hover is **pre-created** in the
        control tree and hidden until then, so "the panel is there" is not "the menu is
        open": a rule that accepts presence presses coordinates into empty screen, which
        is what a live run did. Split out as a method so a fake can script the hidden
        panel without a window; the read itself is
        :func:`~udv_echo_process.acquire.win32.tree._is_visible`, where an unreadable
        answer is ``False``.
        """
        return _is_visible(hwnd, gui=_gui)

    def _hidden_panels(self) -> list[dict]:
        """The panels present in the tree but **not visible** (diagnostics, never targets)."""
        return _hidden_panels(self._resolve()["window"], gui=_gui)

    def _dialog_panels(self, roles: Mapping | None = None) -> list[dict]:
        """The panels that are modal dialogs, fullest first — the reference's rule.

        A dialog is identified **structurally** (:func:`_is_dialog_panel`): a panel that
        is not the sidebar parameter column — that exclusion is by identity, the resolved
        ``left_panel``, never by position, because the column owns ``TSp_Value_Button``
        fields of its own — wider than :data:`_DIALOG_MIN_W`, and holding input controls
        of its own or at least :data:`_DIALOG_MIN_CHILDREN` direct children or a
        ``TSp_Browse``. This is what ``recon/41_burst_sampling_volume.py`` polled for, and
        it deliberately does **not** require the channel combo: which dialog *this* is, is
        the caller's question, and a dialog whose combo cannot be found must not be
        reported as "no dialog opened".

        Fullest first, the way the reference chose when several matched
        (``len(kids) > len(children(best, roles))``), then widest, so a warning strip
        cannot win over a real dialog.
        """
        roles = self._resolve() if roles is None else roles
        left = roles.get("left_panel")
        out: list[dict] = []
        for panel in roles.get("panels") or []:
            if left is not None and panel["hwnd"] == left["hwnd"]:
                continue
            kids = self._children_of(panel["hwnd"], roles)
            if _is_dialog_panel(panel, kids):
                out.append(panel)
        return sorted(
            out,
            key=lambda p: (
                -len(self._children_of(p["hwnd"], roles)),
                -p["w"],
                p["top"],
            ),
        )

    def _poll_dialog(self, timeout_s: float) -> dict | None:
        """The dialog panel that is up, or ``None`` when none appeared in ``timeout_s``.

        Found by structure (:meth:`_dialog_panels`), never by a caption and never by the
        channel combo — the live dialog's channel combo sits in its header, and a rule
        that demanded the combo inside a value field rejected a correctly opened dialog.
        ``None`` is a fact to report, not to paper over: the caller names it and tries the
        next entry by screen order.
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            panels = self._dialog_panels()
            if panels:
                return panels[0]
            if time.monotonic() >= deadline:
                return None
            time.sleep(_MENU_POLL_S)

    def _panel_observation(self, panel: dict, roles: dict) -> dict:
        """One panel as the entry diagnostics report it: handle, rect, child classes.

        Classes only, never a caption: this application's widgets carry none (see the
        module docstring), so the classes of the panel's *direct* children are the
        structural fingerprint a live run can be read back against.
        """
        return {
            "hwnd": panel["hwnd"],
            "rect": tuple(panel["rect"]),
            "classes": tuple(
                sorted({k["cls"] for k in self._children_of(panel["hwnd"], roles)})
            ),
        }

    def _pressed_state(self, entry: dict, overlay: dict) -> dict:
        """What the overlay offered **at the moment of the press** — never read after it.

        A press closes the popup, so its entries are gone from the visible tree by the time
        the outcome is observed: a record that read them afterwards said "the overlay was
        NOT visible and held 0 entries" on a press that had in fact opened the operating
        dialog (measured live 2026-09-17). These four facts therefore come from *before* the
        gesture; the after-state is :attr:`…last_entry_attempt`'s ``overlay_closed`` and
        ``overlay_visible_after``.
        """
        roles = self._resolve()
        entries = _entry_buttons(overlay, roles["raw"])
        return {
            "overlay_visible": self._is_visible(overlay["hwnd"]),
            "overlay_items": len(entries),
            "entry_tops": [e["rect"][1] for e in entries],
            "entry_caption": self._get_text(entry["hwnd"]),
        }

    def _observe_entry_attempt(
        self,
        entry: dict,
        overlay: dict,
        before: set[int],
        gesture: str,
        panel: dict | None,
        *,
        gesture_failed: bool = False,
        pressed: Mapping | None = None,
    ) -> dict:
        """Record what the application actually did on one popup-entry press.

        Mechanical on purpose — was the overlay *visible*, did the popup close, did a panel
        appear that was not up before the press, and what does it hold — because the live
        run's failure was *not* that the driver pressed the wrong thing: it was that the
        press did nothing at all and the run could not say what the application did
        instead. The record is kept on :attr:`last_entry_attempt` whether the press worked
        or not, and it is what the caller puts in its failure message.

        ``pressed`` is the state captured **before** the gesture
        (:meth:`_pressed_state`): a press closes the popup, so the overlay's visibility and
        its entries can only be read truthfully beforehand.
        """
        roles = self._resolve()
        panels = self._panel_map(roles)
        state = dict(pressed or {})
        state.setdefault("overlay_visible", self._is_visible(overlay["hwnd"]))
        state.setdefault("overlay_items", 0)
        state.setdefault("entry_tops", [])
        state.setdefault("entry_caption", self._get_text(entry["hwnd"]))
        observation = {
            "gesture": gesture,
            "gesture_failed": bool(gesture_failed),
            "overlay_visible": state["overlay_visible"],
            "overlay_visible_after": self._is_visible(overlay["hwnd"]),
            "overlay_hwnd": overlay["hwnd"],
            "overlay_rect": tuple(overlay["rect"]),
            "overlay_items": state["overlay_items"],
            "entry_hwnd": entry["hwnd"],
            "entry_rect": tuple(entry["rect"]),
            "entry_caption": state["entry_caption"],
            "entry_tops": state["entry_tops"],
            "overlay_closed": overlay["hwnd"] not in panels,
            "new_panels": [
                self._panel_observation(p, roles)
                for hwnd, p in panels.items()
                if hwnd not in before
            ],
            "dialog": None if panel is None else self._panel_observation(panel, roles),
        }
        self.last_entry_attempt = observation
        return observation

    def _require_visible_popup(self, entry: dict, overlay: dict) -> None:
        """Refuse to press an entry of a popup that is not **visible**.

        The handoff's hardest-won rule: this application pre-creates the ``Parameters``
        overlay in its control tree with ``IsWindowVisible == False`` and shows it on the
        hover, so a panel that is *present* is not a menu that is *open*. A press accepted
        on presence puts real or posted coordinates into empty screen — which is what a
        live run did — so the overlay and the entry are both required to report visible,
        and the panels that are in the tree but hidden are named in the refusal.
        """
        hidden = []
        if not self._is_visible(overlay["hwnd"]):
            hidden.append(overlay)
        if not self._is_visible(entry["hwnd"]):
            hidden.append(entry)
        if not hidden:
            return
        named = ", ".join(
            f"{k['cls']} at {k['rect'][:2]} (rect {k['rect']})" for k in hidden
        )
        others = [p for p in self._hidden_panels() if p["hwnd"] != overlay["hwnd"]]
        if others:
            named += (
                "; other panels present in the tree with IsWindowVisible == False: "
                + ", ".join(f"{p['rect']}" for p in others[:4])
            )
        raise AcquisitionError(
            f"refusing to press the popup entry: {named} reports IsWindowVisible == False, "
            "so the overlay in the control tree is not a menu that is on screen — this "
            "application pre-creates that panel and shows it on the hover, and a press on "
            "a panel that is only *present* lands on whatever is painted there"
        )

    def _press_entry(self, entry: dict, overlay: dict) -> dict | None:
        """Take one popup entry; return the dialog it opened, or ``None``.

        The **posted held press** on the entry's own handle is the gesture
        (:meth:`_click_hold`): the reference's own ``click_hold(entry_hwnd)``, which opened
        ``Operating parameters``, read the dialog, changed a combo and accepted, repeatedly
        (``recon/41_burst_sampling_volume.py``). It is neither a cursor move nor a click,
        and there is deliberately no second gesture and no ``allow_real_input`` gate here:
        the entry needs no cursor, and a re-derived alternative gesture is what three fix
        cycles went into.

        The press is **refused** unless the overlay and the entry both report visible
        (:meth:`_require_visible_popup`) — the live failure was a press aimed at a
        pre-created panel that was not on screen.

        Whatever happens, the attempt is **observed**
        (:meth:`_observe_entry_attempt`): the popup's visibility, its state, any panel that
        appeared, and that panel's rect and top-level child classes go on
        :attr:`last_entry_attempt` — on success and on failure alike, and also when the
        gesture itself raised — because the next live run must be told what the
        application did, not merely that the step failed.

        Nothing here presses anything *inside* a dialog: which dialog opened is the
        caller's question, and it answers it structurally and by content.
        """
        before = set(self._panel_map())
        gesture = GESTURE_POSTED_PRESS
        # Read what the overlay offers *now*: the press closes it, and the entries are gone
        # from the visible tree by the time the outcome is recorded.
        pressed = self._pressed_state(entry, overlay)
        try:
            self._require_visible_popup(entry, overlay)
            self._click_hold(entry["hwnd"])
        except AcquisitionError:
            self._observe_entry_attempt(
                entry, overlay, before, gesture, None, gesture_failed=True, pressed=pressed
            )
            raise
        panel = self._poll_dialog(_ENTRY_DIALOG_TIMEOUT_S)
        self._observe_entry_attempt(
            entry, overlay, before, gesture, panel, pressed=pressed
        )
        return panel

    def _close_wrong_dialog(self, panel: dict) -> None:
        """Close a dialog that is not the operating one with its **LEFT** button.

        Never its right-hand/default button: on a parameters dialog that button *accepts*
        the dialog's values, and this is precisely the dialog whose identity is not yet
        established — a default parameters dialog's Accept is a change nobody asked for.
        The leftmost button of the bottom row is ``Cancel`` on every dialog this
        application paints (:func:`_bottom_row`, :data:`…actuator.DialogControl.SAFE`).
        A close that does not resolve is noted, never raised through: the caller still has
        entries to try, and the bounded loop is what keeps that safe.
        """
        try:
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.SAFE)
            self._note(
                f"a dialog without the channel combo was up at {panel['rect'][:2]}; closed "
                "it with its left button — never its default button"
            )
        except AcquisitionError as exc:
            self._note(f"a dialog without the channel combo could not be closed: {exc}")

    def _open_parameters_dialog(self) -> dict:
        """Open ``Parameters → Operating parameters`` and return the dialog's panel.

        The dialog is a modal overlay reached through the menubar — not a sidebar
        control, and not a top-level window (``EnumWindows`` finds nothing: the app's
        dialogs are child panels, docs/16 §6).

        Nothing on this path matches a control by its caption, and nothing can: this
        application's widgets are caption-less (``GetWindowText`` is empty for all of them
        — the live read of the open popup showed the overlay panel and its five entries
        with empty captions), which is why a title lookup found no entry at all. What
        identifies each thing instead:

        1. the **overlay** is the panel that became *visible* on the hover
           (:meth:`_poll_parameters_overlay`, with the reference's ``left == 169 and
           h > 120`` rect as the fallback when the appearance diff is ambiguous). The panel
           this application pre-creates and hides is not an overlay: presence is not
           visibility, and a popup whose panel reports ``IsWindowVisible == False`` is
           refused by name rather than pressed into (:meth:`_require_visible_popup`);
        2. the **entries** are the ``TSp_Button`` widgets lying inside that overlay,
           ordered by screen ``top`` — the first is ``Operating parameters``
           (:func:`_entry_buttons`; enumeration order is not screen order) — and an entry
           is taken with the **posted held press on its own handle** (:meth:`_press_entry`,
           the reference's own gesture). Every attempt records what the application did
           (whether the overlay was visible, whether the popup closed, any panel that
           appeared, its rect and its top-level child classes —
           :attr:`last_entry_attempt`) and the failure below reports that record;
        3. the **dialog** is found **structurally** (:meth:`_dialog_panels`: a panel
           wider than :data:`_DIALOG_MIN_W` that is not the parameter column and is full
           of controls — the reference's own ``find_dialog`` predicate), and among dialogs
           the operating one is the one holding the **channel combo**
           (:meth:`_channel_combo` — a ``TComboBox`` listing ``'1'``..``'10'``, wherever
           the dialog nests it). An entry whose dialog does not hold it is tried past:
           that dialog is closed with its **left** button
           (:meth:`_close_wrong_dialog`, never its Accept, which on a parameters dialog is
           what would commit whatever it holds), and the next entry by screen order is
           pressed. A bounded number of entries is tried; when none yields the operating
           dialog the failure is raised by name.

        The menu is opened by **hovering the menubar button with the operator's real
        cursor** (:meth:`_hover_centre`): this application's menubar ignores posted
        messages — a posted ``WM_MOUSEMOVE`` opened nothing and so did a posted press
        held for :data:`…actuator.PRESS_HOLD_MS` (two live runs, both aborting safely) —
        while the same button opened its menu under a real cursor in
        ``recon/41_burst_sampling_volume.py``. Nothing posts a message to the menubar any
        more. The cursor stays on the button through the poll for the popup — a
        hover-opened popup can be dismissed by moving the cursor off the menubar — and is
        put back once the entry has been taken, or the attempt has failed
        (:meth:`_restore_cursor`). Both moves go through :meth:`_move_real_cursor`, which
        clears the clip this application sets on an open popup: a clipped restore is what
        put a live run's cursor in the menu's bottom-left corner, and a clipped hover is
        what made the button unreachable at ``(204, 40)``.
        ``allow_real_input=False`` refuses this step by name instead — never falling
        back to the posted press, which is known not to open this menu.
        """
        if not self._allow_real_input:
            raise AcquisitionError(
                f"the {PARAMETERS_MENU!r} menu cannot be opened without real input: this "
                "application's menubar ignores posted messages, so its button is hovered "
                "with the operator's real cursor (SetCursorPos + mouse_event) and there "
                "is deliberately no posted fallback — allow_real_input=False, so nothing "
                "was moved on this unattended or locked desktop"
            )
        roles = self._resolve()
        if roles["open_popup"]:
            raise AcquisitionError(
                "a menu popup is already open; the entry press would be unreliable — "
                "close it from the UI, this driver never WM_CLOSEs a popup"
            )
        menu = (roles.get("menu") or {}).get(PARAMETERS_MENU)
        if menu is None:
            # The anchor is proven where it is *resolved* and nowhere else: ``_resolve`` publishes
            # no binding for a bar the signature cannot show, so this method has nothing to hover
            # (ledger B03, and the anchor rule itself is ``ui/menu.py``'s
            # :func:`…ui.menu.anchor_clause`). Naming the pure clause here is not a second rule —
            # it is the diagnosis, and it is produced *before* the cursor is read, moved and
            # parked on a menubar button.
            clause = anchor_clause(observation_of(roles))
            raise AcquisitionError(
                f"no {PARAMETERS_MENU!r} button in the menubar"
                + (f": {clause}" if clause else "")
            )
        # The hover's precondition, asserted before the cursor is moved: this application
        # ignores a hover while it is inactive, so a window in front turns the one gesture
        # that opens this menu into a no-op that reads like a broken gesture (measured
        # live 2026-09-17: a console window in front, no popup, nothing pressed).
        self._require_foreground(roles["window"])
        saved = self._cursor_position()
        sidebar_before = bool(roles.get("params"))
        try:
            # The snapshot is taken *before* this hover, so "visible after, not before" is
            # a statement about *this* attempt: a popup panel a previous attempt left
            # hidden is not in the set, and one the app reuses without hiding it falls back
            # to the recorded rect below.
            before = self._panel_map()
            self._hover_centre(menu["hwnd"])  # the popup opens on this real hover
            overlay = self._poll_parameters_overlay(before)
            entries = _entry_buttons(overlay, self._resolve()["raw"])
            if not entries:
                raise AcquisitionError(
                    f"the {PARAMETERS_MENU!r} popup holds no entries to press; the entry is "
                    "the ``TSp_Button`` inside the overlay, ordered by screen top — "
                    f"{_observation_text(self.last_entry_attempt)}"
                )
            # **The topmost entry, and no other.** It is ``Operating parameters``; the ones
            # below it are ``Default parameters``, ``Save parameters``, ``Recall
            # parameters`` and the trigger parameters — and pressing *Default parameters*
            # **selects the assisted mode** (manual doc 04: "the default parameters select
            # the assisted mode"), which this application switches on silently while the
            # popup is up. A retry that walks down the popup therefore changes the
            # instrument's state in order to recover from a transient failure: the stored
            # `assisted Mode` word read 0 in every file up to 19:01 and 1 by 21:26, in a
            # window whose only presses were this driver's. The reference never pressed
            # more than the entry it meant (`recon/41_burst_sampling_volume.py`).
            entry = entries[0]
            panel = self._press_entry(entry, overlay)
            if panel is None:
                raise AcquisitionError(
                    f"the topmost {PARAMETERS_MENU!r} popup entry at {entry['rect'][:2]} "
                    "opened no dialog, and no lower entry is pressed on purpose: the second "
                    "one is 'Default parameters', which selects the assisted mode — "
                    f"{_observation_text(self.last_entry_attempt)}"
                )
            try:
                self._channel_combo(panel)
            except AcquisitionError as exc:
                self._close_wrong_dialog(panel)
                raise AcquisitionError(
                    f"the topmost {PARAMETERS_MENU!r} popup entry at {entry['rect'][:2]} "
                    f"did not open the {PARAMETERS_ENTRY!r} dialog (the one holding the "
                    f"channel combo): {exc} — "
                    f"{_observation_text(self.last_entry_attempt)}"
                ) from exc
            self._assert_assisted_unchanged(sidebar_before)
            return panel
        finally:
            # The menu has been used (or the attempt is over, hover or press): the
            # operator's cursor goes back, so no path leaves it parked on the menubar.
            self._restore_cursor(saved)

    def _assert_assisted_unchanged(self, sidebar_before: bool) -> None:
        """Refuse when this interaction switched the assisted mode **on** by itself.

        The mode is the application's own state and this driver never sets it — but a press
        one entry low in the ``Parameters`` popup does: the second entry is ``Default
        parameters`` and the default parameters select the assisted mode. The visible
        consequence is that the sidebar parameter column goes away (43 visible controls in 4
        panels become 21 in 3) and every parameter write loses its target, so the point is
        already lost: this raises *now*, naming the cause, instead of a sweep failing later
        with a message about a missing field.

        A mode that was already on when the interaction started is not this driver's doing
        and is not raised here — :meth:`ensure_channel` records which mode the channel's
        panel came up in, and a point on an assisted channel is refused by the parameter
        write itself, with the mode named.
        """
        if not sidebar_before:
            return
        if self._resolve().get("params"):
            return
        raise AcquisitionError(
            "the assisted mode was switched ON during this menu interaction: the sidebar "
            "parameter column is gone, which is what this application does when the assisted "
            "mode is on (43 visible controls in 4 panels -> 21 in 3). The second entry of the "
            f"{PARAMETERS_MENU!r} popup is 'Default parameters', and the manual's rule is "
            "'the default parameters select the assisted mode' — while the application "
            "highlights that very entry by itself, so any press one entry low turns the mode "
            "on silently. Nothing has been written to the instrument by this driver, which "
            "does not leave the assisted mode either: its own toggle is the application's "
            "Preference menu, so an operator has to clear it before the point can be made"
        )

    def _close_parameters_dialog(self, panel: dict) -> None:
        """Close the dialog with its LEFT button (``Cancel``), never a window close.

        The app confines the cursor to its dialogs, so an open one traps the operator
        (docs/16 §6); a panel whose bottom row cannot be resolved is noted instead of
        raising, so a failed point is never masked by a failed cleanup.
        """
        try:
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.SAFE)
        except AcquisitionError as exc:
            self._note(f"the {PARAMETERS_ENTRY!r} dialog could not be closed: {exc}")

    def ensure_channel(self) -> int:
        """Make the application measure on the configured channel, and prove it took.

        Called before **every** point, because the channel is what decides which
        channel's block the stored file carries — and a point recorded on the wrong
        channel decodes as a perfectly valid point that is not the point (docs/16 §12,
        the channel trap). The order is the load-bearing part:

        1. open ``Parameters → Operating parameters`` — the menubar button is
           **hovered with the operator's real cursor** (:meth:`_hover_centre`: this
           application's menubar answers nothing posted), the popup is identified as the
           panel that became **visible** on that hover, its caption-less entries are taken
           in **screen order** (the first is ``Operating parameters``) with a **posted held
           press on the entry's own handle** — the reference's own gesture
           (``recon/41_burst_sampling_volume.py``), and the one step in this cycle that
           needs no cursor at all — and the cursor is put back once an entry has been
           taken, clearing the clip the open popup sets first so the restore is not
           clamped into it. The dialog an entry opened is identified **structurally**, not
           by a caption and not by the channel combo: a dialog that does not hold the
           channel combo is closed with its LEFT button and the next entry in screen order
           is tried;
        2. find the channel combo *structurally* (see :meth:`_channel_combo`);
        3. read the channel back from the dialog; if it is not the configured one,
           write the selection (``CB_SETCURSEL`` + ``CBN_SELCHANGE``, no Enter) and
           read it back **again** — a combo write can silently not apply (docs/16 §2);
        4. accept the dialog, then re-open it and read the selection again: only the
           re-opened dialog shows what the *application* kept, not what the control
           believes;
        5. close it with the left button.

        Returns the verified channel. Any step that cannot be verified raises
        :class:`AcquisitionError` naming what was asked for and what the dialog showed,
        which fails the point — recording on an unverified channel is the worst outcome
        this driver can produce.
        """
        wanted = self._channel_setting
        panel = self._open_parameters_dialog()
        try:
            combo, parent = self._channel_combo(panel)
            index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                self._note(
                    f"the {PARAMETERS_ENTRY!r} dialog reads channel index {index} "
                    f"({text!r}), not channel {wanted.channel} (combo index "
                    f"{wanted.combo_index}): writing the selection"
                )
                self._combo_select(combo["hwnd"], wanted.combo_index, parent)
                # **Re-resolve the dialog here.** Measured live 2026-09-17: changing the
                # channel makes this application *replace* its parameters dialog — channel 2
                # is in assisted mode, so the write closed `Operating parameters`
                # (627x384, 21 children) and opened `Assisted mode parameters for channel 2`
                # (511x384, 14 children, a block slider) — and every handle taken before the
                # write is then dead. The reference re-resolved at exactly this point
                # (`find_dialog(resolve()) or dlg`, `recon/41_burst_sampling_volume.py`); the
                # port kept the old panel and pressed a window that no longer existed, which
                # left the new dialog on the operator's screen with nothing able to close it.
                replaced = self._poll_dialog(_DIALOG_REPLACE_S)
                if replaced is not None:
                    if replaced["hwnd"] != panel["hwnd"]:
                        self._note(
                            "the application replaced its parameters dialog after the "
                            f"write: {panel['rect'][:2]} -> {replaced['rect'][:2]} — every "
                            "handle taken before the write is dead, so the read-back and the "
                            "accept use the re-resolved panel"
                        )
                    panel = replaced
                mode = panel_mode(
                    panel, self._children_of(panel["hwnd"], self._resolve())
                )
                self._note(
                    f"channel {wanted.channel}'s parameters panel is the {mode!r} one "
                    f"(application's own statement, read from the panel it built)"
                )
                combo, _parent = self._channel_combo(panel)
                index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                raise AcquisitionError(
                    f"the measurement channel was not selected: channel {wanted.channel} "
                    f"(combo index {wanted.combo_index}) was requested in the "
                    f"{PARAMETERS_ENTRY!r} dialog, but the dialog reads back index {index} "
                    f"({text!r}) — recording here would store another channel's block"
                )
            kids = self._children_of(panel["hwnd"], self._resolve())
            self._dialog_button(panel, kids, DialogControl.CONFIRM)  # accept the dialog
        except BaseException:
            # Re-resolved, not the handle held: the application may have replaced the dialog
            # under us (it does on a channel write), and a close on a dead handle presses
            # nothing and leaves the dialog on the operator's screen.
            self._close_any_dialog()
            raise
        confirmed = self._open_parameters_dialog()
        try:
            combo, _parent = self._channel_combo(confirmed)
            index, text = self._channel_readback(combo)
            if not self._channel_matches(index, text):
                raise AcquisitionError(
                    f"the application did not keep the measurement channel: channel "
                    f"{wanted.channel} (combo index {wanted.combo_index}) was selected and "
                    f"accepted, but a re-opened {PARAMETERS_ENTRY!r} dialog reads back index "
                    f"{index} ({text!r})"
                )
        finally:
            self._close_any_dialog()
        return wanted.channel

    # ------------------------------------------------------------------ Actuator

    # ------------------------------------------------------------- the read-only surface

    def window_caption(self) -> str:
        """The top-level window's caption, read with ``WM_GETTEXT`` — nothing is pressed.

        The one surface that states **which process** is on the screen (:class:`ProcessMode`):
        the simulator's own name or the measurement application's, and every widget inside the
        window is caption-less, so nothing structural answers the same question (plan §22.1).
        Read rather than interpreted: the vocabulary is applied by
        :func:`~udv_echo_process.acquire.actuator.process_mode`, and the string itself is carried
        into the reading so a refusal can name it.
        """
        return self._get_text(self._main_hwnd())

    def screen_fingerprint(self) -> ScreenFingerprint:
        """What the screen is right now, without pressing anything.

        The first thing to read on an instrument nobody here can see
        (``docs/dop3000/live-bringup.md`` §3, stage 1): the counts are **evidence** (the reference
        install reads 43 in 4, the instrument 44 in 4, and both are clean — plan §24.5 D4), the
        shape verdict and the stated process mode are the *verdict*, the strip view says which of
        the three buttons means what, and the overlay says whether a modal is up while it should
        not be. Nothing is pressed, no dialog is opened and nothing is written, so it is safe to
        take on an instrument someone else is using — which is the whole reason it exists as a
        supported call.

        A screen that cannot be resolved at all *does* raise, from :meth:`_resolve`: no window
        is an answer the caller has to see. An unreadable cursor does not — it comes back
        ``None``, because this driver's own shell runs in a service session where
        ``GetCursorPos`` fails with error 1459.
        """
        roles = self._resolve()
        hwnd = self._main_hwnd()
        win32gui, _ = _gui()  # loaded here, like every other win32 use in this module
        user32 = ctypes.windll.user32  # this build of pywin32 has no IsZoomed/GetSystemMetrics
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        try:
            cursor: tuple[int, int] | None = self._cursor_position()
        except Exception:  # noqa: BLE001 - a cursor this session cannot read is not a fault
            cursor = None
        try:
            foreground = self._foreground_window() == hwnd
        except Exception:  # noqa: BLE001 - the foreground is a precondition of presses, not of reading
            foreground = False
        # Read, not inferred: which process is in front is stated by the caption alone, and the
        # shape verdict and the counts come off the tree that was already resolved above (plan
        # §24.4, §24.5 D4 — a diagnostic reports the mode, it never refuses on it).
        caption = self.window_caption()
        return ScreenFingerprint(
            class_name=self._class_name,
            hwnd=hwnd,
            rect=(left, top, right, bottom),
            maximized=bool(user32.IsZoomed(hwnd)),
            screen=(user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)),
            panels=len(roles["panels"]),
            visible_controls=len(roles["raw"]),
            # Through the public primitive rather than `_state_of(roles)` directly: it is the
            # same read (`strip_state()` is `_state_of(_resolve())`), and it is the one a faked
            # actuator can answer — the point of this method existing at all is that it is
            # testable off the instrument.
            strip=self.strip_state(),
            # The detector the *cycle* uses (`_peek_overlay`), not the rect-rule finder: what
            # a reader needs to know is whether a modal is up that the next step would trip on.
            overlay=self.peek_overlay(),
            layout_note=self.layout_note(),
            caption=caption,
            process_mode=process_mode(caption),
            layout_shape_reasons=tuple(roles["layout_shape_reasons"]),
            layout_evidence=str(roles["layout_evidence"]),
            cursor=cursor,
            is_foreground=foreground,
        )

    def read_dialog_parameters(self) -> DialogParameters:
        """Read the sound speed, the first gate and the burst length off the ``Parameters`` dialog.

        **Which surface.** These three facts are the ones no measurement-screen surface states:
        they are not parameter-column roles (the column is the surface a *point* writes, and a
        point never writes them), they live in the ``Operating parameters`` dialog only, and they
        are stated **for the channel that dialog is showing**. So the read has to open the dialog
        and has to say whose parameters it described — both of which are carried in the reading
        (:class:`~udv_echo_process.acquire.snapshot.DialogParameters`).

        **How.** The routing step's own gesture: hover the menubar button with the operator's real
        cursor and press the topmost entry (:meth:`_open_parameters_dialog`), read the table, and
        close the dialog with its own left button in a ``finally``. The close is not housekeeping:
        an open dialog confines the cursor to itself and traps the operator, and **Escape closes
        nothing in this application** (reported 2026-09-18, and noted before).

        **What is checked before any value is believed.** A field's identity here is a *position*
        (:data:`DIALOG_FIELD_ORDER`), so a dialog that is not the table those bindings were
        measured against would hand the compile a plausible wrong fact — the one failure a
        pre-run check must not have. Three checks stand between the two:

        * the table **filled**: an application that has just started builds this table *empty* the
          first time the dialog is opened and states it on the next open (measured 2026-09-18 —
          the first-open table read 2 stating controls where the second read 22), so the read polls
          rather than recording an empty dialog as a filled one;
        * the table's **shape** is the measured one (:data:`DIALOG_COLUMN_ROWS`), and it states
          the channel it is showing in its header combo;
        * every **anchor** (:data:`DIALOG_ANCHORS`) reads the same text the measurement screen
          reads, which is what makes the positions evidence rather than habit.

        **What it does when it refuses.** It returns an unreadable reading whose reason names what
        happened — a dialog that never filled, a shape that is not this table, an anchor that
        disagrees with the screen, a header that does not resolve, a gesture that failed (noted in
        the run log as well). It never raises for those, and it never invents a value: the facts
        stay ``unreadable`` in the snapshot, and the compile refuses on them.
        """
        try:
            panel = self._open_parameters_dialog()
        except AcquisitionError as exc:
            self._note(f"the {PARAMETERS_ENTRY!r} dialog could not be opened for a read: {exc}")
            return DialogParameters(
                reason=f"the {PARAMETERS_ENTRY!r} dialog could not be opened: {exc}"
            )
        try:
            fields = self._poll_dialog_fields(panel)
            channel = self._dialog_channel_text(self._descendants_of(panel["hwnd"]), fields)
            refusal = self._dialog_refusal(fields, channel)
            if refusal:
                return DialogParameters(channel=channel, reason=refusal)
            return DialogParameters(
                channel=channel,
                fields=tuple(
                    (field.value, self._text_at(fields, column, row))
                    for field, column, row in DIALOG_FIELD_ORDER
                ),
            )
        finally:
            self._close_parameters_dialog(panel)

    def _descendants_of(self, hwnd: int) -> list[dict]:
        """Every descendant of ``hwnd``, walked live — because the dialog's values are one level in.

        The resolver's own ``raw`` list stops at the **direct** children of a panel, and this
        dialog states nothing at that level: measured on the running application 2026-09-18, the
        ``Operating parameters`` dialog's 21 direct children are its 15 ``TSp_Value_Button``
        widgets, its header and its bottom buttons, and *no* control among them carries a value.
        The walk is :func:`~udv_echo_process.acquire.win32.tree._descendants_of`; rows carry what
        the rest of the driver's rows carry, and the text is read separately by whoever needs it.
        """
        return _descendants_of(hwnd, gui=_gui)

    def _poll_dialog_fields(self, panel: dict) -> list[dict[str, object]]:
        """The dialog's value table, re-read until it states something or the wait runs out.

        The application fills this table a moment after the dialog appears — and *not at all* the
        first time it is opened on a freshly started application (measured). Reading it once, the
        moment it appears, is therefore the difference between three read facts and three facts
        recorded as unreadable on an instrument that states them perfectly well.
        """
        deadline = time.monotonic() + DIALOG_FILL_TIMEOUT_S
        while True:
            fields = dialog_value_fields(self._descendants_of(panel["hwnd"]), self._get_text)
            if any(row["value"] for row in fields) or time.monotonic() >= deadline:
                return fields
            time.sleep(_POLL_S)

    def _text_at(self, fields: Sequence[Mapping], column: int, row: int) -> str:
        """The text stated at ``(column, row)`` of the dialog's table, or ``\"\"``.

        The lookup itself is ``ui/dialog.py``'s (:func:`…ui.dialog.text_at`); the read is this
        method's, because it is the one that needs a window.
        """
        return text_at(fields, column, row, self._get_text)

    def _dialog_channel_text(self, kids: Sequence[Mapping], fields: Sequence[Mapping]) -> str:
        """The channel the dialog is showing, read from its header combo.

        The header is the combo that is **not** a table row (measured: it sits at the dialog's top,
        ``top`` 373 against the table's 443). It is read because the dialog — not the caller — is
        the surface that decides whose parameters are shown: a reading that did not carry it would
        let a compile compare one channel's sound speed against another channel's run, which is the
        channel trap this driver already refuses to make when it stores a block (docs/16 §12).

        Which combo that is, is ``ui/dialog.py``'s rule (:func:`…ui.dialog.dialog_channel_text`);
        the read itself is this method's.
        """
        return dialog_channel_text(kids, fields, self._get_text)

    def _dialog_refusal(self, fields: Sequence[Mapping], channel: str) -> str:
        """Why no dialog-only fact may be believed, or ``\"\"`` when the reading may be trusted.

        Every refusal is written out in full rather than summarised: the reason lands in a run
        record read by someone with no instrument in front of them, and "the dialog did not read"
        would leave them unable to tell a stale binding from an application that was busy.

        The three checks themselves — the table filled, the table's shape, and every anchor reading
        the same text the screen reads — are ``ui/dialog.py``'s
        (:func:`…ui.dialog.dialog_refusal`); what stays here is the two reads that need a window:
        the dialog's own text (``self._get_text``) and the measurement screen's
        (:meth:`_screen_anchor_text`). ``DIALOG_FILL_TIMEOUT_S`` is read here, at call time, so the
        reason a reading gives always names the wait this run actually performed.
        """
        return dialog_refusal(
            fields,
            channel,
            read_text=self._get_text,
            screen_text=self._screen_anchor_text,
            timeout_s=DIALOG_FILL_TIMEOUT_S,
        )

    def _screen_anchor_text(self, role: ParamRole) -> str:
        """The measurement screen's own text for an anchor role, or ``\"\"`` when it states none.

        The other half of an anchor check: the dialog's value at the same ``(column, row)`` has to
        be the text the parameter column itself reads for that role, which is what makes a
        positional binding evidence rather than habit (``ui/dialog.py``'s
        :func:`…ui.dialog.dialog_refusal`, :data:`…actuator.DIALOG_ANCHORS`).
        """
        screen = (self._resolve().get("params") or {}).get(role)
        return "" if screen is None else self._get_text(screen["edit"]["hwnd"])

    def instrument_snapshot(
        self,
        *,
        routed_channel: int | None,
        dialog_parameters: DialogParameters | None = None,
    ) -> InstrumentSnapshot:
        """Read the instrument's current state, pressing nothing that changes it.

        Read-only with respect to the configuration — it writes no parameter, accepts no dialog
        and selects no channel — and narrower than that even: it presses **nothing at all**. The
        screen fingerprint and the parameter column are read off the resolved control tree (the
        same reads :meth:`screen_fingerprint` and :meth:`read_parameter` make), and the menubar
        hover that *reading the channel* would cost is deliberately not paid
        (:meth:`_channel_fact`). An instrument somebody else is using is therefore safe to read
        this way.

        The channel and the dialog-only facts are the two things this reading cannot establish for
        itself, so neither is asked for — each is **handed over**: ``routed_channel`` is the
        channel :meth:`ensure_channel` selected and read back, and ``dialog_parameters`` is what
        :meth:`read_dialog_parameters` read while the ``Operating parameters`` dialog was open.
        Both are keyword-only, and only the channel is required, because that is the difference
        between a caller that *cannot* have established a fact and one that merely did not:
        routing always happens before a run, while the dialog read is a step a caller may not have
        paid for. A caller that established nothing passes ``None`` — or omits it — and the facts
        are carried as ``unreadable``, with the reason saying what no step established. A default
        per fact would let a caller leave a verification implied that never happened, which is the
        one thing a reading must never do.

        There is one more thing the two handed-over values give this reading, and it is not a
        fact: they meet nowhere else, which is why the one check that compares them lives here.
        The dialog-only facts belong to the channel the *dialog* states, while the recording
        lands on the channel the run routed, so a dialog on another channel would attach that
        channel's burst, sound speed and first gate to this reading — invisibly, since every
        value is a plausible number (:meth:`_require_same_channel`, plan §16.1).

        Two of the six fixed facts come off the column and are recorded as ``read``; three more are
        recorded as ``read`` when the dialog reading was handed over and the values came out of it;
        the block cap is carried as ``unreadable`` with its reason, because it is an application
        Preference and nothing in this driver reads the Preference surface. That asymmetry is the
        honest state today, and the fact that changes here is a fact about the *driver*: a read
        path that reconnaissance finds later becomes a read, without the models changing.

        The **process mode** is a third kind, and it belongs to this reading rather than to a
        hand-over: the caption costs no gesture at all, so this method reads it itself
        (:meth:`_process_mode_fact`) and carries it as a ``read`` fact — or as ``unreadable`` with
        the caption in the reason when the window states none this driver knows. It is what a
        resume compares instead of a count (plan §24.5, D2/D6).

        A screen that cannot be resolved at all raises, from :meth:`_resolve` — the same answer
        :meth:`screen_fingerprint` gives, for the same reason: no window is a fact the caller has
        to see.

        The screen is enumerated twice, once for the fingerprint and once for the mode, and that
        is the driver's standing habit rather than an oversight: everything here re-resolves
        instead of holding what it read a moment ago (the alternative — reading
        :attr:`last_roles` — would couple this method to the order of the calls inside
        :meth:`screen_fingerprint`), and anything that moved on screen between the two reads is
        a state the compile refuses on rather than one this recording can hide.
        """
        # Nothing is read, and no fact is attributed, until the dialog's own channel is known
        # to be the one this reading is for — the two values meet only here (plan §16.1).
        self._require_same_channel(routed_channel, dialog_parameters)
        fingerprint = self.screen_fingerprint()
        roles = self._resolve()
        mode = screen_mode(roles)
        return InstrumentSnapshot(
            fingerprint=fingerprint,
            channel=self._channel_fact(routed_channel),
            # The process mode comes off the caption, which costs no gesture at all — so unlike
            # the channel and the dialog facts it is *read* here rather than handed over, and a
            # caption that states nothing makes it `unreadable` with the caption in the reason
            # (plan §24.4: nothing may imply this verification).
            process_mode=self._process_mode_fact(),
            mode=(
                unreadable(
                    "no mode could be read from this screen: a dialog, a menu popup or a layout "
                    "this driver does not recognise is up, so the absent parameter column is "
                    "evidence about the screen and not about the channel's mode"
                )
                if mode is None
                else InstrumentFact(value=mode.value, source=FactSource.READ)
            ),
            prf_us=self._column_fact(roles, ParamRole.PRF),
            emissions_per_profile=self._column_fact(roles, ParamRole.EMISSIONS_PER_PROFILE),
            burst_length=_dialog_fact(dialog_parameters, DialogField.BURST_LENGTH),
            sound_speed_ms=_dialog_fact(dialog_parameters, DialogField.SOUND_SPEED_MS),
            first_gate_mm=_dialog_fact(dialog_parameters, DialogField.FIRST_GATE_MM),
            max_profiles_per_block=unreadable(
                "the block cap is an application Preference (\"Do not keep in a block more "
                "profiles than\"), not a measurement parameter, and nothing in this driver "
                "reads the Preference surface"
            ),
        )

    def _process_mode_fact(self) -> InstrumentFact:
        """Which process the caption states, as a fact of this reading — or why it states none.

        A ``read`` fact when the caption matches the fixed vocabulary
        (:func:`~udv_echo_process.acquire.actuator.process_mode`), and ``unreadable`` with the
        caption *in the reason* otherwise: an empty caption and a caption this driver was not
        measured against are two states a compile must refuse on by name, and neither may be
        defaulted into a mode (plan §24.4).
        """
        caption = self.window_caption()
        stated = process_mode(caption)
        if stated is None:
            names = [prefix for _mode, prefix in PROCESS_MODE_PREFIXES]
            return unreadable(
                "nothing stated the mode: the top-level window's caption is "
                f"{caption!r}, which names none of {names}"
            )
        return InstrumentFact(value=stated.value, source=FactSource.READ)

    def _require_same_channel(
        self, routed_channel: int | None, dialog_parameters: DialogParameters | None
    ) -> None:
        """Refuse a dialog reading that describes a channel this reading was not routed to.

        The dialog-only facts are read *for the channel the dialog states* and the point is stored
        on the channel the run routed. The two values meet only here, so this is the one place the
        mismatch can be caught before anything is attributed — and the one place it would otherwise
        be invisible: a channel-2 burst, sound speed and first gate attached to a channel-1 reading
        read as channel 1's parameters, in the record and in everything downstream of it (the
        wrong-channel trap, plan §14).

        What is **not** compared matters as much as what is. Nothing is compared when nothing was
        routed — there is no second channel to disagree with — and nothing is compared against a
        *refused* reading: a dialog that could not be opened, or stated no channel, already carries
        the reason it establishes nothing, and the campaign turns that reason into its own refusal.
        Raising here instead would replace a precise reader diagnostic with a vaguer error this
        method cannot substantiate, because a reading that failed established no channel's facts
        (plan §16.1).

        The comparison and its wording are ``ui/dialog.py``'s
        (:func:`…ui.dialog.channel_mismatch`), which returns the refusal instead of raising so the
        same rule holds for a fake, a fixture and this driver; this method is the raise.
        """
        refusal = channel_mismatch(routed_channel, dialog_parameters)
        if refusal is not None:
            raise AcquisitionError(refusal)

    def _channel_fact(self, routed_channel: int | None) -> InstrumentFact:
        """The channel, on the authority the caller hands over — never this reading's own.

        Reading the channel means opening ``Operating parameters``: a menubar hover with the
        operator's real cursor, which is the *routing* step's own gesture and by design happens
        before this snapshot (:meth:`ensure_channel`, which refuses a selection the application
        did not keep and leaves the dialog's read-back in the run log). Paying for a second
        dialog here would buy a number the run already holds — and on a channel in assisted mode
        it would buy nothing at all: that panel carries no channel combo to read.

        So the value can only come from the caller, and the caller has to say *what it
        established*: a verified channel is ``routed`` (the application's own dialog answered for
        it, to that step), and nothing established is ``unreadable`` with the reason. That is what
        stops a standalone call to :meth:`instrument_snapshot` from implying a verification that
        never ran.
        """
        if routed_channel is None:
            return unreadable(
                "no channel was established for this reading: the channel cannot be read off the "
                "measurement screen without the menubar hover this snapshot does not pay, and "
                "nothing has routed or verified one (ensure_channel) before it"
            )
        return routed(
            str(routed_channel),
            reason=(
                "the channel the routing step (ensure_channel) selected in the application and "
                "read back from its own dialog before this reading; this snapshot asked the "
                "application for no channel of its own"
            ),
        )

    def _column_fact(self, roles: dict, role: ParamRole) -> InstrumentFact:
        """One parameter-column field as a fact, or an unreadable fact saying why not.

        Read off the already-resolved role map rather than through :meth:`read_parameter`, which
        *raises* on a missing row. A column that is absent is not a failed binding here: it is a
        fact about the *screen* — the application builds it that way for a channel in assisted
        mode, and a manual channel whose fast-access panel is switched off in ``Preferences``
        paints the same screen (ledger B01) — and a snapshot exists to carry facts rather than to
        fail on them. The reason therefore states the absence and both of its causes, never one
        of them as the cause. A field that resolves but reads back empty is unreadable for the
        same reason a missing one is — an empty control stated nothing, and a value of ``""``
        recorded as ``read`` would claim it did.
        """
        row = roles.get("params", {}).get(role)
        if row is None:
            return unreadable(
                f"the parameter column holds no field for {role.value!r} on this screen: the "
                "fast-access panel is absent, which is what this application builds for a "
                f"channel in {MODE_ASSISTED} mode and also what a manual channel paints when "
                "the panel is switched off in Preferences (so the screen states no mode)"
            )
        text = self._get_text(row["edit"]["hwnd"])
        if not text.strip():
            return unreadable(
                f"the parameter column's field for {role.value!r} read back empty — an empty "
                "control states no value, so there is nothing to record as read"
            )
        return InstrumentFact(value=text, source=FactSource.READ)

    def preflight(
        self,
        duration_s: float = 2.0,
        *,
        expect_directory: Path | None = None,
    ) -> PreflightReport:
        """Run one whole cycle and throw the point away: record, stop, read the Store dialog, cancel.

        The operator's sequence with the one dangerous step removed — the Store dialog is
        answered with its **left** button, never its accept, so nothing is stored and no name is
        committed. Its purpose is the first contact with an instrument whose application has
        never been driven: the menubar, the strip, the store view and the Store dialog are the
        four things a run depends on, and this is the check that all four are reachable *before*
        a recording is spent on a point (`docs/dop3000/live-bringup.md` stage 3).

        ``expect_directory`` is the directory the caller believes the application stores into;
        the dialog's own working directory is compared with it rather than written (the cycle
        itself asserts and *writes* that field, which is exactly what a preflight must not do).
        Notes raised during the sequence are captured into the report as well as passed to the
        caller's sink, so a failure on a remote instrument can be read back afterwards.
        """
        captured: list[str] = []
        sink = self._note_sink

        def capture(message: str) -> None:
            captured.append(message)
            if sink is not None:
                sink(message)

        self._note_sink = capture
        try:
            state = self.strip_state()
            started_from = state.view.value
            if state.view is StripView.STORE:
                self.press(StripControl.NEW_ACQUISITION)
                self._note("a leftover store view was up: cleared and restarted")
                state = self.wait_for_view_guarded((StripView.READY,), VIEW_TIMEOUT_S)

            self.press(StripControl.RECORD)
            state = self.wait_for_view_guarded((StripView.RECORDING,), VIEW_TIMEOUT_S)
            view_after_record = state.view.value
            if state.view is not StripView.RECORDING:
                raise AcquisitionError(
                    f"the Record press did not start a recording (view {view_after_record!r})"
                )

            self.hold_recording(duration_s)
            self.press(StripControl.STOP)
            state = self.wait_for_view_guarded((StripView.STORE,), VIEW_TIMEOUT_S)
            view_after_stop = state.view.value
            if state.view is not StripView.STORE:
                raise AcquisitionError(
                    f"Stop did not reach the store view (view {view_after_stop!r})"
                )

            self.press(StripControl.DO_STORE)
            panel, kids = self._require_store_dialog()
            name_field = self._store_name_field(panel, kids)
            name_edit, path_edit = self._store_edits(panel, kids)
            store_name = self._get_text(name_field["hwnd"])
            first_edit = self._get_text(name_edit["hwnd"])
            working = None if path_edit is None else self._get_text(path_edit["hwnd"])
            matches: bool | None = None
            if working is not None and expect_directory is not None:
                matches = _same_directory(working, expect_directory)

            self._dialog_button(panel, kids, DialogControl.SAFE)
            time.sleep(_OVERLAY_SETTLE_S)
            view_after_cancel = self.strip_state().view.value
            return PreflightReport(
                started_from=started_from,
                view_after_record=view_after_record,
                held_s=duration_s,
                view_after_stop=view_after_stop,
                view_after_cancel=view_after_cancel,
                channel=self._channel_setting.channel,
                store_dialog_size=f"{panel['w']}x{panel['h']}",
                store_dialog_children=len(kids),
                store_name=store_name,
                store_first_edit=first_edit,
                store_working_directory=working,
                working_directory_matches=matches,
                notes=tuple(captured),
            )
        finally:
            self._note_sink = sink

    def layout_note(self, *, expected_mode: ProcessMode | None = None) -> str | None:
        """``None`` only on an accepted measurement shape; a refusal note otherwise.

        A popup, a dialog panel or a screen satisfying neither accepted shape means parameter
        roles may resolve to the wrong widgets, so a run must refuse to start. The note states
        **one clause per reason** (shape clause, overlay, and the mode when one was expected) and
        then the evidence — the counts, the panels and the strip's view — so the refusal is
        diagnosable from the log alone (plan §24.5, D5).

        ``expected_mode`` is the declaration a *record* path makes: when it is given, the
        window's caption is read and checked against it, and a mismatch or an unreadable caption is
        a clause of its own naming the caption it saw. ``None`` is the diagnostic reading
        (``acquire status``, the probes): the shape is still checked, the mode is only reported —
        a diagnostic that refused would be useless.
        """
        roles = self._resolve()
        overlay = self._find_overlay(roles)
        caption = self.window_caption() if expected_mode is not None else ""
        return layout_refusal(
            roles,
            overlay=None if overlay is None else overlay[0],
            caption=caption,
            expected_mode=expected_mode,
        )

    def process_mode_note(self, expected: ProcessMode) -> str | None:
        """A note when the screen's stated process mode is not ``expected``; ``None`` when it is.

        The runner's per-point gate (plan §24.4): the runner's own layout check answers *which
        shape*, and this answers *which process* — the one thing that cannot be checked
        structurally, because only the caption states it. It is a **composed** call on the sweep
        port rather than a new primitive, so an implementation that satisfied the primitive
        ``Actuator`` before this slice still does, and the run refuses a point measured against
        the other mode **before** it writes a parameter, not after.
        """
        return process_mode_clause(self.window_caption(), expected)

    def read_parameter(self, role: ParamRole | str) -> str:
        """The parameter column's current field text for ``role``.

        A missing row is not just a missing control: a screen with **no** fast-access parameter
        column has every role missing at once, and the failure says so. What it must not do is
        name a *mode* as the cause (ledger B01): the application removes the column for a channel
        in assisted mode, and it also paints the same screen for a manual channel whose panel is
        switched off in ``Preferences`` — so the failure names both readings
        (:meth:`_assisted_mode_clause`) and leaves the diagnosis to the operator who can see the
        checkbox.
        """
        wanted = self._as_role(role)
        row = self._resolve()["params"].get(wanted)
        if row is None:
            raise AcquisitionError(
                f"no parameter column field for {wanted.value!r}; only "
                f"{[r.value for r in PARAM_COLUMN_ORDER]} live in the column"
                f"{self._assisted_mode_clause()}"
            )
        return self._get_text(row["edit"]["hwnd"])

    def _assisted_mode_clause(self) -> str:
        """The explanation appended to a missing-parameter failure, when the panel is absent.

        Empty string when the panel resolved — the clause is a diagnosis, so it is only added
        when the evidence for it is on screen (no parameter column).

        **It does not assert a mode** (ledger B01): the absent panel is what this application
        paints for an assisted channel *and* what a manual channel paints with the fast-access
        panel switched off in ``Preferences`` (``UI-OVERLAY-06``), and the tree cannot tell the
        two apart. So the wording offers both readings and names the option that hides the
        panel; claiming assisted mode as a fact sent the operator to the channel's mode instead
        of to the checkbox. The wording lives in
        :func:`~udv_echo_process.acquire.ui.layout.parameter_panel_absent_clause` so the gate's
        clause and this failure cannot drift apart.
        """
        roles = self._resolve()
        if roles.get("params") or roles.get("param_rows"):
            return ""
        return parameter_panel_absent_clause(" — and ")

    def write_parameter(self, role: ParamRole | str, value: str) -> str:
        """Write one column field, commit it, and **return the app's read-back**.

        The read-back is the return value on purpose: a write is never assumed to have
        taken (the app trims gate counts to what fits, docs/07). Returning the text is a
        superset of the Protocol's ``None``.
        """
        wanted = self._as_role(role)
        row = self._resolve()["params"].get(wanted)
        if row is None:
            raise AcquisitionError(
                f"no parameter column field for {wanted.value!r}"
                f"{self._assisted_mode_clause()}"
            )
        win32gui, _ = _gui()
        edit = row["edit"]
        self._set_text_commit(edit["hwnd"], value, win32gui.GetParent(edit["hwnd"]))
        return self._get_text(edit["hwnd"])

    def apply_point(self, parameters: ParameterSet) -> dict[ParamRole, str]:
        """Apply a point's window in :func:`…actuator.ordered_writes` order.

        Resolution before gates, always: writing the resolution makes the app recompute
        the gate count, so the gate count must be the last request it sees (805 requested
        -> 474 accepted in the wrong order, docs/16 §14). Returns the read-back for every
        write, keyed by role.
        """
        readbacks: dict[ParamRole, str] = {}
        for role, value in ordered_writes(parameters):
            readbacks[role] = self.write_parameter(role, value)
        return readbacks

    def select_combo(self, name: str, index: int) -> None:
        """Select entry ``index`` of the named column combo (no Enter)."""
        combo = self._resolve()["combos"].get(name)
        if combo is None:
            raise AcquisitionError(f"no {name!r} combo in the parameter column")
        win32gui, _ = _gui()
        self._combo_select(combo["hwnd"], index, win32gui.GetParent(combo["hwnd"]))

    def set_store_name(self, name: str) -> None:
        """Write the Store dialog's file-name field with the commit recipe.

        The name field is the edit that does *not* hold a path; the path field is
        recognised by its separator, never by its position.
        """
        panel, kids = self._require_store_dialog()
        self._set_text_commit(
            self._store_name_field(panel, kids)["hwnd"], name, panel["hwnd"]
        )

    def assert_working_directory(self, directory: Path) -> str:
        """Assert the Store dialog's ``Working directory``, and set it when it differs.

        The field decides where the point lands, so it is never assumed: it is read,
        compared with ``directory`` (the path the caller will watch), written with the
        numeric/text commit recipe when it differs, and read **back** — because a write
        that did not commit leaves the application storing somewhere else while the
        control paints the new value (docs/16 §12a, §12b). Returns the verified text.

        An unresolved mismatch raises :class:`AcquisitionError` **naming both paths**,
        which fails the point: watching a folder the application is not writing to
        surfaces only as a false "no file appeared", minutes later, with nothing in it
        pointing at the real cause.
        """
        panel, kids = self._require_store_dialog()
        path_edit = self._store_edits(panel, kids)[1]
        if path_edit is None:
            edits = [
                self._get_text(k["hwnd"])
                for k in kids
                if k["cls"] in ("TEdit", "TSp_Edit")
            ]
            raise AcquisitionError(
                "the Store dialog shows no path-looking field, so its Working directory "
                f"cannot be asserted against '{directory}' (the dialog's edits are {edits})"
            )
        shown = self._get_text(path_edit["hwnd"])
        if same_directory(shown, directory):
            return shown
        self._set_text_commit(path_edit["hwnd"], str(directory), panel["hwnd"])
        readback = self._get_text(path_edit["hwnd"])
        if not same_directory(readback, directory):
            raise AcquisitionError(
                f"the Store dialog's Working directory is '{readback}' where '{directory}' "
                f"is expected (it showed '{shown}' before the write): the point would land "
                "outside the directory the caller watches, so it is refused rather than "
                "stored and waited for in the wrong folder"
            )
        self._note(
            f"the Store dialog's Working directory was {shown!r}; wrote {readback!r}"
        )
        return readback

    def commit_store(self) -> None:
        """Press the Store dialog's rightmost bottom button (``Do store``)."""
        panel, kids = self._require_store_dialog()
        self._dialog_button(panel, kids, DialogControl.CONFIRM)

    def wait_for_stored_file(
        self,
        directory: Path,
        *,
        known: Iterable[str],
        timeout_s: float = STORE_TIMEOUT_S,
    ) -> Path:
        """Wait for a file that was not in ``directory`` before, and return it.

        The *new name* is detected, never the arrival of any file. An overwrite warning
        means the name was taken and the store was refused, so this raises instead of
        returning a path — the caller retries under a fresh name.
        """
        path, kind = self._poll_new_file(directory, frozenset(known), timeout_s)
        if path is not None:
            return path
        if kind is OverlayKind.WARNING:
            self.answer_overlay()
            raise AcquisitionError(
                "the Store dialog raised its overwrite warning (the name is taken); answered "
                "with its safe button — retry under a fresh name"
            )
        raise AcquisitionError(
            f"no new file appeared in {directory} within {timeout_s:.0f} s of Do store"
        )

    # ------------------------------------------------------------------ cycle internals

    def _as_role(self, role: ParamRole | str) -> ParamRole:
        """Coerce to :class:`ParamRole`, refusing the dialog-only parameters by name."""
        if isinstance(role, ParamRole):
            return role
        key = str(role)
        if key in DIALOG_ONLY_PARAMETERS:
            extra = (
                " (read back only: the app derives it from the burst and the physics)"
                if key == "sampling_volume"
                else " (it has no column field at all)"
            )
            raise AcquisitionError(
                f"{key!r} is set in the Operating parameters dialog{extra}"
            )
        try:
            return ParamRole(key)
        except ValueError:
            raise AcquisitionError(
                f"unknown parameter role {key!r}; known roles are {[r.value for r in ParamRole]}"
            ) from None

    def _await_store_dialog(self, timeout_s: float) -> tuple[dict, list[dict]]:
        """Wait for the Store dialog, answering warnings that come up first."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            kind = self._peek_overlay()
            if kind is OverlayKind.STORE_DIALOG:
                return self._require_store_dialog()
            if kind is OverlayKind.WARNING:
                self._note("answered a warning before the Store dialog appeared")
                self.answer_overlay()
            time.sleep(_POLL_S)
        raise AcquisitionError("the Store dialog did not open after Do store")

    def _store_edits(self, panel: dict, kids: Sequence[dict]) -> tuple[dict, dict | None]:
        """The Store dialog's ``(name edit, path edit)``, top to bottom.

        The path field is recognised by its **separator** (``:`` or ``\\``), never by
        its position: which of the two edits is on top is not a fact this driver may
        assume. ``path`` is ``None`` when neither edit holds a path — a dialog that has
        never stored anything — which the caller reports rather than guesses around.
        """
        edits = sorted(
            (k for k in kids if k["cls"] in ("TEdit", "TSp_Edit")),
            key=lambda k: k["top"],
        )
        if len(edits) < 2:
            raise AcquisitionError(
                "the Store dialog does not show both a path and a name field"
            )

        def looks_like_a_path(k: dict) -> bool:
            text = self._get_text(k["hwnd"])
            return ":" in text or "\\" in text

        path_edit = next((k for k in edits if looks_like_a_path(k)), None)
        name_edit = next((k for k in edits if k is not path_edit), None)
        if name_edit is None:
            raise AcquisitionError("could not identify the Store dialog's name field")
        return name_edit, path_edit

    def _store_name_field(self, panel: dict, kids: Sequence[dict]) -> dict:
        """The Store dialog's file-name edit: the one whose text is not a path."""
        return self._store_edits(panel, kids)[0]

    @staticmethod
    def _names_in(directory: Path) -> frozenset[str]:
        """The directory's current entry names (empty when it does not exist yet)."""
        if not directory.is_dir():
            return frozenset()
        return frozenset(p.name for p in directory.glob("*"))

    def _poll_new_file(
        self, directory: Path, known: frozenset[str], timeout_s: float
    ) -> tuple[Path | None, OverlayKind | None]:
        """Poll for a name that was not in ``known``; report a warning instead of waiting."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while True:
            new = sorted(self._names_in(directory) - known)
            if new:
                return directory / new[0], None
            kind = self._peek_overlay()
            if kind is OverlayKind.WARNING:
                return None, kind
            if time.monotonic() >= deadline:
                return None, None
            time.sleep(_POLL_S)

    def _store_until_file(
        self, name: str, directory: Path, known: frozenset[str], timeout_s: float
    ) -> Path:
        """Wait for the file; on the overwrite warning answer ``No`` and retry once.

        The retry is the contract: the warning means the name was taken, and answering it
        with the LEFT button keeps the existing file — the point is stored again under a
        suffixed name, never over the old one (docs/16 §12b).
        """
        deadline = time.monotonic() + max(0.0, timeout_s)
        attempt = name
        retried = False
        while time.monotonic() < deadline:
            remaining = min(1.0, max(0.1, deadline - time.monotonic()))
            path, kind = self._poll_new_file(directory, known, remaining)
            if path is not None:
                return path
            if kind is not OverlayKind.WARNING:
                continue
            self.answer_overlay()  # LEFT button = No: never replace an existing file
            if retried:
                raise AcquisitionError(
                    "the store was refused twice by the overwrite warning; the name still collides"
                )
            retried = True
            attempt = f"{name}b"
            self._note(f"the name {name!r} was taken; retrying as {attempt!r}")
            self.set_store_name(attempt)
            self.commit_store()
        raise AcquisitionError(
            f"no file appeared in {directory} within {timeout_s:.0f} s of Do store"
        )

#: Import-time conformance check: this class must satisfy every Actuator method. Derived
#: from the Protocol itself, so it keeps holding if the Protocol grows.
_MISSING_METHODS = tuple(
    n
    for n in dir(Actuator)
    if not n.startswith("_") and not callable(getattr(Win32Actuator, n, None))
)
if _MISSING_METHODS:  # pragma: no cover - a wiring error, not a runtime case
    raise RuntimeError(
        f"Win32Actuator does not satisfy Actuator: missing {_MISSING_METHODS}"
    )
