"""The surface-identity matrix — Slice 1 of ``docs/dop3000/identity-classification-plan.md``.

One row per surface the instrument was measured to produce, and every row asserts the **same
seven facts**: the panel's *identity*, whether it is in the resolver's dialog union, whether it
was selected as the strip, ``open_popup``, the blocking-surface result, the surface kind, and the
first refusal clause. The point is not that any single fact is wrong today — it is that the five
symptoms §1 of the plan lists are one defect seen from five sides, so a fix that repairs one
symptom must move all of them together or fail *here*, by name.

**Where the evidence comes from, and what each source is.** Every row states its own source in its
docstring, and they are four different kinds:

* **a raw tree, sanitised** — ``tests/data/udop-screen-*.json``, the kept live reads of 2026-09-19
  (and the 2026-09-18 ``Define TGC`` read) projected back onto a ``win32gui`` stand-in and resolved
  by :meth:`Win32Actuator._resolve` itself. Their provenance, hidden controls and sanitisation
  round trip are recorded in each fixture's own ``note`` and guarded by
  ``tests/test_acquire_instrument_screen.py``;
* **a committed fixture** — ``tests/data/udop-measurement-screen-tree-instrument.json`` (the
  instrument's clean 352 px screen) and ``tests/data/udop-parameters-dialog-tree.json`` (the
  measured ``Operating parameters`` dialog), through the helpers the suite already has
  (``resolved_instrument``, ``resolved_dialog_screen``);
* **a synthesised measured shape** — a panel and its own buttons at the geometry a crop or a
  status read measured, hung over the instrument's tree (the warning family's 397x135 and 353x155
  forms, the sitting-C ``Define TGC`` confirmation, the ``Parameters`` popup), so the shape goes
  through the same resolve a read does;
* **a resolved role map** — the repository's own synthesised screens
  (``test_acquire_surface_classification``'s ``replacement_surface`` / ``screen_with_overlay``)
  for the cases whose claim is about the *pure* surface functions. A hand-built map states no
  tree, so it cannot carry identities; each such row says so in its docstring and asserts the half
  of the interface that is a function of the map.

**The interface these rows are written against** (frozen by the plan §3, and the only thing this
file may not re-derive): ``PanelIdentity`` in ``udv_echo_process.acquire.ui.identity`` with
``MEASUREMENT_STRIP``, ``MENU_POPUP``, ``APPLICATION_DIALOG``, ``WARNING``, ``REPLACEMENT``,
``OVERLAY``, ``CURSOR_INFO`` and ``OTHER``; ``_resolve`` publishing ``roles["identities"]``
(panel handle → identity) and ``roles["blocking_surface"]`` (a member, or ``None``); every
existing role key unchanged; ``value_dialogs``/``browse_dialogs`` derived only from
``APPLICATION_DIALOG``; ``open_popup`` true only for a real ``Parameters`` popup; and
``classify_surface`` / ``surface_kind`` / ``surface_clauses`` keeping their signatures, stating
``REPLACEMENT`` ahead of ``OVERLAY`` and a warning/overlay/dialog/real-popup surface before any
strip or sidebar clause.

**This file is expected to be RED before the fix lands**, and that is the deliverable: the rows
that are red are the measured counterexamples and their failure text is the evidence. One row is
red by *design* rather than by the missing interface — the band demonstration at the end — and its
docstring says why. Nothing here presses anything: the one case that drives a press path
booby-traps the transport so an attempted press raises, and every other case stops at a resolved
map.
"""

from __future__ import annotations

import typing

import pytest
from test_acquire_driver import FakeUdopWindow
from test_acquire_instrument_screen import (
    HANDLE_BASE,
    STRIP_PANEL,
    instrument_tree,
    kept_read,
    project_rows,
    resolved_instrument,
    resolved_kept_read,
)
from test_acquire_layout_gate import ORIGIN, _button, _panel
from test_acquire_surface_classification import (
    DIALOG_HWND,
    WINDOW_HWND,
    _MeasuredGui,
    _row,
    replacement_surface,
    resolved_dialog_screen,
    screen_with_overlay,
)

from udv_echo_process.acquire import driver
from udv_echo_process.acquire.actuator import (
    StripControl,
    StripState,
    StripView,
    classify_strip_view,
    press_index,
)
from udv_echo_process.acquire.ui.dialog import bottom_row
from udv_echo_process.acquire.ui.layout import (
    classify_surface,
    observation_of,
    surface_clauses,
)
from udv_echo_process.acquire.ui.menu import (
    PARAMETERS_POPUP_LEFT,
    PARAMETERS_POPUP_MIN_H,
)
from udv_echo_process.acquire.ui.model import SurfaceKind
from udv_echo_process.acquire.ui.strip import press_refusal

try:  # the interface this slice freezes; guarded so the pre-fix run fails row by row, not at import
    from udv_echo_process.acquire.ui.identity import PanelIdentity
except ImportError:  # pragma: no cover - the pre-fix state this file is landed in
    PanelIdentity = None  # type: ignore[assignment]


def _member(name: str) -> typing.Any:
    """One frozen identity, by member name — the enum member when published, else its own value.

    Comparing *values* keeps every row about the classification rather than about whether a
    mapping states the member or the string it carries (``PanelIdentity`` is a ``str`` enum, so
    both compare equal), so a row cannot go red merely because a fix published ``"overlay"`` where
    the frozen interface names ``PanelIdentity.OVERLAY``.
    """
    frozen = {
        "MEASUREMENT_STRIP": "measurement_strip",
        "MENU_POPUP": "menu_popup",
        "APPLICATION_DIALOG": "application_dialog",
        "WARNING": "warning",
        "REPLACEMENT": "replacement",
        "OVERLAY": "overlay",
        "CURSOR_INFO": "cursor_info",
        "OTHER": "other",
    }[name]
    return getattr(PanelIdentity, name, frozen)


