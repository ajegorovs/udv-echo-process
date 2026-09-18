"""Contract tests for the campaign layer — ``acquire/campaign.py`` + its CLI subcommands.

``test_acquire_runner.py`` pins the per-point cycle and ``test_acquire_live.py`` the live
commands; this module pins the layer above both: a campaign is a **file**, it is validated
before the first recording is spent, its points run through the *runner's* own body rather
than a copy of it, its log is what a resume reads, and its manifest is what says which
definition produced which job.

Everything here is headless. The instrument is never touched: the run-level cases drive the
same in-memory fake the runner's tests use (imported, not re-implemented, so the two files
cannot drift apart), and the CLI cases spy the actuator the way the live tests do. What the
planning cases assert is the *law*, not an implementation shape — the measured ladder, the
depth budget and the block cap are the repo's own numbers (docs/08 §1–§3, docs/16 §15b).

The load-bearing cases are the two that would cost a recording if they were wrong:

- :func:`test_a_point_that_would_be_silently_clamped_is_refused_by_name` — the application
  trims a clamped window without saying so, so the plan has to say it *instead*, naming the
  point, before anything is recorded;
- :func:`test_resume_skips_exactly_the_points_the_log_holds_as_ok` — a resumed job must skip
  what was recorded and re-run exactly what was not, keyed on an identity the log already
  holds (no new field in the log record).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_acquire_runner import (
    BURST_LENGTH,
    DURATION_S,
    EMISSIONS_PER_PROFILE,
    PRF_US,
    SOUND_SPEED_MS,
    STORE_CALLS,
    TINY_SIZE,
    FakeActuator,
    ScriptedVerifier,
    definition_for,
    expected_snapshot,
    index_of,
    make_runner,
    patch_reader,
    patch_verifier,
    stored_names,
)

from udv_echo_process.acquire import campaign, live
from udv_echo_process.acquire.actuator import ChannelMode
from udv_echo_process.acquire.config import ParameterSet, RecordSettings
from udv_echo_process.acquire.log import (
    PointStatus,
    SweepPointRecord,
    append_entry,
    point_records,
    read_entries,
)
from udv_echo_process.acquire.plan import SweepPoint, plan_sweep
from udv_echo_process.acquire.snapshot import (
    FactSource,
    InstrumentFact,
    InstrumentSnapshot,
)
from udv_echo_process.cli import acquire_main

# --------------------------------------------------------------- the fixture campaign

#: The measured window frame of the tested channel (docs/13 §1, the committed fixture):
#: c = 1460 m/s, first gate 2 mm, PRF period 169 µs, 52 emissions per profile, burst 4.
FIRST_GATE_MM = 2.0

#: The rung ladder at c = 1460 m/s: one rung is c / 12000 = 0.121667 mm (docs/08 §1).
RUNG_1_MM = 0.121667
RUNG_2_MM = 0.243333

#: The gate counts the validated 99 mm window lands on at those two rungs — the handoff's
#: two-point sweep, measured live: "k=1 (0.122 mm, 797 gates) and k=2 (0.243 mm, 399 gates)"
#: (handoff §4).
GATES_K1 = 797
GATES_K2 = 399

#: The campaign's window: one duration for the whole slot, which is what makes the points
#: comparable (docs/dop3000/parameter-sweep-matrix.md §5).
CAMPAIGN_DURATION_S = 12.0

#: The example the repository ships for the near-term goal.
EXAMPLE = (
    Path(__file__).resolve().parents[1] / "examples" / "campaign-single-channel.json"
)


def parameters(
    resolution_mm: float,
    gates: int,
    *,
    sound_speed_ms: float = SOUND_SPEED_MS,
    first_gate_mm: float = FIRST_GATE_MM,
    **extra: object,
) -> dict[str, object]:
    """A point's requested ``ParameterSet`` as the campaign file writes it."""
    values: dict[str, object] = {
        "sound_speed_ms": sound_speed_ms,
        "first_gate_mm": first_gate_mm,
        "resolution_mm": resolution_mm,
        "gates": gates,
    }
    values.update(extra)
    return values


def campaign_payload(**overrides: object) -> dict[str, object]:
    """The test campaign: two rungs of one window, one channel, one duration.

    The shared covariates live on the campaign — they are dialog-only, read once for the
    channel, and a point's write cannot change them (``actuator.DIALOG_ONLY_PARAMETERS``).
    """
    payload: dict[str, object] = {
        "job": "test-single-channel",
        "channel": 1,
        "duration_s": CAMPAIGN_DURATION_S,
        "name_prefix": "c1",
        "prf_us": PRF_US,
        "emissions_per_profile": EMISSIONS_PER_PROFILE,
        "burst_length": BURST_LENGTH,
        "points": [
            {"label": "k1", "parameters": parameters(RUNG_1_MM, GATES_K1)},
            {"label": "k2", "parameters": parameters(RUNG_2_MM, GATES_K2)},
        ],
    }
    payload.update(overrides)
    return payload


def campaign_file(tmp_path: Path, payload: dict[str, object], name: str = "job.json") -> Path:
    """Write a campaign definition exactly as the loader will read it."""
    path = Path(tmp_path) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def load_definition(tmp_path: Path, **overrides: object) -> campaign.CampaignDefinition:
    """The test campaign, loaded through the loader the CLI uses."""
    return campaign.load_campaign(campaign_file(tmp_path, campaign_payload(**overrides)))


def plan_refusal(tmp_path: Path, **overrides: object) -> str:
    """Plan the test campaign and return the refusal's own words.

    Asserting on the message is the point: the plan exists to tell an operator which point
    is wrong and what to change, so a refusal that does not say so is not a refusal.
    """
    definition = load_definition(tmp_path, **overrides)
    with pytest.raises(campaign.CampaignError) as excinfo:
        campaign.plan_campaign(definition)
    return str(excinfo.value)


def load_refusal(path: Path) -> str:
    """Load ``path`` and return the loader's refusal."""
    with pytest.raises(campaign.CampaignError) as excinfo:
        campaign.load_campaign(path)
    return str(excinfo.value)


# --------------------------------------------------------------- the run-level fixture


@dataclass(frozen=True)
class Job:
    """A campaign bound to the runner's fake: its definition, its paths and its actuator."""

    fake: FakeActuator
    definition: campaign.CampaignDefinition
    definition_path: Path
    directory: Path
    log_path: Path


def campaign_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: object) -> Job:
    """A campaign over the runner's own fake, with the decoder and the verifier scripted.

    The fake stores buffers rather than real ``.BDD`` files, so both module-local adapters
    of the runner are scripted the way the runner's own tests script them: a decode that
    agrees with the stored size, and a verifier that agrees with the request. Nothing else
    about the path changes — ``run_campaign`` builds a real ``SweepRunner``.
    """
    base = Path(tmp_path) / "job"
    directory = base / "capture"
    directory.mkdir(parents=True, exist_ok=True)
    fake = FakeActuator(directory)
    patch_reader(monkeypatch, fake=fake)
    patch_verifier(monkeypatch, ScriptedVerifier())
    definition_path = campaign_file(Path(tmp_path), campaign_payload(**overrides))
    definition = campaign.load_campaign(definition_path)
    return Job(
        fake=fake,
        definition=definition,
        definition_path=definition_path,
        directory=directory,
        log_path=base / "campaign.jsonl",
    )


def run_job(job: Job, **kwargs: object) -> campaign.JobManifest:
    """Run the fixture job through the fake, with the paths it was built with."""
    return campaign.run_campaign(
        job.definition,
        job.fake,
        store_dir=job.directory,
        log_path=job.log_path,
        **kwargs,  # type: ignore[arg-type]
    )


