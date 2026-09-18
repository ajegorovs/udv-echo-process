"""Contract tests for the compile — ``campaign.compile_campaign``.

``test_acquire_snapshot.py`` pins the two models; ``test_acquire_campaign.py`` pins the planner
and the job. This module pins the step between them, on the plan's own "Done when" list for W3
(§4), one case per rule:

- a **read** fact that disagrees refuses *before the first recording*, naming the fact and both
  values — and one refusal names **every** fact that disagreed, not the first one found;
- the emissions per profile is the one **advisory** fact: its disagreement is carried on the
  compiled plan and the run proceeds, because that value in a definition is derived rather than
  read (``verify.ADVISORY_COVARIATES``);
- a fact nothing could read keeps the declaration, is marked as such, and is listed by
  ``ExecutableCampaign.unproven`` — never silently treated as verified (criterion 4);
- an **assisted** channel refuses, and so does every screen that is not the measurement screen:
  a modal, a minimised window, an unreadable mode. Each names the *state*, not a mode;
- the channel is the one the **routing** step established, and nothing weaker: not routed, or
  routed to another channel, is a refusal;
- the compiled plan carries the reading's ``CompilationIdentity``, so a resume compares what the
  plan says the instrument was (criterion 3).

Everything here is headless and instrument-free: the readings are the fake's expected one
(``test_acquire_runner.expected_snapshot``) with single fields replaced, and no test needs a
window. The compile takes no actuator at all — that is its signature, and the reason it cannot
have touched an instrument on the way through these cases.
"""

from __future__ import annotations

import pytest
from test_acquire_runner import (
    BURST_LENGTH,
    EMISSIONS_PER_PROFILE,
    PRF_US,
    SOUND_SPEED_MS,
    expected_snapshot,
)

from udv_echo_process.acquire import campaign
from udv_echo_process.acquire.actuator import ChannelMode, ScreenFingerprint
from udv_echo_process.acquire.config import ParameterSet
from udv_echo_process.acquire.snapshot import (
    FIXED_FACT_FIELDS,
    CompilationIdentity,
    FactSource,
    InstrumentFact,
    InstrumentSnapshot,
    identity_digest,
    routed,
    unreadable,
)

#: The fixture campaign: the handoff's two-point sweep of the tested channel, one window.
JOB = "test-single-channel"
DURATION_S = 12.0
FIRST_GATE_MM = 2.0
RUNG_1_MM = 0.121667
RUNG_2_MM = 0.243333
GATES_K1 = 797
GATES_K2 = 399

#: The four facts nothing on this machine can read yet (``driver.instrument_snapshot``).
UNREADABLE_FACTS = (
    "burst_length",
    "sound_speed_ms",
    "first_gate_mm",
    "max_profiles_per_block",
)


def read(value: str) -> InstrumentFact:
    """A fact the application's own surface answered."""
    return InstrumentFact(value=value, source=FactSource.READ)


def reading(**overrides: object) -> InstrumentSnapshot:
    """The expected reading of the tested channel, with single fields replaced.

    Built by validating the fake's own expected reading rather than by a second fixture: the
    compile's input is exactly what ``instrument_snapshot()`` produces, so a case here cannot
    drift into testing a snapshot that method could never return.
    """
    base = expected_snapshot(routed_channel=1)
    if not overrides:
        return base
    return InstrumentSnapshot(**{**base.model_dump(), **overrides})


def fingerprint(**overrides: object) -> ScreenFingerprint:
    """The clean manual measurement screen's fingerprint, with single fields replaced."""
    base = reading().fingerprint
    return ScreenFingerprint(**{**base.model_dump(), **overrides})


def point(label: str, resolution_mm: float, gates: int) -> campaign.CampaignPoint:
    """One campaign point on the tested channel's window frame."""
    return campaign.CampaignPoint(
        label=label,
        parameters=ParameterSet(
            sound_speed_ms=SOUND_SPEED_MS,
            first_gate_mm=FIRST_GATE_MM,
            resolution_mm=resolution_mm,
            gates=gates,
        ),
    )


def definition(**overrides: object) -> campaign.CampaignDefinition:
    """The fixture campaign, built directly: the subject here is the reconciliation, not the loader.

    ``test_acquire_campaign.py`` covers the JSON loader; a case in this module is about what the
    compile does with a definition it is handed.
    """
    fields: dict[str, object] = {
        "job": JOB,
        "channel": 1,
        "duration_s": DURATION_S,
        "points": (point("k1", RUNG_1_MM, GATES_K1), point("k2", RUNG_2_MM, GATES_K2)),
        "name_prefix": "c1",
        "prf_us": PRF_US,
        "emissions_per_profile": EMISSIONS_PER_PROFILE,
        "burst_length": BURST_LENGTH,
    }
    fields.update(overrides)
    return campaign.CampaignDefinition(**fields)