# --- the measured rects each row names, quoted from the read that measured them -----------------
#
# `docs/dop3000/device-verification.md`, *the four-button strip, block-held*: the strip is the same
# `TSp_Panel` 3149132 in every state, sized by the state.
STRIP_453 = (343, 414, 796, 454)
STRIP_502 = (343, 414, 845, 537)
STRIP_551 = (343, 414, 894, 537)
STRIP_370 = (343, 414, 713, 537)
#: The two controls of that row the cleanup hazard is about (same record, the per-handle table):
#: `2821164` `Do store` at `[537,423,628,443]` and `1641666` `Clear and restart` at
#: `[638,423,776,443]` in the intermediate state.
DO_STORE_RECT = (537, 423, 628, 443)
CLEAR_AND_RESTART_RECT = (638, 423, 776, 443)
#: The cursor info box, present in the 453 and 551 reads: `TSp_Panel 131916` `[908,466,1057,525]`
#: (149x59) with its caption-less child panel `131920` `[916,475,1045,514]` and the button it owns
#: at `[917,578,997,598]` — **outside** its own rect, which is what it may never be read as.
INFO_BOX = (908, 466, 1057, 525)
INFO_BOX_CHILD = (916, 475, 1045, 514)
INFO_BOX_BUTTON = (917, 578, 997, 598)
#: The reused destructive guard (392x132), from the same record.
GUARD_392 = (772, 490, 1164, 622)
#: The `Define TGC` overlay the 2026-09-18 read and sitting C both measured: 450x120.
TGC_OVERLAY = (400, 168, 850, 288)
#: The `Parameters` popup: the live rect (`ui.menu.PARAMETERS_POPUP_LEFT`, 195 px tall, above the
#: 120 px floor) and its five entries at the screen tops `ui.menu` records (61/95/130/165/205).
POPUP_RECT = (169, 55, 401, 250)
POPUP_ENTRIES = (
    (190, 61, 365, 101),
    (190, 95, 348, 135),
    (188, 130, 336, 170),
    (189, 165, 344, 205),
    (189, 205, 345, 245),
)
#: The warning family's two further measured members, from `docs/dop3000/ui-element-index.md`:
#: UI-OVERLAY-23 (`warning-emmiting-power-auto-tgc.png`, 397x135, the power↔TGC `Warning`) and
#: UI-OVERLAY-10 (`overlay-default-parameters-blocking.png`, 353x155, the default-parameters
#: confirmation). Their *positions* are not measured (both crops are regions of the box), so they
#: are placed over the instrument's monitor — where a blocking box sits — and no row keys on where.
WARNING_397 = (600, 353, 997, 488)
WARNING_353 = (600, 353, 953, 508)
#: The store path's own overwrite warning: **no measured geometry at all** (the corpus never
#: cropped it), so this rect is deliberately none of the three above and the family rule the plan
#: §2.1 item 3 states is the only thing that can carry it.
WARNING_UNMEASURED = (640, 300, 1051, 441)


# ------------------------------------------------------------------ the shared row assertions


def identity_of(roles: dict, hwnd: int) -> typing.Any:
    """One panel's identity, **out of the resolved roles map** — never from the classifier.

    ``_resolve`` publishes the inventory (plan §3), so a row reads the same answer the consumers
    read: a row that imported the classifier could pass while the resolver published nothing, which
    is exactly the state this slice has to see.
    """
    identities = roles.get("identities")
    assert identities is not None, (
        "the resolved roles carry no `identities` map, so no panel on this screen has an identity: "
        "the interface this slice freezes is `Win32Actuator._resolve()` publishing "
        "`roles['identities'] = {panel hwnd: PanelIdentity}` "
        "(docs/dop3000/identity-classification-plan.md §3), and every identity row of this matrix "
        "is red by construction until it does"
    )
    assert hwnd in identities, f"panel {hwnd} is not in the published identities ({identities})"
    return identities[hwnd]


def blocking_surface_of(roles: dict) -> typing.Any:
    """``roles['blocking_surface']`` — the result the plan adds beside ``open_popup``."""
    assert "blocking_surface" in roles, (
        "the resolved roles carry no `blocking_surface`: the plan §3 adds it so that narrowing "
        "`open_popup` to a real `Parameters` popup erases no safety information "
        "(`WARNING` / `OVERLAY` / `APPLICATION_DIALOG` / `MENU_POPUP`, else `None`)"
    )
    return roles["blocking_surface"]


def panel_with(roles: dict, rect: tuple[int, int, int, int]) -> int:
    """The handle of the **window-level** panel painted at ``rect`` — by geometry, never by index.

    A handle is an action reference for the moment of one resolve, so a row that pinned one would
    be testing the projection's own numbering; the rect is what the read measured.
    """
    found = [panel["hwnd"] for panel in roles["panels"] if tuple(panel["rect"]) == tuple(rect)]
    assert len(found) == 1, f"no single window-level panel at {rect} on this screen: {found}"
    return found[0]


def dialog_union_of(roles: dict) -> set[int]:
    """The resolver's dialog union — ``value_dialogs`` | ``browse_dialogs``."""
    return set(roles["value_dialogs"]) | set(roles["browse_dialogs"])


def first_clause_of(roles: dict) -> str:
    """The first clause of the shape refusal — the reason an operator reads first (plan §3)."""
    reasons = driver.layout_shape_reasons(roles)
    assert reasons, "this screen produced no refusal clause at all"
    return reasons[0]


def first_surface_clause_of(roles: dict) -> str:
    """The first clause of the **surface** group — what is on the screen, before any diagnosis."""
    clauses = surface_clauses(observation_of(roles))
    assert clauses, "the surface group states no clause for this screen"
    return clauses[0]


# ---------------------------------------------------------------------------- the row sources


def resolve_rows(monkeypatch: pytest.MonkeyPatch, rows: list[dict]) -> dict:
    """``Win32Actuator._resolve``'s own answer for one hand-built tree of rows."""
    gui = _MeasuredGui(list(rows))
    monkeypatch.setattr(driver, "_gui", lambda: (gui, None))
    return driver.Win32Actuator(channel=1)._resolve()


def instrument_rows() -> list[dict]:
    """The committed instrument tree, projected onto the stand-in surface."""
    return project_rows(instrument_tree())


def screen_with_panel(
    rows: list[dict],
    *,
    panel_rect: tuple[int, int, int, int],
    buttons: tuple[tuple[int, int, int, int], ...],
    handle: int,
) -> list[dict]:
    """The instrument's tree with one synthesised measured panel and its own buttons on the window.

    The shape every "synthesised measured shape" row uses: a ``TSp_Panel`` at the rect a crop, a
    status read or the reference's own predicate measured, hosting *its own* ``TSp_Button``s and
    nothing else — which is what makes it a candidate for the strip vote, the warning family and
    the overlay warrant at once, and therefore a real test of which one claims it.
    """
    panel = _row(handle, "TSp_Panel", WINDOW_HWND, panel_rect)
    kids = [
        _row(handle + 1 + index, "TSp_Button", handle, rect)
        for index, rect in enumerate(buttons)
    ]
    return [*rows, panel, *kids]


def two_button_band(panel_rect: tuple[int, int, int, int]) -> tuple[tuple, tuple]:
    """The two-button bottom band a warning-family member carries, inside ``panel_rect``.

    The family rule asks for exactly two buttons in the panel's own last 70 px
    (``ui.dialog.bottom_row``), so the pair is placed there: the left one is the *safe* end and the
    right one the confirm end, the convention every box in this corpus follows.
    """
    left, _top, right, bottom = panel_rect
    band_top = bottom - 40
    first = (left + 40, band_top, left + 150, band_top + 25)
    second = (right - 170, band_top, right - 60, band_top + 25)
    return first, second


