"""The instrument's state as one reading: the evidence, and what a resume compares.

Two questions are asked of the same reading, and they are not the same question:

- *what is this instrument right now* — kept whole, for the record and for the diagnosis of a
  refusal: :class:`InstrumentSnapshot`;
- *is this the instrument the previous run measured on* — the projection onto the facts
  campaign compatibility depends on, and nothing else: :class:`CompilationIdentity`.

**Why two models, and not one.** ``ScreenFingerprint`` carries the window's ``hwnd`` and its
rectangle, and both change for reasons that have nothing to do with the instrument: a restart
hands out a new handle, a drag moves the window, maximising changes the rect. A compile keyed on
the whole fingerprint would read a **restart** as a **different instrument**, and the resume it
feeds would re-run a job that was already done. So the identity keeps what a campaign can
disagree with — the channel, its mode, the fixed facts, and the layout that makes the reads
trustworthy — and drops what is true only of a session (``hwnd``, ``rect``, ``maximized``,
``screen``, ``cursor``, ``is_foreground``, the free-text ``layout_note``), together with the one
thing that is a *precondition* rather than a property: an overlay being up, or the window being
minimised, is refused by the compiler (W3) instead of being compiled as an instrument whose
layout differs.

**A fact is a value and where it came from** (:class:`InstrumentFact`) — never a bare number, so
nothing downstream can read a declared value as a measurement. Of the six fixed facts a campaign
declares, two are readable today off the measurement screen (the PRF and the emissions per
profile, the parameter column's own fields) and four are not: the sound speed, the first gate and
the burst length live in the ``Operating parameters`` dialog with no column field of their own
(:data:`~udv_echo_process.acquire.actuator.DIALOG_ONLY_PARAMETERS`), and the block cap is an
application ``Preference``. The four are carried as ``unreadable`` **with the reason** rather
than omitted, which is the difference between a fact the instrument cannot state and a fact
nobody asked it. Four of the six are also decoded from a *stored file*
(:class:`~udv_echo_process.acquire.verify.WordFacts`), and that is evidence only **after** a
recording has been spent — the whole point of reading them before the first point is that the
first point must not be what tells us.

**The projection keeps the provenance and drops the prose** (:class:`Provenance`). A fact's
``reason`` is written for a reader who has no instrument in front of them — which is exactly why
it gets rewritten — and compatibility hashed on it would turn a documentation improvement into
"a different instrument" and re-run a point that was already measured. So the identity is each
fact's *value and source* and nothing else, and everything a human reads stays in the reading.

This module is **pure Python on purpose**, like :mod:`~udv_echo_process.acquire.actuator`: it
imports no Win32 binding, so the models can be built, compared and round-tripped through JSON on
any host, and a fake actuator can answer the port with one.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum

from pydantic import Field, model_validator

from udv_echo_process.acquire.actuator import (
    DIALOG_FIELD_ORDER,
    ScreenFingerprint,
    StripView,
)
from udv_echo_process.models.base import ValueModel

__all__ = [
    "FIXED_FACT_FIELDS",
    "SUPPORTED_READ_FACTS",
    "CompilationIdentity",
    "DialogParameters",
    "FactSource",
    "InstrumentFact",
    "InstrumentSnapshot",
    "Provenance",
    "declared",
    "identity_digest",
    "routed",
    "unreadable",
]

#: The fixed facts a campaign declares about the instrument and a compile reconciles against
#: it, in the order the plan's identity table lists them. Each is named by the **field it has to
#: agree with** — the campaign's own for the first three
#: (:class:`~udv_echo_process.acquire.campaign.CampaignDefinition`), and the shared window frame
#: of its points for the two next (``ParameterSet.sound_speed_ms`` / ``first_gate_mm``, which
#: ``plan_campaign`` already refuses to see disagree) — so the compiler's table is the two
#: models' field names and not a third vocabulary.
FIXED_FACT_FIELDS: tuple[str, ...] = (
    "prf_us",
    "emissions_per_profile",
    "burst_length",
    "sound_speed_ms",
    "first_gate_mm",
    "max_profiles_per_block",
)

#: The fixed facts **this driver has a supported read path for**, so that a value missing from a
#: reading means the read *failed* rather than that nothing on this machine can state the fact. Five
#: of the six: the PRF and the emissions per profile come off the measurement screen's own column,
#: and the burst length, the sound speed and the first gate out of the ``Operating parameters``
#: dialog (W1, plan §14 — the dialog's value table, read by position and checked against the screen).
#: The block cap is deliberately absent: it is an application Preference whose surface reconnaissance
#: could not open safely, so no reader here reaches it.
#:
#: This is a claim about *this* driver and it moves with it: gaining a reader means adding its fact
#: here, and the compile then refuses a normal campaign whose reading does not carry it (plan §9.2).
SUPPORTED_READ_FACTS: tuple[str, ...] = (
    "prf_us",
    "emissions_per_profile",
    "burst_length",
    "sound_speed_ms",
    "first_gate_mm",
)


class FactSource(str, Enum):
    """Where a fixed fact's value came from — stated, never implied.

    Four states, because a fact can rest on four different things, and telling them apart is
    what keeps a number from being read as more proof than it is. They run from what the
    application itself answered to what nothing could answer:

    ``READ``
        The application's own surface produced the value, for *this* reading: the parameter
        column's text, or the structure of the screen it built. A *mode* is such a value — this
        application states it by which panel it builds for the channel, and never by a caption
        (every widget here is caption-less), so the structure is the statement.
    ``ROUTED``
        The application answered, but to the **routing** step rather than to this reading:
        ``ensure_channel`` selects the channel and reads the application's own confirmation back
        (:meth:`~udv_echo_process.acquire.driver.Win32Actuator.ensure_channel`), and hands that
        value over here. Stronger than a claim and weaker than a read of its own, so it shares a
        name with neither — a caller that established no channel gets ``unreadable``, never this.
    ``DECLARED``
        A caller's claim, with nothing of the application's behind it: what the run *intends*.
        A campaign's own statement about the instrument — "it is at 169 µs" — is the standing
        case, and it is the state a compile reconciles *against* rather than believes.
    ``UNREADABLE``
        Nothing can read this fact yet, so there is no value at all and ``reason`` says why.
        Carried rather than omitted: a fact missing from a record and a fact the instrument
        cannot state are different things to a later reader, and only one of them is honest.
    """

    READ = "read"
    ROUTED = "routed"
    DECLARED = "declared"
    UNREADABLE = "unreadable"


class InstrumentFact(ValueModel):
    """One fixed fact **and its provenance** — a value and where it came from.

    The value is the application's own text where it could be read, not a parsed number: the
    control's text is what the application said, and re-formatting it here would be this
    repository inventing a measurement (the stored artifact's words are the authority on what a
    file carries, and that is :mod:`~udv_echo_process.acquire.verify`).
    """

    value: str | None = None
    source: FactSource
    #: Why there is no value (``unreadable``), or why the value is *not* the instrument's own
    #: statement (``declared``). Forbidden on a ``read`` fact.
    reason: str | None = None

    @model_validator(mode="after")
    def _check_provenance(self) -> InstrumentFact:
        """Refuse the state combinations that would let a reader mistake one state for another."""
        if self.source is FactSource.READ:
            if self.value is None:
                raise ValueError(
                    "a read fact must carry the value its surface answered: having read "
                    "nothing is no fact at all, not a fact without a value"
                )
            if self.reason is not None:
                raise ValueError(
                    "a read fact carries no reason: there is nothing to explain about the "
                    "application's own answer, and a reason here would read as doubt about it"
                )
        elif self.source is FactSource.ROUTED:
            if self.value is None:
                raise ValueError(
                    "a routed fact must carry the value the routing step read back: with no "
                    "value there is nothing it established, and the fact is unreadable"
                )
        elif self.source is FactSource.DECLARED:
            if self.value is None:
                raise ValueError(
                    "a declared fact must carry the value that was declared; with nothing "
                    "declared it is an unreadable fact"
                )
        else:
            if self.value is not None:
                raise ValueError(
                    "an unreadable fact carries no value: that is what makes it unreadable, "
                    "and a value here is exactly the claim this slice exists to prevent"
                )
            if not self.reason:
                raise ValueError(
                    "an unreadable fact must say why: without the reason it is "
                    "indistinguishable from a fact that was simply forgotten"
                )
        return self

    @property
    def is_read(self) -> bool:
        """True only for a value the application's own surface produced."""
        return self.source is FactSource.READ

    def provenance(self) -> Provenance:
        """This fact as what a resume compares: the value, the source, and no prose.

        The one mapping from evidence to identity, so the projection cannot be spelled one way
        in one place and another way somewhere else — and so that a fact's explanation, which is
        edited for readers, can never move a digest.
        """
        return Provenance(value=self.value, source=self.source)