def refusal(*, snapshot: InstrumentSnapshot | None = None, **overrides: object) -> str:
    """Compile the fixture campaign and return the refusal's own words."""
    subject = definition()
    found = snapshot if snapshot is not None else reading(**overrides)
    with pytest.raises(campaign.CampaignError) as caught:
        campaign.compile_campaign(subject, found)
    return str(caught.value)


# ------------------------------------------------------------- the happy path, and its record


def test_the_happy_path_compiles_the_planners_own_points() -> None:
    """Nothing changed: the compiled plan carries exactly what the static planner computed.

    Criterion 5 in miniature — the compile *adds* a reconciliation and re-derives nothing, so
    the points a run executes are the points the offline plan promised.
    """
    subject = definition()
    compiled = campaign.compile_campaign(subject, reading())

    assert compiled.points == campaign.plan_campaign(subject)
    assert compiled.channel == 1
    assert compiled.job == JOB
    assert compiled.definition_fingerprint == campaign.campaign_fingerprint(subject)
    assert [check.name for check in compiled.facts] == list(FIXED_FACT_FIELDS)


def test_the_compiled_plan_says_what_was_read_and_what_was_not() -> None:
    """The record's answer to criterion 2, decided before anything is recorded."""
    compiled = campaign.compile_campaign(definition(), reading())

    assert compiled.fact("prf_us").agreed is True
    assert compiled.fact("prf_us").observed.value == str(PRF_US)
    assert compiled.fact("emissions_per_profile").agreed is True
    assert compiled.unproven == UNREADABLE_FACTS
    assert compiled.advisories == ()
    for name in UNREADABLE_FACTS:
        check = compiled.fact(name)
        assert check.agreed is None, name
        assert check.observed.source is FactSource.UNREADABLE, name
        assert check.declared is not None, name
        assert check.detail, name


def test_the_compiled_plan_carries_the_readings_identity() -> None:
    """Criterion 3: the resume's comparison is a projection of the reading, not the reading."""
    channel_2 = reading(channel=routed("2", reason="the routing step read it back"))
    same_instrument = campaign.compile_campaign(
        definition(),
        reading(
            fingerprint=fingerprint(
                hwnd=reading().fingerprint.hwnd + 1,
                rect=(-8, -8, 1600, 900),
                cursor=None,
            )
        ),
    )
    another_channel = campaign.compile_campaign(definition(channel=2), channel_2)

    assert (
        same_instrument.identity_digest
        == campaign.compile_campaign(definition(), reading()).identity_digest
    )
    assert another_channel.identity_digest != same_instrument.identity_digest
    assert another_channel.identity_digest == identity_digest(
        CompilationIdentity.from_snapshot(channel_2)
    )


# ----------------------------------------------------------- a read fact that disagrees refuses


@pytest.mark.parametrize(
    ("name", "stated"),
    [
        ("prf_us", "212.0"),
        ("burst_length", "8"),
        ("sound_speed_ms", "1500.0"),
        ("first_gate_mm", "5.0"),
        ("max_profiles_per_block", "500"),
    ],
)
def test_a_read_fact_that_disagrees_refuses_before_the_first_recording(
    name: str, stated: str
) -> None:
    """Criterion 1, per fact: the fact is named, with the declaration and the reading."""
    message = refusal(**{name: read(stated)})

    assert name in message
    assert stated in message
    assert "nothing was stored" in message


def test_the_refusal_names_every_fact_that_disagreed() -> None:
    """An operator with a campaign to fix should not have to fix it one run at a time."""
    message = refusal(
        prf_us=read("212.0"),
        burst_length=read("8"),
        max_profiles_per_block=read("500"),
    )

    for name in ("prf_us", "burst_length", "max_profiles_per_block"):
        assert name in message, name
    assert "212.0" in message and "8" in message and "500" in message


def test_the_prf_keeps_the_verifiers_own_tolerance() -> None:
    """The app stores integer microseconds, so the compile is exactly as strict as the verifier.

    A pre-run check stricter than the stored-file check would refuse jobs that would have been
    accepted with a recording already spent; a looser one would compile a job the verifier then
    refuses. Both directions are asserted here.
    """
    within = campaign.compile_campaign(definition(), reading(prf_us=read("170.0")))
    assert within.fact("prf_us").agreed is True

    message = refusal(prf_us=read("172.0"))
    assert "tolerance 1" in message