def record_for(
    name: str,
    sweep_id: str,
    *,
    status: PointStatus = PointStatus.OK,
    key: int = 1,
    gates: int = GATES_K1,
    failure: str | None = None,
) -> SweepPointRecord:
    """One log record, written the way the runner writes it."""
    return SweepPointRecord(
        sweep_id=sweep_id,
        key=key,
        name=name,
        status=status,
        requested=ParameterSet(
            sound_speed_ms=SOUND_SPEED_MS,
            first_gate_mm=FIRST_GATE_MM,
            resolution_mm=RUNG_1_MM,
            gates=gates,
        ),
        failure=failure,
    )


# ------------------------------------------------------- 1. the definition loads and plans


def test_the_shipped_example_loads_and_plans() -> None:
    """``examples/campaign-single-channel.json`` is a real definition, not a sketch.

    Its numbers are the instrument's measured ones: c = 1460 m/s on channel 1, first gate
    2 mm, PRF 212 µs, 150 emissions per profile, burst 4 (handoff §3/§4), a 12 s window
    inside the operator's 10-15 s band, and the rung ladder of the validated two-point
    sweep — k=1 at 797 gates and k=2 at 399 gates of a 99 mm window.
    """
    assert EXAMPLE.is_file(), f"the example moved: {EXAMPLE}"

    definition = campaign.load_campaign(EXAMPLE)
    points = campaign.plan_campaign(definition)

    assert definition.channel == 1
    assert definition.duration_s == 12.0
    assert definition.prf_us == 212.0
    assert definition.emissions_per_profile == 150
    assert [point.label for point in points] == [
        "c1460-k1-a",
        "c1460-k2",
        "c1460-k4",
        "c1460-k1-b",
        "c1460-k8",
        "c1460-k1-c",
    ]
    assert [point.key for point in points] == [1, 2, 3, 4, 5, 6]
    assert [point.parameters.gates for point in points] == [797, 399, 199, 797, 100, 797]
    # The ladder is the sound speed's own: one rung is c / 12000 mm (docs/08 §1), written
    # at the sidebar's 3-decimal display value (docs/16 §12a).
    assert [point.parameters.resolution_mm for point in points] == [
        pytest.approx(1 * 1460 / 12000, abs=1e-6),
        pytest.approx(2 * 1460 / 12000, abs=1e-6),
        pytest.approx(4 * 1460 / 12000, abs=1e-6),
        pytest.approx(1 * 1460 / 12000, abs=1e-6),
        pytest.approx(8 * 1460 / 12000, abs=1e-6),
        pytest.approx(1 * 1460 / 12000, abs=1e-6),
    ]
    # Every point is one window: the 99 mm the operator measured, to a third of a mm.
    assert all(abs(point.expected_depth_mm - 99.0) < 0.4 for point in points)
    assert all(point.duration_s == 12.0 for point in points)
    # The baseline is repeated at the start, in the middle and at the end, which is how rig
    # drift is told from a parameter effect (docs/dop3000/parameter-sweep-matrix.md §5).
    assert len({point.identity for point in points}) == 6
    repeated = [point for point in points if point.parameters.gates == 797]
    assert [point.label for point in repeated] == ["c1460-k1-a", "c1460-k1-b", "c1460-k1-c"]


def test_a_definition_loads_and_plans_every_point(tmp_path: Path) -> None:
    """The declarative list becomes the run's points: keys, identities, windows, requests."""
    definition = load_definition(tmp_path)
    points = campaign.plan_campaign(definition)

    assert definition.job == "test-single-channel"
    assert [point.label for point in points] == ["k1", "k2"]
    assert [point.identity for point in points] == ["c1-k1", "c1-k2"]
    assert [point.key for point in points] == [1, 2]
    assert [point.duration_s for point in points] == [
        CAMPAIGN_DURATION_S,
        CAMPAIGN_DURATION_S,
    ]
    assert [point.parameters.gates for point in points] == [GATES_K1, GATES_K2]
    assert points[0].expected_depth_mm == pytest.approx(
        2.0 + GATES_K1 * RUNG_1_MM, abs=1e-3
    )
    # The campaign's shared covariates reach the request every point records with: the
    # period law needs them or the runner refuses the point after a recording is spent.
    for point in points:
        assert point.parameters.prf_us == PRF_US
        assert point.parameters.emissions_per_profile == EMISSIONS_PER_PROFILE
        assert point.parameters.burst_length == BURST_LENGTH
        assert point.profiles >= 1
    # profiles = T / period, at the measured period law (docs/16 §15).
    assert points[0].profiles == pytest.approx(
        CAMPAIGN_DURATION_S / (EMISSIONS_PER_PROFILE * PRF_US * 1e-6 + 1e-3), rel=0.01
    )


def test_a_point_may_override_the_campaigns_window(tmp_path: Path) -> None:
    """One duration for the slot, and an override for the point that is deliberately different."""
    payload = campaign_payload(
        points=[
            {"label": "k1", "parameters": parameters(RUNG_1_MM, GATES_K1)},
            {
                "label": "k2",
                "parameters": parameters(RUNG_2_MM, GATES_K2),
                "duration_s": 6.0,
            },
        ]
    )
    definition = campaign.load_campaign(campaign_file(tmp_path, payload, "override.json"))

    assert [point.duration_s for point in campaign.plan_campaign(definition)] == [
        CAMPAIGN_DURATION_S,
        6.0,
    ]


# ------------------------------------------------ 2. a malformed file is a clear refusal


def test_an_unknown_field_is_refused_by_name(tmp_path: Path) -> None:
    """``extra="forbid"``, reported as a sentence rather than as a traceback."""
    payload = campaign_payload(prf=212.0)  # the field is prf_us; prf is a sweep's flag
    message = load_refusal(campaign_file(tmp_path, payload))

    assert "unknown field 'prf'" in message
    assert "job.json" in message  # the file is named too


def test_an_unknown_field_inside_a_point_is_refused_by_path(tmp_path: Path) -> None:
    payload = campaign_payload(points=[{"label": "k1", "parameters": parameters(RUNG_1_MM, GATES_K1), "seconds": 3}])
    message = load_refusal(campaign_file(tmp_path, payload))

    assert "unknown field 'points.0.seconds'" in message


def test_a_missing_field_is_refused_by_name(tmp_path: Path) -> None:
    payload = campaign_payload()
    del payload["duration_s"]  # required: there is no window to record for without it
    message = load_refusal(campaign_file(tmp_path, payload))

    assert "missing field 'duration_s'" in message
    assert "job.json" in message


def test_an_empty_point_list_is_refused(tmp_path: Path) -> None:
    message = load_refusal(campaign_file(tmp_path, campaign_payload(points=[])))

    assert "points" in message
    assert "at least one parameter permutation" in message


def test_a_file_that_is_not_json_is_refused_by_name(tmp_path: Path) -> None:
    """A definition that does not parse is the same class of problem as one that does not fit."""
    path = Path(tmp_path) / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    assert "not valid JSON" in load_refusal(path)


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    assert "could not be read" in load_refusal(Path(tmp_path) / "nothing-here.json")


def test_a_label_that_cannot_name_a_file_is_refused(tmp_path: Path) -> None:
    """A label becomes a file name in a modal dialog: a name it refuses leaves the panel up."""
    payload = campaign_payload(
        points=[{"label": "../escape", "parameters": parameters(RUNG_1_MM, GATES_K1)}]
    )
    message = load_refusal(campaign_file(tmp_path, payload))

    assert "cannot name a stored point" in message


# ------------------------------------------- 3. what the application would clamp silently


@pytest.mark.parametrize(
    ("gates", "expected_words"),
    [
        (1200, "outside the accepted 4..1000"),  # the measured gate range (docs/08 §2)
        (1000, "depth budget"),  # in range, but 2 + 1000 x 0.121667 > P_max at 169 µs
    ],
)
def test_a_point_that_would_be_silently_clamped_is_refused_by_name(
    tmp_path: Path, gates: int, expected_words: str
) -> None:
    """Plan-time, not discovery-time: the refusal names the point and what to change."""
    payload = campaign_payload(
        points=[{"label": "too-far", "parameters": parameters(RUNG_1_MM, gates)}]
    )
    message = plan_refusal(tmp_path, points=payload["points"])

    assert "'too-far'" in message, message
    assert expected_words in message, message