def unreadable(reason: str) -> InstrumentFact:
    """A fact nothing can read yet — carried with its reason, never as a value."""
    return InstrumentFact(source=FactSource.UNREADABLE, reason=reason)


def declared(value: str, reason: str | None = None) -> InstrumentFact:
    """A fact the caller states rather than the instrument, marked as such."""
    return InstrumentFact(value=value, source=FactSource.DECLARED, reason=reason)


def routed(value: str, reason: str | None = None) -> InstrumentFact:
    """A fact the *routing* step established and handed over — not this reading's own answer.

    The distinction is the whole point: :func:`declared` is a caller's intention, ``read`` is
    this reading's own answer, and a routed value is the application's answer to *another* step.
    A reading that pressed nothing can carry it only because the caller said so, and the source
    is what makes that visible to whoever reads the record later.
    """
    return InstrumentFact(value=value, source=FactSource.ROUTED, reason=reason)


class DialogParameters(ValueModel):
    """What one open ``Operating parameters`` dialog stated, and what was true if it stated nothing.

    The dialog-only fixed facts are read **while that dialog is up**, for the channel the dialog
    shows, so they are carried as *one reading* rather than as three loose facts. ``channel`` is
    the dialog's own channel field, kept for the caller to check against the routed channel: the
    dialog is the surface that decides whose parameters these are, and reading them for one
    channel while routing another is the same trap as storing a block on the wrong channel
    (docs/16 §12) — so the reading states which channel it described rather than letting a caller
    assume.

    ``reason`` is empty exactly when the facts were read, and says why they were not otherwise:
    a dialog that was open but stated nothing (measured 2026-09-18: an application that has just
    started builds its value table empty the first time it is opened, and states it on the
    second), a dialog whose shape is not the one these bindings were measured against, or a
    dialog whose anchor fields disagree with the measurement screen. Every one of those is
    ``unreadable`` — the facts are carried as unread, never as a value and never as a guess.
    """

    #: The dialog's own channel field, as the application states it.
    channel: str = ""
    #: ``(field name, the application's own text)`` for each dialog-only fact that was stated.
    fields: tuple[tuple[str, str], ...] = ()
    #: Why nothing was read — empty when the fields above were.
    reason: str = ""

    def value(self, field: str) -> str | None:
        """The text this dialog stated for ``field``, or ``None`` when it stated nothing."""
        for name, text in self.fields:
            if name == field and text:
                return text
        return None

    def readable(self) -> bool:
        """Whether this reading actually carries a value for every dialog-only fact."""
        return not self.reason and all(
            self.value(name) for name, _column, _row in DIALOG_FIELD_ORDER
        )


