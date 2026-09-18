"""Contract tests for the instrument snapshot — ``acquire/snapshot.py``.

``test_acquire_actuator.py`` pins the port's binding tables; this module pins the two models
the next slice compiles against, and it pins them on the plan's own criteria:

- **criterion 4** — nothing here claims an instrument fact that was not read. A fact the
  instrument cannot state is carried as ``unreadable`` *with its reason*, and the model refuses
  the combinations that would let a reader take one state for another (a ``read`` fact with no
  value, an ``unreadable`` one with a value). The reason is asserted to be there, because a
  nameless ``None`` is indistinguishable from a fact somebody forgot.
- **criterion 3, in both directions** — the identity moves with every fact campaign
  compatibility depends on (each of the six, by value *and* by provenance, plus the channel, the
  mode and the layout signature), and it does **not** move with anything a restart changes
  (``hwnd``, rect, maximised state, screen, cursor, foreground) or with the store slider's
  maximum, which is the selected block's profile count rather than the layout.
- **the projection is values and sources, never wording** — a ``reason`` rewritten for a human
  reader does not move the identity, because a documentation improvement must not re-run a point
  that was already measured.

Everything here is headless and instrument-free: the readings are built from the measured
shapes (43 visible controls in 4 panels on the clean manual screen, 169.0 µs and 52 emissions
on the tested channel), and no test needs a window.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire.actuator import (
    ChannelMode,
    ScreenFingerprint,
    StripState,
    StripView,
)
from udv_echo_process.acquire.snapshot import (
    FIXED_FACT_FIELDS,
    CompilationIdentity,
    FactSource,
    InstrumentFact,
    InstrumentSnapshot,
    Provenance,
    declared,
    identity_digest,
    unreadable,
)

#: The tested channel's fixed facts as the application's own surface states them
#: (``docs/13 §1``: PRF period 169 µs, 52 emissions per profile).
PRF_TEXT = "169.0"
EMISSIONS_TEXT = "52"

#: The clean manual measurement screen, as the live fingerprint reads it.
CLEAN_CLASS = "TMain_Scr"
CLEAN_HWND = 660124
CLEAN_RECT = (-8, -8, 1928, 1058)
CLEAN_SCREEN = (1920, 1080)
CLEAN_PANELS = 4
CLEAN_CONTROLS = 43

#: Why the four facts nothing can read yet are unreadable — the driver's own reasons, reproduced
#: here because a reason is part of the fact, not decoration.
DIALOG_ONLY_REASON = (
    "{name!r} has no parameter-column field: it is set in the 'Operating parameters' dialog "
    "only, so nothing on the measurement screen states it"
)
CAP_REASON = (
    "the block cap is an application Preference, not a measurement parameter, and nothing in "
    "this driver reads the Preference surface"
)


def fingerprint(**overrides: object) -> ScreenFingerprint:
    """One reading of the clean manual screen; ``overrides`` replace single fields."""
    fields: dict[str, object] = {
        "class_name": CLEAN_CLASS,
        "hwnd": CLEAN_HWND,
        "rect": CLEAN_RECT,
        "maximized": True,
        "screen": CLEAN_SCREEN,
        "panels": CLEAN_PANELS,
        "visible_controls": CLEAN_CONTROLS,
        "strip": StripState(button_count=3),
        "overlay": None,
        "layout_note": None,
        "cursor": (33, 77),
        "is_foreground": True,
    }
    fields.update(overrides)
    return ScreenFingerprint(**fields)


def read(value: str) -> InstrumentFact:
    """A fact the application's own surface answered."""
    return InstrumentFact(value=value, source=FactSource.READ)