def test_the_depth_budget_refusal_reads_like_the_sweep_plans(tmp_path: Path) -> None:
    """The same law, and the same words, as ``plan_sweep``: P_max = c x T_prf / 2 (docs/08 §3)."""
    payload = campaign_payload(
        points=[{"label": "deep", "parameters": parameters(RUNG_1_MM, 1000)}]
    )
    message = plan_refusal(tmp_path, points=payload["points"])

    expected_p_max = SOUND_SPEED_MS * PRF_US * 1e-3 / 2.0
    assert f"{expected_p_max:.3f} mm" in message
    assert "silently reduce the gate count" in message


def test_a_pitch_off_the_ladder_is_refused_by_name(tmp_path: Path) -> None:
    """The application snaps a pitch to the nearest rung, silently (docs/08 §1)."""
    payload = campaign_payload(
        points=[{"label": "off-rung", "parameters": parameters(0.2, GATES_K1)}]
    )
    message = plan_refusal(tmp_path, points=payload["points"])

    assert "'off-rung'" in message
    assert "not a ladder rung" in message
    assert "0.243" in message  # the rung the application would actually use


def test_a_pitch_within_half_a_display_unit_of_a_rung_is_accepted(tmp_path: Path) -> None:
    """The sidebar shows three decimals (docs/16 §12a), so 0.122 *is* rung 1 at c = 1460."""
    payload = campaign_payload(
        points=[{"label": "shown", "parameters": parameters(0.122, GATES_K1)}]
    )
    points = campaign.plan_campaign(load_definition(tmp_path, points=payload["points"]))

    assert points[0].parameters.resolution_mm == pytest.approx(0.122)


def test_a_duplicate_label_is_refused(tmp_path: Path) -> None:
    """One label, one identity: two points cannot both be the point a resume keys on."""
    payload = campaign_payload(
        points=[
            {"label": "k1", "parameters": parameters(RUNG_1_MM, GATES_K1)},
            {"label": "k1", "parameters": parameters(RUNG_2_MM, GATES_K2)},
        ]
    )
    message = plan_refusal(tmp_path, points=payload["points"])

    assert "duplicate label 'k1'" in message
    assert "point 2" in message  # it says which two points collided


def test_two_labels_may_ask_for_the_same_parameters(tmp_path: Path) -> None:
    """The baseline repeated at the start, middle and end of an axis is a *design*, not a bug."""
    payload = campaign_payload(
        points=[
            {"label": "k1-a", "parameters": parameters(RUNG_1_MM, GATES_K1)},
            {"label": "k2", "parameters": parameters(RUNG_2_MM, GATES_K2)},
            {"label": "k1-b", "parameters": parameters(RUNG_1_MM, GATES_K1)},
        ]
    )
    definition = load_definition(tmp_path, points=payload["points"])
    points = campaign.plan_campaign(definition)

    assert len(points) == 3
    assert len({point.identity for point in points}) == 3


@pytest.mark.parametrize("field", ["sound_speed_ms", "first_gate_mm"])
def test_points_must_share_the_window_frame(tmp_path: Path, field: str) -> None:
    """Sound speed and first gate are dialog-only: a point's write cannot change them.

    A list planned on two of either would record every point at the channel's own values,
    so the refusal names both points instead of planning files that contradict themselves.
    """
    changed = {"sound_speed_ms": 1500.0} if field == "sound_speed_ms" else {"first_gate_mm": 5.0}
    payload = campaign_payload(
        points=[
            {"label": "k1", "parameters": parameters(RUNG_1_MM, GATES_K1)},
            {"label": "k2", "parameters": parameters(RUNG_2_MM, GATES_K2, **changed)},
        ]
    )
    message = plan_refusal(tmp_path, points=payload["points"])

    assert "'k2'" in message and "'k1'" in message
    assert field in message
    assert "dialog-only" in message


def test_a_point_that_disagrees_with_a_shared_covariate_is_refused(tmp_path: Path) -> None:
    """The PRF period is read once for the channel; a point may repeat it, never change it."""
    payload = campaign_payload(
        points=[
            {
                "label": "k1",
                "parameters": parameters(RUNG_1_MM, GATES_K1, prf_us=300.0),
            }
        ]
    )
    message = plan_refusal(tmp_path, points=payload["points"])

    assert "'k1'" in message
    assert "prf_us=300.0" in message
    assert str(PRF_US) in message


def test_a_window_longer_than_the_block_cap_is_stated_not_refused(tmp_path: Path) -> None:
    """The near-term goal is a 10-15 s recording, so the plan must not refuse one.

    The instrument honours the request while its block keeps only the last ``cap x period``
    seconds of it (measured: a 12 s request stored ~257 profiles at 46.7 ms/profile). So the
    plan states what will be kept and lets the point run: refusing here would make the goal
    unrunnable, and saying nothing would let the plan pretend the file covers the whole
    window it was asked for.
    """
    definition = load_definition(tmp_path, max_profiles_per_block=100)

    points = campaign.plan_campaign(definition)

    assert all(point.note is not None for point in points)
    assert "above the block cap of 100" in points[0].note


@pytest.mark.parametrize(
    "duration", [campaign.MIN_POINT_DURATION_S / 2, campaign.MAX_POINT_DURATION_S * 2]
)
def test_a_window_outside_the_sane_range_is_refused(tmp_path: Path, duration: float) -> None:
    payload = campaign_payload(
        points=[
            {
                "label": "k1",
                "parameters": parameters(RUNG_1_MM, GATES_K1),
                "duration_s": duration,
            }
        ]
    )
    message = plan_refusal(tmp_path, points=payload["points"])

    assert "'k1'" in message
    assert "outside the sane range" in message


# ------------------------------------------------------------------- 4. the fingerprint


def test_the_fingerprint_is_stable_and_moves_with_a_point(tmp_path: Path) -> None:
    """A manifest says which definition produced a job: the hash has to mean something."""
    first = campaign.campaign_fingerprint(load_definition(tmp_path))
    second = campaign.campaign_fingerprint(load_definition(tmp_path))
    assert first == second
    assert len(first) == 64 and int(first, 16) >= 0  # a SHA-256 hex digest

    # A different point, a different duration, a different name prefix: all move it.
    changed_point = campaign.campaign_fingerprint(
        load_definition(
            tmp_path,
            points=[
                {"label": "k1", "parameters": parameters(RUNG_1_MM, GATES_K1)},
                {"label": "k2", "parameters": parameters(RUNG_2_MM, GATES_K1)},
            ],
        )
    )
    changed_window = campaign.campaign_fingerprint(
        load_definition(tmp_path, duration_s=CAMPAIGN_DURATION_S + 1.0)
    )
    changed_prefix = campaign.campaign_fingerprint(load_definition(tmp_path, name_prefix="c2"))
    assert len({first, changed_point, changed_window, changed_prefix}) == 4


# --------------------------------------------------------------- 5. the manifest