class Provenance(ValueModel):
    """A fact as compatibility reads it: the value and the source, with the prose left out.

    :class:`InstrumentFact` carries a ``reason``, and that reason is *diagnostic* text — written
    for a reader with no instrument in front of them, and rewritten whenever it can be made
    clearer. Hashing it would make the identity depend on wording: the same instrument, the same
    evidence strength, two digests, and a resume that re-runs points already measured. So the
    projection has no field for a reason at all — this is a structural guarantee rather than a
    convention someone has to remember.

    The source *is* in the projection, deliberately: a fact that moved from ``read`` to
    ``unreadable`` between two runs is a weaker claim about the same instrument, and a resume
    that ignored that would be comparing evidence it no longer has.
    """

    value: str | None = None
    source: FactSource

    @model_validator(mode="after")
    def _check_provenance(self) -> Provenance:
        """The value/source combinations that are a fact, and no others.

        The same rule :class:`InstrumentFact` enforces, minus everything about ``reason``: only
        an ``unreadable`` fact has no value, and a ``read``, ``routed`` or ``declared`` one
        without a value is a fact nobody established.
        """
        if self.source is FactSource.UNREADABLE:
            if self.value is not None:
                raise ValueError(
                    "an unreadable fact carries no value: that is what makes it unreadable"
                )
        elif self.value is None:
            raise ValueError(
                f"a {self.source.value} fact must carry the value it came with: with no value "
                "there is nothing to compare"
            )
        return self


