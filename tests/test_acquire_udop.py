"""The udop package's boundary: the facade's composition, its published surface, its import hygiene.

Patch 4 split the live workflows out of the flat ``acquire/driver.py`` into
``acquire/udop/{parameters,recording,store,session}.py``. The cycle itself is pinned where it
always was — ``tests/test_acquire_driver.py`` drives ``Win32Actuator`` through the fake window, and
``tests/test_acquire_dialog.py`` the dialog reads — so nothing here re-implements a workflow. What
this module pins is the *composition* the move produced and the boundary it draws:

* ``Win32Actuator`` is one class whose methods are the surface modules' — the Parameters
  interaction in ``parameters.py``, the strip lifecycle in ``recording.py``, the Store dialog in
  ``store.py`` — and the facade's own reads, which live in ``acquire/driver.py``. A method that
  drifted to another surface, or a name two surfaces both claim, fails here by name.
* ``acquire.driver`` **is the facade module**: ``acquire/driver.py`` defines the class, so
  ``driver._gui``, ``driver._user32`` and ``driver._post`` (the names this repository's fakes
  script the window layer with) are the objects the facade's own bodies read — natively, not
  through ``sys.modules`` surgery. ``udop/session.py`` is the *compatibility name* of that facade:
  a documented re-export, so ``driver.Win32Actuator is session.Win32Actuator`` and every name the
  facade publishes resolves from both.
* the class's own 97 names are ``bfbbb10``'s recorded 96-name surface plus the one documented
  addition (``FLAT_CLASS_SURFACE`` / ``CLASS_ADDITIONS``), so a method that leaves the class fails
  here by name — the four lists alone cannot see that, being closed over themselves.
* every name ``driver.__all__`` publishes resolves from ``driver`` and from the compatibility name,
  and the re-exported names are the *same objects* their surface defines. The flat module's whole
  module-namespace is deliberately **not** claimed: six of the 145 top-level bindings ``bfbbb10``'s
  flat module published no longer resolve from ``driver`` (``ChannelMode``, ``STRIP_BUTTON_ORDER``,
  ``os``, ``pairwise`` from Patch 2's ``ui`` slice; ``NUMERIC_WRITE_RECIPE``, ``lru_cache`` from
  Patch 4), none of them read by any file in ``src/``, ``tests/`` or ``tools/`` through the driver —
  a narrowing that is named in ``docs/dop3000/acquisition-architecture.md`` §5 rather than rounded
  off.
* no module in the package imports ``campaign``/``runner``/``verify``/``plan``/``log``, none reaches
  the platform (``ctypes.windll``/``win32gui``/``win32con``) outside the facade's one named read,
  and the only edge back to the facade is the compatibility name — the graph is a DAG, checked by
  walking the ASTs.

The workflow timings the moved loops read (``DIALOG_FILL_TIMEOUT_S``, ``_ENTRY_DIALOG_TIMEOUT_S``,
``_DIALOG_REPLACE_S``, ``_MENU_TIMEOUT_S``, ``_MENU_POLL_S``, ``_OVERLAY_SETTLE_S``, ``_POLL_S``) are
*re-exported* from ``driver`` and are read by the surface whose loop uses them, so a patch that has to
*bite* is a patch on ``udop.parameters`` / ``udop.recording`` / ``udop.store`` — never on the facade's
copy of the value. **"Owner" is the definition, not the only binding:** ``from … import v`` copies the
reference at import time, so every importer holds a binding of its own and a rebinding on the
defining module reaches only that module's own loops. ``_POLL_S`` is defined once, in ``recording``,
and also bound by ``parameters``, ``store``, ``driver`` and ``session``; ``_OVERLAY_SETTLE_S`` is
read by ``recording``'s overlay waits *and* by the facade's own ``preflight``, each on its own
binding (``docs/dop3000/acquisition-architecture.md`` §5, which carries the same correction).
``KNOB_HOLDERS`` / ``KNOB_READERS`` and
``test_a_knob_binding_is_a_copy_so_only_the_module_that_reads_it_is_a_patch_target`` record both
facts — which modules hold a binding of each knob, and that rebinding the definition leaves the other
holders untouched — because an identity-only assertion cannot see either: for an immutable scalar
``getattr(driver, n) is getattr(owner, n)`` holds for every module that imported the same constant.
``test_every_name_the_facade_publishes_resolves_and_the_dropped_six_are_named`` states the identity
of the re-exported names and pins the six module-level names the flat module lost (listed in
``DROPPED_FROM_THE_FLAT_NAMESPACE``), and ``tests/test_acquire_driver.py`` /
``tests/test_acquire_dialog.py`` prove the patch targets.
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Iterator
from pathlib import Path

import pytest

from udv_echo_process.acquire import driver, udop
from udv_echo_process.acquire.actuator import Actuator
from udv_echo_process.acquire.udop import parameters, recording, session, store
from udv_echo_process.acquire.win32 import _acquisition_error

#: The surface each moved method belongs to, as Patch 4 cut it. Every name is a method of
#: ``Win32Actuator`` and is defined in exactly one of these modules.
PARAMETERS_METHODS = (
    "_open_parameters_dialog",
    "_assert_assisted_unchanged",
    "_close_parameters_dialog",
    "ensure_channel",
    "read_dialog_parameters",
    "write_dialog_burst_length",
    "_row_reading",
    "_row_reading_or_none",
    "_answer_burst_rejection",
    "_burst_refusal",
    "_poll_dialog_fields",
    "_text_at",
    "_dialog_channel_text",
    "_dialog_refusal",
    "_screen_anchor_text",
    "_close_any_dialog",
    "_panel_map",
    "_poll_parameters_overlay",
    "_dialog_panels",
    "_poll_dialog",
    "_panel_observation",
    "_pressed_state",
    "_observe_entry_attempt",
    "_require_visible_popup",
    "_press_entry",
    "_close_wrong_dialog",
    "_dialog_button",
    "_channel_combo",
    "_channel_readback",
    "_channel_matches",
)
RECORDING_METHODS = (
    "_state_of",
    "_find_overlay",
    "_peek_overlay",
    "strip_state",
    "wait_for_view",
    "press",
    "answer_overlay",
    "hold_recording",
    "wait_for_view_guarded",
    "peek_overlay",
    "_settle_press",
    "_wait_for_view_guarded",
    "_hold_recording",
    "record_and_store",
    "try_record_and_store",
    "_recover",
)
STORE_METHODS = (
    "_require_store_dialog",
    "set_store_name",
    "assert_working_directory",
    "commit_store",
    "wait_for_stored_file",
    "_await_store_dialog",
    "_store_edits",
    "_store_name_field",
    "_names_in",
    "_poll_new_file",
    "_store_until_file",
)
#: The facade's own: the transport, the cursor, the enumeration, the resolve, the class's state,
#: the read-only surface and the protocol surface. Defined in ``acquire/driver.py`` — the module
#: ``acquire.driver`` *is*.
FACADE_METHODS = (
    "__init__",
    "_note",
    "_send",
    "_get_text",
    "_control_id",
    "_set_text_commit",
    "_combo_select",
    "_click_hold",
    "_clip_rect",
    "_release_clip",
    "_cursor_position",
    "_restore_cursor",
    "_move_real_cursor",
    "_foreground_window",
    "_thread_of",
    "_activate_window",
    "_require_foreground",
    "_hover_centre",
    "_main_hwnd",
    "_children_of",
    "_param_rows",
    "_resolve",
    "_has_slider",
    "_is_visible",
    "_hidden_panels",
    "_descendants_of",
    "window_caption",
    "screen_fingerprint",
    "instrument_snapshot",
    "_process_mode_fact",
    "_require_same_channel",
    "_channel_fact",
    "_column_fact",
    "channel",
    "_combo_index",
    "_combo_items",
    "preflight",
    "layout_note",
    "process_mode_note",
    "read_parameter",
    "_assisted_mode_clause",
    "write_parameter",
    "apply_point",
    "select_combo",
    "_as_role",
)
SURFACES = {
    parameters: PARAMETERS_METHODS,
    recording: RECORDING_METHODS,
    store: STORE_METHODS,
    driver: FACADE_METHODS,
}

#: ``Win32Actuator``'s own method names at ``bfbbb10`` — the freeze commit of
#: ``docs/dop3000/acquisition-architecture.md`` §4, read out of the flat module before any of it was
#: split (``git show bfbbb10:src/udv_echo_process/acquire/driver.py``, the class's ``FunctionDef``
#: names, docstrings and decorators excluded). Recorded here on purpose: the four lists above are
#: closed over *themselves*, so ``own == set(claimed)`` passes when a name is deleted from the class
#: **and** from its list — which is how ``_has_slider`` left the class in Patch 2's ``ui/strip.py``
#: slice and stayed gone until ``0bbcc68`` restored it as a seam over ``ui/strip.has_slider``. This
#: set is the baseline that makes such a removal fail by name.
FLAT_CLASS_SURFACE = frozenset(
    {
        "__init__", "_note", "_send", "_get_text",
        "_control_id", "_set_text_commit", "_combo_select", "_click_hold",
        "_clip_rect", "_release_clip", "_cursor_position", "_restore_cursor",
        "_move_real_cursor", "_foreground_window", "_thread_of", "_activate_window",
        "_require_foreground", "_hover_centre", "_main_hwnd", "_children_of",
        "_param_rows", "_resolve", "_has_slider", "_state_of",
        "_find_overlay", "_peek_overlay", "_require_store_dialog", "_dialog_button",
        "channel", "_combo_index", "_combo_items", "_channel_combo",
        "_channel_readback", "_channel_matches", "_close_any_dialog", "_panel_map",
        "_poll_parameters_overlay", "_is_visible", "_hidden_panels", "_dialog_panels",
        "_poll_dialog", "_panel_observation", "_pressed_state", "_observe_entry_attempt",
        "_require_visible_popup", "_press_entry", "_close_wrong_dialog", "_open_parameters_dialog",
        "_assert_assisted_unchanged", "_close_parameters_dialog", "ensure_channel", "window_caption",
        "screen_fingerprint", "read_dialog_parameters", "_descendants_of", "_poll_dialog_fields",
        "_text_at", "_dialog_channel_text", "_dialog_refusal", "instrument_snapshot",
        "_process_mode_fact", "_require_same_channel", "_channel_fact", "_column_fact",
        "hold_recording", "wait_for_view_guarded", "peek_overlay", "preflight",
        "layout_note", "process_mode_note", "read_parameter", "_assisted_mode_clause",
        "write_parameter", "apply_point", "select_combo", "strip_state",
        "wait_for_view", "press", "answer_overlay", "set_store_name",
        "assert_working_directory", "commit_store", "wait_for_stored_file", "record_and_store",
        "try_record_and_store", "_as_role", "_settle_press", "_wait_for_view_guarded",
        "_hold_recording", "_await_store_dialog", "_store_edits", "_store_name_field",
        "_names_in", "_poll_new_file", "_store_until_file", "_recover",
    }
)

#: The methods the composed class carries that ``bfbbb10``'s flat class did not. Named rather than
#: absorbed, because a name that leaves a surface list would otherwise pass: ``_screen_anchor_text``
#: (``udop/parameters.py``) is the screen read split out of ``_dialog_refusal`` when that rule moved
#: to ``ui/dialog.py``, and the four the burst transition added to the same surface —
#: ``write_dialog_burst_length`` (the transaction), ``_row_reading`` / ``_row_reading_or_none`` (the
#: two reads it needs and a read path does not: a row's entry list, and the same row by binding) and
#: ``_burst_refusal`` (the refusal that closes the dialog without its ``Accept``) — plus
#: ``_answer_burst_rejection``. The class's own name set at this tip is 102, not 96
#: (``docs/dop3000/acquisition-architecture.md`` §5, ``docs/dop3000/burst-length-control-plan.md``).
CLASS_ADDITIONS = (
    "_screen_anchor_text",
    "write_dialog_burst_length",
    "_row_reading",
    "_row_reading_or_none",
    "_answer_burst_rejection",
    "_burst_refusal",
)

#: The names the flat module published that no method of the facade reads any more — the workflow
#: timings that travelled with their loops, the two helpers of the Parameters module, and the
#: imports the moved methods were the last users of. Every one is re-exported, so it still resolves
#: as ``driver.<name>``, as the same object its surface defines.
RE_EXPORTED = {
    "udv_echo_process.acquire.udop": ("AcquisitionError",),
    "udv_echo_process.acquire.udop.parameters": (
        "DIALOG_FILL_TIMEOUT_S",
        "GESTURE_POSTED_PRESS",
        "_DIALOG_REPLACE_S",
        "_ENTRY_DIALOG_TIMEOUT_S",
        "_MENU_POLL_S",
        "_MENU_TIMEOUT_S",
        "_descendants",
        "channel_items",
    ),
    "udv_echo_process.acquire.udop.recording": ("_OVERLAY_SETTLE_S", "_POLL_S"),
}

#: The workflow timing knobs and the module that **defines** each one. "Owner" is the definition, not
#: the only binding: ``from X import v`` copies the reference at import time, so a rebinding on the
#: defining module reaches only that module's own loops and a test that has to shorten a loop must
#: patch the module that runs it. ``_POLL_S`` is defined once, in ``recording.py``, and read by a view
#: wait in ``recording``, the dialog table's fill in ``parameters`` and the waits for the stored file
#: in ``store``; ``_OVERLAY_SETTLE_S`` is read by ``recording``'s overlay waits and by the facade's
#: own ``preflight``, which imported the value — the two knobs with more than one reading module
#: (``docs/dop3000/acquisition-architecture.md`` §5, and the correction it carries after the
#: independent review).
WORKFLOW_KNOBS = {
    "DIALOG_FILL_TIMEOUT_S": parameters,
    "_ENTRY_DIALOG_TIMEOUT_S": parameters,
    "_DIALOG_REPLACE_S": parameters,
    "_MENU_TIMEOUT_S": parameters,
    "_MENU_POLL_S": parameters,
    "_OVERLAY_SETTLE_S": recording,
    "_POLL_S": recording,
}

#: The modules the layer's names can be held by, by name, for the tables below.
KNOB_MODULES = {
    "driver": driver,
    "session": session,
    "parameters": parameters,
    "recording": recording,
    "store": store,
}

#: Every module that holds a binding of each knob: the one that defines it, each surface that
#: imported the value, and the facade with its compatibility name (which re-export the *value*, so
#: their loops — there are none — would follow nothing). Pinned, because a *new* silent copy of a knob
#: is the failure mode this file exists to catch: it resolves, it raises nothing, and it leaves the
#: suite longer than it should be.
KNOB_HOLDERS = {
    "DIALOG_FILL_TIMEOUT_S": ("driver", "parameters", "session"),
    "_ENTRY_DIALOG_TIMEOUT_S": ("driver", "parameters", "session"),
    "_DIALOG_REPLACE_S": ("driver", "parameters", "session"),
    "_MENU_TIMEOUT_S": ("driver", "parameters", "session"),
    "_MENU_POLL_S": ("driver", "parameters", "session"),
    "_OVERLAY_SETTLE_S": ("driver", "recording", "session"),
    "_POLL_S": ("driver", "parameters", "recording", "session", "store"),
}

#: The modules whose function bodies actually read each knob — the patch target of a test that has to
#: shorten one loop. Asserted off the ASTs below, not from this table: a knob that gains a reading
#: module without gaining a patch target is the exact bug the repointing commit fixed.
KNOB_READERS = {
    "DIALOG_FILL_TIMEOUT_S": ("parameters",),
    "_ENTRY_DIALOG_TIMEOUT_S": ("parameters",),
    "_DIALOG_REPLACE_S": ("parameters",),
    "_MENU_TIMEOUT_S": ("parameters",),
    "_MENU_POLL_S": ("parameters",),
    "_OVERLAY_SETTLE_S": ("driver", "recording"),
    "_POLL_S": ("parameters", "recording", "store"),
}

#: The file each holder's module is read from, for :func:`knob_readers`.
KNOB_FILES = {
    "driver": Path(driver.__file__),
    "parameters": Path(parameters.__file__),
    "recording": Path(recording.__file__),
    "store": Path(store.__file__),
}

PLATFORM_NAMES = {"windll", "win32gui", "win32con"}
ALLOWED_PACKAGES = {"actuator", "config", "snapshot", "ui", "win32", "udop"}
FORBIDDEN_PACKAGES = {"campaign", "runner", "verify", "plan", "log"}


def package_files() -> Iterator[Path]:
    here = Path(udop.__file__).parent
    yield from sorted(here.glob("*.py"))


def admitted_files() -> Iterator[Path]:
    """The facade first, then the package: the files this layer's boundary is asserted over.

    ``acquire/driver.py`` is where the facade's code lives, so a boundary check that walked only
    ``udop/*.py`` would silently stop covering the class it is about.
    """
    yield Path(driver.__file__)
    yield from package_files()


def imported_modules(path: Path) -> set[str]:
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def knob_readers(path: Path, knobs: Collection[str]) -> set[str]:
    """The knobs some function body in ``path`` *reads* — the names it resolves at call time.

    A name a module imports is a binding; a name a function body loads is a read. Only the second
    makes the module a patch target, which is why the distinction is asserted off the AST instead of
    being inferred from ``hasattr``: every importer of a constant has the attribute, and only the
    module that runs the loop follows a rebinding of its own global.
    """
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    read: set[str] = set()
    for node in ast.walk(parsed):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load) and inner.id in knobs:
                read.add(inner.id)
    return read


# ------------------------------------------------------------------ the composition


def test_the_actuator_is_the_facade_over_the_three_surfaces() -> None:
    """One live class: the three surfaces mixed in under the facade's own methods."""
    assert driver.Win32Actuator.__mro__[:4] == (
        driver.Win32Actuator,
        parameters.ParametersSurface,
        recording.RecordingSurface,
        store.StoreSurface,
    )
    # The pieces are disjoint: no name is claimed by two surfaces, so the order above cannot
    # change what a name resolves to.
    claimed: dict[str, str] = {}
    for module, names in SURFACES.items():
        for name in names:
            assert name not in claimed, f"{name} claimed by {claimed.get(name)} and {module.__name__}"
            claimed[name] = module.__name__
    # ...and every one of them is on the class and defined in the module it was cut into.
    for module, names in SURFACES.items():
        for name in names:
            member = getattr(driver.Win32Actuator, name, None)
            assert member is not None, f"{name} is missing from Win32Actuator"
            defined_in = getattr(member, "__module__", None) or member.fget.__module__  # type: ignore[attr-defined]
            assert defined_in == module.__name__, f"{name} -> {defined_in}"
    # The four groups are the whole class, bar the inherited object members.
    own = {
        name
        for klass in driver.Win32Actuator.__mro__[:-1]
        for name in vars(klass)
        if not name.startswith("__") or name == "__init__"
    }
    assert own == set(claimed)


def test_the_class_surface_is_the_flat_one_plus_the_one_named_addition() -> None:
    """The recorded 96-name surface: a name may not leave the class unseen.

    ``own == set(claimed)`` above closes the four lists over *themselves* — delete a method and its
    entry together and it passes. That is how ``_has_slider`` left the class in Patch 2's
    ``ui/strip.py`` slice and stayed gone for several commits (an independent review of this branch
    found it; ``0bbcc68`` restored it as a seam over ``ui/strip.has_slider``). Pinning the *baseline*
    is the fix: the class's names must be ``bfbbb10``'s set plus the one documented addition, so a
    deletion fails by name and an undocumented addition fails too.
    """
    claimed = {name for names in SURFACES.values() for name in names}
    assert claimed == FLAT_CLASS_SURFACE | set(CLASS_ADDITIONS)
    assert claimed - FLAT_CLASS_SURFACE == set(CLASS_ADDITIONS)


def test_the_surface_pieces_carry_no_state_of_their_own() -> None:
    """The facade owns ``__init__`` and everything it sets; the pieces are method sets."""
    for surface in (parameters.ParametersSurface, recording.RecordingSurface, store.StoreSurface):
        assert "__init__" not in vars(surface)
        non_dunder = {
            name: value
            for name, value in vars(surface).items()
            if not name.startswith("__") and not callable(value)
        }
        assert non_dunder == {}, f"{surface.__name__} carries {sorted(non_dunder)}"


# ------------------------------------------------------------------ the compatibility name


def test_the_facade_is_its_own_module_and_session_only_re_exports_it() -> None:
    """The boring graph: ``driver`` is ``acquire/driver.py``; ``udop.session`` is a name for it.

    Patch 4 had this the other way round — ``acquire/driver.py`` published ``udop.session`` under
    its own name with ``sys.modules[__name__] = session`` — so ``import
    udv_echo_process.acquire.driver`` handed back a module whose ``__name__`` and ``__file__`` were
    another file's, and every traceback pointed at code the reader was not looking at. The module a
    patch has to reach is the module whose own globals the bodies read, and that is this one.
    """
    assert driver is not session
    assert driver.__name__ == "udv_echo_process.acquire.driver"
    assert Path(driver.__file__).name == "driver.py"
    assert session.__name__ == "udv_echo_process.acquire.udop.session"
    assert Path(session.__file__).name == "session.py"
    # The compatibility name hands back the facade's own objects, not copies of them.
    assert driver.Win32Actuator is session.Win32Actuator
    assert driver.AcquisitionError is session.AcquisitionError
    assert driver._gui is session._gui
    assert driver._post is session._post
    assert driver._user32 is session._user32
    assert session.__all__ == driver.__all__
    # ...and the class the bodies belong to is the facade module's: this is what makes
    # ``monkeypatch.setattr(driver, "_gui", ...)`` — how every fake in this repository scripts the
    # window layer — reach the body it was written for.
    assert driver.Win32Actuator.__module__ == driver.__name__


def test_nothing_in_the_layer_replaces_itself_in_sys_modules() -> None:
    """No runtime module surgery: the file *is* the module a reader opens and a traceback names."""
    for path in admitted_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        touched = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "modules"
        ]
        assert touched == [], f"{path.name} reaches into sys.modules"


def test_every_workflow_knob_is_the_owning_surface_s_own_object() -> None:
    """A re-exported knob is the defining surface's *object*, never a second copy of its value.

    What this proves is identity and nothing more: for an immutable scalar ``driver._MENU_POLL_S is
    parameters._MENU_POLL_S`` holds for any module that imported the same constant, so it says
    nothing about which module a loop reads the name from or which patch bites — that is
    ``test_a_knob_binding_is_a_copy_so_only_the_module_that_reads_it_is_a_patch_target``'s job.
    """
    for name, owner in WORKFLOW_KNOBS.items():
        assert getattr(driver, name) is getattr(owner, name), f"{name} is a copy"
        assert getattr(session, name) is getattr(owner, name), f"session.{name} is a copy"


def test_a_knob_binding_is_a_copy_so_only_the_module_that_reads_it_is_a_patch_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The binding table and the reader table, both asserted — the two facts identity cannot show.

    An import is a copy of a reference, so ``_POLL_S`` and ``_OVERLAY_SETTLE_S`` have more than one
    binding each while having one definition, and a rebinding on the definition moves only the loops
    that resolve it in *that* module's globals. Asserted here rather than described, because the
    2026-09-18 repointing commit (``b68b80d``) exists precisely because a patch that resolves and
    does nothing keeps the suite green while it runs the measured timeouts: a knob that gains a
    reading module without gaining a patch target is the regression, and
    ``tests/test_acquire_driver.py`` / ``tests/test_acquire_dialog.py`` are where it has to be
    shortened (``docs/dop3000/acquisition-architecture.md`` §5).
    """
    assert set(KNOB_HOLDERS) == set(KNOB_READERS) == {name for name, _ in WORKFLOW_KNOBS.items()}
    for name, owner in WORKFLOW_KNOBS.items():
        value = getattr(owner, name)
        holders = KNOB_HOLDERS[name]
        readers = KNOB_READERS[name]
        # The module WORKFLOW_KNOBS names is a holder; a holder that reads nothing (the facade and
        # its compatibility name) is a re-export, not a patch target.
        assert owner.__name__.rpartition(".")[2] in holders, f"{name}: the definition holds no binding"
        assert set(holders) >= set(readers), f"{name}: a reader that holds no binding"
        for holder in holders:
            assert getattr(KNOB_MODULES[holder], name) is value, f"{holder}.{name} is a copy"
        # `from X import v` copies the reference: rebinding the definition moves the definition.
        marker = object()
        monkeypatch.setattr(owner, name, marker)
        for holder in holders:
            module = KNOB_MODULES[holder]
            if module is owner:
                assert getattr(module, name) is marker
            else:
                assert getattr(module, name) is value, (
                    f"{holder}.{name} followed a rebinding on {owner.__name__} — the binding tables "
                    "and the patch targets are stale"
                )


def test_the_loops_read_the_knobs_the_binding_tables_name() -> None:
    """The reader of each knob, off the ASTs: which module's globals its loops resolve the name in.

    ``KNOB_HOLDERS`` says who *has* the name; this says who *reads* it, which is what a test that
    shortens a loop must patch. Both are compared, so a new reading module fails here instead of
    quietly paying the measured timeout.
    """
    knobs = {name for name, _ in WORKFLOW_KNOBS.items()}
    readers: dict[str, set[str]] = {name: set() for name in knobs}
    for module_name, path in KNOB_FILES.items():
        for name in knob_readers(path, knobs):
            readers[name].add(module_name)
    assert readers == {name: set(modules) for name, modules in KNOB_READERS.items()}
    # ...and the facade's own reads are the ones §5 records rather than a general rule: `preflight`
    # is the facade's only knob read (`_OVERLAY_SETTLE_S`), and `session` reads none at all.
    assert knob_readers(KNOB_FILES["driver"], knobs) == {"_OVERLAY_SETTLE_S"}
    assert knob_readers(KNOB_FILES["store"], knobs) == {"_POLL_S"}


def test_the_failure_class_is_the_packages_one_class() -> None:
    """One failure type for every surface, and the class the win32 mechanics resolve."""
    assert udop.AcquisitionError is driver.AcquisitionError
    assert issubclass(udop.AcquisitionError, RuntimeError)
    assert _acquisition_error() is udop.AcquisitionError


#: The module-level names ``bfbbb10``'s flat module published that do **not** resolve from ``driver``
#: at this tip, and where each went. The document this file's boundary is written against used to say
#: every one of them still resolved; an independent review measured the opposite, so the six are
#: named here and asserted absent below — a compatibility narrowing that is recorded rather than
#: papered over (``docs/dop3000/acquisition-architecture.md`` §5). None of the six is read through
#: the driver anywhere in ``src/``, ``tests/`` or ``tools/``; ``STRIP_BUTTON_ORDER`` and
#: ``NUMERIC_WRITE_RECIPE`` are ``acquire/actuator.py``'s and re-exported by ``acquire``.
DROPPED_FROM_THE_FLAT_NAMESPACE = {
    "ChannelMode": "Patch 2 (the acquire/ui slice)",
    "STRIP_BUTTON_ORDER": "Patch 2 (the acquire/ui slice)",
    "os": "Patch 2 (the acquire/ui slice)",
    "pairwise": "Patch 2 (the acquire/ui slice)",
    "NUMERIC_WRITE_RECIPE": "Patch 4 (incidental import)",
    "lru_cache": "Patch 4 (incidental import)",
}


def test_every_name_the_facade_publishes_resolves_and_the_dropped_six_are_named() -> None:
    """The facade's promise is its published surface, not the flat module's whole namespace.

    ``__all__`` says only what is there, and everything it says resolves to the surface's own object;
    the six names in ``DROPPED_FROM_THE_FLAT_NAMESPACE`` are the part of the flat module's namespace
    that is *not* published any more, each pinned absent with its cause so that re-exporting one (or
    losing another) has to update this table on purpose.
    """
    for name in driver.__all__:
        assert hasattr(driver, name), f"{name} is in __all__ but does not resolve"
    for name in DROPPED_FROM_THE_FLAT_NAMESPACE:
        assert not hasattr(driver, name), f"driver.{name} resolves again — update the table"
        assert name not in driver.__all__, f"{name} is published again — update the table"
    for module_name, names in RE_EXPORTED.items():
        module = __import__(module_name, fromlist=["__all__"])
        for name in names:
            assert hasattr(driver, name), f"driver.{name} stopped resolving"
            assert getattr(driver, name) is getattr(module, name), (
                f"driver.{name} is a copy, not {module_name}.{name}"
            )


def test_the_class_satisfies_the_protocol_it_always_did() -> None:
    """The composition is the flat class's method set, so the protocol still holds."""
    missing = [
        name
        for name in dir(Actuator)
        if not name.startswith("_") and not callable(getattr(driver.Win32Actuator, name, None))
    ]
    assert missing == []
    assert isinstance(driver.Win32Actuator(channel=1), Actuator)


# ------------------------------------------------------------------ import hygiene


def test_the_udop_package_imports_no_campaign_policy_and_no_platform() -> None:
    """The boundary: this layer combines observations with actions, and nothing else.

    A surface that imported the campaign, a runner or the verification would drag the run's policy
    into the workflow; one that reached ``win32gui`` or ``win32con`` would move the Windows boundary
    out of ``acquire/win32``, where it lives (resolved *inside* the calls, so this layer still
    imports on a host with no ``pywin32``). The one platform read the layer does make is the
    facade's ``Win32Actuator.screen_fingerprint`` — its ``ctypes.windll.user32`` pair, read-only
    diagnostics of a screen the facade has already resolved, named in
    ``docs/dop3000/acquisition-architecture.md`` §5 — and it is asserted to be the *only* one.

    The one import edge back to the facade is ``udop/session.py``'s: the compatibility name
    re-exports ``acquire.driver``, and no surface (and not the package) may import it.
    """
    for path in admitted_files():
        for name in sorted(imported_modules(path)):
            if not name.startswith("udv_echo_process.acquire"):
                continue
            if name == driver.__name__:
                assert path.name == "session.py", f"{path.name}: {name}"
                continue
            package = name.split(".")[2]
            assert package not in FORBIDDEN_PACKAGES, f"{path.name}: {name}"
            assert package in ALLOWED_PACKAGES, f"{path.name}: {name}"
        assert not (windll_users(path) - {"screen_fingerprint"}), (
            f"{path.name}: {sorted(windll_users(path))}"
        )


def windll_users(path: Path) -> set[str]:
    """The functions of ``path`` that reach ``ctypes.windll`` (the one read outside ``win32/``)."""
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    users: set[str] = set()
    for node in ast.walk(parsed):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Attribute) or inner.attr != "windll":
                continue
            base = inner
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name) and base.id == "ctypes":
                users.add(node.name)
    return users


def test_the_package_imports_do_not_reach_the_platform_at_import_time() -> None:
    """No module here imports ``win32gui``/``win32con``/``pywinauto`` — not even lazily."""
    for path in package_files():
        for name in sorted(imported_modules(path)):
            assert not name.startswith(("win32gui", "win32con", "pywinauto")), f"{path.name}: {name}"


def test_the_package_graph_is_a_dag_and_the_facade_is_its_root() -> None:
    """No cycles: the facade imports the surfaces, the surfaces never import it back."""
    wanted = (udop.__name__, driver.__name__)

    def layer_imports(path: Path) -> set[str]:
        """Every import of ``path`` that lands inside this layer (the package or the facade)."""
        return {name for name in imported_modules(path) if name.startswith(wanted)}

    edges: dict[str, set[str]] = {}
    for path in package_files():
        module = f"{udop.__name__}.{path.stem}" if path.stem != "__init__" else udop.__name__
        edges[module] = {name for name in layer_imports(path) if name.startswith(udop.__name__)}
    # The facade is at the root of that graph and outside the package: walk its AST too, or the
    # direction these assertions are about would be asserted of a node nobody collected. Its only
    # edge back is ``udop/session.py``'s — the compatibility name — and that edge is collected
    # with the facade as its target.
    edges[driver.__name__] = layer_imports(Path(driver.__file__))
    edges[f"{udop.__name__}.session"] = layer_imports(Path(session.__file__))
    for module, targets in edges.items():
        assert module not in targets, f"{module} imports itself"
    # A topological order exists, which is what "no cycle" means.
    pending = dict(edges)
    resolved: set[str] = set()
    while pending:
        ready = {m for m, targets in pending.items() if targets <= resolved | {udop.__name__}}
        assert ready, f"import cycle among {sorted(pending)}"
        for module in ready:
            resolved.add(module)
            del pending[module]
    assert resolved == set(edges)
    # ...and the direction is the documented one: the facade imports every surface, the
    # compatibility name imports the facade and nothing else, the package itself imports none of
    # them, no surface imports the facade back, and the only edges between surfaces are the two
    # cadence constants the Parameters and Store loops read from the recording surface.
    surfaces = {
        f"{udop.__name__}.parameters",
        f"{udop.__name__}.recording",
        f"{udop.__name__}.store",
    }
    assert edges[driver.__name__] >= surfaces
    assert edges[f"{udop.__name__}.session"] == {driver.__name__}
    assert edges[udop.__name__] == set()
    for surface in surfaces:
        assert driver.__name__ not in edges[surface], f"{surface} imports the facade back"
    assert edges[f"{udop.__name__}.parameters"] <= {udop.__name__, f"{udop.__name__}.recording"}
    assert edges[f"{udop.__name__}.store"] <= {udop.__name__, f"{udop.__name__}.recording"}
    assert edges[f"{udop.__name__}.recording"] <= {udop.__name__}


def test_the_package_exports_its_one_failure_class() -> None:
    """The package's own surface is the failure type the four surfaces share."""
    assert udop.__all__ == ["AcquisitionError"]


@pytest.mark.parametrize(
    ("module", "filename"),
    [
        (udop, "__init__.py"),
        (parameters, "parameters.py"),
        (recording, "recording.py"),
        (store, "store.py"),
        (session, "session.py"),
    ],
)
def test_each_module_is_where_the_layer_says_it_is(module: object, filename: str) -> None:
    """The files the status table names exist and are imported (not text-polished copies)."""
    assert Path(module.__file__).name == filename  # type: ignore[attr-defined]
    assert Path(module.__file__).parent == Path(udop.__file__).parent  # type: ignore[attr-defined]