# ============================================================== 1. every measured strip shape
# The five forms the device record measured: 352x40 (the committed instrument fixture), 370x123,
# 453x40, 502x123 and 551x123. Each is the strip — the panel a run binds to — and none of them is
# a dialog or a popup, which is symptoms 1 and 2 of the plan's §1 together.


@pytest.mark.parametrize(
    ("name", "rect", "view", "buttons", "slider"),
    [
        ("instrument", STRIP_PANEL, StripView.READY, 3, False),
        ("370", STRIP_370, StripView.STORE, 3, True),
        ("453", STRIP_453, StripView.AMBIGUOUS, 4, False),
        ("502", STRIP_502, StripView.STORE, 4, True),
        ("551", STRIP_551, StripView.STORE, 4, True),
    ],
)
def test_a_measured_strip_shape_is_the_strip_and_never_a_dialog_or_a_popup(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    rect: tuple[int, int, int, int],
    view: StripView,
    buttons: int,
    slider: bool,
) -> None:
    """Row 1: the strip's own identity, for every measured form, asserted through the roles map.

    ``instrument`` is the committed fixture of the instrument's clean screen (352x40, ``ready``, no
    slider); the other four are the kept reads of 2026-09-19, sanitised — the 370x123 ``store`` row,
    the 453x40 intermediate row (four buttons; the slider present and **hidden**), the 502x123 row
    after a removal and the 551x123 block-held row. The strip is *that* panel (not the cursor info
    box, which is what the pre-fix vote hands over once the strip is excluded as a dialog), it is in
    no half of the dialog union, and it never makes the screen claim a menu popup — three facts that
    were wrong on the device and are fixed by one identity.
    """
    roles = (
        resolved_instrument(monkeypatch)
        if name == "instrument"
        else resolved_kept_read(monkeypatch, name)
    )
    strip = panel_with(roles, rect)

    # The measured consequences first — these are the facts the device record paid for, and their
    # failure text is the diagnosis: the strip bound to the panel that *is* the strip, the panel
    # outside every half of the dialog union, the screen claiming no menu popup, and nothing over
    # it that a press would have to answer.
    assert roles["strip_panel"] is not None and roles["strip_panel"]["hwnd"] == strip, (
        "the strip panel this read measured is not the panel the resolver bound as the strip: "
        f"it bound {roles['strip_panel']}"
    )
    assert strip not in dialog_union_of(roles), (
        "the recording strip's own panel was admitted by the dialog predicate — measured on the "
        "instrument, and the clause that admits it is its one direct `Show block` TComboBox "
        "(plan §2.2), which no run should read as a dialog"
    )
    assert roles["open_popup"] is False, (
        "a strip is not a menu popup: on this screen the panel the pre-fix flag calls one is the "
        f"cursor info box or the strip itself, not a `Parameters` popup ({roles['open_popup']})"
    )
    assert classify_surface(roles) is SurfaceKind.MEASUREMENT

    # ...the identity the slice publishes, and the blocking result the plan adds.
    assert identity_of(roles, strip) == _member("MEASUREMENT_STRIP")
    assert blocking_surface_of(roles) is None, (
        "a measurement strip is not a blocking surface: nothing is over the screen"
    )

    # The row, the view and the slider mark — the read's own numbers, so a row cannot pass on a
    # panel that merely happens to be `strip_panel`.
    assert len(roles["strip_row"]) == buttons
    assert roles["state"] == view.value
    assert roles["strip_slider"] is slider