class InstrumentSnapshot(ValueModel):
    """What the instrument is, read once — the evidence, kept whole.

    The ``ScreenFingerprint`` is carried **as it is**, every field including the volatile ones,
    because a fingerprint that has been trimmed is no longer the diagnostic it exists to be: the
    geometry is how a screen that does not match gets *described*, and the cursor and the
    foreground flag are what a press failure is read against. Trimming belongs to
    :class:`CompilationIdentity`, which is a different question.

    The six facts named by :data:`FIXED_FACT_FIELDS` are present whatever happened: one that was
    read carries the application's text, one nothing could read carries the reason. ``channel``
    and ``mode`` are facts too, for the same reason — the run's record has to say which channel
    and which mode were active, and has to say on what authority.
    """

    fingerprint: ScreenFingerprint
    #: The channel the run is aimed at, carried on the authority of whoever established it:
    #: ``routed`` when the caller handed over the channel ``ensure_channel`` verified, and
    #: ``unreadable`` when nothing did. Never ``read`` — reading it means opening ``Operating
    #: parameters`` with the operator's real cursor, which is the *routing* step's gesture
    #: (:meth:`~udv_echo_process.acquire.driver.Win32Actuator.ensure_channel`), and this reading
    #: deliberately presses nothing, so it cannot claim a verification it did not perform.
    channel: InstrumentFact
    #: Which of the two parameter surfaces the application built for that channel
    #: (:class:`~udv_echo_process.acquire.actuator.ChannelMode`).
    mode: InstrumentFact
    prf_us: InstrumentFact
    emissions_per_profile: InstrumentFact
    burst_length: InstrumentFact
    sound_speed_ms: InstrumentFact
    first_gate_mm: InstrumentFact
    max_profiles_per_block: InstrumentFact

    def facts(self) -> tuple[tuple[str, InstrumentFact], ...]:
        """Every fixed fact, in the plan's table order, named by the field it reconciles with."""
        return tuple((name, getattr(self, name)) for name in FIXED_FACT_FIELDS)

    def fact(self, name: str) -> InstrumentFact:
        """The fixed fact called ``name`` (:data:`FIXED_FACT_FIELDS`), or a refusal naming them."""
        if name not in FIXED_FACT_FIELDS:
            raise ValueError(
                f"no fixed fact {name!r}: a campaign declares "
                f"{list(FIXED_FACT_FIELDS)} about the instrument, and only those are "
                "reconciled against it"
            )
        return getattr(self, name)

    def read_facts(self) -> tuple[str, ...]:
        """The names of the facts the instrument itself answered."""
        return tuple(name for name, fact in self.facts() if fact.is_read)

    def unreadable_facts(self) -> tuple[str, ...]:
        """The names of the facts nothing can read — carried, never omitted."""
        return tuple(
            name for name, fact in self.facts() if fact.source is FactSource.UNREADABLE
        )


