"""The udop package's boundary: the facade's composition, its published surface, its import hygiene.

Patch 4 split the live workflows out of the flat ``acquire/driver.py`` into
``acquire/udop/{parameters,recording,store,session}.py``. The cycle itself is pinned where it
always was — ``tests/test_acquire_driver.py`` drives ``Win32Actuator`` through the fake window, and
``tests/test_acquire_dialog.py`` the dialog reads — so nothing here re-implements a workflow. What
this module pins is the *composition* the move produced and the boundary it draws:

* ``Win32Actuator`` is one class whose methods are the surface modules' — the Parameters
  interaction in ``parameters.py``, the strip lifecycle in ``recording.py``, the Store dialog in
  ``store.py`` and the facade's own reads in ``session.py``. A method that drifted to another
  surface, or a name two surfaces both claim, fails here by name.
* ``acquire.driver`` **is** ``udop.session`` — the same module object, so ``driver._gui``,
  ``driver._user32`` and ``driver._post`` (the names this repository's fakes script the window
  layer with) are the objects the facade's own bodies read. A re-export shell would pass a copy.
* every name the flat module published still resolves from ``driver``, ``driver.__all__`` is
  truthful, and the re-exported names are the *same objects* their surface defines.
* no module in the package imports ``campaign``/``runner``/``verify``/``plan``/``log``, none reaches
  the platform (``ctypes.windll``/``win32gui``/``win32con``) and none imports the facade back — the
  graph is a DAG, checked by walking the ASTs.

The workflow timings the moved loops read (``DIALOG_FILL_TIMEOUT_S``, ``_ENTRY_DIALOG_TIMEOUT_S``,
``_MENU_TIMEOUT_S``, ``_MENU_POLL_S``, ``_OVERLAY_SETTLE_S``, ``_POLL_S``) are *re-exported* from
``driver`` and are read by the surface that owns the loop, so a patch on ``driver`` resolves but no
longer shortens that loop: patching ``udop.parameters`` / ``udop.recording`` is what does —
``test_every_name_the_flat_module_published_still_resolves`` states the identity of those names.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
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
#: the read-only surface and the protocol surface.
SESSION_METHODS = (
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
    session: SESSION_METHODS,
}

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

PLATFORM_NAMES = {"windll", "win32gui", "win32con"}
ALLOWED_PACKAGES = {"actuator", "config", "snapshot", "ui", "win32", "udop"}
FORBIDDEN_PACKAGES = {"campaign", "runner", "verify", "plan", "log"}


def package_files() -> Iterator[Path]:
    here = Path(udop.__file__).parent
    yield from sorted(here.glob("*.py"))


def imported_modules(path: Path) -> set[str]:
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


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


def test_acquire_driver_is_the_facade_module_itself() -> None:
    """``driver`` is not a copy of the facade: it *is* the module the bodies read globals from.

    That is what keeps ``monkeypatch.setattr(driver, "_gui", ...)`` — how every fake in this
    repository scripts the window layer — biting at the same place it always did: a re-export shell
    would hand a caller a copy of every name the class reads.
    """
    assert driver is session
    assert vars(driver) is vars(session)
    assert driver.Win32Actuator is session.Win32Actuator
    assert driver._gui is session._gui
    assert driver._post is session._post
    assert driver._user32 is session._user32


def test_the_failure_class_is_the_packages_one_class() -> None:
    """One failure type for every surface, and the class the win32 mechanics resolve."""
    assert udop.AcquisitionError is driver.AcquisitionError
    assert issubclass(udop.AcquisitionError, RuntimeError)
    assert _acquisition_error() is udop.AcquisitionError


def test_every_name_the_flat_module_published_still_resolves() -> None:
    """Nothing moved out of the caller's reach, and ``__all__`` says only what is there."""
    for name in driver.__all__:
        assert hasattr(driver, name), f"{name} is in __all__ but does not resolve"
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

    A udop module that imported the campaign, a runner or the verification would drag the run's
    policy into the workflow; one that reached ``win32gui`` or ``win32con`` would move the Windows
    boundary out of ``acquire/win32``, where it lives (resolved *inside* the calls, so this package
    still imports on a host with no ``pywin32``). The one platform read the package does make is
    ``session.screen_fingerprint``'s ``ctypes.windll.user32`` pair — read-only diagnostics of a
    screen the facade has already resolved, named in
    ``docs/dop3000/acquisition-architecture.md`` §5 — and it is asserted to be the *only* one.
    """
    for path in package_files():
        for name in sorted(imported_modules(path)):
            if not name.startswith("udv_echo_process.acquire"):
                continue
            package = name.split(".")[2]
            assert package not in FORBIDDEN_PACKAGES, f"{path.name}: {name}"
            assert package in ALLOWED_PACKAGES, f"{path.name}: {name}"
            assert name != "udv_echo_process.acquire.driver", f"{path.name}: {name}"
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
    edges: dict[str, set[str]] = {}
    for path in package_files():
        module = f"{udop.__name__}.{path.stem}" if path.stem != "__init__" else udop.__name__
        edges[module] = {name for name in imported_modules(path) if name.startswith(udop.__name__)}
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
    # ...and the direction is the documented one: the facade imports every surface, the package
    # itself imports none of them, and the only edges between surfaces are the two cadence
    # constants the Parameters and Store loops read from the recording surface.
    assert edges[f"{udop.__name__}.session"] >= {
        f"{udop.__name__}.parameters",
        f"{udop.__name__}.recording",
        f"{udop.__name__}.store",
    }
    assert edges[udop.__name__] == set()
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