def test_the_manifest_round_trips(tmp_path: Path) -> None:
    """What a job was, when, which definition, and how each point ended."""
    manifest = campaign.JobManifest(
        job="test-single-channel",
        fingerprint="a" * 64,
        channel=1,
        planned=3,
        skipped=("c1-k1",),
        started_at=datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 9, 17, 12, 5, 0, tzinfo=UTC),
        outcomes=(
            campaign.ManifestPoint(
                key=2,
                label="k2",
                identity="c1-k2",
                status=PointStatus.INVALID,
                ok=False,
                file="C:/capture/c1-k2-stamp.BDD",
                reason="the stored file is 10x the signature",
            ),
            campaign.ManifestPoint(
                key=3,
                label="k3",
                identity="c1-k3",
                status=PointStatus.OK,
                ok=True,
            ),
        ),
        store_dir="C:/capture",
        log_path="C:/capture/campaign.jsonl",
        definition_path="C:/defs/job.json",
    )
    path = campaign.manifest_path_for(tmp_path / "campaign.jsonl")
    assert path.name == "campaign.manifest.json"

    campaign.write_manifest(path, manifest)

    assert path.is_file()
    assert campaign.read_manifest(path) == manifest
    assert campaign.read_manifest_if_present(path) == manifest
    assert campaign.read_manifest_if_present(tmp_path / "other.manifest.json") is None
    assert manifest.points_skipped == 1
    assert manifest.ok_count == 1 and manifest.failed_count == 1 and not manifest.aborted
    assert "1/3 point(s) ok" in manifest.summary
    assert "1 skipped as already recorded" in manifest.summary


def test_a_malformed_manifest_is_refused_by_name(tmp_path: Path) -> None:
    path = Path(tmp_path) / "campaign.manifest.json"
    path.write_text(json.dumps({"job": "x"}), encoding="utf-8")

    with pytest.raises(campaign.CampaignError) as excinfo:
        campaign.read_manifest(path)
    message = str(excinfo.value)
    assert "not a job manifest" in message
    assert "missing field" in message


# ------------------------------------------------------------- 6. the runner-level seam


def test_an_explicit_sequence_of_points_is_written_and_recorded_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``SweepRunner.run_points``: the campaign's seam into the proven per-point body.

    The sequence is explicit — keys, requests and windows chosen by the caller — and no
    window is forced, so each point runs for its *own* ``duration_s``: that is what a
    campaign passes, and it is the only difference from ``run``, which plans a ladder and
    gives every point the same window.
    """
    planned = plan_sweep(definition_for(1, 2, 3))
    sequence = tuple(
        SweepPoint(key=key, parameters=planned[key - 1].parameters, duration_s=window)
        for key, window in ((1, 1.0), (2, 2.5), (3, 1.0))
    )
    fake, engine, log_path, _ = make_runner(tmp_path, monkeypatch)

    outcomes = engine.run_points(sequence)

    assert [outcome.point.key for outcome in outcomes] == [1, 2, 3]
    assert all(outcome.ok for outcome in outcomes), [o.reason for o in outcomes]
    # Each point's own window was used, in the order the sequence gave them.
    assert [
        call[2] for call in fake.calls if call[0] == "try_record_and_store"
    ] == [1.0, 2.5, 1.0]
    records = point_records(read_entries(log_path))
    assert [record.key for record in records] == [1, 2, 3]
    stamp = records[0].sweep_id
    assert [record.name for record in records] == [
        f"sw100-k{key}-{stamp}" for key in (1, 2, 3)
    ]
    assert len(stored_names(fake.directory)) == 3

    # A forced window overrides every point's own, the way ``run`` gives one to the whole plan.
    other_fake, other_engine, _, _ = make_runner(tmp_path / "forced", monkeypatch)
    other_engine.run_points(sequence, DURATION_S)

    assert [
        call[2] for call in other_fake.calls if call[0] == "try_record_and_store"
    ] == [DURATION_S, DURATION_S, DURATION_S]
    assert other_fake.stored and all(
        path.stat().st_size > 0 for path in other_fake.stored
    )


def test_the_runner_still_refuses_a_nonpositive_forced_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_points`` keeps ``run``'s contract: a window of zero is a caller error, not a run."""
    _fake, engine, _, _ = make_runner(tmp_path, monkeypatch)
    point = plan_sweep(definition_for(1))[0]

    with pytest.raises(ValueError, match="duration_s"):
        engine.run_points((point,), 0.0)


# ------------------------------------------------------- 7. a run, its log and its manifest


def test_the_label_names_the_stored_file() -> None:
    """``<prefix>-<label>-<stamp>``, and the identity is that minus the run's stamp."""
    settings = campaign.CampaignRecordSettings(name_prefix="c1", labels=("k1", "k2"))

    assert settings.point_name(1, "20260917T120000") == "c1-k1-20260917T120000"
    assert settings.point_name(2, "20260917T120000") == "c1-k2-20260917T120000"
    # The uniqueness retry is inherited, not re-implemented.
    assert settings.next_name(1, "s", {"c1-k1-s"}) == "c1-k1-sb"
    with pytest.raises(ValueError, match="stamp"):
        settings.point_name(1, "")
    with pytest.raises(ValueError, match="no label for key 3"):
        settings.point_name(3, "20260917T120000")


def test_a_run_writes_the_manifest_beside_its_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One log entry per point, a file named from each label, and a manifest saying so."""
    job = campaign_job(tmp_path, monkeypatch)

    manifest = run_job(job)

    assert manifest.job == job.definition.job
    assert manifest.fingerprint == campaign.campaign_fingerprint(job.definition)
    assert manifest.channel == 1
    assert manifest.planned == 2 and manifest.points_skipped == 0
    assert manifest.ok_count == 2 and manifest.failed_count == 0
    assert not manifest.aborted
    assert manifest.log_errors == ()
    assert [row.label for row in manifest.outcomes] == ["k1", "k2"]
    assert [row.identity for row in manifest.outcomes] == ["c1-k1", "c1-k2"]
    assert [row.status for row in manifest.outcomes] == [PointStatus.OK, PointStatus.OK]
    assert "2/2 point(s) ok" in manifest.summary

    manifest_path = campaign.manifest_path_for(job.log_path)
    assert manifest_path.is_file()
    assert campaign.read_manifest(manifest_path) == manifest

    records = point_records(read_entries(job.log_path))
    assert [record.key for record in records] == [1, 2]
    assert [Path(record.file_path or "").name for record in records] == [
        f"c1-k1-{records[0].sweep_id}.BDD",
        f"c1-k2-{records[0].sweep_id}.BDD",
    ]
    # The channel dialog was opened twice for the campaign run, and that is the run path's
    # own shape: once by the routing step (step 3, whose return the reading carries as its
    # ``routed`` fact) and once by the runner's itself-once guard before the first recording.
    # Each gesture is a dialog the operator watches, so the count is pinned rather than left
    # to drift into "one per point".
    assert job.fake.channel_checks == 2
    assert job.fake.verify_channel_flags == [False, False]


def test_recorded_points_reads_the_log_the_runner_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resume reads the log's own records — name minus stamp — and nothing else."""
    job = campaign_job(tmp_path, monkeypatch)

    assert campaign.recorded_points(job.log_path) == set()  # nothing recorded yet

    run_job(job)

    records = point_records(read_entries(job.log_path))
    assert campaign.recorded_points(job.log_path) == {"c1-k1", "c1-k2"}
    assert [
        campaign.record_identity(record) for record in records
    ] == ["c1-k1", "c1-k2"]
    # The identity comes out of the record's own fields, and no field was added for it.
    assert {"record_type", "sweep_id", "key", "name", "status", "requested"} <= set(
        SweepPointRecord.model_fields
    )
    assert "identity" not in SweepPointRecord.model_fields

    # A failed or invalid record is not "recorded": that point has to be run again.
    append_entry(
        job.log_path,
        record_for("c1-k2-oldstamp", "oldstamp", status=PointStatus.INVALID, key=2),
    )
    assert campaign.recorded_points(job.log_path) == {"c1-k1", "c1-k2"}


def test_a_log_with_only_failures_records_nothing(tmp_path: Path) -> None:
    log_path = Path(tmp_path) / "campaign.jsonl"
    append_entry(
        log_path,
        record_for("c1-k1-s1", "s1", status=PointStatus.FAILED, failure="refused"),
    )
    append_entry(log_path, record_for("c1-k2-s1", "s1", status=PointStatus.INVALID, key=2))

    assert campaign.recorded_points(log_path) == set()


