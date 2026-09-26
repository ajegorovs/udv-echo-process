"""The committed-pass catalog: its identities, the roles it states, and its refusals.

Every check here reads the committed plan and run record a ref names, or the identity the
frozen WP0 authority resolves from them; **no recording is decoded**, so the whole file
runs in about a second and stays a contract test rather than a measurement. Decoding a
pass is the shared loader's job, and the notebook's.

The last group pins the *delegation*: :meth:`PassRef.identify` must add no check of its
own, so a ref's refusal is compared with ``identify_pass``'s own message character for
character. A duplicated identity check is exactly the drift the catalog exists to prevent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from udv_echo_process.analysis.sparse_inventory import (
    PERIOD_LAW_BY_PASS,
    SparseIngestError,
    identify_pass,
    read_job_records,
)
from udv_echo_process.analysis.sparse_passes import (
    COMMITTED_PASSES,
    PassRef,
    PassRole,
    pass_by_name,
    period_law_by_pass,
)

ROOT = Path(__file__).resolve().parent.parent

#: The nine-job design's own job kinds: the shape a sitting's plan carries.
SITTING_KINDS = frozenset({"scientific", "common-reference"})

#: The campaign's own kind: every job of the Stage-2 block is one run-level realization.
CAMPAIGN_KIND = "run-level"

#: The pair letters the campaign's four counterbalanced pairs must all appear under.
CAMPAIGN_PAIRS = 4

IDS = [ref.name for ref in COMMITTED_PASSES]


@pytest.fixture(autouse=True)
def _resolve_a_refs_paths_at_the_repository_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ref's paths are repository-relative, so a test resolves them from the root."""
    monkeypatch.chdir(ROOT)


def _plan(ref: PassRef) -> dict[str, object]:
    """The pass's own run plan, as committed."""
    return json.loads((ROOT / ref.plan_path).read_text(encoding="utf-8"))


def _run(ref: PassRef) -> dict[str, object]:
    """The pass's own record ``<name>.run.json`` inside its root, as committed."""
    return json.loads(
        (ROOT / ref.root / f"{ref.name}.run.json").read_text(encoding="utf-8")
    )


def _mismatched(*, name: str, root: Path, plan_path: Path) -> PassRef:
    """A ref whose name, root and plan need not agree — built here, never committed."""
    return PassRef(
        name=name,
        root=root,
        plan_path=plan_path,
        role=PassRole.SITTING,
        note="a deliberately inconsistent ref, built by a test",
        period_law="",
        in_frozen_design=True,
    )


# ── identity: delegated to the frozen WP0 authority ────────────────────


@pytest.mark.parametrize("ref", COMMITTED_PASSES, ids=IDS)
def test_every_committed_pass_identifies_against_its_own_plan_and_run_record(
    ref: PassRef,
) -> None:
    """A committed ref's own inputs resolve to its own name, through ``identify_pass``."""
    assert (ROOT / ref.root).is_dir()
    assert (ROOT / ref.plan_path).is_file()
    assert (ROOT / ref.root / f"{ref.name}.run.json").is_file()
    assert ref.identify() == ref.name


def test_a_ref_whose_plan_and_name_disagree_is_refused() -> None:
    """Two committed plans and two committed names, crossed: no combination is accepted.

    The mismatch is built in the test — a bad ref is never added to the committed tuple —
    and it is refused before any recording is read, which is why this stays fast.
    """
    live1 = pass_by_name("sparse-mixer-live-1")
    live2 = pass_by_name("sparse-mixer-live-2")
    for ref, other in (
        (
            _mismatched(name=live1.name, root=live1.root, plan_path=live2.plan_path),
            live2,
        ),
        (
            _mismatched(name=live2.name, root=live2.root, plan_path=live1.plan_path),
            live1,
        ),
    ):
        with pytest.raises(SparseIngestError) as raised:
            ref.identify()
        message = str(raised.value)
        assert ref.name in message
        assert other.name in message


def test_identify_adds_no_check_of_its_own() -> None:
    """The ref's refusal *is* the authority's, so a second implementation cannot drift.

    Same message, character for character, for both ways a ref can disagree: a plan that
    names another pass, and a root that does not hold the pass record the name asks for.
    """
    live1 = pass_by_name("sparse-mixer-live-1")
    live2 = pass_by_name("sparse-mixer-live-2")
    refs = (
        _mismatched(name=live1.name, root=live1.root, plan_path=live2.plan_path),
        _mismatched(name=live1.name, root=live2.root, plan_path=live1.plan_path),
    )
    for ref in refs:
        with pytest.raises(SparseIngestError) as via_ref:
            ref.identify()
        with pytest.raises(SparseIngestError) as direct:
            identify_pass(ref.root, plan_path=ref.plan_path, plan_name=ref.name)
        assert str(via_ref.value) == str(direct.value)


# ── role: what the pass's own plan and record state ────────────────────