class CompilationIdentity(ValueModel):
    """The reading projected onto what campaign compatibility depends on, and nothing else.

    In it, because a campaign can disagree with it or a read depends on it: the channel and its
    mode (an assisted channel has its own parameter surface entirely, so a manual campaign
    against it has nothing to write), every fixed fact *with its provenance* — a :class:`Provenance`,
    value and source, never the prose that explains it (the provenance belongs in the identity: a
    fact that moved from ``read`` to ``unreadable`` between two runs is a weaker claim about the
    same instrument, and a resume that ignored that would be comparing evidence it no longer has)
    — and the layout signature: the window class, the panel and visible-control counts, and the
    strip's view.

    Out of it, deliberately: ``hwnd``, ``rect``, ``maximized``, ``screen``, ``cursor``,
    ``is_foreground`` and ``layout_note`` (true only of a session: a restart or a drag must not
    read as a different instrument), ``overlay`` (a modal being up is a precondition failure the
    compiler refuses on, not a property of the instrument), every ``reason`` (see
    :class:`Provenance`), and everything that is a property of **the data in the application's
    buffer rather than of the instrument**: the store slider's ``maximum`` — the strip's
    *structure* is in, its slider's range is not, because that range is the selected block's
    profile count — and the strip's top-row **button count**, which is 3 or 4 depending on
    whether a leftover block is held (``actuator.STRIP_BUTTON_ORDER`` documents both rows, and
    ``classify_strip_view`` puts both in the same ``READY`` view).

    What the count classifies *into* stays in, and it is the half the driving needs: the view.
    A press is bound to a control's position in the live row, and the driver resolves that row at
    press time from the count it has *just* read (:func:`~udv_echo_process.acquire.actuator.
    press_index`), so a run's presses never depend on this projection carrying the count — while
    a *view* the run did not bind against (``RECORDING``, ``STORE``, an unrecognised screen) is a
    screen whose presses would land elsewhere, and that is what belongs in the comparison.
    """

    channel: Provenance
    mode: Provenance
    prf_us: Provenance
    emissions_per_profile: Provenance
    burst_length: Provenance
    sound_speed_ms: Provenance
    first_gate_mm: Provenance
    max_profiles_per_block: Provenance
    class_name: str
    panels: int = Field(ge=0)
    visible_controls: int = Field(ge=0)
    #: The view the strip was in: a press is bound to a button's **position in that row**
    #: (:func:`~udv_echo_process.acquire.actuator.press_index`), so a view the run did not bind
    #: against is a screen whose presses would land elsewhere.
    strip_view: StripView
    strip_has_slider: bool

    @classmethod
    def from_snapshot(cls, snapshot: InstrumentSnapshot) -> CompilationIdentity:
        """Project a reading onto the identity — the one place the mapping is written down.

        Built by field name from the snapshot's own facts, so a fact added to the snapshot and
        forgotten here is refused at construction (``extra="forbid"``) instead of being silently
        left out of every resume comparison. Each fact goes through
        :meth:`InstrumentFact.provenance`, so the identity keeps the value and the source and
        cannot inherit the explanation.
        """
        fingerprint = snapshot.fingerprint
        strip = fingerprint.strip
        return cls(
            **{
                name: getattr(snapshot, name).provenance()
                for name in ("channel", "mode", *FIXED_FACT_FIELDS)
            },
            class_name=fingerprint.class_name,
            panels=fingerprint.panels,
            visible_controls=fingerprint.visible_controls,
            strip_view=strip.view,
            strip_has_slider=strip.has_slider,
        )


def identity_digest(identity: CompilationIdentity) -> str:
    """A stable hash of the identity — the resume's comparison, as one string.

    Canonical JSON (keys sorted, no whitespace, ASCII) through SHA-256, the way
    :func:`~udv_echo_process.acquire.campaign.campaign_fingerprint` hashes a definition: the
    same reading hashes the same on every host and every load, and a change to any fact, to a
    fact's provenance or to the layout changes it. What it hashes is the projected values and
    their sources — never the commentary around them, which would make the digest a function of
    how the diagnostic text was last worded.
    """
    canonical = json.dumps(
        identity.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