def snapshot(**overrides: object) -> InstrumentSnapshot:
    """One full reading of the tested channel, with two facts read and four unreadable."""
    fields: dict[str, object] = {
        "fingerprint": fingerprint(),
        "channel": declared(
            "1", reason="the configured channel, routed before this read"
        ),
        "mode": read(ChannelMode.MANUAL.value),
        "prf_us": read(PRF_TEXT),
        "emissions_per_profile": read(EMISSIONS_TEXT),
        "burst_length": unreadable(DIALOG_ONLY_REASON.format(name="burst_length")),
        "sound_speed_ms": unreadable(DIALOG_ONLY_REASON.format(name="sound_speed_ms")),
        "first_gate_mm": unreadable(DIALOG_ONLY_REASON.format(name="first_gate_mm")),
        "max_profiles_per_block": unreadable(CAP_REASON),
    }
    fields.update(overrides)
    return InstrumentSnapshot(**fields)


def digest(reading: InstrumentSnapshot) -> str:
    """The identity a resume would compare, as its digest."""
    return identity_digest(CompilationIdentity.from_snapshot(reading))


# ---------------------------------------------------------- the models round-trip and refuse


def test_both_models_round_trip_through_json() -> None:
    """A snapshot and an identity survive serialisation: they are what a record carries."""
    reading = snapshot()
    identity = CompilationIdentity.from_snapshot(reading)

    assert InstrumentSnapshot.model_validate_json(reading.model_dump_json()) == reading
    assert (
        CompilationIdentity.model_validate_json(identity.model_dump_json()) == identity
    )
    # The evidence keeps the volatile half a fingerprint exists for; the identity does not
    # carry it at all (asserted by name below), so a restart cannot read as a new instrument.
    assert reading.fingerprint.hwnd == CLEAN_HWND
    assert reading.fingerprint.cursor == (33, 77)


def test_a_read_fact_needs_a_value_and_explains_nothing() -> None:
    """The application's own answer is either a value or not a ``read`` fact at all."""
    with pytest.raises(ValidationError, match="must carry the value"):
        InstrumentFact(source=FactSource.READ)
    with pytest.raises(ValidationError, match="carries no reason"):
        InstrumentFact(value="169.0", source=FactSource.READ, reason="maybe")


def test_an_unreadable_fact_carries_no_value_and_says_why() -> None:
    """The one state that must never look like a measurement: no value, and a reason."""
    with pytest.raises(ValidationError, match="carries no value"):
        InstrumentFact(
            value="169.0", source=FactSource.UNREADABLE, reason="no read path"
        )
    with pytest.raises(ValidationError, match="must say why"):
        InstrumentFact(source=FactSource.UNREADABLE)
    with pytest.raises(ValidationError, match="must say why"):
        InstrumentFact(source=FactSource.UNREADABLE, reason="")


def test_a_declared_fact_needs_something_declared() -> None:
    """'Declared' is a weaker claim than a read — not an absence of one."""
    with pytest.raises(ValidationError, match="must carry the value"):
        InstrumentFact(source=FactSource.DECLARED)


# ---------------------------------------------------------------- criterion 4: nothing unread


def test_every_fixed_fact_is_carried_read_or_unreadable() -> None:
    """All six are named on every reading — the unreadable ones are facts, not omissions."""
    reading = snapshot()

    assert list(dict(reading.facts())) == list(FIXED_FACT_FIELDS)
    assert reading.read_facts() == ("prf_us", "emissions_per_profile")
    assert reading.unreadable_facts() == (
        "burst_length",
        "sound_speed_ms",
        "first_gate_mm",
        "max_profiles_per_block",
    )
    for name in reading.unreadable_facts():
        assert reading.fact(name).reason, name


@pytest.mark.parametrize("name", FIXED_FACT_FIELDS)
def test_a_fact_that_was_not_read_is_not_a_value(name: str) -> None:
    """The four with no read path have *no* value: a number here would be the whole failure."""
    fact = snapshot().fact(name)
    if fact.source is FactSource.UNREADABLE:
        assert fact.value is None
        assert not fact.is_read
    else:
        assert fact.is_read and fact.value


def test_an_unknown_fact_name_is_refused_by_name() -> None:
    """A caller reconciling a fact it invented is told which ones exist."""
    with pytest.raises(ValueError, match="no fixed fact 'gates'"):
        snapshot().fact("gates")


