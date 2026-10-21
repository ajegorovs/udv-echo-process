"""Repeated-sequence declarations: honest expected-total arithmetic, unknown repeat count.

The one measurable fact is the **stored total** per channel. ``--profiles`` keeps its
legacy meaning (that total). The explicit pair ``--profiles-per-visit N --repeats M``
states the operator's per-visit count and repeat count, and the expected total is their
product — arithmetic over the operator's own numbers, never a decoded fact. The
authentic 200RPM fixture is a 100-block multiplexed acquisition with 400 stored rows per
channel: declaring 4 per visit x 100 repeats reaches the matching total, and the check
must still report the actual repeat/visit count as unknown, because the decoder flattens
every stored block into one stream per channel.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from udv_echo_process.acquire import mpx_artifact
from udv_echo_process.acquire.store_completed import (
    CompletedBlockDeclaration,
    ProfileCountBasis,
    block_declaration_clauses,
)
from udv_echo_process.cli import acquire_main

FIXTURE = Path("data/4-sensor-velocity/200RPM.BDD")
CHANNELS = (6, 7, 8, 9)
TOTAL = 400


def repeated(
    *, channels: tuple[int, ...] = CHANNELS, per_visit: int = 4, repeats: int = 100
) -> CompletedBlockDeclaration:
    return CompletedBlockDeclaration(
        channels=channels,
        profiles_per_visit=per_visit,
        sequence_repeats=repeats,
        stated_by="pytest",
    )


# --------------------------------------------------------------- legacy total is unchanged


def test_legacy_total_basis_is_unchanged_and_still_consistent() -> None:
    declaration = CompletedBlockDeclaration(
        channels=CHANNELS, profiles_per_channel=TOTAL, stated_by="pytest"
    )

    report = mpx_artifact.verify_mpx_artifact(FIXTURE, declaration)

    assert report.verdict is mpx_artifact.MpxVerdict.CONSISTENT
    assert report.count_basis is ProfileCountBasis.STATED_TOTAL
    assert report.declared_profiles_per_channel == TOTAL
    assert report.expected_total_profiles == TOTAL
    assert report.declared_profiles_per_visit is None
    assert report.declared_sequence_repeats is None
    assert report.repeat_verification is mpx_artifact.MpxRepeatVerification.NOT_DECLARED
    assert report.repeat_note == ""
    # No repeat clause is invented for a declaration that states no repeat.
    assert {clause.subject for clause in report.clauses} == {
        "channels",
        "profiles:channel 6",
        "profiles:channel 7",
        "profiles:channel 8",
        "profiles:channel 9",
    }


# ------------------------------------------------------------- the synthetic declaration


def test_synthetic_declaration_normalizes_expected_total_once() -> None:
    """SYNTHETIC declaration only: no file, no fixture, and not an acceptance claim.

    This establishes the arithmetic normalization and its provenance fields. It says
    nothing about any real recording: no acquired repeat = 2 file exists on this host.
    """

    declaration = CompletedBlockDeclaration(
        channels=(1, 2),
        profiles_per_visit=50,
        sequence_repeats=2,
        stated_by="operator",
        statement="MPX on, channels 1 2, 50 profiles, repeat 2 (synthetic example)",
    )

    assert declaration.count_basis is ProfileCountBasis.PER_VISIT_TIMES_REPEATS
    assert declaration.expected_total_profiles == 100
    assert declaration.profiles_per_channel is None
    assert declaration.profiles_per_visit == 50
    assert declaration.sequence_repeats == 2
    assert "100 profiles each expected" in declaration.count_summary()
    assert "2 repeat(s) x 50 per visit" in declaration.count_summary()
    assert "actual number of stored visits is unknown" in (
        declaration.repeat_verification_unknown
    )


# ------------------------------------------------- authentic 100-block fixture, repeats stated


def test_authentic_400_row_fixture_matches_the_total_but_not_the_repeat_count() -> None:
    """4 per visit x 100 repeats = the 400 decoded rows, and the repeats stay unknown.

    This is arithmetic agreement with an **authentic** multiplexed file. It is not proof
    that 100 visits ran: the decoder emits one unpartitioned stream per channel, so the
    visited count is unestablished and the verdict is ``unverifiable``, never
    ``consistent``.
    """

    report = mpx_artifact.verify_mpx_artifact(FIXTURE, repeated())

    assert report.verdict is mpx_artifact.MpxVerdict.UNVERIFIABLE
    assert report.verdict is not mpx_artifact.MpxVerdict.CONSISTENT
    assert report.count_basis is ProfileCountBasis.PER_VISIT_TIMES_REPEATS
    assert report.declared_profiles_per_channel is None
    assert report.declared_profiles_per_visit == 4
    assert report.declared_sequence_repeats == 100
    assert report.expected_total_profiles == TOTAL
    assert report.repeat_verification is mpx_artifact.MpxRepeatVerification.UNKNOWN
    assert "actual number of stored visits is unknown" in report.repeat_note
    assert "not proof that 100 visit(s)" in report.repeat_note

    profiles = [c for c in report.clauses if c.subject.startswith("profiles:")]
    assert len(profiles) == len(CHANNELS)
    for clause in profiles:
        assert clause.status is mpx_artifact.MpxVerdict.CONSISTENT
        assert clause.expected == TOTAL
        assert clause.observed == TOTAL
        # The derivation is named, so the per-visit number is never silently converted.
        assert "= 100 repeat(s) x 4 per visit" in clause.detail

    repeats = [c for c in report.clauses if c.subject == "repeats"]
    assert len(repeats) == 1
    assert repeats[0].status is mpx_artifact.MpxVerdict.UNVERIFIABLE
    assert repeats[0].expected == 100
    assert "decodes no repeat, block or visit count" in repeats[0].detail
    assert "actual number of stored visits is unknown" in repeats[0].detail
    assert "unknown" in report.summary()


def test_repeated_declaration_with_a_wrong_product_is_contradicted() -> None:
    report = mpx_artifact.verify_mpx_artifact(
        FIXTURE, repeated(per_visit=5, repeats=100)
    )

    assert report.verdict is mpx_artifact.MpxVerdict.CONTRADICTED
    assert report.expected_total_profiles == 500
    profiles = [c for c in report.clauses if c.subject.startswith("profiles:")]
    assert {c.expected for c in profiles} == {500}
    assert {c.observed for c in profiles} == {TOTAL}
    # The repeat unknown is still reported beside the contradiction.
    assert report.repeat_verification is mpx_artifact.MpxRepeatVerification.UNKNOWN


# ------------------------------------------------------------ strict refusals, before a read


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        (
            {
                "profiles_per_channel": 100,
                "profiles_per_visit": 50,
                "sequence_repeats": 2,
            },
            "one declaration states one basis",
        ),
        ({"profiles_per_visit": 50}, "without a repeat count"),
        ({"sequence_repeats": 2}, "without a per-visit profile count"),
        (
            {"profiles_per_visit": 50, "sequence_repeats": 0},
            "positive repeat count",
        ),
        (
            {"profiles_per_visit": -50, "sequence_repeats": 2},
            "positive profile count per visit",
        ),
        ({"profiles_per_channel": 0}, "positive profile count"),
        # Strict field types refuse these before any clause is built; the clause function
        # refuses them too (see the direct test below). Either way: no count is inferred.
        ({"profiles_per_channel": True}, "valid integer"),
        ({"profiles_per_channel": "400"}, "valid integer"),
        ({"profiles_per_visit": True, "sequence_repeats": 2}, "valid integer"),
        ({"profiles_per_visit": 50, "sequence_repeats": True}, "valid integer"),
        ({"profiles_per_channel": None}, "states no profile count"),
    ],
)
def test_invalid_count_combinations_are_refused(
    overrides: dict[str, object], needle: str
) -> None:
    values: dict[str, object] = {"channels": CHANNELS, "stated_by": "pytest"}
    values.update(overrides)
    with pytest.raises(ValueError, match=needle):
        CompletedBlockDeclaration(**values)


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"profiles_per_channel": True}, "positive profile count"),
        ({"profiles_per_channel": "400"}, "positive profile count"),
        (
            {"profiles_per_visit": True, "sequence_repeats": 2},
            "positive profile count per visit",
        ),
        (
            {"profiles_per_visit": 50, "sequence_repeats": True},
            "positive repeat count",
        ),
    ],
)
def test_count_clause_refuses_non_integer_counts(kwargs: dict, needle: str) -> None:
    """The pure clause function is the CLI's refusal path, so it refuses by itself."""
    clauses = block_declaration_clauses(
        CHANNELS,
        kwargs.get("profiles_per_channel"),
        "pytest",
        profiles_per_visit=kwargs.get("profiles_per_visit"),
        sequence_repeats=kwargs.get("sequence_repeats"),
    )
    assert any(needle in clause for clause in clauses)