def test_an_identity_that_does_not_end_in_its_stamp_is_not_a_skip(
    tmp_path: Path,
) -> None:
    """The safe direction: an identity in doubt is re-run, never skipped."""
    log_path = Path(tmp_path) / "campaign.jsonl"
    append_entry(log_path, record_for("c1-k1-s1b", "s1"))  # the 'b'-suffix retry

    assert campaign.recorded_points(log_path) == {"c1-k1-s1b"}


def test_resume_skips_exactly_the_points_the_log_holds_as_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing case: an interrupted job resumes, and re-records only what is missing.

    The resume no longer trusts the log on its own, and that is **one of the seams this slice
    adds deliberately**: before any point leaves the todo set, the previous manifest has to
    carry a compilation identity that matches the one this run compiles against the instrument
    (step 6 of the run path). A log alone says what was recorded and nothing about *what was
    measured on*, so a resume keyed on it could skip a point of a job that was run against a
    different instrument. Here the two identities match — the same fake, the same reading —
    so the skip this cache-case is about still happens.
    """
    job = campaign_job(tmp_path, monkeypatch)
    # The second point comes back far off the signature — a truncated store, the other
    # shape of the containment guard (docs/16 §15b): 128 B where the 12 s window at 399
    # gates expects hundreds of kB. It is refused *for its own sake*, so the run continues.
    job.fake.script_size(None, TINY_SIZE)

    first = run_job(job)

    assert [row.ok for row in first.outcomes] == [True, False]
    assert first.failed_count == 1
    assert campaign.recorded_points(job.log_path) == {"c1-k1"}

    notes: list[str] = []
    second = run_job(job, resume=True, notes=notes)

    assert second.points_skipped == 1
    assert second.skipped == ("c1-k1",)
    assert [row.label for row in second.outcomes] == ["k2"]
    assert second.ok_count == 1 and second.failed_count == 0
    assert notes and "resume: 1 of 2" in notes[0]
    # Five stores in total: two the first run spent, one the resumed run spent, plus none
    # for the point it skipped — and the skipped point's file is the one it already had.
    assert [record.key for record in point_records(read_entries(job.log_path))] == [1, 2, 2]
    assert campaign.recorded_points(job.log_path) == {"c1-k1", "c1-k2"}
    assert len(campaign.plan_campaign(job.definition)) == 2
    assert second.planned == 2  # the manifest still describes the whole job
    assert second.fingerprint == first.fingerprint
    # ...and the skip rested on an identity both runs agree about (step 6 of the run path):
    # the previous manifest carries one and this run compiled the same one. A skip on an
    # identity nothing proved is what `skipped_without_evidence` marks, and this is not it.
    assert first.compilation_identity is not None
    assert second.compilation_identity == first.compilation_identity
    assert second.skipped_without_evidence == ()


def test_a_campaign_run_aborts_on_an_unverified_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A point that ends the run ends the manifest too: the rest is not attempted."""
    job = campaign_job(tmp_path, monkeypatch)
    job.fake.layout_note_value = "not the measurement layout: 49 controls in 5 panels"

    manifest = run_job(job)

    assert len(manifest.outcomes) == 1
    assert manifest.outcomes[0].aborted is True
    assert manifest.aborted is True
    assert manifest.failed_count == 1
    assert "cut short" in manifest.summary
    assert job.fake.stored == []


def test_no_store_directory_is_refused_by_the_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never a guess: the cycle writes the dialog's directory, so one has to be named."""
    job = campaign_job(tmp_path, monkeypatch)

    with pytest.raises(campaign.CampaignError, match="no store directory"):
        campaign.run_campaign(job.definition, job.fake, store_dir=None, log_path=job.log_path)


# ------------------------------- 7b. the run path: route, read, compile — then the resume
#
# The plan's §4 step order, implemented literally: load (1), statically plan (2), establish the
# channel (3), take the reading (4), compile (5), validate the resume identity (6), compute the
# todo/skipped sets (7), run the compiled points (8). These cases pin the three seams the run
# path carries — the compile happens *before* the first recording is spent, the manifest keeps
# the compiled identity, and a resume is refused until that identity is proven — because each
# of them costs a recording, or a wrongly-skipped point, if it is missing.


def snapshot_with(**facts: InstrumentFact) -> InstrumentSnapshot:
    """The fake's expected reading with one or more of its facts replaced.

    The fake hands a scripted reading back verbatim, so this is how a case changes what the
    instrument *states* between two runs without a second fake: the same fake, a different
    reading — which is the shape of a rig somebody re-configured between the two runs.
    """
    return expected_snapshot(1).model_copy(update=facts)


def legacy_manifest(manifest: campaign.JobManifest) -> campaign.JobManifest:
    """``manifest`` as every manifest written *before* this slice states it — with no identity.

    Built by dropping the fields this slice added, which is the point of the case that uses
    it: the reader has to keep accepting those manifests, which is why every new field has a
    default (a required one would make every pre-existing manifest raise on read).
    """
    payload = manifest.model_dump()
    for field in ("compilation_identity", "declared_only", "skipped_without_evidence"):
        payload.pop(field, None)
    return campaign.JobManifest.model_validate(payload)


def test_a_run_routes_reads_and_compiles_once_before_the_first_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Steps 3-5 happen once, in that order, and strictly before the first point is stored.

    The order is the whole safety argument: the routing step establishes the channel the
    reading then carries as a ``routed`` fact, the reading states the fixed facts, and the
    compile reconciles the two against the definition — all *before* the runner is built, so
    a job that cannot be compiled costs no recording. The channel dialog is opened twice for
    a campaign run and that is deliberate: once as the routing step (whose own return is
    handed to the reading) and once as the runner's own once-per-run guard, which is the
    runner's guard and not the campaign's business to skip.
    """
    job = campaign_job(tmp_path, monkeypatch)

    manifest = run_job(job)

    assert job.fake.channel_checks == 2  # the routing step, then the runner's own guard
    assert job.fake.snapshot_checks == 1  # one reading, taken once for the whole job
    assert job.fake.dialog_checks == 1  # the dialog-only facts read as their own step
    assert job.fake.snapshot_dialogs == job.fake.dialog_readings, (
        "the reading was handed the dialog reading the routing step made: the snapshot "
        "deliberately does not open the dialog itself, so the campaign path reads it and "
        "hands it over"
    )

    read_at = index_of(job.fake.calls, lambda call: call[0] == "instrument_snapshot")
    stored_at = index_of(job.fake.calls, lambda call: call[0] in STORE_CALLS)
    assert read_at is not None and stored_at is not None, job.fake.calls
    assert read_at < stored_at, "the reading was taken after the first point was stored"
    # ...and it carried the channel the routing step verified, not a claim nobody made.
    assert job.fake.calls[read_at] == ("instrument_snapshot", 1)
    assert manifest.ok_count == 2


def test_a_compile_refusal_stops_the_run_before_anything_is_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reading the compile refuses raises — with no recording, no ``.BDD``, no manifest.

    The refusal is not wrapped: ``compile_campaign``'s own message names the state or the
    fact that stopped the job, and re-raising it here would give one cause two diagnoses.
    Nothing about the *run* exists afterwards, and that is the point of compiling first: a
    manifest written for a refused job would claim a run that never happened.
    """
    job = campaign_job(tmp_path, monkeypatch)
    job.fake.scripted_snapshot = snapshot_with(
        sound_speed_ms=InstrumentFact(value="1500", source=FactSource.READ)
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job)

    message = str(excinfo.value)
    assert "sound_speed_ms" in message and "1500" in message, message
    assert job.fake.snapshot_checks == 1  # the reading happened; the compile is what refused
    assert job.fake.stored == []
    assert stored_names(job.directory) == []
    assert not job.log_path.exists()
    assert not campaign.manifest_path_for(job.log_path).exists()