# ------------------------------------------------------------ criterion 3: the two directions


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        ("a new hwnd after a restart", {"hwnd": CLEAN_HWND + 1}),
        ("the window moved", {"rect": (-8, -8, 1600, 900)}),
        ("the window restored", {"maximized": False}),
        ("another screen", {"screen": (2560, 1440)}),
        ("the cursor somewhere else", {"cursor": (900, 40)}),
        ("a session that cannot read the cursor", {"cursor": None}),
        ("the application no longer foreground", {"is_foreground": False}),
        ("a layout note added", {"layout_note": "a popup is open"}),
    ],
)
def test_nothing_a_restart_changes_moves_the_identity(
    label: str, changed: dict[str, object]
) -> None:
    """A restart is the same instrument: the identity is a projection, not the fingerprint."""
    assert digest(snapshot(fingerprint=fingerprint(**changed))) == digest(snapshot())


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        ("a modal is up", {"overlay": "warning"}),
        ("a dialog is up", {"overlay": "store_dialog"}),
    ],
)
def test_a_precondition_is_not_a_property_of_the_instrument(
    label: str, changed: dict[str, object]
) -> None:
    """An overlay refuses the compile; it does not make a different instrument of this one."""
    assert digest(snapshot(fingerprint=fingerprint(**changed))) == digest(snapshot())


def test_the_store_sliders_maximum_is_not_the_layout() -> None:
    """The slider's range is the selected block's profile count — the run's own data."""
    idle = snapshot(fingerprint=fingerprint(strip=StripState(button_count=3)))
    holding = snapshot(
        fingerprint=fingerprint(strip=StripState(button_count=3, slider_max=1384))
    )
    assert idle.fingerprint.strip.slider_max is None
    assert holding.fingerprint.strip.slider_max == 1384
    assert digest(idle) == digest(holding)


def test_a_leftover_block_in_the_buffer_is_not_a_different_instrument() -> None:
    """The ready row's 3 vs 4 buttons is buffer state — ``STRIP_BUTTON_ORDER`` holds both rows.

    This application's ready row gains ``Do store`` once its block holds data, so a restart with
    an empty buffer and a run resuming while holding a block differ by exactly this — and both
    are ``READY``, the view a press is bound against. A comparison that included the count would
    call the same instrument two, on a difference that is the *run's own progress*.
    """
    empty = snapshot(fingerprint=fingerprint(strip=StripState(button_count=3)))
    holding = snapshot(fingerprint=fingerprint(strip=StripState(button_count=4)))

    assert empty.fingerprint.strip.button_count == 3
    assert holding.fingerprint.strip.button_count == 4
    assert empty != holding
    assert digest(empty) == digest(holding)


@pytest.mark.parametrize("name", FIXED_FACT_FIELDS)
def test_every_fixed_fact_moves_the_identity_by_value_and_by_provenance(
    name: str,
) -> None:
    """Each of the six facts, and each fact's provenance: a weaker claim is not the same claim.

    The baseline *reads* the fact, so both directions are measurable on it — another value, and
    the same fact carried as one nothing read. This is the half that keeps "the instrument said
    999" and "something claims 999" from being the same instrument, and it is also why the
    reason cannot be in the projection: for the four facts that are unreadable today, the only
    thing that used to tell one reading from another was the wording of the explanation.
    """
    baseline = digest(snapshot(**{name: read("999")}))
    other_value = digest(snapshot(**{name: read("998")}))
    unproven = digest(snapshot(**{name: unreadable("nothing could read it")}))

    assert other_value != baseline, name
    assert unproven != baseline, name
    assert unproven != other_value, name


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        ("another channel", {"channel": declared("4", reason="configured")}),
        ("the channel read rather than declared", {"channel": read("1")}),
        ("an assisted channel", {"mode": read(ChannelMode.ASSISTED.value)}),
        ("no mode could be read", {"mode": unreadable("a dialog is up")}),
        ("a different window class", {"fingerprint": fingerprint(class_name="TOther")}),
        ("another panel count", {"fingerprint": fingerprint(panels=3)}),
        ("another control count", {"fingerprint": fingerprint(visible_controls=21)}),
        (
            "the strip is recording rather than ready",
            {"fingerprint": fingerprint(strip=StripState(button_count=1))},
        ),
        (
            "the strip is in its store view",
            {
                "fingerprint": fingerprint(
                    strip=StripState(button_count=4, has_slider=True)
                )
            },
        ),
    ],
)
def test_every_compatibility_fact_moves_the_identity(label: str, changed: dict) -> None:
    """The other direction: every fact the plan's table lists, changed on its own."""
    assert digest(snapshot(**changed)) != digest(snapshot())


