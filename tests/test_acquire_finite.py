"""The finite multiplexed Run: what a post-Run snapshot is allowed to mean.

The measured state these tests are built from is
``docs/dop3000/evidence/finite-multiplex-live-20261028.json``: one native ``Run``
on a 1+2 pair took the mode word from ``65585`` (``0x10031``) to ``2162739``
(``0x200000 | 0x10033``), left ``Execution_Code`` **5** queued — one command
identifier, not a depth — then the application completed the held block itself,
cleared the arm bit, left nothing queued and dispatched no ``Record``.

So the classifier is asked one question and answers with one of three actions.
These tests pin the measured case, every refusal boundary, and the property that
made the classifier reusable: it is a pure function of the snapshot it is handed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from udv_echo_process.acquire.actuator import StripState
from udv_echo_process.acquire.finite import (
    FiniteAction,
    FiniteObservation,
    FiniteRunDecision,
    FiniteRunReceipt,
    FiniteRunRequest,
    classify_finite_run,
)

TOKEN = "finite-1+2-01"
INSTANCE = "pid=4120;created=133700000000000000"

REQUEST = FiniteRunRequest(
    channels=(1, 2),
    sequences=1,
    trigger_word=4,
    mode_before=65585,
    run_token=TOKEN,
)

RECEIPT = FiniteRunReceipt(
    run_token=TOKEN,
    identity=INSTANCE,
    invocations=1,
    pending_after_run=5,
    record_dispatches=0,
    stop_dispatches=0,
)

#: The strip the application left behind: two buttons and the slider.  The
#: view is the gate — this classifier presses nothing, so the row needs no
#: button-role binding (``STRIP_BUTTON_ORDER`` has none for it).
COMPLETED_STRIP = StripState(button_count=2, has_slider=True)
RECORDING_STRIP = StripState(button_count=1, has_slider=False)
READY_STRIP = StripState(button_count=3, has_slider=False)


def observation(**overrides: object) -> FiniteObservation:
    fields: dict[str, object] = {
        "identity": INSTANCE,
        "error": "",
        "mode_after": 2162739,
        "pending": 0,
        "sequences": 1,
        "participants": (1, 2),
        "current_channel": 2,
        "assisted_mode": False,
        "trigger_word": 4,
        "held_block_token": TOKEN,
        "strip": COMPLETED_STRIP,
    }
    fields.update(overrides)
    return FiniteObservation(**fields)


def decide(
    *,
    request: FiniteRunRequest = REQUEST,
    receipt: FiniteRunReceipt | None = RECEIPT,
    observed: FiniteObservation | None = None,
) -> FiniteRunDecision:
    return classify_finite_run(request, receipt, observed or observation())


# -- the measured state ----------------------------------------------------


def test_measured_completed_pair_authorises_the_store() -> None:
    decision = decide()
    assert decision.action is FiniteAction.STORE_COMPLETED
    assert decision.reasons == ()
    assert decision.store_token == TOKEN


def test_unknown_store_ownership_waits_only_while_run_command_is_pending() -> None:
    assert (
        decide(observed=observation(pending=5, held_block_token="")).action
        is FiniteAction.WAIT
    )
    assert (
        decide(observed=observation(pending=0, held_block_token="")).action
        is FiniteAction.REFUSE
    )
    assert (
        decide(observed=observation(pending=5, held_block_token="foreign")).action
        is FiniteAction.REFUSE
    )


@pytest.mark.parametrize("buttons", [0, 1, 3, 4])
def test_unmeasured_finite_store_shape_refuses(buttons: int) -> None:
    decision = decide(
        observed=observation(strip=StripState(button_count=buttons, has_slider=True))
    )
    assert decision.action is FiniteAction.REFUSE
    assert decision.reasons == ("finite_store_shape_unmeasured",)


def test_owned_block_still_draining_waits_and_authorises_nothing() -> None:
    for strip in (
        RECORDING_STRIP,
        READY_STRIP,
        COMPLETED_STRIP,  # held, but command 5 is still queued
    ):
        decision = decide(
            observed=observation(pending=5, current_channel=1, strip=strip)
        )
        assert decision.action is FiniteAction.WAIT
        assert decision.store_token == ""


def test_the_measured_arm_and_derived_bits_are_accepted() -> None:
    # The arm bit with the application's derived bit 21: the measured return.
    assert decide().action is FiniteAction.STORE_COMPLETED
    # The arm bit alone, before the derivation is visible.
    assert (
        decide(observed=observation(mode_after=65585 | (1 << 1))).action
        is FiniteAction.STORE_COMPLETED
    )


def test_a_completed_owned_store_may_already_have_cleared_the_arm_bit() -> None:
    # A successful finite completion clears bit 1; the drained block is still
    # the one this run produced and its store is still the authorised action.
    for mode_after in (65585, 65585 | (1 << 21)):
        decision = decide(observed=observation(mode_after=mode_after))
        assert decision.action is FiniteAction.STORE_COMPLETED
        assert decision.store_token == TOKEN


def test_a_cleared_arm_bit_does_not_complete_a_block_nobody_owns() -> None:
    # Bit 1 clear is only a completion when there is an owned, held block.
    for strip in (READY_STRIP, RECORDING_STRIP):
        decision = decide(observed=observation(mode_after=65585, strip=strip))
        assert decision.reasons == ("finite_mode_not_armed",)


# -- the Run receipt -------------------------------------------------------


def test_missing_receipt_refuses() -> None:
    assert decide(receipt=None).reasons == ("finite_receipt_missing",)


@pytest.mark.parametrize("pending_after_run", [0, 4, 28])
def test_a_receipt_must_state_the_run_command(pending_after_run: int) -> None:
    receipt = FiniteRunReceipt(
        run_token=TOKEN,
        identity=INSTANCE,
        invocations=1,
        pending_after_run=pending_after_run,
        record_dispatches=0,
        stop_dispatches=0,
    )
    assert decide(receipt=receipt).reasons == ("finite_receipt_pending_invalid",)


@pytest.mark.parametrize(
    ("receipt", "reason"),
    [
        (
            FiniteRunReceipt(
                run_token="other-run",
                identity=INSTANCE,
                invocations=1,
                pending_after_run=5,
                record_dispatches=0,
                stop_dispatches=0,
            ),
            "finite_receipt_foreign",
        ),
        (
            FiniteRunReceipt(
                run_token=TOKEN,
                identity=INSTANCE,
                invocations=0,
                pending_after_run=0,
                record_dispatches=0,
                stop_dispatches=0,
            ),
            "finite_receipt_not_dispatched",
        ),
        (
            FiniteRunReceipt(
                run_token=TOKEN,
                identity=INSTANCE,
                invocations=2,
                pending_after_run=5,
                record_dispatches=0,
                stop_dispatches=0,
            ),
            "finite_receipt_replayed",
        ),
        (
            FiniteRunReceipt(
                run_token=TOKEN,
                identity=INSTANCE,
                invocations=1,
                pending_after_run=5,
                record_dispatches=1,
                stop_dispatches=0,
            ),
            "finite_receipt_record_dispatched",
        ),
        (
            FiniteRunReceipt(
                run_token=TOKEN,
                identity=INSTANCE,
                invocations=1,
                pending_after_run=5,
                record_dispatches=0,
                stop_dispatches=1,
            ),
            "finite_receipt_stop_dispatched",
        ),
    ],
)
def test_receipt_that_is_not_the_one_owned_run_refuses(
    receipt: FiniteRunReceipt, reason: str
) -> None:
    decision = decide(receipt=receipt)
    assert decision.action is FiniteAction.REFUSE
    assert decision.reasons == (reason,)
    assert decision.store_token == ""


# -- identity and the application's own state ------------------------------


@pytest.mark.parametrize(
    "observed",
    [
        {"identity": ""},
        {"identity": "pid=9999;created=1"},
        {"error": "Fatal error: driver not ready"},
    ],
    ids=["unknown-identity", "changed-identity", "application-error"],
)
def test_identity_must_be_known_and_shared_and_the_app_must_be_clean(
    observed: dict[str, object],
) -> None:
    assert decide(observed=observation(**observed)).action is FiniteAction.REFUSE


def test_unknown_identity_is_named_as_such_even_on_the_receipt() -> None:
    receipt = RECEIPT.model_copy(update={"identity": ""})
    assert decide(receipt=receipt).reasons == ("finite_identity_unknown",)


def test_application_error_outranks_every_evidence_question() -> None:
    # No receipt, a foreign identity and a changed trigger: the error still wins.
    decision = decide(
        receipt=None,
        observed=observation(error="Fatal error", identity="pid=9", trigger_word=6),
    )
    assert decision.reasons == ("finite_application_error",)


# -- the request the Run was made for --------------------------------------


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"trigger_word": 6}, "finite_trigger_changed"),
        ({"participants": (1, 3)}, "finite_participants_changed"),
        ({"participants": (1,)}, "finite_participants_changed"),
        ({"sequences": 2}, "finite_sequences_changed"),
        ({"assisted_mode": True}, "finite_assisted_mode"),
        ({"current_channel": 3}, "finite_current_channel_unexpected"),
        ({"current_channel": 1}, "finite_current_channel_unexpected"),
        ({"mode_after": 2162739 | (1 << 7)}, "finite_mode_unexpected_bits"),
        ({"mode_after": 2162739 & ~0x10000}, "finite_mode_unexpected_bits"),
    ],
)
def test_the_requested_configuration_and_activity_must_be_preserved(
    overrides: dict[str, object], reason: str
) -> None:
    decision = decide(observed=observation(**overrides))
    assert decision.action is FiniteAction.REFUSE
    assert decision.reasons == (reason,)


@pytest.mark.parametrize("pending", [2, 3, 4, 6, 28])
def test_execution_code_carries_one_command_identifier_not_a_depth(
    pending: int,
) -> None:
    # 28 is Record and 2 the Off/refresh path: values below the queued 5 are
    # still other commands, and 6 is not a depth either.
    decision = decide(observed=observation(pending=pending))
    assert decision.reasons == ("finite_pending_unexpected",)


# -- the held block --------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"held_block_token": ""},
        {"held_block_token": "some-earlier-block"},
    ],
    ids=["unowned", "foreign"],
)
def test_a_store_view_the_owned_run_did_not_produce_refuses(
    overrides: dict[str, object],
) -> None:
    decision = decide(observed=observation(**overrides))
    assert decision.reasons == ("finite_held_block_foreign",)


def test_a_drained_run_with_no_held_block_refuses() -> None:
    decision = decide(observed=observation(strip=READY_STRIP))
    assert decision.reasons == ("finite_no_completed_block",)


def test_a_drained_recording_view_is_a_live_finite_run() -> None:
    # Execution_Code 0 is idle, not "finished": a finite sequence can be
    # recording with nothing queued, so this is a wait — the caller owns the
    # bounded completion deadline, this classifier owns no clock.
    decision = decide(
        observed=observation(pending=0, current_channel=1, strip=RECORDING_STRIP)
    )
    assert decision.action is FiniteAction.WAIT
    assert decision.store_token == ""


@pytest.mark.parametrize(
    "strip",
    [
        StripState(button_count=4, has_slider=False),
        StripState(button_count=2, has_slider=False),
    ],
    ids=["ambiguous", "unknown"],
)
def test_a_strip_whose_roles_are_not_settled_refuses(strip: StripState) -> None:
    decision = decide(observed=observation(strip=strip))
    assert decision.action is FiniteAction.REFUSE
    assert decision.reasons in (
        ("finite_strip_ambiguous",),
        ("finite_strip_unknown",),
    )


# -- purity and the trust boundary ----------------------------------------


def test_the_decision_is_a_pure_function_of_the_evidence() -> None:
    before_request = REQUEST.model_dump()
    before_receipt = RECEIPT.model_dump()
    observed = observation()
    before_observed = observed.model_dump()

    first = decide(observed=observed)
    second = decide(observed=observed)

    assert first == second
    assert REQUEST.model_dump() == before_request
    assert RECEIPT.model_dump() == before_receipt
    assert observed.model_dump() == before_observed


def test_a_strip_read_into_a_model_does_not_follow_later_mutation() -> None:
    source: dict[str, object] = {"button_count": 2, "has_slider": True}
    strip = StripState(**source)
    source["button_count"] = 4
    source["has_slider"] = False
    assert strip == COMPLETED_STRIP
    assert (
        decide(observed=observation(strip=strip)).action is FiniteAction.STORE_COMPLETED
    )


def test_the_evidence_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        observation().pending = 5  # type: ignore[misc]
    with pytest.raises(ValidationError):
        REQUEST.run_token = "replayed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        RECEIPT.invocations = 2  # type: ignore[misc]


# -- request validation ----------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"channels": ()},
        {"channels": (2, 1)},
        {"channels": (1, 1)},
        {"channels": (0, 1)},
        {"channels": (1, 11)},
        {"sequences": 0},
        {"run_token": ""},
        {"mode_before": 65585 | (1 << 1)},
        {"mode_before": 65584},
        {"channels": (1, 3)},
        {"mode_before": 65585 | (1 << 6)},
        {"trigger_word": 6},
        {"trigger_word": 4 | 0x40},
        {"trigger_word": 0},
    ],
    ids=[
        "no-channels",
        "unordered-channels",
        "duplicate-channels",
        "non-positive-channel",
        "channel-above-ten",
        "no-sequences",
        "no-token",
        "rollover-already-armed",
        "not-finite",
        "membership-mismatch",
        "extra-member-bit",
        "external-trigger",
        "guarded-trigger",
        "unmeasured-trigger",
    ],
)
def test_a_request_that_cannot_describe_one_owned_run_is_rejected(
    overrides: dict[str, object],
) -> None:
    fields: dict[str, object] = {
        "channels": (1, 2),
        "sequences": 1,
        "trigger_word": 4,
        "mode_before": 65585,
        "run_token": TOKEN,
    }
    fields.update(overrides)
    with pytest.raises(ValidationError):
        FiniteRunRequest(**fields)


def test_the_ten_channel_membership_edge_is_valid() -> None:
    request = FiniteRunRequest(
        channels=(1, 10),
        sequences=1,
        trigger_word=4,
        mode_before=1 | (8 << 1) | (8 << 10),
        run_token=TOKEN,
    )
    assert request.channels == (1, 10)