def test_the_manifest_carries_the_compiled_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The manifest keeps the §3.3 projection — each fact as value+source, not the reading.

    The identity is what a resume compares, so it is what the manifest has to carry: the
    channel and its mode, every fixed fact with its provenance, and the layout signature.
    Deliberately **not** the raw ``InstrumentSnapshot``: its volatile half (``hwnd``, the
    rect, the cursor, ``is_foreground``, the geometry) is a property of a session rather than
    of the instrument, so it is evidence for a diagnosis and not compatibility evidence —
    §3.3 exists to keep it out of the identity, and a manifest that stored the reading would
    undo that.
    """
    job = campaign_job(tmp_path, monkeypatch)

    manifest = run_job(job)

    identity = manifest.compilation_identity
    assert identity is not None, "the manifest dropped the identity the run compiled"
    assert identity.channel.value == "1" and identity.channel.source is FactSource.ROUTED
    assert identity.mode.value == ChannelMode.MANUAL.value
    assert identity.prf_us.value == str(PRF_US)
    assert identity.emissions_per_profile.value == str(EMISSIONS_PER_PROFILE)
    assert identity.sound_speed_ms.value == str(int(SOUND_SPEED_MS))
    assert identity.first_gate_mm.value == str(int(FIRST_GATE_MM))
    assert not manifest.declared_only
    assert manifest.skipped_without_evidence == ()
    # It survives the round trip a report reads it back through...
    assert campaign.read_manifest(campaign.manifest_path_for(job.log_path)) == manifest
    # ...and the volatile half of a reading is not in it, by construction.
    fields = set(type(identity).model_fields)
    assert not fields & {"fingerprint", "hwnd", "rect", "cursor", "is_foreground", "layout_note"}


def test_a_resume_against_a_legacy_manifest_refuses_until_told_to_proceed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest with no identity proves nothing — fail closed, or say so on purpose.

    Every manifest written before this slice carries no ``compilation_identity``, so nothing
    says the previous run measured on *this* instrument; a resume that skipped on it would
    leave points out of the todo set on an unproven identity. ``resume_declaration_only`` is
    the operator's explicit way to proceed on the declaration alone — and then every skipped
    point is marked in the manifest as skipped without evidence, so the record does not read
    like a proven resume.
    """
    job = campaign_job(tmp_path, monkeypatch)
    first = run_job(job)
    assert first.ok_count == 2
    campaign.write_manifest(
        campaign.manifest_path_for(job.log_path), legacy_manifest(first)
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job, resume=True)

    message = str(excinfo.value)
    assert "compilation identity" in message and "resume-declaration-only" in message, message

    notes: list[str] = []
    resumed = run_job(job, resume=True, resume_declaration_only=True, notes=notes)

    assert resumed.planned == 2
    assert resumed.skipped == ("c1-k1", "c1-k2")
    assert resumed.skipped_without_evidence == ("c1-k1", "c1-k2")
    assert resumed.outcomes == ()  # nothing ran: every point was skipped
    assert not resumed.declared_only  # a reading *was* taken; only the identity is unproven
    assert any("declaration" in note for note in notes), notes
    # No new point was stored and the log was not appended to by this run.
    assert len(stored_names(job.directory)) == 2
    assert [record.key for record in point_records(read_entries(job.log_path))] == [1, 2]


def test_a_resume_against_a_changed_definition_refuses_even_when_told_to_proceed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The definition's own change is not an identity question, so nothing bypasses it.

    A one-second-longer window moves the definition's fingerprint while leaving the reading —
    and therefore the identity — exactly where it was, which is the case the asymmetry exists
    for: the recorded points belong to a job this definition never asked for, and
    ``resume_declaration_only`` is about *instrument evidence*, not about which job this is.
    Nothing runs and nothing is stored; the manifest is the first run's.
    """
    job = campaign_job(tmp_path, monkeypatch)
    first = run_job(job)
    changed = campaign.load_campaign(
        campaign_file(
            tmp_path, campaign_payload(duration_s=CAMPAIGN_DURATION_S + 1.0), "changed.json"
        )
    )
    assert campaign.campaign_fingerprint(changed) != first.fingerprint

    with pytest.raises(campaign.CampaignError) as excinfo:
        campaign.run_campaign(
            changed,
            job.fake,
            store_dir=job.directory,
            log_path=job.log_path,
            resume=True,
            resume_declaration_only=True,
        )

    message = str(excinfo.value)
    assert "different job" in message, message
    assert "does not bypass" in message, message
    assert len(stored_names(job.directory)) == 2
    assert campaign.read_manifest(campaign.manifest_path_for(job.log_path)) == first


def test_a_resume_with_a_recording_log_and_no_manifest_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The log alone is not an identity: records with no manifest say nothing about the rig."""
    job = campaign_job(tmp_path, monkeypatch)
    run_job(job)
    campaign.manifest_path_for(job.log_path).unlink()  # the manifest is gone; the log is not

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job, resume=True)

    message = str(excinfo.value)
    assert "no manifest" in message, message
    assert campaign.recorded_points(job.log_path) == {"c1-k1", "c1-k2"}

    # ...and a log with nothing recorded in it has nothing to prove: the resume runs the job.
    empty = campaign_job(tmp_path / "empty", monkeypatch)
    whole = run_job(empty, resume=True)

    assert whole.points_skipped == 0 and whole.ok_count == 2


def test_a_resume_against_a_changed_fact_refuses_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fact that moved between the two runs is named with both sides, not summarised.

    The comparison is fact by fact through the identity's provenance, because the operator's
    next question is *which* fact moved and what it moved between — "a different instrument"
    alone would send them to the window geometry, which is deliberately not in the identity.
    The fact used here is the emissions per profile: a disagreement about it *warns* at
    compile time (``verify.ADVISORY_COVARIATES``) instead of refusing, which makes it exactly
    the case where the identity comparison is the only thing that can stop a resume.
    """
    job = campaign_job(tmp_path, monkeypatch)
    run_job(job)

    job.fake.scripted_snapshot = snapshot_with(
        emissions_per_profile=InstrumentFact(value="60", source=FactSource.READ)
    )

    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job, resume=True)

    message = str(excinfo.value)
    assert "emissions_per_profile" in message, message
    assert "'52'" in message and "'60'" in message, message  # both sides, as they were stated
    # Nothing ran on the unproven identity: the two stored points are the first run's.
    assert len(stored_names(job.directory)) == 2

    notes: list[str] = []
    resumed = run_job(job, resume=True, resume_declaration_only=True, notes=notes)

    assert resumed.skipped_without_evidence == ("c1-k1", "c1-k2")
    assert resumed.outcomes == ()


def test_a_run_without_a_snapshot_is_marked_declared_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``no_snapshot`` skips the reading and the compile, and the manifest says nothing was read.

    The flag exists for the operator who wants the points recorded with no instrument evidence
    — during bring-up, or where the dialog reads are not trusted yet. What it must never do is
    leave a manifest that reads like a compiled job: ``declared_only`` states that nothing was
    read, and ``compilation_identity`` stays ``None`` because there is no reading to project.
    The points that run are the static plan's, which is the same list the compile would have
    built its identity around — nothing about the points themselves changes.
    """
    job = campaign_job(tmp_path, monkeypatch)

    manifest = run_job(job, no_snapshot=True)

    assert manifest.declared_only is True
    assert manifest.compilation_identity is None
    # Not one instrument read: neither the routing step's reading nor the dialog's.
    assert job.fake.snapshot_checks == 0 and job.fake.dialog_checks == 0
    assert manifest.ok_count == 2
    assert [row.label for row in manifest.outcomes] == ["k1", "k2"]
    assert manifest.fingerprint == campaign.campaign_fingerprint(job.definition)
    assert campaign.read_manifest(campaign.manifest_path_for(job.log_path)) == manifest

    # A resume under it can never prove an identity — this run has no reading of its own to
    # compare the previous job with — so it fails closed, and proceeds only when told to.
    with pytest.raises(campaign.CampaignError) as excinfo:
        run_job(job, resume=True, no_snapshot=True)
    assert "takes no instrument reading" in str(excinfo.value)

    notes: list[str] = []
    resumed = run_job(
        job, resume=True, no_snapshot=True, resume_declaration_only=True, notes=notes
    )

    assert resumed.declared_only is True
    assert resumed.skipped_without_evidence == ("c1-k1", "c1-k2")
    assert resumed.outcomes == ()
    assert len(stored_names(job.directory)) == 2  # nothing was run again
    assert any("no-snapshot" in note for note in notes), notes