def test_invalid_declaration_is_refused_before_the_file_is_read(tmp_path: Path) -> None:
    """No decode, no report: the declaration is judged before the path is opened."""
    with pytest.raises(ValueError, match="one basis"):
        CompletedBlockDeclaration(
            channels=CHANNELS,
            profiles_per_channel=100,
            profiles_per_visit=50,
            sequence_repeats=2,
            stated_by="pytest",
        )

    missing = tmp_path / "absent.BDD"
    with pytest.raises(ValueError, match="one basis"):
        mpx_artifact.verify_mpx_artifact(
            missing,
            CompletedBlockDeclaration(
                channels=CHANNELS,
                profiles_per_channel=100,
                profiles_per_visit=50,
                sequence_repeats=2,
                stated_by="pytest",
            ),
        )
    assert not missing.exists()


# --------------------------------------------------------------------------- CLI boundary


def run_cli(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as raised:
        acquire_main(argv)
    return int(raised.value.code)


def test_cli_legacy_profiles_exits_zero(capsys) -> None:
    code = run_cli(
        [
            "mpx-check",
            str(FIXTURE),
            "--channel",
            *[str(c) for c in CHANNELS],
            "--profiles",
            str(TOTAL),
            "--stated-by",
            "pytest",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "consistent" in captured.out
    assert "repeats" not in captured.out


def test_cli_per_visit_pair_exits_three_and_names_the_unknown(capsys) -> None:
    code = run_cli(
        [
            "mpx-check",
            str(FIXTURE),
            "--channel",
            *[str(c) for c in CHANNELS],
            "--profiles-per-visit",
            "4",
            "--repeats",
            "100",
            "--stated-by",
            "pytest",
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 3
    assert '"verdict": "unverifiable"' in captured.out
    assert '"expected_total_profiles": 400' in captured.out
    assert '"declared_sequence_repeats": 100' in captured.out
    assert '"repeat_verification": "unknown"' in captured.out
    assert '"verdict": "consistent"' not in captured.out


@pytest.mark.parametrize(
    "declaration_args",
    [
        ["--profiles", "400", "--profiles-per-visit", "4", "--repeats", "100"],
        ["--profiles-per-visit", "4"],
        ["--repeats", "100"],
        ["--profiles-per-visit", "4", "--repeats", "0"],
        [],
    ],
)
def test_cli_bad_count_input_exits_two_with_one_line_and_no_decode(
    tmp_path: Path, capsys, declaration_args: list[str]
) -> None:
    """No device, no decode, no claim: the refusal is one line and exit 2."""
    absent = tmp_path / "absent.BDD"
    code = run_cli(
        [
            "mpx-check",
            str(absent),
            "--channel",
            "6",
            "7",
            "--stated-by",
            "pytest",
            *declaration_args,
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("udv-acquire: refused: ")


@pytest.mark.parametrize(
    "declaration_args",
    [
        ["--profiles", "100", "--profiles-per-visit", "50", "--repeats", "2"],
        ["--profiles-per-visit", "50"],
        [],
    ],
)
def test_cli_record_multiplexed_refuses_bad_counts_before_any_device_action(
    tmp_path: Path, capsys, declaration_args: list[str]
) -> None:
    """The refusal happens before a window is enumerated, so no GUI is needed to test it."""
    store = tmp_path / "store"
    store.mkdir()
    code = run_cli(
        [
            "record-multiplexed",
            "repeated-01",
            "--channel",
            "1",
            "2",
            "--mpx-enabled",
            "--completion-timeout",
            "30",
            "--stated-by",
            "operator",
            "--store-dir",
            str(store),
            *declaration_args,
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("udv-acquire: refused: ")
    assert list(store.iterdir()) == []