def test_the_453_strip_row_is_the_ambiguous_four_button_row_and_binds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 1's own edge: the four-button, no-slider row is the strip **and** unbound (ledger B10).

    Identity and binding are separate claims (plan §2.1 item 4): the intermediate state's row is
    the strip, and nothing may be pressed out of it — ``press_index`` refuses, ``is_startable`` is
    false, and the refusal names the ambiguity rather than naming a row a run could be gated on. The
    panel also carries a ``TSp_Sliding_Bar`` **present and hidden** (the device record: *present,
    hidden*), so the fixture's own hidden node is what makes the distinction observable: a resolver
    that counted it would answer ``store``.
    """
    roles = resolved_kept_read(monkeypatch, "453")
    strip = panel_with(roles, STRIP_453)
    fixture = kept_read("453")
    hidden = [c for c in fixture["controls"] if c.get("visible") is False]
    projected = project_rows(fixture)

    assert any(
        c["cls"] == "TSp_Sliding_Bar" and tuple(c["rect"]) == (465, 449, 716, 499)
        for c in hidden
    ), "the fixture no longer carries the strip's own hidden slider"
    assert roles["strip_slider"] is False, (
        "the slider the read found **hidden** was counted: `has_slider` reads the panel's visible "
        "children, and this node paints nothing"
    )
    # The read's hidden controls were enumerated and dropped: the resolved tree holds exactly the
    # visible ones, and no handle the fixture states hidden is in it.
    assert len(roles["raw"]) == len(fixture["controls"]) - len(hidden)
    assert not ({row["hwnd"] for row in projected if not row["visible"]} & {
        row["hwnd"] for row in roles["raw"]
    }), "a hidden control survived `_visible_children`: a hidden row is evidence, never a target"

    assert identity_of(roles, strip) == _member("MEASUREMENT_STRIP")
    assert roles["state"] == StripView.AMBIGUOUS.value
    state = StripState(button_count=len(roles["strip_row"]), has_slider=False)
    assert state.is_startable is False
    assert press_refusal(state) is not None
    with pytest.raises(ValueError):
        state.index_of(StripControl.RECORD)
    with pytest.raises(ValueError):
        press_index(StripView.READY, StripControl.RECORD, 4)


# ================================================================== 2. the warning family
# Symptom 2 of the plan's §1: the reused destructive guard is not admitted by the dialog predicate
# at 392 px, and what it does instead is win the strip vote. Its identity is `WARNING`, and the
# blocking-surface result is what keeps that safety information alive once `open_popup` means "a
# real menu popup" and nothing else.


def warning_screen(monkeypatch: pytest.MonkeyPatch, name: str) -> tuple[dict, int]:
    """A warning-family screen and the guard's handle: the measured 392 read, or a shape over it.

    ``"392"`` is the kept read itself. The other three are the family's measured forms placed over
    the committed instrument tree (the module constants say which crop each one is): a row's source
    is the shape *and* its size, because the family rule — not one rect — is what has to carry them.
    """
    if name == "392":
        roles = resolved_kept_read(monkeypatch, "warning")
        return roles, panel_with(roles, GUARD_392)
    rect = {
        "397x135": WARNING_397,
        "353x155": WARNING_353,
        "unmeasured": WARNING_UNMEASURED,
    }[name]
    rows = screen_with_panel(
        instrument_rows(),
        panel_rect=rect,
        buttons=two_button_band(rect),
        handle=HANDLE_BASE + 800,
    )
    roles = resolve_rows(monkeypatch, rows)
    return roles, panel_with(roles, rect)


@pytest.mark.parametrize("name", ["392", "397x135", "353x155", "unmeasured"])
def test_a_measured_warning_form_is_the_warning_surface(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Row 2: every measured warning-family form is ``WARNING``, never strip, dialog or popup.

    The 392x132 member is the read itself (the guard `TSp_Panel 4393476`, device-verification.md
    *the removal guard*), with the 502x123 strip painted behind it; 397x135 and 353x155 are the
    other two measured members, from the crops UI-OVERLAY-23 and UI-OVERLAY-10; and the fourth is
    the store path's overwrite warning, whose geometry **is not measured** — the family rule (a
    compact panel wider than 250 px, taller than 90 px, two buttons in its own bottom band) is the
    only thing that carries it, which is why this row is one of the four.

    ``WARNING`` is not the measurement screen, a dialog or a popup; the blocking result is
    ``WARNING`` (the result the plan adds so narrowing ``open_popup`` erases nothing); and the
    surface's own clauses state the warning **first**, before any strip or sidebar clause — a
    warning screen diagnosed as a strip row is the misdiagnosis the device record paid for. The
    exact ``SurfaceKind`` is left as the exclusion set rather than pinned, because the plan freezes
    the member list and the clause order but not which member a *warning* reads as.
    """
    roles, guard = warning_screen(monkeypatch, name)

    # The measured consequences first: this box is not a dialog (it is 392 px, under the predicate's
    # 400), the screen is not claiming a menu popup, the surface's first clause names the warning,
    # and the kind is not any of the four the plan forbids for it. What the device record paid for is
    # exactly this reading: a guard diagnosed as a strip row, or a warning screen read as a popup.
    assert guard not in dialog_union_of(roles), (
        "the guard is not a dialog: it is under the 400 px the predicate needs, which is exact — "
        "what it does instead is win the strip vote (plan §2.2)"
    )
    assert roles["open_popup"] is False, (
        "no popup is open on this screen: `open_popup` now means a real `Parameters` popup, not "
        "'some panel hosts a button'"
    )
    kind = classify_surface(roles)
    # The kind is **pinned**, not merely excluded (the adversarial review's reading of §4): the kind
    # vocabulary has no ``WARNING`` member and the plan keeps it that way, so a warning screen is one
    # of the overlay group's surfaces and reads ``OVERLAY`` — the *identity* and the blocking surface
    # are what name it as a warning. The four exclusions the plan's pass list states are implied by
    # this one assertion, and asserted as a set here after it so a future kind cannot slip in.
    assert kind is SurfaceKind.OVERLAY, (
        f"a warning screen reads {kind!r}: a warning guard is over the measurement screen, and the "
        "kind vocabulary carries no WARNING member (plan §3) — the warning is the identity"
    )
    assert kind not in {
        SurfaceKind.MEASUREMENT,
        SurfaceKind.DIALOG,
        SurfaceKind.POPUP,
        SurfaceKind.REPLACEMENT,
    }
    clause = first_surface_clause_of(roles)
    assert "warning" in clause.lower(), (
        f"the surface's first clause does not name the warning surface: {clause!r}"
    )
    first = first_clause_of(roles)
    assert "warning" in first.lower(), (
        "the first refusal clause does not name the warning surface, so the operator is sent "
        f"looking for something else: {first!r}"
    )
    for other in ("menubar", "status band", "parameter column", "sidebar"):
        assert other not in first.lower(), f"{other!r} is named before the warning surface"

    assert identity_of(roles, guard) == _member("WARNING")
    assert blocking_surface_of(roles) == _member("WARNING")


# ======================================================================= 3. the cursor info box
# Symptom 4: the info box's out-of-panel button made the generic popup test claim a menu popup was
# open (measured 12:03:31, device-verification.md). Its identity is `CURSOR_INFO`: incidental,
# neither a target nor a readout — and never the strip it won the vote as while the strip was
# excluded.