# ------------------------------------------------------------------- 8. the CLI


def test_the_cli_plan_prints_the_points_and_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The half of the feature that works on a machine with no application running."""
    path = campaign_file(tmp_path, campaign_payload())

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["plan", "--definition", str(path)])

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "test-single-channel" in out
    assert "k1" in out and "k2" in out
    # Each point's window, as the plan predicts it: the pitch, the gates, the depth.
    assert f"{GATES_K1}" in out and "0.122" in out
    assert f"{2.0 + GATES_K1 * RUNG_1_MM:.3f}" in out


def test_the_cli_plan_json_is_the_only_thing_on_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = campaign_file(tmp_path, campaign_payload())

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["plan", "--definition", str(path), "--json"])

    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["job"] == "test-single-channel"
    assert payload["channel"] == 1
    assert [point["label"] for point in payload["points"]] == ["k1", "k2"]
    assert payload["points"][0]["gates"] == GATES_K1
    assert payload["points"][0]["identity"] == "c1-k1"
    assert payload["fingerprint"] == campaign.campaign_fingerprint(
        campaign.load_campaign(path)
    )


def test_the_cli_plan_exits_two_and_names_the_field_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2 for a bad file, the reason on stderr, and nothing on stdout for a machine."""
    path = campaign_file(tmp_path, campaign_payload(prf=212.0))

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["plan", "--definition", str(path), "--json"])

    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown field 'prf'" in captured.err


def test_the_cli_plan_exits_two_for_a_point_the_application_would_clamp(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A valid file with an unplannable point is still exit 2, and it names the point."""
    payload = campaign_payload(
        points=[{"label": "too-deep", "parameters": parameters(RUNG_1_MM, 1200)}]
    )

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            ["plan", "--definition", str(campaign_file(tmp_path, payload))]
        )

    assert exit_info.value.code == 2
    assert "'too-deep'" in capsys.readouterr().err


def test_the_cli_compile_prints_the_plan_and_records_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``compile`` reconciles a definition against the fake's reading and writes nothing.

    The verb is ``campaign``'s steps 3-5 and stops there: it drives the instrument (so unlike
    ``plan`` it needs the application running), and it is the *reviewing* half of the run path
    — no store, no log, no manifest — because nothing in this path names one. The store
    directory is asserted empty rather than the absence of one file: a compile that recorded
    anything at all would be a different verb.
    """
    job = campaign_job(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["compile", "--definition", str(job.definition_path)])

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "test-single-channel" in out
    assert "k1" in out and "k2" in out
    # Steps 3-5, each once: the routing read, the dialog read, the reading.
    assert job.fake.channel_checks == 1 and job.fake.dialog_checks == 1
    assert job.fake.snapshot_checks == 1
    assert job.fake.stored == []
    assert stored_names(job.directory) == []
    assert list(job.directory.iterdir()) == []  # nothing at all, not merely no point
    assert not job.log_path.exists()
    assert not campaign.manifest_path_for(job.log_path).exists()


def test_the_cli_compile_exits_two_and_names_the_fact_it_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An instrument that disagrees is exit 2, in the compile's own words, and writes nothing.

    The refusal is the compile's, unwrapped: it already names the fact and both sides, which
    is the whole value of the verb — an operator reads which declaration the instrument
    contradicts. A refused compile spends no recording, so the directory is still empty.
    """
    job = campaign_job(tmp_path, monkeypatch)
    job.fake.scripted_snapshot = snapshot_with(
        sound_speed_ms=InstrumentFact(value="1500", source=FactSource.READ)
    )
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["compile", "--definition", str(job.definition_path), "--json"])

    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""  # a refusal is not a report
    assert "udv-acquire: " in captured.err
    assert "sound_speed_ms" in captured.err and "1500" in captured.err
    assert job.fake.snapshot_checks == 1  # the reading happened; the compile is what refused
    assert job.fake.stored == []
    assert stored_names(job.directory) == []
    assert not job.log_path.exists()
    assert not campaign.manifest_path_for(job.log_path).exists()


def test_the_cli_compile_json_is_one_document_with_the_unproven_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One parseable document on stdout, carrying the identity, the unproven facts and the
    advisories.

    ``unproven`` and ``advisories`` are properties of the compiled plan rather than fields, so
    they have to be stated for the machine to see them — and they are the two things an
    operator acts on: which facts nothing on the instrument could state (the declaration
    stands unverified), and which disagreements the plan proceeds despite.
    """
    job = campaign_job(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["compile", "--definition", str(job.definition_path), "--json"])

    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["job"] == "test-single-channel"
    assert payload["channel"] == 1
    assert payload["definition_fingerprint"] == campaign.campaign_fingerprint(job.definition)
    # The identity is §3.3's projection: each fact as its value and where it came from.
    assert payload["identity"]["channel"]["value"] == "1"
    assert payload["identity"]["channel"]["source"] == FactSource.ROUTED.value
    assert payload["unproven"] == ["max_profiles_per_block"]
    assert payload["advisories"] == []
    assert [point["label"] for point in payload["points"]] == ["k1", "k2"]
    # The note about the routing step goes to stderr, so stdout is the document alone.
    assert "note:" in captured.err
    assert "routed channel 1" in captured.err


def test_the_cli_compile_hands_the_channel_flag_to_the_actuator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--channel`` is the actuator's, exactly as it is for the other live verbs.

    ``None`` is the default and means the ``UDV_CHANNEL`` setting, so the flag arriving at all
    is what this pins: the verb routes the channel the operator named, and the note it leaves
    says which one that turned out to be.
    """
    job = campaign_job(tmp_path, monkeypatch)
    seen: list[int | None] = []

    def spy(channel: int | None = None, notes: list[str] | None = None) -> FakeActuator:
        seen.append(channel)
        return job.fake

    monkeypatch.setattr(live, "live_actuator", spy)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["compile", "--definition", str(job.definition_path), "--channel", "1"])

    assert exit_info.value.code == 0
    assert seen == [1]
    assert job.fake.channel_checks == 1
    assert "note:" in capsys.readouterr().out  # the routed channel is on the record


def test_the_cli_campaign_runs_a_definition_through_the_live_actuator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``campaign`` drives the same live actuator the other subcommands use."""
    job = campaign_job(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "campaign",
                "--definition",
                str(job.definition_path),
                "--store-dir",
                str(job.directory),
            ]
        )

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "k1" in out and "2/2 point(s) ok" in out
    log_path = job.directory / campaign.DEFAULT_LOG_NAME
    assert log_path.is_file()
    assert campaign.manifest_path_for(log_path).is_file()

    # ...and the report reads that job back off the instrument's own record.
    with pytest.raises(SystemExit) as report_exit:
        acquire_main(["report", "--log", str(log_path)])

    assert report_exit.value.code == 0
    report = capsys.readouterr().out
    assert "test-single-channel" in report
    assert "c1-k1" in report and "c1-k2" in report
    assert "summary    : 2/2 ok, 0 failed, 0 invalid" in report


def test_the_cli_campaign_exits_one_when_a_point_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = campaign_job(tmp_path, monkeypatch)
    job.fake.script_size(None, TINY_SIZE)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "campaign",
                "--definition",
                str(job.definition_path),
                "--store-dir",
                str(job.directory),
            ]
        )

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert "1 failed" in out
    # A refused point's own reason reaches the report, not only its status.
    assert "signature" in out


