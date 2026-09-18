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
* every name the flat module published still resolves from ``driver``, ``driver.__all__`` is
  truthful, and the re-exported names are the *same objects* their surface defines.
* no module in the package imports ``campaign``/``runner``/``verify``/``plan``/``log``, none reaches
  the platform (``ctypes.windll``/``win32gui``/``win32con``) outside the facade's one named read,
  and the only edge back to the facade is the compatibility name — the graph is a DAG, checked by
  walking the ASTs.

The workflow timings the moved loops read (``DIALOG_FILL_TIMEOUT_S``, ``_ENTRY_DIALOG_TIMEOUT_S``,
``_MENU_TIMEOUT_S``, ``_MENU_POLL_S``, ``_OVERLAY_SETTLE_S``, ``_POLL_S``) are *re-exported* from
``driver`` and are read by the surface that owns the loop, so a patch that has to *bite* is a patch
on ``udop.parameters`` / ``udop.recording`` — never on the facade's copy of the value.
``test_every_name_the_flat_module_published_still_resolves`` states the identity of those names,
and ``tests/test_acquire_driver.py`` / ``tests/test_acquire_dialog.py`` prove the patch targets.
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

#: The workflow timing knobs and the module that **owns** each one: the surface whose loop reads
#: it, so the module a test must patch for the patch to bite. ``_POLL_S`` is defined once, in
#: ``recording.py``, and read by loops in all three surfaces (a view wait in ``recording``, the
#: dialog table's fill in ``parameters``, the wait for the stored file in ``store``): the
#: definition is not duplicated, and a test that shortens one of those loops patches the module
#: that runs *that* loop. ``_OVERLAY_SETTLE_S`` has a second reader, the facade's own
#: ``preflight``, which imported the value — the one knob whose second binding is named rather
#: than papered over (``docs/dop3000/acquisition-architecture.md`` §5).
WORKFLOW_KNOBS = {
    "DIALOG_FILL_TIMEOUT_S": parameters,
    "_ENTRY_DIALOG_TIMEOUT_S": parameters,
    "_DIALOG_REPLACE_S": parameters,
    "_MENU_TIMEOUT_S": parameters,
    "_MENU_POLL_S": parameters,
    "_OVERLAY_SETTLE_S": recording,
    "_POLL_S": recording,
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
    """One binding per reader, and it is the surface's that runs the loop.

    A knob the facade re-exports is the surface's *object*, never a second copy of its value — and
    a test that has to shorten the loop it feeds patches that surface
    (``tests/test_acquire_driver.py``'s ``test_the_popup_wait_is_shortened_on_the_surface_that_
    owns_the_loop`` and ``tests/test_acquire_dialog.py``'s
    ``test_the_dialog_fill_cadence_is_read_from_the_module_that_owns_the_loop``).
    """
    for name, owner in WORKFLOW_KNOBS.items():
        assert getattr(driver, name) is getattr(owner, name), f"{name} is a copy"
        assert getattr(session, name) is getattr(owner, name), f"session.{name} is a copy"


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