def test_the_identity_holds_the_table_and_nothing_of_a_session() -> None:
    """The projection is the plan's table, written down — and the volatile half is not in it."""
    assert set(CompilationIdentity.model_fields) == {
        "channel",
        "mode",
        *FIXED_FACT_FIELDS,
        "class_name",
        "panels",
        "visible_controls",
        "strip_view",
        "strip_has_slider",
    }
    reading = snapshot()
    identity = CompilationIdentity.from_snapshot(reading)
    assert identity.class_name == CLEAN_CLASS
    assert identity.visible_controls == CLEAN_CONTROLS
    assert identity.panels == CLEAN_PANELS
    assert identity.strip_view is StripView.READY
    assert not identity.strip_has_slider
    for volatile in (
        "hwnd",
        "rect",
        "maximized",
        "screen",
        "cursor",
        "is_foreground",
        "layout_note",
        "overlay",
        "slider_max",
        "strip_button_count",
    ):
        assert volatile not in CompilationIdentity.model_fields, volatile


def test_the_digest_is_stable_and_names_a_change() -> None:
    """What a resume compares: the same reading hashes the same, and a change does not."""
    assert digest(snapshot()) == digest(snapshot())
    assert len(digest(snapshot())) == 64
    assert digest(snapshot()) != digest(snapshot(prf_us=read("212.0")))


# ------------------------------------------ a reason is explanatory prose, not compatibility


@pytest.mark.parametrize(
    ("label", "first", "second"),
    [
        (
            "a declared fact's explanation reworded",
            {
                "channel": declared(
                    "1", reason="the configured channel, routed before this read"
                )
            },
            {
                "channel": declared(
                    "1",
                    reason="the channel the routing step selected and verified before this read",
                )
            },
        ),
        (
            "an unreadable fact's reason reworded",
            {"max_profiles_per_block": unreadable(CAP_REASON)},
            {
                "max_profiles_per_block": unreadable(
                    "the Preferences dialog is not currently read by this driver"
                )
            },
        ),
    ],
)
def test_a_reason_is_prose_and_is_not_the_identity(
    label: str, first: dict[str, object], second: dict[str, object]
) -> None:
    """The same value from the same source, explained in other words, is the same instrument.

    ``reason`` is written for a reader with no instrument in front of them, which is exactly why
    it gets edited — and a digest that covered it would turn a documentation improvement into
    "a different instrument" and re-run points that were already measured. The readings
    themselves still differ: the explanation is evidence, it is just not *compatibility*.
    """
    reworded = snapshot(**second)
    assert reworded != snapshot(**first)
    assert digest(reworded) == digest(snapshot(**first))


def test_the_identity_cannot_carry_prose_at_all() -> None:
    """Structural rather than conventional: a reason has no field of the identity to live in.

    A rule that lived only in this docstring would be one refactor away from being undone — an
    identity field typed ``InstrumentFact`` would put the explanation back into the digest
    without any test noticing which field it happened to.
    """
    assert set(Provenance.model_fields) == {"value", "source"}
    assert "reason" not in CompilationIdentity.model_fields
    assert all(
        CompilationIdentity.model_fields[name].annotation is Provenance
        for name in ("channel", "mode", *FIXED_FACT_FIELDS)
    )
    assert Provenance(value="1", source=FactSource.DECLARED).model_dump() == {
        "value": "1",
        "source": "declared",
    }