def test_the_cli_campaign_resume_says_how_many_it_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--resume`` skips what the log holds as ok, and the note goes to stderr with --json."""
    job = campaign_job(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)
    argv = [
        "campaign",
        "--definition",
        str(job.definition_path),
        "--store-dir",
        str(job.directory),
    ]
    with pytest.raises(SystemExit):
        acquire_main(argv)
    capsys.readouterr()

    with pytest.raises(SystemExit) as exit_info:
        acquire_main([*argv, "--resume", "--json"])

    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["planned"] == 2
    assert payload["skipped"] == ["c1-k1", "c1-k2"]
    assert payload["outcomes"] == []
    assert "resume: 2 of 2" in captured.err


def test_the_cli_campaign_no_snapshot_flag_reaches_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--no-snapshot`` reaches ``run_campaign``: no reading, and the manifest says so.

    The flag's consequence is a *mark*, so the manifest is the only place it can be checked:
    ``declared_only`` says the points were recorded with no instrument evidence behind them,
    and ``compilation_identity`` is ``None`` because there is no reading to project. The fake
    is the proof that nothing was read — and the manifest on disk carries the same mark, so
    the record and not only the report states it.
    """
    job = campaign_job(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(
            [
                "campaign",
                "--definition",
                str(job.definition_path),
                "--store-dir",
                str(job.directory),
                "--no-snapshot",
                "--json",
            ]
        )

    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["declared_only"] is True
    assert payload["compilation_identity"] is None
    assert payload["skipped_without_evidence"] == []
    assert [row["ok"] for row in payload["outcomes"]] == [True, True]
    assert job.fake.snapshot_checks == 0 and job.fake.dialog_checks == 0
    assert job.fake.channel_checks == 1  # only the runner's own once-per-run guard
    assert len(stored_names(job.directory)) == 2  # the points still ran
    assert "no-snapshot" in captured.err

    written = campaign.read_manifest(
        campaign.manifest_path_for(job.directory / campaign.DEFAULT_LOG_NAME)
    )
    assert written.declared_only is True and written.compilation_identity is None


def test_the_cli_campaign_resume_declaration_only_flag_reaches_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--resume-declaration-only`` reaches ``run_campaign``: the unproven skip is marked.

    Against a manifest that carries no identity the library's own rule is to fail closed, and
    that refusal is asserted first — so exit 0 afterwards can only be the flag arriving. Every
    point the resumed run skipped is then marked as decided without instrument evidence, which
    is what the flag buys and the price of it: the record does not read like a proven resume.
    """
    job = campaign_job(tmp_path, monkeypatch)
    monkeypatch.setattr(live, "live_actuator", lambda *args, **kwargs: job.fake)
    first = run_job(job)
    campaign.write_manifest(campaign.manifest_path_for(job.log_path), legacy_manifest(first))
    argv = [
        "campaign",
        "--definition",
        str(job.definition_path),
        "--store-dir",
        str(job.directory),
        "--log",
        str(job.log_path),
        "--resume",
    ]

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(argv)

    assert exit_info.value.code == 2  # refused until the operator says so on purpose
    assert "compilation identity" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exit_info:
        acquire_main([*argv, "--resume-declaration-only", "--json"])

    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["skipped"] == ["c1-k1", "c1-k2"]
    assert payload["skipped_without_evidence"] == ["c1-k1", "c1-k2"]
    assert payload["outcomes"] == []
    assert payload["declared_only"] is False  # a reading *was* taken; the identity is unproven
    assert len(stored_names(job.directory)) == 2  # nothing was run again
    assert "declaration" in captured.err


def test_the_cli_report_reads_a_synthetic_log_without_an_instrument(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A log from any run — a sweep's own, with no manifest — is still a full report."""
    log_path = Path(tmp_path) / "campaign.jsonl"
    append_entry(log_path, record_for("c1-k1-s1", "s1"))
    append_entry(
        log_path,
        record_for("c1-k2-s1", "s1", status=PointStatus.FAILED, key=2, failure="refused"),
    )

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["report", "--log", str(log_path)])

    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "no manifest beside this log" in out
    assert "c1-k1" in out and "c1-k2" in out
    assert "refused" in out
    assert "summary    : 1/2 ok, 1 failed, 0 invalid" in out


def test_the_cli_report_reads_the_manifest_beside_the_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = campaign_job(tmp_path, monkeypatch)
    manifest = run_job(job)

    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["report", "--log", str(job.log_path), "--json"])

    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"]["job"] == manifest.job
    assert payload["manifest"]["fingerprint"] == manifest.fingerprint
    assert payload["summary"] == {
        "points": 2,
        "ok": 2,
        "failed": 0,
        "invalid": 0,
        "recorded": ["c1-k1", "c1-k2"],
    }
    assert [point["identity"] for point in payload["points"]] == ["c1-k1", "c1-k2"]
    assert payload["points"][0]["gates"] == GATES_K1


def test_the_cli_report_exits_two_for_a_log_it_cannot_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        acquire_main(["report", "--log", str(Path(tmp_path) / "nothing.jsonl")])

    assert exit_info.value.code == 2
    assert "no sweep log" in capsys.readouterr().err


def test_the_cli_needs_a_definition_for_plan_and_a_log_for_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The required arguments are the usage surface: nothing to review, nothing to report."""
    for argv in (["plan"], ["compile"], ["report"], ["campaign"]):
        with pytest.raises(SystemExit) as exit_info:
            acquire_main(argv)
        assert exit_info.value.code == 2


# --------------------------------------------------------------- 9. the repo's own rules


def test_the_shipped_example_is_a_single_channel_slot_of_permutations() -> None:
    """What the near-term goal asked for, asserted on the file rather than on a docstring."""
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    assert payload["channel"] == 1  # one channel is the scope (handoff §3)
    assert 10.0 <= payload["duration_s"] <= 15.0  # the operator's band (handoff §4)
    assert len(payload["points"]) >= 4
    labels = [point["label"] for point in payload["points"]]
    assert len(set(labels)) == len(labels)
    # The permutation slot is in the two fields a point's write can actually change
    # (actuator.ordered_writes): the pitch and the gate count.
    assert len({point["parameters"]["resolution_mm"] for point in payload["points"]}) >= 3


def test_the_log_record_gained_no_field_for_this_layer() -> None:
    """The resume reads ``name`` and ``sweep_id``; the log's shape is not this layer's to change.

    The set is pinned exactly, so a field added *for a campaign* fails here. The four
    fields below that a campaign never reads are the acquisition layer's own evidence:
    what the word-level check enforced, what it reported without enforcing, the window
    that was requested, and the block cap it ran under.
    """
    assert set(SweepPointRecord.model_fields) == {
        "record_type",
        "sweep_id",
        "key",
        "name",
        "status",
        "requested",
        "timing",
        "requested_duration_s",
        "block_cap_profiles",
        "readback_gates",
        "readback_resolution",
        "file_path",
        "file_size_bytes",
        "expected_size_bytes",
        "decoded",
        "failure",
        "covariates_enforced",
        "covariate_advisories",
        "covariates_advisory",
    }


def test_the_runner_still_names_a_sweep_by_its_rungs() -> None:
    """A campaign's naming is a *subclass*: a plain ``RecordSettings`` is untouched."""
    assert RecordSettings(name_prefix="sw100").point_name(1, "s") == "sw100-k1-s"
    assert RecordSettings(name_prefix="sw100").next_name(1, "s", {"sw100-k1-s"}) == "sw100-k1-sb"
    campaign_settings = campaign.CampaignRecordSettings(
        name_prefix="sw100", labels=("k1",)
    )
    assert campaign_settings.max_profiles_per_block == RecordSettings(
        name_prefix="sw100"
    ).max_profiles_per_block