def test_a_stated_value_that_is_not_a_number_refuses() -> None:
    """A value that cannot be compared is not agreement — the failure direction is refusal."""
    message = refusal(prf_us=read("n/a"))

    assert "prf_us" in message
    assert "not a number" in message


# ------------------------------------------------------------------- the advisory fact, and the
# ------------------------------------------------------------------- facts nothing could read


def test_the_emissions_disagreement_is_recorded_and_the_run_proceeds() -> None:
    """The one advisory fact: its definition value is derived, so a disagreement does not refuse.

    ``verify.ADVISORY_COVARIATES`` carries the same reasoning for the stored file; W6 is where the
    declaration stops being derived. Until then the disagreement is *carried*, never swallowed.
    """
    compiled = campaign.compile_campaign(
        definition(), reading(emissions_per_profile=read("150"))
    )

    check = compiled.fact("emissions_per_profile")
    assert check.agreed is False
    assert check.acceptance is campaign.Acceptance.WARN
    assert compiled.unproven == UNREADABLE_FACTS
    assert len(compiled.advisories) == 1
    assert "emissions_per_profile" in compiled.advisories[0]
    assert "150" in compiled.advisories[0]


def test_every_fact_that_can_disagree_has_an_acceptance() -> None:
    """The policy is the verifier's own table, not a second opinion about which facts matter."""
    refuses = {
        name
        for name, value in campaign.COVARIATE_ACCEPTANCE.items()
        if value is campaign.Acceptance.REFUSE
    }

    assert set(campaign.COVARIATE_ACCEPTANCE) == set(FIXED_FACT_FIELDS)
    assert (
        campaign.COVARIATE_ACCEPTANCE["emissions_per_profile"]
        is campaign.Acceptance.WARN
    )
    assert refuses == set(FIXED_FACT_FIELDS) - {"emissions_per_profile"}


def test_a_campaign_that_declares_nothing_for_a_fact_checks_nothing() -> None:
    """``burst_length`` is optional in a definition: with nothing declared there is no dispute."""
    compiled = campaign.compile_campaign(definition(burst_length=None), reading())

    check = compiled.fact("burst_length")
    assert check.declared is None
    assert check.agreed is None
    assert "declares no value" in (check.detail or "")


# --------------------------------------------------------------- screens and channels that are
# --------------------------------------------------------------- not the measurement screen


def test_an_assisted_channel_refuses() -> None:
    """A campaign's points write the manual parameter column; an assisted one has none."""
    message = refusal(mode=read(ChannelMode.ASSISTED.value))

    assert "assisted" in message
    assert "manual parameter column" in message


@pytest.mark.parametrize(
    ("label", "changed"),
    [
        ("a modal is up", {"fingerprint": fingerprint(overlay="warning")}),
        (
            "the window is minimised",
            {"fingerprint": fingerprint(panels=0, visible_controls=0)},
        ),
        (
            "no mode could be read",
            {
                "mode": unreadable(
                    "a dialog, a menu popup or an unrecognised layout is up"
                )
            },
        ),
    ],
)
def test_a_screen_that_is_not_the_measurement_screen_refuses(
    label: str, changed: dict[str, object]
) -> None:
    """Each names the *state* that has to change, never a mode or an identity that "differs"."""
    message = refusal(**changed)

    assert "nothing was stored" in message or "compile again" in message


def test_a_channel_that_was_not_routed_is_not_a_channel() -> None:
    """The reading cannot establish a channel, so a compile cannot be handed one that is assumed."""
    message = refusal(snapshot=expected_snapshot(routed_channel=None))

    assert "no routed channel" in message
    assert "ensure_channel" in message


def test_a_channel_that_is_not_the_campaigns_channel_refuses() -> None:
    """Every point would be stored under another channel's window."""
    message = refusal(snapshot=expected_snapshot(routed_channel=2))

    assert "channel 2" in message and "channel 1" in message


def test_the_definitions_own_laws_are_refused_before_the_screen_is_judged() -> None:
    """A file that cannot be planned is refused for that reason, not for a transient screen state."""
    off_ladder = definition(
        points=(point("k1", RUNG_1_MM + 0.05, GATES_K1),),
    )
    with pytest.raises(campaign.CampaignError) as caught:
        campaign.compile_campaign(
            off_ladder, reading(fingerprint=fingerprint(overlay="warning"))
        )

    assert "modal" not in str(caught.value)
    assert "pitch" in str(caught.value).lower() or "rung" in str(caught.value).lower()