@pytest.mark.parametrize("ref", COMMITTED_PASSES, ids=IDS)
def test_each_pass_carries_the_role_its_own_plan_and_record_state(
    ref: PassRef,
) -> None:
    """A sitting is the nine-job block; a campaign is run-level counterbalanced pairs.

    Both shapes are read off the committed plan and run record rather than asserted from
    the role: the role is what those two files say the dataset is.
    """
    plan = _plan(ref)
    run = _run(ref)
    jobs = plan["jobs"]
    kinds = {job["kind"] for job in jobs}
    recorded = run["jobs"]
    if ref.role is PassRole.CAMPAIGN:
        assert kinds == {CAMPAIGN_KIND}
        assert plan["analysis_orientation"]
        assert len(recorded) == len(jobs)
        assert all(
            job["pair"] and job["role"] and job["orientation"] for job in recorded
        )
        assert len({job["pair"] for job in recorded}) == CAMPAIGN_PAIRS
    else:
        assert kinds <= SITTING_KINDS
        assert "analysis_orientation" not in plan
        assert all(job.get("pair") is None for job in recorded)


def test_a_campaign_is_never_presentable_as_a_sitting() -> None:
    """The one role that may be mislabelled is pinned: the campaign, and only it."""
    campaigns = [ref for ref in COMMITTED_PASSES if ref.role is PassRole.CAMPAIGN]
    assert [ref.name for ref in campaigns] == ["stage2-e20-e64"]
    assert all(not ref.presentable_as_sitting for ref in campaigns)
    sittings = [ref for ref in COMMITTED_PASSES if ref.role is PassRole.SITTING]
    assert [ref.name for ref in sittings] == [
        "sparse-mixer-first-pass",
        "sparse-mixer-live-1",
        "sparse-mixer-live-2",
    ]
    assert all(ref.presentable_as_sitting for ref in sittings)


# ── the catalog's own surface ──────────────────────────────────────────


def test_the_catalog_is_a_frozen_tuple_addressed_by_name() -> None:
    assert isinstance(COMMITTED_PASSES, tuple)
    names = [ref.name for ref in COMMITTED_PASSES]
    assert len(names) == len(set(names))
    for ref in COMMITTED_PASSES:
        assert pass_by_name(ref.name) is ref
    with pytest.raises(KeyError, match="no committed pass is named"):
        pass_by_name("sparse-mixer-live-3")


@pytest.mark.parametrize("ref", COMMITTED_PASSES, ids=IDS)
def test_a_refs_report_dir_and_design_membership_are_committed_facts(
    ref: PassRef,
) -> None:
    """``report_dir`` and ``in_frozen_design`` describe the repo, not the ref's word."""
    if ref.report_dir is None:
        assert not (ROOT / "reports" / ref.name).exists()
    else:
        assert (ROOT / ref.report_dir).is_dir()
        assert (ROOT / ref.report_dir / "README.md").is_file()
    assert ref.in_frozen_design == (
        {job["kind"] for job in _plan(ref)["jobs"]} <= SITTING_KINDS
    )


def test_a_ref_is_frozen_and_rejects_an_undeclared_field() -> None:
    """The frozen ``ValueModel`` contract, on the ref: no ``sitting`` label comes back."""
    ref = pass_by_name("sparse-mixer-live-2")
    with pytest.raises(ValidationError):
        PassRef(**{**ref.model_dump(mode="json"), "sitting": "free text"})
    with pytest.raises(ValidationError):
        ref.note = "rewritten"


# ── the period-law table: derived from the catalog, values unchanged ───


def test_the_period_law_table_is_the_catalogs_own_and_unchanged() -> None:
    """The table maps exactly what it always has, and it derives from the refs."""
    assert PERIOD_LAW_BY_PASS == {
        "sparse-mixer-live-1": "emissions_per_profile x prf_us + 1 ms",
        "sparse-mixer-live-2": (
            "T_tran + T_prf x (16 + N_PRF) (acquire/plan.py::profile_period_s)"
        ),
    }
    assert period_law_by_pass() == PERIOD_LAW_BY_PASS


@pytest.mark.parametrize("ref", COMMITTED_PASSES, ids=IDS)
def test_each_ref_carries_the_law_the_ingest_screens_it_with(ref: PassRef) -> None:
    assert ref.period_law == PERIOD_LAW_BY_PASS.get(ref.name, "")


def test_a_pass_the_table_does_not_classify_keeps_no_entry() -> None:
    """Naming a law is the catalog's tightening, and this catalog names only the two.

    The zero-signal first pass and the Stage-2 campaign are screened against *both*
    planning forms, as they were before the table existed; deriving the table must not
    quietly classify them, which is why their refs carry ``""``.
    """
    for name in ("sparse-mixer-first-pass", "stage2-e20-e64"):
        assert pass_by_name(name).period_law == ""
        assert name not in PERIOD_LAW_BY_PASS


# ── what is deliberately not a committed pass ──────────────────────────


def test_the_bounded_trial_is_not_a_pass_of_its_own() -> None:
    """The trial is the first pass's own record at two jobs, so it cannot be a ref.

    It carries no plan of its own — its record answers the first pass's plan name, which a
    second ref would make ambiguous — and its record names jobs whose logs are not
    committed there, so the shared binding refuses to read it as a pass at all.
    """
    first = pass_by_name("sparse-mixer-first-pass")
    trial = ROOT / "data" / "sparse-mixer-first-pass-trial"
    assert trial.is_dir()
    assert trial not in {ROOT / ref.root for ref in COMMITTED_PASSES}
    record = json.loads((trial / f"{first.name}.run.json").read_text(encoding="utf-8"))
    assert record["plan"] == first.name
    plan, run, resolved = identify_pass(
        first.root, plan_path=first.plan_path, plan_name=first.name
    )
    assert resolved == first.name
    with pytest.raises(SparseIngestError, match="not committed"):
        read_job_records(trial, plan, run)