@pytest.mark.parametrize("name", ["453", "551"])
def test_the_cursor_info_box_is_incidental_and_never_the_strip_or_a_popup(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Row 3: the 149x59 box, in two of the reads the device record carries it up in.

    Measured `TSp_Panel 131916 [908,466,1057,525]`, holding the caption-less child panel
    `[916,475,1045,514]` and owning a button whose centre lies **outside** the box — which is why an
    owned button may confer neither strip nor popup identity. The box is present in the 453 and 551
    reads (and in the 370 one, whose `open_popup: True` false positive this same box caused), and in
    the 453 read it is the panel the pre-fix vote hands the strip over to.
    """
    roles = resolved_kept_read(monkeypatch, name)
    box = panel_with(roles, INFO_BOX)

    # The measured consequence first: the box paints nothing below the strip, so it is not the
    # panel a press may be bound to — and on the 453 read it is the panel the pre-fix vote picked.
    assert roles["strip_panel"] is not None and roles["strip_panel"]["hwnd"] != box, (
        "the cursor info box was bound as the strip: it paints nothing below the strip, and the "
        "button it owns lies outside its own rect"
    )
    assert roles["open_popup"] is False, (
        "the screen claims a menu popup is open because the info box owns one button — the "
        "measured false positive of 12:03:31"
    )

    assert identity_of(roles, box) == _member("CURSOR_INFO")
    assert box not in dialog_union_of(roles)
    assert blocking_surface_of(roles) is None, "the info box is not a blocking surface"

    # The box's own shape, off the resolved tree: its child panel, and the button it owns below
    # itself.
    kids = [row for row in roles["raw"] if row["parent"] == box]
    assert [tuple(kid["rect"]) for kid in kids if kid["cls"] == "TSp_Panel"] == [INFO_BOX_CHILD]
    owned = [kid for kid in kids if kid["cls"] == "TSp_Button"]
    assert [tuple(kid["rect"]) for kid in owned] == [INFO_BOX_BUTTON]
    assert owned[0]["top"] > INFO_BOX[3], "the owned button is not below the box it belongs to"


# ================================================================== 4. the Parameters popup
# The one case that may set `open_popup`: the real menu popup. Every other row of this file asserts
# `open_popup is False`, which is what makes "the only case" a statement rather than a hope.


def parameters_popup_screen(monkeypatch: pytest.MonkeyPatch) -> dict:
    """The committed instrument tree with the measured ``Parameters`` popup open over it.

    The popup is `TSp_Panel [169,55,401,250]` — ``ui.menu.PARAMETERS_POPUP_LEFT`` 169 and 195 px
    tall, above the 120 px floor the reference's own predicate uses — with its five caption-less
    entries at the screen tops ``ui.menu`` records, hung off the window the way the application
    paints a menu (the pre-created panel is *shown* on the hover; nothing here is hidden).
    """
    rows = screen_with_panel(
        instrument_rows(),
        panel_rect=POPUP_RECT,
        buttons=POPUP_ENTRIES,
        handle=HANDLE_BASE + 700,
    )
    return resolve_rows(monkeypatch, rows)


def test_the_real_parameters_popup_is_the_only_case_that_sets_open_popup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 4: ``MENU_POPUP``, ``open_popup`` true, ``blocking_surface`` ``MENU_POPUP``, surface POPUP.

    The popup's identity is its demonstrated signature *and* its own entries
    (:func:`…ui.menu.entry_buttons`), which is what keeps every unknown button-hosting panel — the
    ``Define TGC`` overlay, a warning box, the cursor info box — out of this claim. The surface
    reads ``POPUP``, and the blocking result names the popup: a menu that is up *is* a surface a
    press must not be posted behind, so narrowing ``open_popup`` to this one case may not lose it.
    """
    roles = parameters_popup_screen(monkeypatch)
    popup = panel_with(roles, POPUP_RECT)

    assert identity_of(roles, popup) == _member("MENU_POPUP")
    assert roles["open_popup"] is True
    assert blocking_surface_of(roles) == _member("MENU_POPUP")
    assert classify_surface(roles) is SurfaceKind.POPUP
    assert popup not in dialog_union_of(roles)

    # The popup's own entries, in screen order, off the tree the resolver bound: five of them, at
    # the measured tops — the popup the `Parameters` hover opens is *this* one, not "a panel with
    # buttons".
    entries = sorted(
        (
            row
            for row in roles["raw"]
            if row["parent"] == popup and row["cls"] == "TSp_Button"
        ),
        key=lambda row: (row["top"], row["left"]),
    )
    assert [tuple(entry["rect"]) for entry in entries] == list(POPUP_ENTRIES)
    # ...and the menubar's own `Parameters` anchor still resolves under it: the popup is opened by
    # that button and may not rename it (the bar is evidence; the anchor is the one binding).
    anchor = driver.anchor_button(driver.observation_of(roles))
    assert anchor is not None and anchor.rect is not None
    assert anchor.rect.left == PARAMETERS_POPUP_LEFT
    assert PARAMETERS_POPUP_MIN_H < POPUP_RECT[3] - POPUP_RECT[1]


# =============================================================== 5. Define TGC, three sources
# Symptom 5 (and V3's own failure): the overlay is admitted by the dialog predicate, so the surface
# reads `dialog` — and the strip's absence is then reported as a strip failure instead of a surface
# standing in front of the measurement layout. Three independent sources, kept distinct: the raw
# 2026-09-18 read, the crop-derived synthesised tree, and sitting C's own 450x120 status read.


def sitting_c_tgc_screen(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Sitting C's own measurement, as a tree: the visible ``Define TGC`` panel at 450x120.

    The status read of 2026-09-19 (device-verification.md, *sitting C, V3*) reports the overlay at
    ``[400,168,850,288]`` with the real strip **not visible** — the shape the 2026-09-18 read
    carries too — and its children are the class of control the wider predicate accepts: two
    ``TSp_Value_Button``s, a ``TComboBox`` and three ``TSp_Button``s whose tops begin 46-89 px below
    the panel's own top. The bare instrument tree underneath is the clean screen sitting C started
    from.
    """
    left, top, _right, _bottom = TGC_OVERLAY
    panel = _row(HANDLE_BASE + 900, "TSp_Panel", WINDOW_HWND, TGC_OVERLAY)
    kids = [
        _row(HANDLE_BASE + 901, "TSp_Value_Button", panel["hwnd"], (left + 100, top + 4, left + 160, top + 28)),
        _row(HANDLE_BASE + 902, "TSp_Value_Button", panel["hwnd"], (left + 200, top + 4, left + 260, top + 28)),
        _row(HANDLE_BASE + 903, "TComboBox", panel["hwnd"], (left + 300, top + 4, left + 360, top + 28)),
        _row(HANDLE_BASE + 904, "TSp_Button", panel["hwnd"], (left + 50, top + 82, left + 120, top + 107)),
        _row(HANDLE_BASE + 905, "TSp_Button", panel["hwnd"], (left + 160, top + 82, left + 230, top + 107)),
        _row(HANDLE_BASE + 906, "TSp_Button", panel["hwnd"], (left + 270, top + 82, left + 340, top + 107)),
    ]
    return resolve_rows(monkeypatch, [*instrument_rows(), panel, *kids])


def assert_the_active_overlay_is_named_first(roles: dict) -> None:
    """The ordering V3 requires: the surface first, and never a strip or sidebar reason before it."""
    first = first_clause_of(roles)
    assert "overlay" in first.lower() or "non-measurement" in first.lower(), (
        "the first refusal clause does not name the active overlay/non-measurement surface: "
        f"{first!r}"
    )
    for other in ("STRIP_BUTTON_ORDER", "sidebar", "parameter column", "menubar"):
        assert other not in first, f"{other!r} is named before the overlay standing in front of it"


def test_the_define_tgc_overlay_is_an_overlay_and_never_a_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 5, source 1 — the raw 2026-09-18 read (``outputs/live/tgc-d-overlay-open.json``).

    The overlay is up and the real strip panel is **present and not visible**, so no strip resolves
    and the pre-fix dialog predicate admits the overlay instead: the surface reads ``dialog``, the
    operator is told a dialog is up, and the *second* refusal blames the strip. ``REPLACEMENT`` is
    not available to it either (the menubar and the monitor are both on screen). The first refusal
    clause has to name the active non-measurement surface — that ordering *is* V3's requirement.
    """
    roles = resolved_kept_read(monkeypatch, "tgc")
    overlay = panel_with(roles, TGC_OVERLAY)

    # The measured consequence first: the overlay is in the dialog union today, which is why the
    # status read calls this screen a dialog and then blames the strip.
    assert overlay not in dialog_union_of(roles), (
        "the `Define TGC` overlay entered the dialog union: it directly owns `TSp_Value_Button`s, "
        "which `_DIALOG_INPUT_CLASSES` accepts for any panel wider than 400 px (plan §2.2)"
    )
    assert classify_surface(roles) is not SurfaceKind.REPLACEMENT, (
        "the menubar band and the monitor are both on this screen, so `REPLACEMENT` is not an "
        "answer it may take"
    )
    assert_the_active_overlay_is_named_first(roles)

    assert identity_of(roles, overlay) == _member("OVERLAY")
    assert classify_surface(roles) is SurfaceKind.OVERLAY
    assert blocking_surface_of(roles) == _member("OVERLAY")


def test_the_crop_derived_tgc_fixture_classifies_as_an_overlay() -> None:
    """Row 5, source 2 — the repository's own crop-derived fixture (``screen_with_overlay``).

    This source is a *resolved role map*, not a tree (the overlay is 453x123 there, at the size
    UI-OVERLAY-01 measures, placed in the plot band), so it carries no ``identities`` map and the
    identity claim belongs to the two tree sources. What it states is the pure half of the same
    interface: the surface is ``OVERLAY`` and never ``REPLACEMENT``, and the first **surface**
    clause names the overlay — the assertion
    ``tests/test_acquire_surface_classification.py`` already rests on, kept here as the row that
    says what a fix may not move.
    """
    roles = screen_with_overlay()

    kind = classify_surface(roles)
    assert kind is SurfaceKind.OVERLAY
    assert kind is not SurfaceKind.REPLACEMENT
    clause = first_surface_clause_of(roles)
    assert "overlay" in clause.lower(), clause
    assert "STRIP_BUTTON_ORDER" not in first_clause_of(roles), (
        "the strip's own row is diagnosed before the overlay on this screen"
    )


def test_sitting_cs_visible_overlay_is_an_overlay_and_never_a_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 5, source 3 — sitting C's own 450x120 status read, as a synthesised tree.

    The device record's V3 failure, in the shape the operator left on the screen: the overlay is
    visible, the real strip is not, and the status read reports *"a dialog is up"* with the surface
    reading ``dialog`` and the ``overlay`` field ``None``. Identity ``OVERLAY``, never
    ``REPLACEMENT``, and the overlay clause first — the item V3 was failed on.
    """
    roles = sitting_c_tgc_screen(monkeypatch)
    overlay = panel_with(roles, TGC_OVERLAY)

    assert overlay not in dialog_union_of(roles), (
        "the visible overlay is in the dialog union, which is why this read says *a dialog is up* "
        "and then blames the strip for not resolving"
    )
    assert_the_active_overlay_is_named_first(roles)
    assert classify_surface(roles) is not SurfaceKind.REPLACEMENT

    assert identity_of(roles, overlay) == _member("OVERLAY")
    assert classify_surface(roles) is SurfaceKind.OVERLAY
    assert blocking_surface_of(roles) == _member("OVERLAY")


# ============================================================== 6. the replacement surfaces
# B08: `Compare profiles` / `Measure US field` replace the client area, so "no sidebar and no strip"
# is another surface and not a channel mode. Both fixtures here are resolved role maps (no tree), so
# as with the crop-derived case above the claim is the pure surface half — which is exactly what the
# plan's Slice 2 pass criterion states for them.


def measure_us_field_surface() -> dict:
    """``Measure US field`` (UI-OVERLAY-19) as a resolved tree — the five-button widget band.

    The other replacement surface, modelled the way ``replacement_surface`` models UI-OVERLAY-22:
    the crop paints the surface's own controls — ``Parameters``, ``Recall from file``, ``Add
    slice``, ``Show slices`` and ``Exit`` (the first four inside its left band, ``Exit`` alone at
    the band's right end) — over a client area with no menubar band, no plot, no column and no
    strip. Nothing about a channel mode is read from it (ledger B08).
    """
    band = _panel(190, ORIGIN[1], w=1000, h=60)
    buttons = [_button(191 + index, 20 + 150 * index, ORIGIN[1] + 10) for index in range(4)]
    buttons.append(_button(195, 1850, ORIGIN[1] + 10))
    raw = [band, *buttons]
    return {
        "window": 0,
        "class_name": driver.MAIN_CLASS,
        "client": (1920, 1027),
        "origin": ORIGIN,
        "raw": raw,
        "panels": [band],
        "parent_of": {widget["hwnd"]: 0 for widget in raw},
        "menu": {},
        "menu_band": None,
        "plot": None,
        "open_popup": False,
        "value_dialogs": set(),
        "browse_dialogs": set(),
        "strip_panel": band,
        "strip_row": buttons,
        "state": classify_strip_view(len(buttons), False).value,
        "left_panel": None,
        "param_rows": [],
        "params": {},
    }


@pytest.mark.parametrize(
    ("label", "screen"),
    [
        ("compare-profiles", replacement_surface),
        ("measure-us-field", measure_us_field_surface),
    ],
)
def test_both_replacement_surfaces_are_replacement_and_never_an_overlay(
    label: str, screen: typing.Callable[[], dict]
) -> None:
    """Row 6: the two committed replacement surfaces, both of them ``REPLACEMENT``.

    UI-OVERLAY-22 (`Compare profiles`, the six-button band) and UI-OVERLAY-19 (`Measure US field`,
    the five-button band and its slice geometry): neither is a measurement screen and neither may be
    read as an overlay — the ordering clause that puts ``REPLACEMENT`` ahead of ``OVERLAY`` in the
    plan §3 is the one this row rests on, and it is asserted on both sources so a fix that reorders
    them fails here and nowhere subtler.
    """
    roles = screen()

    kind = classify_surface(roles)
    assert kind is SurfaceKind.REPLACEMENT, (
        f"{label!r}: the surface that replaced the client area is read as {kind!r}"
    )
    assert kind is not SurfaceKind.OVERLAY
    clause = first_surface_clause_of(roles)
    assert "surface" in clause.lower() or "replacement" in clause.lower(), clause


# ============================================== 7. the application dialogs (values and browse)


def test_the_measured_operating_parameters_dialog_is_an_application_dialog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 7: the 627x384 / 21-direct-child panel — ``APPLICATION_DIALOG``, ``DIALOG``, values half.

    The measured ``Operating parameters`` dialog is a dialog *structurally* (the committed fixture,
    read live 2026-09-18) and carries neither a direct edit nor a ``TSp_Browse`` — the pair the
    resolver's older private rule asked for — so before the canonical predicate it stayed outside
    the union, took part in the strip vote, and its five bottom buttons outvoted the recording
    strip's three. Its identity is the fallback item of the plan's §2.1 (the dialog predicate
    itself, unchanged), and what this row adds is that the narrower identities above it — overlay,
    warning, strip, cursor box — do not steal it.
    """
    roles = resolved_dialog_screen(monkeypatch)

    assert identity_of(roles, DIALOG_HWND) == _member("APPLICATION_DIALOG")
    assert DIALOG_HWND in roles["value_dialogs"], (
        "a dialog holding `TSp_Value_Button` fields of its own is the values dialog; only the "
        "browse/store class is `browse_dialogs`"
    )
    assert DIALOG_HWND not in roles["browse_dialogs"]
    assert classify_surface(roles) is SurfaceKind.DIALOG
    assert blocking_surface_of(roles) == _member("APPLICATION_DIALOG")
    assert roles["open_popup"] is False


def store_dialog_rows(app: FakeUdopWindow) -> list[dict]:
    """``FakeUdopWindow``'s own tree as stand-in rows, with the store class's browse discriminator.

    The synthetic driver fixture is the repository's store dialog — the measured panel with its name
    and directory edits and its ``Cancel`` / ``Do store`` pair — and the one node it does not state
    is the ``TSp_Browse`` the browse/store class is identified by (plan §2.1 item 2, and what
    ``_find_overlay`` / ``_require_store_dialog`` have always asked for). It is added here, inside
    the panel, because without it the panel is a compact box with two buttons in its bottom band —
    the warning family's own rule — which is precisely the confusion this row exists to forbid.
    """
    rows = [
        _row(
            node["hwnd"],
            node["cls"],
            WINDOW_HWND if app.parent_of(node["hwnd"]) == 0 else app.parent_of(node["hwnd"]),
            (node["left"], node["top"], node["left"] + node["w"], node["top"] + node["h"]),
            node.get("text", ""),
        )
        for node in app.nodes()
    ]
    store = next(row for row in rows if row["cls"] == "TSp_Panel" and row["text"] == "Store")
    rows.append(
        _row(
            store["hwnd"] + 500,
            "TSp_Browse",
            store["hwnd"],
            (store["left"] + 430, store["top"] + 90, store["left"] + 540, store["top"] + 110),
            "...",
        )
    )
    return rows


def test_the_store_dialog_is_a_dialog_never_a_warning_and_the_warning_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 8: the browse/store class first, and the overwrite warning still reachable after it.

    Two states of the same path, distinguished *before* the warning family is considered: the store
    dialog up (the synthetic driver fixture, with the browse discriminator the class carries) —
    ``APPLICATION_DIALOG``, in ``browse_dialogs``, **never** ``WARNING``, and the blocking result
    naming the dialog; then the dialog answered and the overwrite warning raised (its geometry
    unmeasured — the continuation the store path answers with its safe end,
    ``wait_for_stored_file`` → ``answer_overlay``) — ``WARNING`` again. A fix that read the store
    class as a warning would swallow the commit path; one that answered a warning as a dialog would
    press the wrong end of a destructive box. Both are refused here.
    """
    app = FakeUdopWindow()
    app.store_open = True
    rows = store_dialog_rows(app)
    roles = resolve_rows(monkeypatch, rows)
    store = panel_with_text(roles, "Store")

    assert identity_of(roles, store) == _member("APPLICATION_DIALOG")
    assert store in roles["browse_dialogs"], (
        "the store class must stay in `browse_dialogs`: everything that answers a Store dialog looks "
        "for it there, and a store dialog filed as a values dialog stops being found"
    )
    assert store not in roles["value_dialogs"]
    assert classify_surface(roles) is SurfaceKind.DIALOG
    assert blocking_surface_of(roles) == _member("APPLICATION_DIALOG")

    # The continuation: the store dialog is answered and the overwrite warning is what is up. Its
    # geometry is deliberately unlike the three measured forms (the corpus has no crop of it), so
    # the family rule is the only thing that can classify it.
    owned = {
        row["hwnd"]
        for row in rows
        if row["hwnd"] == store or row["parent"] == store
    }
    panel = next(row for row in rows if row["hwnd"] == store)
    warning = _row(
        WINDOW_HWND + 9000,
        "TSp_Panel",
        WINDOW_HWND,
        (panel["left"], panel["top"], panel["left"] + 560, panel["top"] + 200),
    )
    warning_kids = [
        _row(
            WINDOW_HWND + 9001,
            "TSp_Button",
            warning["hwnd"],
            (warning["left"] + 40, warning["top"] + 140, warning["left"] + 150, warning["top"] + 165),
        ),
        _row(
            WINDOW_HWND + 9002,
            "TSp_Button",
            warning["hwnd"],
            (warning["left"] + 400, warning["top"] + 140, warning["left"] + 520, warning["top"] + 165),
        ),
    ]
    answered = [row for row in rows if row["hwnd"] not in owned]
    roles = resolve_rows(monkeypatch, [*answered, warning, *warning_kids])

    assert identity_of(roles, warning["hwnd"]) == _member("WARNING"), (
        "the store path's own overwrite warning is not classified as a warning after the store "
        "dialog is handled, so the continuation it answers with has no surface to answer"
    )
    assert blocking_surface_of(roles) == _member("WARNING")
    assert warning["hwnd"] not in dialog_union_of(roles)


def panel_with_text(roles: dict, text: str) -> int:
    """The handle of the window-level panel whose own text is ``text`` (the fake's `Store` panel)."""
    found = [panel["hwnd"] for panel in roles["panels"] if panel.get("text") == text]
    assert len(found) == 1, f"no single window-level panel stating {text!r}: {found}"
    return found[0]


# ================================================== 9. the clean screen, and no false surface


def test_the_clean_instrument_screen_has_no_false_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Row 9: the guard every row above rests on — the clean screen stays clean.

    The committed instrument fixture (44 visible controls in 4 panels, the 352 px ``ready`` strip,
    the real-experiment caption): no surface at all, ``open_popup`` false, no blocking surface, no
    dialog, and the strip carrying its identity. A matrix of counterexamples is evidence only if the
    machinery it goes through can also accept the real screen.
    """
    roles = resolved_instrument(monkeypatch)
    strip = panel_with(roles, STRIP_PANEL)

    assert len(roles["raw"]) == 44
    assert len(roles["panels"]) == driver.EXPECTED_PANEL_COUNT == 4
    assert roles["state"] == StripView.READY.value
    assert roles["open_popup"] is False
    assert blocking_surface_of(roles) is None
    assert identity_of(roles, strip) == _member("MEASUREMENT_STRIP")
    assert dialog_union_of(roles) == set()
    assert classify_surface(roles) is SurfaceKind.MEASUREMENT
    assert driver.layout_refusal(roles) is None
    assert surface_clauses(observation_of(roles)) == ()


# ====================================================== the cleanup hazard, and its negative control


def booby_trapped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make **any** send, post, cursor move or press raise — the transport's own tripwire.

    The same shape ``test_acquire_instrument_screen.py``'s ``NoTransport`` uses, extended to the
    primitives a press could reach: ``user32`` answers nothing and the module-level post helper
    raises. A case that drives a press path with this installed cannot press anything by accident —
    reaching the transport *is* the failure.
    """

    class NoTransport:
        def __getattr__(self, name: str) -> typing.NoReturn:
            raise AssertionError(
                f"a press path reached user32.{name} with a non-actionable surface up: nothing on "
                "this screen may be pressed"
            )

    def _no_post(*args: object, **kwargs: object) -> typing.NoReturn:
        raise AssertionError("a press path posted a message where nothing may be pressed")

    monkeypatch.setattr(driver, "_user32", lambda: NoTransport())
    monkeypatch.setattr(driver, "_post", _no_post)


class _ResolvedScreen(driver.Win32Actuator):
    """A driver over the kept read's own resolved roles — no window, and every press tripwired.

    The double ``tests/test_acquire_dialog_guard.py`` uses for the same purpose: ``_resolve`` answers
    the map the read produced, the window layer the cleanup path still needs is the fixture's own
    stand-in, and ``_click_hold`` raises instead of pressing, so an attempted press *is* the failure
    text.
    """

    def __init__(self, roles: dict) -> None:
        super().__init__(channel=1)
        self._roles = roles
        self.presses: list[int] = []
        self.notes: list[str] = []

    def _resolve(self) -> dict:
        return self._roles

    def _click_hold(self, hwnd: int, hold_ms: int = 0) -> None:
        self.presses.append(hwnd)
        raise AssertionError(
            f"the cleanup path pressed {hwnd} on a panel that is not a dialog: this is the measured "
            "hazard (plan §3.1) — `row[-2]` of the 453x40 strip's band is `Do store`"
        )

    def _send(self, *args: object, **kwargs: object) -> int:
        raise AssertionError("the cleanup path sent a message where nothing may be pressed")

    def _note(self, message: str) -> None:
        self.notes.append(message)


def test_the_cleanup_path_presses_nothing_on_the_453_strip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cleanup negative control: ``_close_any_dialog`` on the 453x40 strip presses **nothing**.

    The measured hazard (plan §3.1, device-verification.md *the four-button strip, block-held*): the
    453x40 intermediate panel is admitted by the dialog predicate, its broad bottom band resolves
    **six** buttons rather than the row's four, and the safe end (``row[-2]``) is `2821164` — the
    control the same-process handle map binds as **`Do store`** — while the confirm end (``row[-1]``)
    is `1641666` `Clear and restart`. So a cleanup that closes "whatever dialog is up" on this screen
    presses a state-changing strip control at either end.

    ``_close_any_dialog`` may accept only an ``APPLICATION_DIALOG`` (plan §3), which the 453x40 strip
    is not. With the transport tripwired, any attempted press is this test's failure and reaching the
    end with none attempted is the pass — cloud-side proof that the *classification*, not the band,
    is what closes the hazard. Nothing here is device-verified.
    """
    roles = resolved_kept_read(monkeypatch, "453")
    booby_trapped(monkeypatch)
    screen = _ResolvedScreen(roles)

    screen._close_any_dialog()

    assert screen.presses == [], "the cleanup path attempted a press"
    assert not any(
        "pressed" in note for note in screen.notes
    ), f"the cleanup path reported a press it should not have made: {screen.notes}"


def test_the_453_bands_ends_are_do_store_and_clear_and_restart_and_identity_excludes_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The pre-fix demonstration** — the hazard itself, kept as a failing row on purpose.

    ``ui.dialog.bottom_row`` resolves the 453x40 panel's own band as **six** entries (the plan's
    §3.1 measurement), and left → right by screen left they are
    `[350,467,401,482]` `[353,424,432,444]` `[409,467,453,482]` `[442,424,527,444]`
    `[537,423,628,443]` `[638,423,776,443]` — the two caption-less `Profiles history` toggles
    (painted below the panel's own 40 px rect) interleaved with the row's four, so *neither* end of
    the band is an end of the strip's row. The two ends a dialog close addresses are therefore
    `2821164` **`Do store`** (``row[-2]``) and `1641666` **`Clear and restart`** (``row[-1]``).

    The fix closes that hazard by *identity* — ``_close_any_dialog`` accepts only an
    ``APPLICATION_DIALOG``, which this panel is not — and deliberately does **not** narrow
    ``bottom_row``'s own band, which is a real dialog rule the operating dialog's Cancel/Accept
    pair is read from. So this row pins the band **entry for entry**, as the plan now requires
    (§3.1), states which control each end a dialog close addresses, and asserts the exclusion that
    actually closes the hazard: the panel carries no ``APPLICATION_DIALOG`` identity, so no close
    path may address its band at all. A four-button fixture would have passed here *for the wrong
    reason*, which is why the band is asserted rect for rect; the pre-fix run of this row (its
    ``--tb=line`` failure before Slice 2 landed) is the demonstration the plan asks to preserve and
    is quoted in the pull request that lands it. Nothing here is device-verified.
    """
    roles = resolved_kept_read(monkeypatch, "453")
    panel = next(p for p in roles["panels"] if tuple(p["rect"]) == STRIP_453)
    # The panel's own children, off the projection the resolve read: the driver's `raw` rows carry
    # no parent link (they are one flat enumeration), so the tree comes from the fixture's own
    # projection — the same rows the resolver enumerated.
    kids = [
        row
        for row in project_rows(kept_read("453"))
        if row["parent"] == panel["hwnd"] and row["visible"]
    ]

    band = bottom_row(panel, kids)

    assert len(band) == 6, (
        "the 453x40 strip's band no longer resolves six entries, so this row's evidence is not the "
        f"one the plan §3.1 measured: {[tuple(b['rect']) for b in band]}"
    )
    assert [tuple(b["rect"]) for b in band] == [
        (350, 467, 401, 482),
        (353, 424, 432, 444),
        (409, 467, 453, 482),
        (442, 424, 527, 444),
        DO_STORE_RECT,
        CLEAR_AND_RESTART_RECT,
    ], (
        "the band is not the measured six, left -> right — the two toggles painted below the "
        "panel's own 40 px rect interleave with the row's four, so neither end of the band is an "
        "end of the strip's row, and a four-button fixture would pass for the wrong reason"
    )

    assert tuple(band[-2]["rect"]) == DO_STORE_RECT, (
        "the safe end (`row[-2]`) of the 453x40 strip's band is the control the same-process "
        f"handle map binds as `Do store` ({DO_STORE_RECT}, handle 2821164) — the measured hazard "
        "(plan §3.1)"
    )
    assert tuple(band[-1]["rect"]) == CLEAR_AND_RESTART_RECT, (
        "and its confirm end (`row[-1]`) is `Clear and restart` "
        f"({CLEAR_AND_RESTART_RECT}, handle 1641666): both ends are state-changing strip controls"
    )
    assert roles["identities"][panel["hwnd"]] is not _member("APPLICATION_DIALOG"), (
        "the panel whose band holds those two destructive ends is not an application dialog, and "
        "that — not the band — is what keeps a cleanup press off it (plan §3.1)"
    )
    assert panel["hwnd"] not in (set(roles["value_dialogs"]) | set(roles["browse_dialogs"]))